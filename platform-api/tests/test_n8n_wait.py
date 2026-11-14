"""Ask for a yes held in n8n (ENGINE-PLAN 2.3.4 to 2.3.7 and 2.3.13): the ask, the wake with its
mac, expiry and the lost run, through our API's own records and a fake n8n at the HTTP edge."""

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString

import httpx
import pytest

from platform_api.app import create_app
from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalStep,
    Ended,
    Refusal,
    Verdict,
)
from platform_api.orchestration.dispatch import N8nWaker
from platform_api.orchestration.jira import PRACTICE_SITE
from platform_api.orchestration.model_settings import KeyBox
from platform_api.orchestration.n8n_call_book import CallBook
from platform_api.orchestration.n8n_call_service import NodeCalls
from platform_api.orchestration.n8n_calls import (
    TEST_RUN_STOPS,
    AskCall,
    ExecutionFacts,
    NodeCall,
    NodeCatalog,
    NothingToChange,
    OwnWorkflow,
    ProposeCall,
    ReadCall,
    Waiting,
    Work,
)
from platform_api.orchestration.runs import (
    DEADLINES,
    NO_ANSWER,
    Acting,
    AwaitingApproval,
    Expired,
    Lost,
    Outcome,
    Pending,
    Rejected,
    StepName,
    Succeeded,
)
from platform_api.orchestration.service import Decided, DecisionRefused, Orchestrator, steps_view
from platform_api.orchestration.spec import RunSpec
from platform_api.orchestration.store import WAKE, RunRecord, Store
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.shared import ApprovalId, N8nExecutionId, Principal, Role, RunId, UserId
from tests.conftest import PostgresUrls
from tests.support import ALICE, BOB, LOCAL_ENV, NOW, SPEC
from tests.test_n8n_calls import JIRA, REPO, WORKFLOW, FakeN8n, FakeSources, FakeWorkflows
from tests.test_orchestrator import PUBLIC_BASE_URL, Harness, mint, open_harness

pytestmark = pytest.mark.anyio

N8N = "http://n8n:5678"
NODE_KEY = "test-node-key"
SIGNATURE = "n8n-signed-resume-token-7f3a"
ERIN = Principal(UserId("erin"), frozenset({Role.APPROVER}), "Erin")
DAVE = Principal(UserId("dave"), frozenset({Role.OPERATOR, Role.APPROVER}), "Dave")
TWO_STEPS = ApprovalPolicy(
    (ApprovalStep("First Approver", AnyApprover()), ApprovalStep("Second", AnyApprover()))
)
READ = ReadCall("github_releases", REPO, None)
PROPOSE = ProposeCall("jira.create_ticket", "MOCK", "Upgrade LangGraph", "1.2.16 is out.", "lg")
TWO_WORKING_DAYS_LATER = datetime(2026, 11, 5, 2, 14, tzinfo=UTC)
"""NOW is Tuesday 10:14 in Singapore, so the default expiry is Thursday 10:14 there."""


def resume_url(execution: str) -> str:
    return f"{N8N}/webhook-waiting/{execution}?signature={SIGNATURE}"


def node_accepts(body: dict[str, Any], execution: str, request_id: str) -> bool:
    """Ask for a yes's own check (n8n-node-pack/src/nodes/AskForYes.node.ts), in Python."""
    signed = "\n".join((execution, request_id, body["decision"]))
    mac = hmac.new(NODE_KEY.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return (
        (body["execution_id"], body["request_id"]) == (execution, request_id)
        and isinstance(body.get("mac"), str)
        and hmac.compare_digest(mac, body["mac"])
    )


@dataclass
class FakeN8nWaits:
    """n8n's waiting-webhook endpoint: it takes the wake, answers 409, or is down."""

    answer: str = "ok"
    posts: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.answer == "down":
            raise httpx.ConnectError(f"cannot reach {request.url}")
        self.posts.append((str(request.url), json.loads(request.content)))
        if self.answer == "took it, answer lost":
            raise httpx.ReadTimeout(f"no answer from {request.url}")
        return httpx.Response(409 if self.answer == "gone" else 200, json={})

    @property
    def decisions(self) -> list[str]:
        return [body["decision"] for _, body in self.posts]


@dataclass
class FakeLanding:
    """What n8n's record of each execution says after a wake met a 409."""

    ran: set[str] = field(default_factory=set[str])

    async def landed(self, execution_id: N8nExecutionId) -> bool:
        return execution_id in self.ran


@dataclass
class SpecWorkflows(FakeWorkflows):
    spec: RunSpec = SPEC

    async def workflow(self, n8n_workflow_id: str) -> OwnWorkflow | None:
        own = await super().workflow(n8n_workflow_id)
        return None if own is None else OwnWorkflow(self.spec, own.holder)


@dataclass
class Wait:
    h: Harness
    n8n: FakeN8n
    workflows: SpecWorkflows
    calls: NodeCalls
    waits: FakeN8nWaits
    orchestrator: Orchestrator
    landing: FakeLanding

    def started(self, execution: str, mode: str = "trigger", nonce: str | None = None) -> None:
        self.n8n.executions[execution] = ExecutionFacts(WORKFLOW, mode, None, nonce, "v1")

    async def call(self, execution: str, work: Work, node: str) -> object:
        return await self.calls.call(NodeCall(N8nExecutionId(execution), node, work))

    async def ask(self, execution: str = "101", *, propose: bool = True) -> object:
        if execution not in self.n8n.executions:
            self.started(execution)
        await self.call(execution, READ, "Read release")
        if propose:
            await self.call(execution, PROPOSE, "Propose a change")
        return await self.call(execution, AskCall(resume_url(execution)), "Ask for a yes")

    async def run(self) -> RunRecord:
        [record] = await self.runs()
        return record

    async def runs(self) -> list[RunRecord]:
        async with self.h.db.transaction("orchestration") as uow:
            return await Store().list_runs(uow)

    async def approval_id(self) -> ApprovalId:
        [row] = await self.rows("SELECT approval_id FROM orchestration.approval_requests")
        return ApprovalId(row["approval_id"])

    async def decide(
        self, by: Principal, verdict: Verdict = Verdict.APPROVE, step: int = 0
    ) -> object:
        approval_id = await self.approval_id()
        async with self.h.db.transaction("orchestration") as uow:
            request = await Store().load_approval(uow, approval_id)
        assert request is not None
        return await self.orchestrator.decide(approval_id, by, step, verdict, request.digest)

    async def tick(self, later: timedelta = timedelta()) -> None:
        self.h.advance(later)
        await self.orchestrator.tick(self.h.clock["now"])

    async def rows(self, sql: LiteralString, *args: object) -> list[dict[str, Any]]:
        async with self.h.db.transaction("orchestration") as uow:
            return [dict(r) for r in await (await uow.conn.execute(sql, args)).fetchall()]

    async def wake_rows(self) -> list[dict[str, Any]]:
        return await self.rows(
            "SELECT payload, status, last_error FROM orchestration.outbox "
            "WHERE kind = %s ORDER BY id",
            WAKE,
        )

    async def stray_wake(self, decision: str) -> None:
        """A wake row the records never asked for, as a bug or a tampered row would leave."""
        run, approval_id = await self.run(), await self.approval_id()
        async with self.h.db.transaction("orchestration") as uow:
            payload = {"approval_id": approval_id, "decision": decision}
            await Store().enqueue(uow, run.run_id, WAKE, payload, uow.now)


@pytest.fixture
async def w(postgres: PostgresUrls) -> AsyncIterator[Wait]:
    async with open_harness(postgres) as h:
        box = KeyBox("test-settings-key")
        n8n, workflows, sources = FakeN8n(), SpecWorkflows(), FakeSources()
        calls = NodeCalls(
            h.db,
            h.log,
            h.agent,
            mint,
            NodeCatalog(workflows, sources, [JIRA]),
            workflows,
            n8n,
            sources,
            {"jira": PRACTICE_SITE},
            box=box,
        )
        waits = FakeN8nWaits()
        client = httpx.AsyncClient(transport=httpx.MockTransport(waits.handle))
        orchestrator = Orchestrator(
            h.db,
            h.log,
            h.engine,
            h.teams,
            h.agent,
            WriteGateway(h.db, [h.jira], poll=0.05),
            mint,
            public_base_url=PUBLIC_BASE_URL,
            waker=N8nWaker(N8N, NODE_KEY, box, client),
            landing=(landing := FakeLanding()),
        )
        yield Wait(h, n8n, workflows, calls, waits, orchestrator, landing)


async def test_the_ask_makes_one_request_for_what_the_blocks_proposed(w: Wait):
    answer = await w.ask()
    approval_id = await w.approval_id()
    assert answer == Waiting(approval_id)
    run = await w.run()
    assert isinstance(run.state, AwaitingApproval) and run.state.approval_id == approval_id
    async with w.h.db.transaction("orchestration") as uow:
        request = await Store().load_approval(uow, approval_id)
        proposal = await Store().load_proposal(uow, run.state.proposal_id)
    assert request is not None and proposal is not None
    assert [(a.connector, a.fields["title"]) for a in proposal.actions] == [
        ("jira", "Upgrade LangGraph")
    ]
    assert (request.parties, request.expires_at) == (run.parties, TWO_WORKING_DAYS_LATER)
    assert await w.h.kinds(run.run_id) == [
        "run_created",
        "execution_linked",
        "write_action_proposed",
        "approval_requested",
    ]
    await w.tick()
    assert len(await w.h.teams.messages()) == 1


async def test_a_repeated_ask_gets_its_first_answer_and_asks_nobody_twice(w: Wait):
    first = await w.ask()
    again = await w.call("101", AskCall(resume_url("101")), "Ask for a yes")
    assert again == first
    assert len(await w.rows("SELECT 1 FROM orchestration.approval_requests")) == 1


async def test_an_ask_with_nothing_proposed_leaves_by_nothing_to_change(w: Wait):
    assert await w.ask(propose=False) == NothingToChange()
    run = await w.run()
    assert run.state == Succeeded(run.run_id, Outcome.NOTHING_TO_WRITE, ())
    assert await w.rows("SELECT 1 FROM orchestration.approval_requests") == []


async def test_a_test_run_stops_at_the_gate_and_asks_nobody(w: Wait):
    """ENGINE-PLAN 2.3.3: the run shows what it would ask, and nothing is asked or written."""
    run_id = RunId("run_test")
    record = RunRecord(
        run_id, SPEC, BOB.user_id, NOW, NOW, 1, Pending(run_id, 1, None, NOW), (), None
    )
    async with w.h.db.transaction("orchestration") as uow:
        await Store().insert_run(uow, record, "portal:test")
        start = await CallBook().issue_start(uow, run_id, "test", WORKFLOW)
    w.started("101", "manual", start.nonce)
    w.workflows.holder = BOB.user_id
    assert await w.ask() == TEST_RUN_STOPS
    run = await w.run()
    assert run.state == Succeeded(run_id, Outcome.TEST_PASSED, ())
    assert await w.rows("SELECT 1 FROM orchestration.approval_requests") == []
    assert await w.rows("SELECT 1 FROM orchestration.outbox WHERE run_id = %s", run_id) == []
    assert (await w.h.kinds(run_id))[-2:] == ["write_action_proposed", "run_succeeded"]


async def test_two_runs_that_reach_the_ask_together_make_one_request(w: Wait):
    """ADR 0026: one waiting run per workflow. Both runs started before either waited, so both
    passed the first call's check."""
    for execution in ("101", "102"):
        w.started(execution)
        await w.call(execution, READ, "Read release")
        await w.call(execution, PROPOSE, "Propose a change")
    asks = [w.call(e, AskCall(resume_url(e)), "Ask for a yes") for e in ("101", "102")]
    answers = await asyncio.gather(*asks)
    states = sorted(type(run.state).__name__ for run in await w.runs())
    assert states == ["AwaitingApproval", "Skipped"]
    assert len(await w.rows("SELECT 1 FROM orchestration.approval_requests")) == 1
    assert NothingToChange() in answers
    await w.tick()
    assert len(await w.h.teams.messages()) == 1


async def test_a_skipped_run_that_reaches_the_ask_leaves_by_nothing_to_change(w: Wait):
    await w.ask("101")
    w.started("102")
    answer = await w.call("102", AskCall(resume_url("102")), "Ask for a yes")
    assert answer == NothingToChange()


async def test_an_expired_requests_undecided_steps_read_expired_in_every_view(w: Wait):
    w.workflows.spec = replace(SPEC, approval_policy=TWO_STEPS)
    await w.ask()
    approval_id = await w.approval_id()
    await w.decide(BOB, step=0)
    await w.tick(TWO_WORKING_DAYS_LATER - NOW)
    detail = await w.orchestrator.get_approval(approval_id, ERIN)
    assert detail is not None
    statuses = [step.status for step in steps_view(detail.request, detail.decisions)]
    assert statuses == ["approved", "expired"]


async def test_a_yes_wakes_n8n_and_the_run_acts_only_once_n8n_takes_it(w: Wait):
    await w.ask()
    approval_id = await w.approval_id()
    w.waits.answer = "down"
    assert isinstance(await w.decide(BOB), Decided)
    await w.tick()
    run = await w.run()
    assert isinstance(run.state, AwaitingApproval)
    [row] = await w.wake_rows()
    assert (row["payload"], row["status"]) == (
        {"approval_id": approval_id, "decision": "yes"},
        "pending",
    )

    w.waits.answer = "ok"
    await w.tick(timedelta(minutes=10))
    run = await w.run()
    assert isinstance(run.state, Acting)
    deadline = w.h.clock["now"] + DEADLINES[Acting]
    assert (run.state.approval_id, run.state.claimant, run.state.deadline_at) == (
        approval_id,
        N8nExecutionId("101"),
        deadline,
    )
    [(url, body)] = w.waits.posts
    assert url == resume_url("101")
    assert body["decision"] == "yes" and node_accepts(body, "101", approval_id)
    assert (await w.h.kinds(run.run_id))[-1] == "execution_resumed"


async def test_a_no_ends_the_run_declined_and_wakes_n8n_with_no(w: Wait):
    await w.ask()
    await w.decide(BOB, Verdict.DECLINE)
    assert isinstance((await w.run()).state, Rejected)
    await w.tick()
    assert w.waits.decisions == ["no"]
    assert isinstance((await w.run()).state, Rejected)


async def test_a_409_on_the_wake_loses_the_run_at_once(w: Wait):
    """On a first try a 409 means something else resumed the execution, even when n8n shows it
    running, so the run is lost."""
    await w.ask()
    w.landing.ran.add("101")
    w.waits.answer = "gone"
    await w.decide(BOB)
    await w.tick()
    run = await w.run()
    assert isinstance(run.state, Lost)
    assert (await w.h.kinds(run.run_id))[-1] == "run_lost"
    [row] = await w.wake_rows()
    assert row["status"] == "given_up"


async def test_a_409_after_an_earlier_try_that_n8n_took_is_delivered_not_lost(w: Wait):
    """E2b's lost answer: the first try resumed the execution but its answer never came back, so
    the retry meets a 409. n8n shows the execution running, so the yes was delivered."""
    await w.ask()
    w.landing.ran.add("101")
    w.waits.answer = "took it, answer lost"
    await w.decide(BOB)
    await w.tick()
    assert isinstance((await w.run()).state, AwaitingApproval)
    w.waits.answer = "gone"
    await w.tick(timedelta(minutes=1))
    run = await w.run()
    assert isinstance(run.state, Acting)
    assert (await w.h.kinds(run.run_id))[-1] == "execution_resumed"
    [row] = await w.wake_rows()
    assert row["status"] == "sent"


async def test_a_409_after_an_earlier_try_is_lost_when_n8n_shows_no_run(w: Wait):
    await w.ask()
    w.waits.answer = "took it, answer lost"
    await w.decide(BOB)
    await w.tick()
    w.waits.answer = "gone"
    await w.tick(timedelta(minutes=1))
    assert isinstance((await w.run()).state, Lost)


async def test_a_wake_n8n_cannot_take_for_a_day_loses_the_run(w: Wait):
    await w.ask()
    w.waits.answer = "down"
    await w.decide(BOB)
    await w.tick()
    for _ in range(5):
        await w.tick(timedelta(minutes=1))
    assert isinstance((await w.run()).state, AwaitingApproval)
    await w.tick(timedelta(hours=23, minutes=55))
    await w.tick(timedelta(minutes=5))
    run = await w.run()
    assert isinstance(run.state, Lost)
    assert w.waits.posts == []


async def test_a_request_nobody_answers_expires_after_two_working_days_with_no_answer(w: Wait):
    await w.ask()
    w.h.clock["now"] = TWO_WORKING_DAYS_LATER - timedelta(minutes=1)
    await w.tick()
    assert isinstance((await w.run()).state, AwaitingApproval)
    await w.tick(timedelta(minutes=1))
    run = await w.run()
    assert isinstance(run.state, Expired)
    events = await w.h.log.read_after(run.run_id, 0)
    assert (events[-1].kind, events[-1].summary) == ("run_expired", NO_ANSWER)
    await w.tick()
    assert w.waits.decisions == ["no_answer"]


async def test_an_approved_request_never_expires_while_n8n_wakes(w: Wait):
    await w.ask()
    w.waits.answer = "down"
    w.h.clock["now"] = TWO_WORKING_DAYS_LATER - timedelta(minutes=1)
    await w.decide(BOB)
    await w.tick(timedelta(hours=1))
    run = await w.run()
    assert isinstance(run.state, AwaitingApproval)
    w.waits.answer = "ok"
    await w.tick(timedelta(minutes=5))
    assert isinstance((await w.run()).state, Acting)


async def test_an_old_engine_request_expires_too_and_wakes_nothing(w: Wait):
    started = await w.orchestrator.start_run(SPEC, ALICE, "key-1")
    await w.orchestrator.tick()
    execution = N8nExecutionId("41")
    await w.orchestrator.on_step(started.run_id, StepName.RUN_AGENTS, execution)
    await w.orchestrator.on_step(started.run_id, StepName.ASK_APPROVAL, execution)
    w.h.clock["now"] = TWO_WORKING_DAYS_LATER
    await w.tick()
    assert isinstance((await w.run()).state, Expired)
    assert await w.wake_rows() == []
    tickets = await w.rows("SELECT status FROM orchestration.proposed_tickets")
    assert tickets == [{"status": "dropped"}], "the next check proposes it again (ADR 0024)"


# The safety rules, each with a test that fails when its guard is removed (see mutate.py).


@pytest.mark.parametrize("party", ["started_by", "owner", "holder"])
async def test_safety_no_party_to_the_run_can_approve_its_request(w: Wait, party: str):
    """The Portal's Run now by Bob, carried by a run by hand in n8n that Dave holds, of Alice's
    workflow: Bob, Alice and Dave are each its party."""
    run_id = RunId("run_portal")
    record = RunRecord(
        run_id, SPEC, BOB.user_id, NOW, NOW, 1, Pending(run_id, 1, None, NOW), (), None
    )
    async with w.h.db.transaction("orchestration") as uow:
        await Store().insert_run(uow, record, "portal:run")
        start = await CallBook().issue_start(uow, run_id, "run_now", WORKFLOW)
    w.started("101", "manual", start.nonce)
    w.workflows.holder = DAVE.user_id
    await w.ask()
    who = {"started_by": BOB, "owner": ALICE, "holder": DAVE}[party]
    assert await w.decide(who) == DecisionRefused(Refusal.OWN_WORK)
    assert await w.wake_rows() == []
    assert isinstance(await w.decide(ERIN), Decided)


async def test_safety_the_access_review_needs_two_approvers_in_turn_before_n8n_wakes(w: Wait):
    w.workflows.spec = replace(SPEC, approval_policy=TWO_STEPS)
    await w.ask()
    assert isinstance(await w.decide(BOB, step=0), Decided)
    assert await w.wake_rows() == []
    assert await w.decide(BOB, step=1) == DecisionRefused(Refusal.DECIDED_EARLIER_STEP)
    assert await w.wake_rows() == []
    assert isinstance(await w.decide(ERIN, step=1), Decided)
    await w.tick()
    assert w.waits.decisions == ["yes"]


async def test_safety_a_wake_carries_only_the_decision_the_records_hold(w: Wait):
    await w.ask()
    await w.decide(BOB, Verdict.DECLINE)
    await w.stray_wake("yes")
    await w.tick()
    assert w.waits.decisions == ["no"]


async def test_safety_a_decision_wakes_n8n_once(w: Wait):
    await w.ask()
    await w.decide(BOB)
    await w.tick()
    run = await w.run()
    async with w.h.db.transaction("orchestration") as uow:
        await w.orchestrator._enqueue_wake(uow, run.run_id, await w.approval_id(), "yes")  # pyright: ignore[reportPrivateUsage]
    await w.tick()
    assert w.waits.decisions == ["yes"]
    assert len(await w.wake_rows()) == 1


@pytest.mark.parametrize("ended", ["expired", "cancelled", "lost"])
async def test_safety_an_expired_cancelled_or_lost_request_never_wakes_with_a_decision(
    w: Wait, ended: str
):
    await w.ask()
    approval_id = await w.approval_id()
    match ended:
        case "expired":
            await w.tick(TWO_WORKING_DAYS_LATER - NOW)
            assert await w.decide(BOB) == DecisionRefused(Refusal.NOT_OPEN)
        case "cancelled":
            async with w.h.db.transaction("orchestration") as uow:
                await Store().end_request(uow, approval_id, Ended.CANCELLED)
            assert await w.decide(BOB) == DecisionRefused(Refusal.NOT_OPEN)
        case _:
            w.waits.answer = "gone"
            await w.decide(BOB)
            await w.tick()
            assert isinstance((await w.run()).state, Lost)
            w.waits.answer = "ok"
            w.waits.posts.clear()
    await w.stray_wake("yes")
    await w.stray_wake("no")
    await w.tick()
    assert "yes" not in w.waits.decisions and "no" not in w.waits.decisions


async def test_safety_a_wake_never_writes_and_starts_no_write_of_its_own(w: Wait):
    await w.ask()
    await w.decide(BOB)
    for _ in range(3):
        await w.tick(timedelta(seconds=30))
    assert isinstance((await w.run()).state, Acting)
    assert w.h.engine.legs == []
    assert await w.rows("SELECT 1 FROM orchestration.write_executions") == []
    assert await w.rows("SELECT 1 FROM orchestration.mock_jira_tickets") == []


async def test_safety_the_wake_keys_off_our_request_id_not_n8ns_execution_id(w: Wait):
    await w.ask()
    approval_id = await w.approval_id()
    await w.decide(BOB)
    await w.tick()
    [(_, body)] = w.waits.posts
    assert body["request_id"] == approval_id != body["execution_id"]
    assert node_accepts(body, "101", approval_id)
    forged = {**body, "request_id": "101"}
    assert not node_accepts(forged, "101", approval_id)


async def test_safety_nothing_logs_or_returns_the_node_key_or_the_resume_signature(
    w: Wait, caplog: pytest.LogCaptureFixture
):
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.NOTSET)
    create_app(LOCAL_ENV)
    caplog.set_level(logging.DEBUG)
    answer = await w.ask()
    w.waits.answer = "down"
    await w.decide(BOB)
    await w.tick()
    retrying = await w.wake_rows()
    w.waits.answer = "gone"
    await w.tick(timedelta(minutes=1))
    run = await w.run()
    assert isinstance(run.state, Lost)
    events = [e.model_dump(mode="json") for e in await w.h.log.read_after(run.run_id, 0)]
    kept = await w.rows("SELECT resume_url FROM orchestration.approval_requests")
    calls = await w.rows("SELECT answer FROM orchestration.node_calls")
    seen = json.dumps([repr(answer), events, retrying, kept, calls], default=str) + caplog.text
    assert SIGNATURE not in seen and NODE_KEY not in seen and "webhook-waiting" not in seen
    assert retrying[0]["last_error"] == "n8n did not answer the wake (ConnectError)"
