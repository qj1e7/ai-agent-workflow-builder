"""Make the approved changes (ENGINE-PLAN 2.3.8, 2.3.11 and 2.3.13): the write at the moment it
is made, checked against our records alone, through our API and a fake n8n at the HTTP edge."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from platform_api.orchestration.approvals import Decision, Ended, Refusal, Verdict
from platform_api.orchestration.dispatch import N8nWaker
from platform_api.orchestration.jira import PRACTICE_SITE
from platform_api.orchestration.model_settings import KeyBox
from platform_api.orchestration.n8n_call_book import CallBook
from platform_api.orchestration.n8n_call_service import NodeCalls
from platform_api.orchestration.n8n_calls import (
    ANOTHER_EXECUTION,
    DENIED,
    NO_YES,
    TEST_RUN_WRITES_NOTHING,
    AskCall,
    ExecutionFacts,
    NodeCatalog,
    NothingToChange,
    Refused,
    WriteAnswer,
    WriteCall,
)
from platform_api.orchestration.runs import (
    NO_ANSWER,
    Acting,
    AwaitingApproval,
    Expired,
    Failed,
    FailureReason,
    Lost,
    Outcome,
    Pending,
    Rejected,
    Succeeded,
)
from platform_api.orchestration.service import Decided, DecisionRefused, Orchestrator
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.write_actions import (
    DenyReason,
    WriteAction,
    WriteGateway,
    WriteKey,
)
from platform_api.shared import ApprovalId, N8nExecutionId, RunId
from tests.conftest import PostgresUrls
from tests.practice import PracticeKit
from tests.support import BOB, NOW, SPEC
from tests.test_n8n_calls import JIRA, WORKFLOW, FakeN8n, FakeSources
from tests.test_n8n_wait import (
    ERIN,
    N8N,
    NODE_KEY,
    PROPOSE,
    READ,
    TWO_STEPS,
    TWO_WORKING_DAYS_LATER,
    FakeLanding,
    FakeN8nWaits,
    SpecWorkflows,
    Wait,
    resume_url,
)
from tests.test_orchestrator import PUBLIC_BASE_URL, mint, open_harness

pytestmark = pytest.mark.anyio

MAKE = "Make the approved changes"


class Flaky:
    """The practice Jira, which fails each title in `down` while it is there."""

    name = "jira"
    operations = PracticeKit.operations
    site = PRACTICE_SITE

    def __init__(self, jira: PracticeKit) -> None:
        self.jira = jira
        self.down: set[str] = set()

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        if action.fields["title"] in self.down:
            raise RuntimeError("Jira is down")
        return await self.jira.execute(action, key)

    def link(self, reference: str) -> str:
        return self.jira.link(reference)


class Writes(Wait):
    flaky: Flaky

    async def write(self, execution: str = "101", node: str = MAKE) -> object:
        return await self.call(execution, WriteCall(), node)

    async def acting(self, execution: str = "101") -> RunRecord:
        """A run asked, said yes to, and woken in n8n, ready to make its change."""
        await self.ask(execution)
        await self.decide(BOB)
        await self.tick()
        run = await self.run_of(execution)
        assert isinstance(run.state, Acting)
        return run

    async def run_of(self, execution: str) -> RunRecord:
        [row] = await self.rows(
            "SELECT run_id FROM orchestration.executions WHERE execution_id = %s", execution
        )
        async with self.h.db.transaction("orchestration") as uow:
            record = await Store().load_run(uow, RunId(row["run_id"]))
        assert record is not None
        return record

    async def approval_of(self, execution: str) -> ApprovalId:
        run = await self.run_of(execution)
        [row] = await self.rows(
            "SELECT approval_id FROM orchestration.approval_requests WHERE run_id = %s",
            run.run_id,
        )
        return ApprovalId(row["approval_id"])

    async def tickets(self) -> list[str]:
        return [ticket.key for ticket in await self.h.jira.tickets()]

    def retried(self, execution: str, of: str) -> None:
        self.n8n.executions[execution] = ExecutionFacts(
            WORKFLOW, "retry", N8nExecutionId(of), None, None
        )


@pytest.fixture
async def w(postgres: PostgresUrls) -> AsyncIterator[Writes]:
    async with open_harness(postgres) as h:
        box = KeyBox("test-settings-key")
        n8n, workflows, sources = FakeN8n(), SpecWorkflows(), FakeSources()
        flaky = Flaky(h.jira)
        gateway = WriteGateway(h.db, [flaky], poll=0.05)
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
            gateway=gateway,
        )
        waits = FakeN8nWaits()
        client = httpx.AsyncClient(transport=httpx.MockTransport(waits.handle))
        orchestrator = Orchestrator(
            h.db,
            h.log,
            h.engine,
            h.teams,
            h.agent,
            gateway,
            mint,
            public_base_url=PUBLIC_BASE_URL,
            waker=N8nWaker(N8N, NODE_KEY, box, client),
        )
        writes = Writes(h, n8n, workflows, calls, waits, orchestrator, FakeLanding())
        writes.flaky = flaky
        yield writes


async def test_a_yes_n8n_took_makes_the_approved_change_once(w: Writes):
    run = await w.acting()
    answer = await w.write()
    assert isinstance(answer, WriteAnswer) and (answer.made, answer.of) == (1, 1)
    [change] = answer.results
    assert (change.change, change.status, change.reference) == (
        "Create Jira ticket in MOCK: Upgrade LangGraph",
        "made",
        "MOCK-1",
    )
    assert await w.write() == answer, "n8n's retryOnFail gets the first answer"
    done = await w.run()
    assert isinstance(done.state, Succeeded) and done.state.outcome is Outcome.WRITTEN
    assert [d.external_reference for d in done.state.written] == ["MOCK-1"]
    assert (await w.h.kinds(run.run_id))[-2:] == ["write_action_done", "run_succeeded"]
    assert await w.tickets() == ["MOCK-1"]


async def test_safety_two_make_blocks_after_one_yes_write_once(w: Writes):
    await w.acting()
    first = await w.write(node="Create ticket")
    second = await w.write(node="Create ticket again")
    assert isinstance(second, WriteAnswer) and (second.made, second.of) == (1, 1)
    assert isinstance(first, WriteAnswer) and second.results[0].reference == "MOCK-1"
    assert await w.tickets() == ["MOCK-1"]


async def test_safety_a_write_before_any_yes_stops_the_run_and_writes_nothing(w: Writes):
    """A version whose Ask for a yes was deleted or moved (ENGINE-PLAN 2.3.11)."""
    w.started("101")
    await w.call("101", READ, "Read release")
    await w.call("101", PROPOSE, "Propose a change")
    assert await w.write() == NO_YES
    assert await w.write() == NO_YES, "a repeat gets the same refusal"
    run = await w.run()
    assert isinstance(run.state, Failed)
    assert (run.state.failure.reason, run.state.failure.retryable) == (
        FailureReason.SAFETY_DENIED,
        False,
    )
    assert await w.tickets() == []


async def test_safety_a_write_while_the_request_is_open_writes_nothing(w: Writes):
    """Something woke the execution without our yes. The run still waits for the real one."""
    await w.ask()
    assert await w.write() == NO_YES
    assert isinstance((await w.run()).state, AwaitingApproval)
    assert await w.tickets() == []


async def test_safety_the_access_review_writes_only_after_two_approvers_in_turn(w: Writes):
    w.workflows.spec = replace(SPEC, approval_policy=TWO_STEPS)
    await w.ask()
    await w.decide(BOB, step=0)
    assert await w.write(node="Too early") == NO_YES
    assert isinstance((await w.run()).state, AwaitingApproval)
    await w.decide(ERIN, step=1)
    await w.tick()
    answer = await w.write()
    assert isinstance(answer, WriteAnswer) and answer.made == 1
    assert await w.tickets() == ["MOCK-1"]


async def test_safety_a_partys_yes_found_at_the_write_never_writes(w: Writes):
    """The gateway reads the decisions again at the moment of writing, so a record changed
    after the wake, here to the owner's own yes, writes nothing."""
    w.workflows.spec = replace(SPEC, approval_policy=TWO_STEPS)
    await w.ask()
    await w.decide(BOB, step=0)
    await w.decide(ERIN, step=1)
    await w.tick()
    assert isinstance((await w.run()).state, Acting)
    async with w.h.db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "UPDATE orchestration.approval_decisions SET decided_by = %s WHERE step_index = 1",
            (SPEC.owner,),
        )
    words = DENIED[DenyReason.INVALID_DECISIONS]
    assert await w.write() == Refused(403, words)
    run = await w.run()
    assert isinstance(run.state, Failed) and run.state.failure.message == words
    assert (await w.h.kinds(run.run_id))[-2:] == ["write_action_denied", "run_failed"]
    assert await w.tickets() == []


async def test_safety_a_declined_request_never_writes(w: Writes):
    await w.ask()
    await w.decide(BOB, Verdict.DECLINE)
    assert isinstance((await w.run()).state, Rejected)
    assert await w.write() == Refused(403, "An Approver said no. Nothing was written.")
    assert await w.tickets() == []


async def test_safety_a_cancelled_request_never_writes_though_its_yes_was_recorded(w: Writes):
    await w.ask()
    w.waits.answer = "down"
    await w.decide(BOB)
    async with w.h.db.transaction("orchestration") as uow:
        await Store().end_request(uow, await w.approval_id(), Ended.CANCELLED)
    assert await w.write() == NO_YES
    assert isinstance((await w.run()).state, AwaitingApproval)
    assert await w.tickets() == []


async def test_safety_an_expired_request_never_writes(w: Writes):
    await w.ask()
    await w.tick(TWO_WORKING_DAYS_LATER - NOW)
    assert isinstance((await w.run()).state, Expired)
    assert await w.write() == Refused(403, NO_ANSWER)
    assert await w.tickets() == []


@pytest.mark.parametrize("step", [0, 1])
async def test_safety_a_yes_after_the_expiry_is_refused_and_recorded_nowhere(w: Writes, step: int):
    """The tick ends a request a few seconds after its expiry. A yes in between is refused, so
    a late first yes never sends the second Approver a request that has already run out."""
    w.workflows.spec = replace(SPEC, approval_policy=TWO_STEPS)
    await w.ask()
    if step == 1:
        assert isinstance(await w.decide(BOB, step=0), Decided)
    w.h.clock["now"] = TWO_WORKING_DAYS_LATER
    late = ERIN if step == 1 else BOB
    assert await w.decide(late, step=step) == DecisionRefused(Refusal.NOT_OPEN)
    decided = await w.rows("SELECT step_index FROM orchestration.approval_decisions")
    assert decided == ([{"step_index": 0}] if step == 1 else [])
    await w.tick()
    assert isinstance((await w.run()).state, Expired)
    await w.tick()
    assert w.waits.decisions == ["no_answer"]
    assert await w.tickets() == []


async def test_safety_a_late_yes_found_in_the_records_never_writes(w: Writes):
    """Defence in depth: a yes the records hold from after the expiry, however it got there,
    is refused at the write."""
    await w.ask()
    approval_id = await w.approval_id()
    w.h.clock["now"] = TWO_WORKING_DAYS_LATER + timedelta(seconds=1)
    async with w.h.db.transaction("orchestration") as uow:
        request = await Store().load_approval(uow, approval_id)
        assert request is not None
        yes = Decision(approval_id, 0, BOB.user_id, Verdict.APPROVE, request.digest, uow.now)
        await Store().insert_decision(uow, yes)
    words = DENIED[DenyReason.EXPIRED]
    assert await w.write() == Refused(403, words)
    run = await w.run()
    assert isinstance(run.state, Failed) and run.state.failure.reason is FailureReason.SAFETY_DENIED
    assert await w.tickets() == []


async def test_safety_a_test_run_never_writes_even_with_a_yes_on_record(w: Writes):
    run = await w.acting()
    async with w.h.db.transaction("orchestration") as uow:
        await CallBook().issue_start(uow, run.run_id, "test", WORKFLOW)
    assert await w.write() == TEST_RUN_WRITES_NOTHING
    failed = await w.run()
    assert isinstance(failed.state, Failed)
    assert failed.state.failure.message == TEST_RUN_WRITES_NOTHING.detail
    assert await w.tickets() == []


async def test_a_test_run_that_stopped_at_the_gate_refuses_a_write(w: Writes):
    run_id = RunId("run_test")
    pending = Pending(run_id, 1, None, NOW)
    record = RunRecord(run_id, SPEC, BOB.user_id, NOW, NOW, 1, pending, (), None)
    async with w.h.db.transaction("orchestration") as uow:
        await Store().insert_run(uow, record, "portal:test")
        start = await CallBook().issue_start(uow, run_id, "test", WORKFLOW)
    w.started("101", "manual", start.nonce)
    w.workflows.holder = BOB.user_id
    await w.ask()
    assert await w.write() == TEST_RUN_WRITES_NOTHING
    assert await w.tickets() == []


async def test_safety_a_subject_an_earlier_run_made_is_left_out_before_anyone_is_asked(
    w: Writes,
):
    first = await w.acting("101")
    await w.write("101")
    w.started("102")
    await w.call("102", READ, "Read release")
    await w.call("102", PROPOSE, "Propose a change")
    answer = await w.call("102", AskCall(resume_url("102")), "Ask for a yes")
    assert answer == NothingToChange()
    second = await w.run_of("102")
    assert isinstance(second.state, Succeeded)
    assert second.state.outcome is Outcome.NOTHING_TO_WRITE
    events = await w.h.log.read_after(second.run_id, 0)
    assert events[-1].summary == (
        "The run succeeded. There was nothing to change. Left out, already made in run "
        f"{first.run_id}: Create Jira ticket in MOCK: Upgrade LangGraph."
    )
    assert len(await w.rows("SELECT 1 FROM orchestration.approval_requests")) == 1
    assert await w.tickets() == ["MOCK-1"]


async def test_safety_a_subject_made_while_a_later_run_waited_is_skipped_at_its_write(
    w: Writes,
):
    first = await w.acting("101")
    w.started("102")
    await w.call("102", READ, "Read release")
    await w.call("102", PROPOSE, "Propose a change")
    await w.call("102", AskCall(resume_url("102")), "Ask for a yes")
    approval = await w.approval_of("102")
    async with w.h.db.transaction("orchestration") as uow:
        request = await Store().load_approval(uow, approval)
    assert request is not None
    await w.orchestrator.decide(approval, ERIN, 0, Verdict.APPROVE, request.digest)
    await w.tick()
    assert isinstance((await w.run_of("102")).state, Acting)
    await w.write("101")
    answer = await w.write("102")
    assert isinstance(answer, WriteAnswer) and (answer.made, answer.of) == (1, 1)
    [change] = answer.results
    assert (change.status, change.reference, change.made_in) == (
        "already_made",
        "MOCK-1",
        first.run_id,
    )
    second = await w.run_of("102")
    assert isinstance(second.state, Succeeded)
    assert second.state.outcome is Outcome.NOTHING_TO_WRITE
    assert await w.tickets() == ["MOCK-1"]


async def test_safety_a_part_done_write_says_2_of_3_and_a_retry_makes_only_the_rest(w: Writes):
    w.started("101")
    await w.call("101", READ, "Read release")
    for title in ("A", "B", "C"):
        propose = replace(PROPOSE, title=title, subject=None)
        await w.call("101", propose, f"Propose {title}")
    await w.call("101", AskCall(resume_url("101")), "Ask for a yes")
    await w.decide(BOB)
    await w.tick()
    w.flaky.down = {"C"}
    answer = await w.write()
    assert isinstance(answer, WriteAnswer) and (answer.made, answer.of) == (2, 3)
    assert [c.status for c in answer.results] == ["made", "made", "not_made"]
    run = await w.run()
    assert isinstance(run.state, Failed) and run.state.failure.retryable
    assert run.state.failure.message.startswith("2 of 3 made. ")
    assert await w.tickets() == ["MOCK-1", "MOCK-2"]
    assert (await w.h.kinds(run.run_id)).count("write_action_done") == 2

    w.flaky.down = set()
    w.retried("201", of="101")
    again = await w.write("201")
    assert isinstance(again, WriteAnswer) and (again.made, again.of) == (3, 3)
    assert await w.tickets() == ["MOCK-1", "MOCK-2", "MOCK-3"]
    done = await w.run()
    assert isinstance(done.state, Succeeded) and len(done.state.written) == 3
    assert (await w.h.kinds(run.run_id)).count("write_action_done") == 3


async def test_a_lost_run_carries_on_when_its_waiting_execution_writes(w: Writes):
    """n8n took the yes, but our record of the wake was lost, and the retried wake met a 409."""
    await w.ask()
    w.waits.answer = "gone"
    await w.decide(BOB)
    await w.tick()
    run = await w.run()
    assert isinstance(run.state, Lost)
    answer = await w.write()
    assert isinstance(answer, WriteAnswer) and answer.made == 1
    assert isinstance((await w.run()).state, Succeeded)
    kinds = await w.h.kinds(run.run_id)
    assert kinds[kinds.index("run_lost") + 1] == "execution_resumed"
    assert await w.tickets() == ["MOCK-1"]


async def test_a_write_that_beats_the_wakes_answer_carries_the_run_on(w: Writes):
    """n8n took the wake, but its answer never reached us, so the run still waits."""
    await w.ask()
    w.waits.answer = "down"
    await w.decide(BOB)
    await w.tick()
    assert isinstance((await w.run()).state, AwaitingApproval)
    answer = await w.write()
    assert isinstance(answer, WriteAnswer) and answer.made == 1
    w.waits.answer = "ok"
    await w.tick(timedelta(minutes=10))
    assert isinstance((await w.run()).state, Succeeded)
    assert await w.tickets() == ["MOCK-1"]


async def retried_before_the_ask(w: Writes) -> None:
    """101 reads and stops past its deadline. n8n's retry of it, 201, asks and waits, so both
    executions are the run's, and only 201 waits for the yes."""
    w.started("101")
    await w.call("101", READ, "Read release")
    await w.tick(timedelta(minutes=9))
    w.retried("201", of="101")
    await w.ask("201")


async def test_safety_only_the_execution_the_run_acts_in_writes(w: Writes):
    await retried_before_the_ask(w)
    await w.decide(BOB)
    await w.tick()
    run = await w.run()
    assert isinstance(run.state, Acting) and run.state.claimant == "201"
    assert await w.write("101") == ANOTHER_EXECUTION
    assert await w.tickets() == []
    assert isinstance(await w.write("201"), WriteAnswer)
    assert await w.tickets() == ["MOCK-1"]


async def test_safety_only_the_execution_that_waited_may_take_a_yes_our_records_missed(
    w: Writes,
):
    await retried_before_the_ask(w)
    w.waits.answer = "down"
    await w.decide(BOB)
    await w.tick()
    assert await w.write("101") == NO_YES
    assert isinstance((await w.run()).state, AwaitingApproval)
    w.waits.answer = "gone"
    await w.tick(timedelta(minutes=10))
    assert isinstance((await w.run()).state, Lost)
    refused = await w.write("101", node="Make the changes again")
    assert isinstance(refused, Refused) and refused.status == 409
    w.retried("301", of="201")
    assert await w.write("301") == Refused(409, "This run cannot take a retry while it is lost.")
    w.started("102")
    assert await w.write("102") == NO_YES, "a new execution is a new run with no yes"
    assert isinstance((await w.run_of("201")).state, Lost)
    assert await w.tickets() == []
    assert isinstance(await w.write("201"), WriteAnswer)
    assert await w.tickets() == ["MOCK-1"]


async def test_safety_a_lost_run_past_its_requests_expiry_never_carries_on(w: Writes):
    await w.ask()
    w.waits.answer = "gone"
    await w.decide(BOB)
    await w.tick()
    w.h.clock["now"] = TWO_WORKING_DAYS_LATER + timedelta(seconds=1)
    refused = await w.write()
    assert isinstance(refused, Refused) and refused.status == 409
    assert isinstance((await w.run()).state, Lost)
    assert await w.tickets() == []
