"""The Orchestrator against real PostgreSQL, driven step by step as n8n would drive it."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from platform_api.db import Database
from platform_api.monitoring import ActivityLog
from platform_api.orchestration.agents import (
    AgentReply,
    AgentUnavailable,
    TaskRequest,
    task_result_adapter,
)
from platform_api.orchestration.approvals import Approved, Declined, Refusal, Verdict
from platform_api.orchestration.dispatch import ApprovalNotice, DispatchFailure, TeamsStub
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
    StepReply,
)
from platform_api.orchestration.write_actions import MockJiraConnector, WriteGateway
from platform_api.shared import ApprovalId, Digest, N8nExecutionId, RunId, TaskId
from tests.conftest import PostgresUrls, truncate_all
from tests.support import ALICE, BOB, CAROL, NOW, SPEC, fixture

pytestmark = pytest.mark.anyio

RUN_AGENTS = StepName.RUN_AGENTS
ASK_APPROVAL = StepName.ASK_APPROVAL
WRITE_ACTION = StepName.WRITE_ACTION


@dataclass
class RecordingEngine:
    """Hands out execution ids and remembers every leg it was asked to start."""

    legs: list[tuple[str, Leg, RunId]] = field(default_factory=list)
    next_execution: int = 41
    down: bool = False

    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId:
        if self.down:
            raise DispatchFailure("n8n is down")
        self.legs.append((workflow, leg, run_id))
        execution = N8nExecutionId(str(self.next_execution))
        self.next_execution += 1
        return execution


@dataclass
class FakeAgent:
    """Replays the contract fixtures, and remembers each request it was sent."""

    mode: str = "finished"
    requests: list[TaskRequest] = field(default_factory=list)

    async def run_task(self, request: TaskRequest) -> AgentReply:
        self.requests.append(request)
        if self.mode == "down":
            return AgentUnavailable("connection refused")
        name = "task-finished" if self.mode == "finished" else "task-failed"
        result = task_result_adapter.validate_python(fixture(f"agent/{name}.json"))
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
        """A second instance over the same database, as after a restart."""
        return Orchestrator(
            self.db,
            self.log,
            self.engine,
            self.teams,
            self.agent,
            WriteGateway(self.db, [self.jira], poll=0.05),
            mint,
        )

    async def kinds(self, run_id: RunId) -> list[str]:
        return [e.kind for e in await self.log.read_after(run_id, 0)]

    async def state(self, run_id: RunId) -> RunState:
        detail = await self.orchestrator.get_run(run_id)
        assert detail is not None
        return detail.record.state


def mint(run_id: RunId, task_id: TaskId, expires_at: datetime) -> tuple[str, str]:
    return (f"http://platform-api:8000/cb/{run_id}?task={task_id}", f"token-{task_id}")


@pytest.fixture
async def h(postgres: PostgresUrls) -> AsyncIterator[Harness]:
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
        db, log, engine, teams, agent, WriteGateway(db, [jira], poll=0.05), mint
    )
    try:
        yield Harness(db, clock, log, engine, agent, jira, teams, orchestrator)
    finally:
        await db.close()


async def start(h: Harness, key: str = "key-1") -> RunId:
    started = await h.orchestrator.start_run(SPEC, ALICE, key)
    return started.run_id


async def work_leg_to_approval(h: Harness) -> tuple[RunId, N8nExecutionId, ApprovalId]:
    run_id = await start(h)
    await h.orchestrator.tick()
    execution = N8nExecutionId("41")
    assert await h.orchestrator.on_step(run_id, RUN_AGENTS, execution) == StepReply(
        True, "proposed", "2 new releases: 1.2.16, 1.2.15"
    )
    reply = await h.orchestrator.on_step(run_id, ASK_APPROVAL, execution)
    assert (reply.proceed, reply.outcome) == (False, "approval_opened")
    await h.orchestrator.tick()
    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    return run_id, execution, state.approval_id


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


async def test_the_outbox_survives_a_crash_between_commit_and_dispatch(h: Harness):
    run_id = await start(h)
    restarted = h.new_orchestrator()
    await restarted.tick()
    assert h.engine.legs == [("release_check", Leg.WORK, run_id)]
    await restarted.tick()
    assert len(h.engine.legs) == 1


async def test_the_whole_success_path_matches_the_recorded_run(h: Harness):
    run_id, _, approval_id = await work_leg_to_approval(h)
    assert isinstance(await h.state(run_id), AwaitingApproval)
    request = h.agent.requests[0]
    assert request.task_id == f"{run_id}/work/1"
    assert request.callback.token == f"token-{run_id}/work/1"
    assert request.carry_forward.last_known_tag == "1.2.14"
    messages = await h.teams.messages()
    assert len(messages) == 1
    assert "New LangGraph releases: 1.2.16, 1.2.15" in messages[0].text
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
    assert h.engine.legs[-1] == ("release_check", Leg.ACT, run_id)

    reply = await h.orchestrator.on_step(run_id, WRITE_ACTION, N8nExecutionId("42"))
    assert reply == StepReply(True, "written", "Created MOCK-1")
    final = await h.state(run_id)
    assert isinstance(final, Succeeded)
    assert [t.key for t in await h.jira.tickets()] == ["MOCK-1"]

    expected = [e["kind"] for e in fixture("runs/success.json")]
    assert await h.kinds(run_id) == expected
    assert await h.orchestrator.latest_carry_forward(SPEC.use_case_id) == "1.2.16"


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
        N8nExecutionId("41"), "release_check", "Run agents", "The service refused the connection"
    )
    state = await h.state(run_id)
    assert isinstance(state, Failed)
    assert state.failure.reason is FailureReason.WORKFLOW_NODE_ERROR
    await h.orchestrator.on_workflow_failure(N8nExecutionId("41"), "release_check", "x", "again")
    assert await h.state(run_id) == state
    await h.orchestrator.on_workflow_failure(N8nExecutionId("404"), "release_check", "x", "y")


async def test_a_failed_write_is_retried_as_acting_and_makes_one_ticket(h: Harness):
    run_id, _, approval_id = await work_leg_to_approval(h)
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    await h.orchestrator.decide(approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest)
    await h.orchestrator.tick()
    await h.orchestrator.on_workflow_failure(
        N8nExecutionId("42"), "release_check", "Do write action", "timed out"
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

        async def announce(self, notice: ApprovalNotice) -> None:
            raise DispatchFailure("Teams is down")

    h.orchestrator = Orchestrator(
        h.db, h.log, h.engine, FlakyTeams(), h.agent, WriteGateway(h.db, [h.jira]), mint
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
