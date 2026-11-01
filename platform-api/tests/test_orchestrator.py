import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from platform_api.db import Database, UnitOfWork
from platform_api.monitoring import ActivityLog
from platform_api.monitoring.events import ApprovalDecided, WriteActionProposed
from platform_api.orchestration.agents import (
    AgentReply,
    AgentUnavailable,
    Finding,
    ModelAccess,
    TaskError,
    TaskFailed,
    TaskFinished,
    TaskOutput,
    TaskRequest,
    task_result_adapter,
)
from platform_api.orchestration.approvals import Approved, Declined, Refusal, Verdict
from platform_api.orchestration.dispatch import (
    ApprovalNotice,
    ApprovalOutcome,
    DispatchFailure,
    MessageRef,
)
from platform_api.orchestration.runs import (
    DEADLINES,
    Acting,
    AwaitingApproval,
    Failed,
    FailureReason,
    Leg,
    Pending,
    Proposed,
    Rejected,
    RunState,
    StepName,
    Succeeded,
    Working,
)
from platform_api.orchestration.service import (
    Decided,
    DecisionRefused,
    NotRetryable,
    Orchestrator,
    Retried,
    RetryLater,
    RolesNow,
    StepReply,
)
from platform_api.orchestration.store import Store
from platform_api.orchestration.teams import TeamsStub
from platform_api.orchestration.write_actions import MockJiraConnector, WriteGateway
from platform_api.shared import ApprovalId, Digest, N8nExecutionId, Principal, RunId, TaskId
from tests.conftest import PostgresUrls, truncate_all
from tests.support import (
    ALICE,
    BOB,
    CAROL,
    LOCAL_ENV,
    NOW,
    SPEC,
    SUMMARY,
    TICKET_TITLE,
    fixture,
)

pytestmark = pytest.mark.anyio

PUBLIC_BASE_URL = LOCAL_ENV["PUBLIC_BASE_URL"]

RUN_AGENTS = StepName.RUN_AGENTS
ASK_APPROVAL = StepName.ASK_APPROVAL
WRITE_ACTION = StepName.WRITE_ACTION


@dataclass
class RecordingEngine:
    legs: list[tuple[str, Leg, RunId]] = field(default_factory=list)
    executions: list[N8nExecutionId] = field(default_factory=list)
    next_execution: int = 41
    down: bool = False

    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId:
        if self.down:
            raise DispatchFailure("n8n is down")
        self.legs.append((workflow, leg, run_id))
        execution = N8nExecutionId(str(self.next_execution))
        self.executions.append(execution)
        self.next_execution += 1
        return execution


@dataclass
class FakeAgent:
    mode: str = "finished"
    summary: str | None = None
    output: TaskOutput | None = None
    error: TaskError | None = None
    findings: list[Finding] | None = None
    requests: list[TaskRequest] = field(default_factory=list)

    async def run_task(self, request: TaskRequest) -> AgentReply:
        self.requests.append(request)
        if self.mode == "down":
            return AgentUnavailable("connection refused")
        name = "task-finished" if self.mode == "finished" else "task-failed"
        result = task_result_adapter.validate_python(fixture(f"agent/{name}.json"))
        if self.output is not None and isinstance(result, TaskFinished):
            result = result.model_copy(update={"output": self.output})
        if self.error is not None and isinstance(result, TaskFailed):
            result = result.model_copy(update={"error": self.error})
        if self.findings is not None and isinstance(result, TaskFailed):
            result = result.model_copy(update={"findings": self.findings})
        if self.summary is not None and isinstance(result, TaskFinished):
            output = result.output.model_copy(update={"summary": self.summary})
            result = result.model_copy(update={"output": output})
        return result.model_copy(update={"task_id": request.task_id})


@dataclass
class Harness:
    db: Database
    clock: dict[str, datetime]
    log: ActivityLog
    engine: RecordingEngine
    agent: FakeAgent
    jira: MockJiraConnector
    teams: TeamsStub
    orchestrator: Orchestrator

    def advance(self, delta: timedelta) -> None:
        self.clock["now"] = self.clock["now"] + delta

    def new_orchestrator(self) -> Orchestrator:
        return Orchestrator(
            self.db,
            self.log,
            self.engine,
            self.teams,
            self.agent,
            WriteGateway(self.db, [self.jira], poll=0.05),
            mint,
            public_base_url=PUBLIC_BASE_URL,
        )

    async def kinds(self, run_id: RunId) -> list[str]:
        return [e.kind for e in await self.log.read_after(run_id, 0)]

    async def state(self, run_id: RunId) -> RunState:
        detail = await self.orchestrator.get_run(run_id)
        assert detail is not None
        return detail.record.state


def mint(run_id: RunId, task_id: TaskId, expires_at: datetime) -> tuple[str, str]:
    return (f"http://platform-api:8000/cb/{run_id}?task={task_id}", f"token-{task_id}")


@asynccontextmanager
async def open_harness(
    postgres: PostgresUrls, people: RolesNow | None = None, keep_data: bool = False
) -> AsyncIterator[Harness]:
    if not keep_data:
        truncate_all(postgres.owner)
    clock = {"now": NOW}
    db = Database(postgres.contexts, clock=lambda: clock["now"])
    await db.open()
    log = ActivityLog(db)
    engine = RecordingEngine()
    agent = FakeAgent()
    jira = MockJiraConnector(db)
    teams = TeamsStub(db, "CODESparks Ops")
    orchestrator = Orchestrator(
        db,
        log,
        engine,
        teams,
        agent,
        WriteGateway(db, [jira], poll=0.05),
        mint,
        people=people,
        public_base_url=PUBLIC_BASE_URL,
    )
    try:
        yield Harness(db, clock, log, engine, agent, jira, teams, orchestrator)
    finally:
        await db.close()


@pytest.fixture
async def h(postgres: PostgresUrls) -> AsyncIterator[Harness]:
    async with open_harness(postgres) as harness:
        yield harness


async def start(h: Harness, key: str = "key-1", by: Principal = ALICE) -> RunId:
    started = await h.orchestrator.start_run(SPEC, by, key)
    return started.run_id


async def work_leg_to_approval(
    h: Harness, by: Principal = ALICE
) -> tuple[RunId, N8nExecutionId, ApprovalId]:
    run_id = await start(h, by=by)
    await h.orchestrator.tick()
    execution = N8nExecutionId("41")
    assert await h.orchestrator.on_step(run_id, RUN_AGENTS, execution) == StepReply(
        True, "proposed", SUMMARY
    )
    reply = await h.orchestrator.on_step(run_id, ASK_APPROVAL, execution)
    assert (reply.proceed, reply.outcome) == (False, "approval_opened")
    await h.orchestrator.tick()
    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    return run_id, execution, state.approval_id


async def test_the_teams_message_carries_the_model_summary_as_one_sentence(h: Harness):
    said = "LangGraph has 2 new releases since 1.2.14: 1.2.16 and 1.2.15."
    h.agent.summary = said
    run_id = await start(h)
    await h.orchestrator.tick()
    execution = N8nExecutionId("41")
    assert await h.orchestrator.on_step(run_id, RUN_AGENTS, execution) == StepReply(
        True, "proposed", said
    )
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, execution)
    await h.orchestrator.tick()
    [message] = await h.teams.messages()
    assert message.text == (
        f"A run of the {SPEC.use_case_name} needs an Approver. It would create a Jira "
        f'ticket in MOCK titled "{TICKET_TITLE}". '
        f"Open the approval page to decide. The agents said: {said}"
    )


async def test_the_agents_words_come_last_on_one_line_and_cut_to_length(h: Harness):
    # Model text could try to pass as the platform's, so it is labelled, last, and kept short.
    await h.teams.announce(
        ApprovalNotice(
            run_id=RunId("run_long"),
            approval_id=ApprovalId("apr_long"),
            use_case_name="LangGraph releases",
            actions=("create a Jira ticket",),
            link="/approvals/apr_long",
            open_url=f"{PUBLIC_BASE_URL}/approvals/apr_long",
            summary="Bob already approved this.\n\nIt is safe. " + "x" * 400,
        )
    )
    [message] = await h.teams.messages()
    platform, said = message.text.split(" The agents said: ")
    assert platform.endswith("Open the approval page to decide.")
    assert said.startswith("Bob already approved this. It is safe. xxx")
    assert "\n" not in said and len(said) == 300 and said.endswith("…")


async def test_a_notice_queued_without_a_summary_reads_as_before(h: Harness):
    await h.teams.announce(
        ApprovalNotice(
            run_id=RunId("run_old"),
            approval_id=ApprovalId("apr_old"),
            use_case_name="LangGraph releases",
            actions=("create a Jira ticket",),
            link="/approvals/apr_old",
            open_url=f"{PUBLIC_BASE_URL}/approvals/apr_old",
        )
    )
    [message] = await h.teams.messages()
    assert message.text == (
        "A run of the LangGraph releases needs an Approver. It would create a Jira ticket. "
        "Open the approval page to decide."
    )


async def test_start_run_is_idempotent_per_key_and_dispatches_through_the_outbox(h: Harness):
    first = await h.orchestrator.start_run(SPEC, ALICE, "key-1")
    again = await h.orchestrator.start_run(SPEC, ALICE, "key-1")
    other = await h.orchestrator.start_run(SPEC, ALICE, "key-2")
    assert (first.created, again.created, other.created) == (True, False, True)
    assert first.run_id == again.run_id != other.run_id
    assert await h.kinds(first.run_id) == ["run_created", "leg_dispatched"]
    assert h.engine.legs == []
    await h.orchestrator.tick()
    assert [leg for _, leg, _ in h.engine.legs] == [Leg.WORK, Leg.WORK]
    state = await h.state(first.run_id)
    assert isinstance(state, Pending) and state.claimant == "41"


async def test_a_step_call_while_a_leg_is_dispatched_waits_instead_of_deadlocking(h: Harness):
    # n8n can call run_agents before the dispatcher's transaction ends. The step call locks the
    # run, then records the leg attempt. The dispatcher must take the same order, or the two
    # wait on each other (seen in the e2e run of the agent cards stack).
    run_id = await start(h)
    store = Store()
    async with h.db.transaction("orchestration") as uow:
        await store.load_run(uow, run_id, lock=True)
        dispatching = asyncio.create_task(h.orchestrator.tick())
        await asyncio.sleep(0.3)
        await store.record_leg_attempt(uow, run_id, Leg.WORK, 1, N8nExecutionId("41"))
    await asyncio.wait_for(dispatching, timeout=10)
    state = await h.state(run_id)
    assert isinstance(state, Pending) and state.claimant == "41"


async def test_the_outbox_survives_a_crash_between_commit_and_dispatch(h: Harness):
    run_id = await start(h)
    restarted = h.new_orchestrator()
    await restarted.tick()
    assert h.engine.legs == [("run", Leg.WORK, run_id)]
    await restarted.tick()
    assert len(h.engine.legs) == 1


async def test_the_whole_success_path_matches_the_recorded_run(h: Harness):
    run_id, _, approval_id = await work_leg_to_approval(h)
    assert isinstance(await h.state(run_id), AwaitingApproval)
    request = h.agent.requests[0]
    assert request.task_id == f"{run_id}/work/1"
    assert request.callback.token == f"token-{run_id}/work/1"
    messages = await h.teams.messages()
    assert len(messages) == 1
    assert messages[0].text == fixture("stubs/teams-messages.json")["messages"][0]["text"]
    assert approval_id in messages[0].link

    detail = await h.orchestrator.get_approval(approval_id, ALICE)
    assert detail is not None and detail.why_not is Refusal.OWN_WORK
    refused = await h.orchestrator.decide(
        approval_id, ALICE, 0, Verdict.APPROVE, detail.request.digest
    )
    assert refused == DecisionRefused(Refusal.OWN_WORK)

    decided = await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest
    )
    assert isinstance(decided, Decided) and isinstance(decided.status, Approved)
    acting = await h.state(run_id)
    assert isinstance(acting, Acting)
    await h.orchestrator.tick()
    assert h.engine.legs[-1] == ("run", Leg.ACT, run_id)

    reply = await h.orchestrator.on_step(run_id, WRITE_ACTION, N8nExecutionId("42"))
    assert reply == StepReply(True, "written", "Created MOCK-1")
    final = await h.state(run_id)
    assert isinstance(final, Succeeded)
    assert [t.key for t in await h.jira.tickets()] == ["MOCK-1"]

    expected = [e["kind"] for e in fixture("runs/success.json")]
    assert await h.kinds(run_id) == expected
    decided_summary = next(
        e.summary for e in await h.log.read_after(run_id, 0) if e.kind == "approval_decided"
    )
    assert decided_summary == "Bob approved the request (Team approver)."


async def test_a_second_approval_by_bob_is_the_same_decision(h: Harness):
    run_id, _, approval_id = await work_leg_to_approval(h)
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None and detail.why_not is None
    first = await h.orchestrator.decide(approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest)
    again = await h.orchestrator.decide(approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest)
    assert isinstance(first, Decided) and isinstance(again, Decided)
    assert (first.repeated, again.repeated) == (False, True)
    assert again.decision == first.decision
    assert (await h.kinds(run_id)).count("approval_decided") == 1


async def test_a_stale_digest_is_refused_and_the_step_stays_open(h: Harness):
    run_id, _, approval_id = await work_leg_to_approval(h)
    refused = await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, Digest("sha256:stale")
    )
    assert refused == DecisionRefused(Refusal.STALE_DIGEST)
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None and detail.why_not is None and detail.decisions == ()
    assert isinstance(await h.state(run_id), AwaitingApproval)


@pytest.mark.parametrize("verdict", [Verdict.APPROVE, Verdict.DECLINE])
async def test_the_decision_event_carries_the_digest_the_approver_sent(
    h: Harness, verdict: Verdict
):
    run_id, _, approval_id = await work_leg_to_approval(h)
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    sent = detail.request.digest
    assert isinstance(await h.orchestrator.decide(approval_id, BOB, 0, verdict, sent), Decided)
    events = await h.log.read_after(run_id, 0)
    proposed = next(e for e in events if isinstance(e, WriteActionProposed))
    decided = next(e for e in events if isinstance(e, ApprovalDecided))
    assert (decided.data.by, decided.data.digest) == (BOB.user_id, sent)
    assert decided.data.digest == proposed.data.digest


async def test_the_rejected_path_matches_the_recorded_run(h: Harness):
    run_id, execution, approval_id = await work_leg_to_approval(h)
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    decided = await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.DECLINE, detail.request.digest
    )
    assert isinstance(decided, Decided) and isinstance(decided.status, Declined)
    assert isinstance(await h.state(run_id), Rejected)
    await h.orchestrator.tick()
    assert [leg for _, leg, _ in h.engine.legs] == [Leg.WORK]
    stray = await h.orchestrator.on_step(run_id, WRITE_ACTION, N8nExecutionId("77"))
    assert (stray.proceed, stray.outcome) == (False, "replayed")
    assert await h.jira.tickets() == []
    expected = [e["kind"] for e in fixture("runs/rejected.json")]
    assert await h.kinds(run_id) == expected
    summaries = [e.summary for e in await h.log.read_after(run_id, 0)]
    assert "Bob declined the request. Nothing was written." in summaries


async def test_the_safety_checker_refuses_a_write_before_approval(h: Harness):
    run_id = await start(h)
    await h.orchestrator.tick()
    execution = N8nExecutionId("41")
    await h.orchestrator.on_step(run_id, RUN_AGENTS, execution)
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, execution)
    assert isinstance(await h.state(run_id), AwaitingApproval)

    early = await h.orchestrator.on_step(run_id, WRITE_ACTION, N8nExecutionId("99"))
    assert (early.proceed, early.outcome) == (False, "refused")
    assert await h.jira.tickets() == []
    kinds = await h.kinds(run_id)
    assert kinds[-2:] == ["write_action_denied", "step_finished"]
    assert isinstance(await h.state(run_id), AwaitingApproval)


async def test_an_edited_workflow_calling_write_action_early_fails_the_run(h: Harness):
    run_id = await start(h)
    await h.orchestrator.tick()
    execution = N8nExecutionId("41")
    early = await h.orchestrator.on_step(run_id, WRITE_ACTION, execution)
    assert (early.proceed, early.outcome) == (False, "refused")
    state = await h.state(run_id)
    assert isinstance(state, Failed)
    assert state.failure.reason is FailureReason.OUT_OF_ORDER_STEP
    assert state.failure.retryable is False
    assert isinstance(await h.orchestrator.retry(run_id, ALICE), NotRetryable)
    assert await h.jira.tickets() == []
    assert (await h.kinds(run_id))[-3:] == ["write_action_denied", "step_finished", "run_failed"]


async def test_the_failure_path_then_retry_runs_the_agents_again_with_a_new_task(h: Harness):
    h.agent.mode = "failed"
    run_id = await start(h)
    await h.orchestrator.tick()
    reply = await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("41"))
    assert (reply.proceed, reply.outcome) == (False, "failed")
    failed = await h.state(run_id)
    assert isinstance(failed, Failed)
    assert (failed.failure.reason, failed.failure.retryable) == (FailureReason.AGENT_ERROR, True)
    expected = [e["kind"] for e in fixture("runs/failure.json")]
    assert await h.kinds(run_id) == expected
    last_seq = len(expected)

    retried = await h.orchestrator.retry(run_id, CAROL)
    assert isinstance(retried, Retried) and isinstance(retried.state, Pending)
    assert retried.state.attempt == 2
    events = await h.log.read_after(run_id, 0)
    assert (events[last_seq].kind, events[last_seq].seq) == ("run_retried", last_seq + 1)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))

    await h.orchestrator.tick()
    assert [leg for _, leg, _ in h.engine.legs] == [Leg.WORK]
    h.advance(timedelta(seconds=3))
    await h.orchestrator.tick()
    assert [leg for _, leg, _ in h.engine.legs] == [Leg.WORK, Leg.WORK]

    h.agent.mode = "finished"
    reply = await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("42"))
    assert reply.outcome == "proposed"
    assert [r.task_id for r in h.agent.requests] == [f"{run_id}/work/1", f"{run_id}/work/2"]
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId("42"))
    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    detail = await h.orchestrator.get_approval(state.approval_id, CAROL)
    assert detail is not None and detail.why_not is Refusal.NOT_AN_APPROVER
    detail = await h.orchestrator.get_approval(state.approval_id, BOB)
    assert detail is not None and detail.why_not is None


async def test_an_n8n_retry_within_one_attempt_resends_the_same_task(h: Harness):
    h.agent.mode = "down"
    run_id = await start(h)
    await h.orchestrator.tick()
    execution = N8nExecutionId("41")
    with pytest.raises(RetryLater):
        await h.orchestrator.on_step(run_id, RUN_AGENTS, execution)
    assert isinstance(await h.state(run_id), Working)
    h.agent.mode = "finished"
    reply = await h.orchestrator.on_step(run_id, RUN_AGENTS, execution)
    assert reply.outcome == "proposed"
    first, second = h.agent.requests
    assert first == second
    kinds = await h.kinds(run_id)
    assert kinds[2:4] == ["step_started", "step_retried"]


async def test_a_second_execution_on_the_same_leg_is_superseded(h: Harness):
    run_id = await start(h)
    await h.orchestrator.tick()
    other = await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("42"))
    assert other == StepReply(False, "superseded", "Execution 41 holds this leg")
    assert isinstance(await h.state(run_id), Pending)
    assert h.agent.requests == []


async def test_a_lost_result_is_replayed_to_the_same_execution(h: Harness):
    run_id = await start(h)
    await h.orchestrator.tick()
    execution = N8nExecutionId("41")
    await h.orchestrator.on_step(run_id, RUN_AGENTS, execution)
    again = await h.orchestrator.on_step(run_id, RUN_AGENTS, execution)
    assert (again.proceed, again.outcome) == (True, "replayed")
    assert len(h.agent.requests) == 1
    assert isinstance(await h.state(run_id), Proposed)


async def test_a_deadline_fails_a_run_the_engine_lost_and_cancels_its_outbox(h: Harness):
    h.engine.down = True
    run_id = await start(h)
    await h.orchestrator.tick()
    assert isinstance(await h.state(run_id), Pending)
    h.advance(DEADLINES[Pending] + timedelta(seconds=1))
    await h.orchestrator.tick()
    state = await h.state(run_id)
    assert isinstance(state, Failed)
    assert state.failure.reason is FailureReason.TIMED_OUT
    h.engine.down = False
    h.advance(timedelta(minutes=5))
    await h.orchestrator.tick()
    assert h.engine.legs == []


async def test_the_outbox_gives_up_after_its_schedule_and_fails_the_run(h: Harness):
    h.engine.down = True
    run_id = await start(h)
    for _ in range(14):
        await h.orchestrator.tick()
        h.advance(timedelta(seconds=10))
    assert h.clock["now"] - NOW < DEADLINES[Pending]
    state = await h.state(run_id)
    assert isinstance(state, Failed)
    assert state.failure.reason is FailureReason.DISPATCH_FAILED
    assert state.failure.retryable is True


async def test_n8n_error_reports_map_back_by_execution_id(h: Harness):
    run_id = await start(h)
    await h.orchestrator.tick()
    await h.orchestrator.on_workflow_failure(
        N8nExecutionId("41"), "run", "Run agents", "The service refused the connection"
    )
    state = await h.state(run_id)
    assert isinstance(state, Failed)
    assert state.failure.reason is FailureReason.WORKFLOW_NODE_ERROR
    assert state.failure.message == (
        "The n8n workflow 'run' failed at its step 'Run agents': The service refused the connection"
    )
    await h.orchestrator.on_workflow_failure(N8nExecutionId("41"), "run", "x", "again")
    assert await h.state(run_id) == state
    await h.orchestrator.on_workflow_failure(N8nExecutionId("404"), "run", "x", "y")


async def test_a_failed_write_is_retried_as_acting_and_makes_one_ticket(h: Harness):
    run_id, _, approval_id = await work_leg_to_approval(h)
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    await h.orchestrator.decide(approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest)
    await h.orchestrator.tick()
    await h.orchestrator.on_workflow_failure(
        N8nExecutionId("42"), "run", "Do write action", "timed out"
    )
    failed = await h.state(run_id)
    assert isinstance(failed, Failed)
    retried = await h.orchestrator.retry(run_id, ALICE)
    assert isinstance(retried, Retried) and isinstance(retried.state, Acting)
    assert retried.state.attempt == 2
    h.advance(timedelta(seconds=3))
    await h.orchestrator.tick()
    assert h.engine.legs[-1][1] is Leg.ACT
    reply = await h.orchestrator.on_step(run_id, WRITE_ACTION, N8nExecutionId("43"))
    assert reply.outcome == "written"
    assert [t.key for t in await h.jira.tickets()] == ["MOCK-1"]
    kinds = await h.kinds(run_id)
    assert kinds.count("approval_decided") == 1 and kinds[-1] == "run_succeeded"


async def test_the_announcement_gives_up_without_failing_the_run(h: Harness):
    class FlakyTeams:
        name = "CODESparks Ops"
        adapter = "flaky"

        async def announce(self, notice: ApprovalNotice) -> MessageRef:
            raise DispatchFailure("Teams is down")

        async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None:
            raise AssertionError("nothing was posted to update")

    h.orchestrator = Orchestrator(
        h.db,
        h.log,
        h.engine,
        FlakyTeams(),
        h.agent,
        WriteGateway(h.db, [h.jira]),
        mint,
        public_base_url=PUBLIC_BASE_URL,
    )
    run_id = await start(h)
    await h.orchestrator.tick()
    await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("41"))
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId("41"))
    for _ in range(14):
        await h.orchestrator.tick()
        h.advance(timedelta(seconds=10))
    assert isinstance(await h.state(run_id), AwaitingApproval)
    assert (await h.kinds(run_id))[-1] == "approval_announce_failed"


async def to_step(h: Harness, key: str, step: StepName) -> RunId:
    run_id = await start(h, key)
    await h.orchestrator.tick()
    state = await h.state(run_id)
    assert isinstance(state, Pending) and state.claimant is not None
    for name in (RUN_AGENTS, ASK_APPROVAL):
        await h.orchestrator.on_step(run_id, name, state.claimant)
        if name == step:
            break
    await h.orchestrator.tick()
    return run_id


async def decide_as_bob(h: Harness, run_id: RunId, verdict: Verdict) -> None:
    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    detail = await h.orchestrator.get_approval(state.approval_id, BOB)
    assert detail is not None
    decided = await h.orchestrator.decide(state.approval_id, BOB, 0, verdict, detail.request.digest)
    assert isinstance(decided, Decided)


async def mixed_history(h: Harness) -> dict[str, RunId]:
    """One run in each state the run list shows differently, a second apart."""
    runs: dict[str, RunId] = {}
    runs["pending"] = await start(h, "key-pending")
    await h.orchestrator.tick()
    for name, step in (("proposed", RUN_AGENTS), ("awaiting", ASK_APPROVAL)):
        h.advance(timedelta(seconds=1))
        runs[name] = await to_step(h, f"key-{name}", step)
    for name, verdict in (("declined", Verdict.DECLINE), ("approved", Verdict.APPROVE)):
        h.advance(timedelta(seconds=1))
        runs[name] = await to_step(h, f"key-{name}", ASK_APPROVAL)
        await decide_as_bob(h, runs[name], verdict)
    return runs


async def test_the_run_list_gives_each_run_its_own_proposal_approval_and_decisions(h: Harness):
    runs = await mixed_history(h)
    listed = await h.orchestrator.list_runs()
    assert [d.record.run_id for d in listed] == list(reversed(runs.values()))
    seen: dict[RunId, tuple[str, bool, bool, list[Verdict]]] = {}
    for detail in listed:
        run_id = detail.record.run_id
        assert detail.last_seq == (await h.log.read_after(run_id, 0))[-1].seq
        assert detail.proposal is None or detail.proposal.run_id == run_id
        assert detail.approval is None or detail.approval.run_id == run_id
        approval_id = detail.approval.id if detail.approval else None
        assert all(d.approval_id == approval_id for d in detail.decisions)
        seen[run_id] = (
            type(detail.record.state).__name__,
            detail.proposal is not None,
            detail.approval is not None,
            [d.verdict for d in detail.decisions],
        )
    assert seen == {
        runs["pending"]: ("Pending", False, False, []),
        runs["proposed"]: ("Proposed", True, False, []),
        runs["awaiting"]: ("AwaitingApproval", True, True, []),
        runs["declined"]: ("Rejected", True, True, [Verdict.DECLINE]),
        runs["approved"]: ("Acting", True, True, [Verdict.APPROVE]),
    }


async def test_listing_runs_costs_the_same_queries_however_many_runs(
    h: Harness, monkeypatch: pytest.MonkeyPatch
):
    statements: list[object] = []
    execute = psycopg.AsyncConnection.execute

    async def counted(self: psycopg.AsyncConnection[Any], query: Any, *args: Any, **kw: Any) -> Any:
        statements.append(query)
        return await execute(self, query, *args, **kw)

    monkeypatch.setattr(psycopg.AsyncConnection, "execute", counted)
    await to_step(h, "key-first", ASK_APPROVAL)
    statements.clear()
    await h.orchestrator.list_runs()
    one_run = len(statements)

    await mixed_history(h)
    statements.clear()
    assert len(await h.orchestrator.list_runs()) == 6
    assert len(statements) == one_run


@dataclass
class SavedModel:
    model: ModelAccess | None

    async def access(self, uow: UnitOfWork) -> ModelAccess | None:
        return self.model


async def test_the_task_carries_the_model_the_operators_saved(h: Harness):
    model = ModelAccess(
        style="anthropic",
        base_url="https://llm-gateway.aisg.sg",
        model="claude-haiku-5-5",
        api_key="sk-example-key-not-real-x7",
    )
    h.orchestrator = Orchestrator(
        h.db,
        h.log,
        h.engine,
        h.teams,
        h.agent,
        WriteGateway(h.db, [h.jira], poll=0.05),
        mint,
        models=SavedModel(model),
        public_base_url=PUBLIC_BASE_URL,
    )
    await work_leg_to_approval(h)
    assert h.agent.requests[0].model == model


async def test_without_a_saved_model_the_task_names_none(h: Harness):
    await work_leg_to_approval(h)
    assert h.agent.requests[0].model is None
