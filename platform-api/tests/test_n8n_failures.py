"""Failures reported through Report a failure, or found by the sweep (ENGINE-PLAN 2.3.9 and 2.8):
each fails the run its execution carried, with the block's words, and never a run that ended."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from platform_api.db import json
from platform_api.orchestration.n8n_call_service import (
    CallBook,
    FailedRun,
    FailureResult,
    LeftAsIs,
    NodeCalls,
)
from platform_api.orchestration.n8n_calls import (
    NOT_FAILED,
    NOT_OUR_ERROR_WORKFLOW,
    AskCall,
    Ended,
    ExecutionFacts,
    FailedExecution,
    Finished,
    NodeCall,
    NodeCatalog,
    ProposeCall,
    ReadCall,
    TryLater,
)
from platform_api.orchestration.runs import (
    Acting,
    Failed,
    FailureReason,
    Outcome,
    Pending,
    RunState,
    Stage,
    Succeeded,
)
from platform_api.orchestration.spec import N8nTarget
from platform_api.orchestration.store import RunRecord, Store
from platform_api.shared import ApprovalId, N8nExecutionId, ProposalId, RunId
from tests.conftest import PostgresUrls
from tests.declared import NODE_KEY, NODE_KEY_ENV, FakeNodeCalls, app_with, declared_status
from tests.support import NOW, SPEC
from tests.test_n8n_calls import JIRA, REPO, WORKFLOW, FakeN8n, FakeSources, FakeWorkflows
from tests.test_orchestrator import Harness, mint, open_harness

pytestmark = pytest.mark.anyio

READ = ReadCall("github_releases", REPO, None)
PROPOSE = ProposeCall("jira.create_ticket", "MOCK", "Upgrade LangGraph", "1.2.16 is out.", None)
ASK = AskCall("http://n8n:5678/webhook-waiting/101?signature=abc")
ERROR_WORKFLOW = "wf_errors"
REPORTER = N8nExecutionId("900")


@dataclass
class FakeFailures:
    """n8n's failed executions, as the public API lists them, what each one's data says, and
    which workflow is the platform's error workflow."""

    errored: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    words: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])
    error_workflow: str | None = ERROR_WORKFLOW
    read: list[str] = field(default_factory=list[str])
    finished: set[str] = field(default_factory=set[str])

    async def error_workflow_id(self) -> str | None:
        return self.error_workflow

    async def ended(self, execution_id: N8nExecutionId) -> Ended | None:
        if execution_id in self.finished:
            return Finished(execution_id)
        return await self.failure(execution_id)

    async def failure(self, execution_id: N8nExecutionId) -> FailedExecution | None:
        self.read.append(execution_id)
        if not any(execution_id in listed for listed in self.errored.values()):
            return None
        node, message = self.words.get(execution_id, ("Read release", "GitHub did not answer"))
        return FailedExecution(execution_id, node, message)


@dataclass
class Reports:
    h: Harness
    n8n: FakeN8n
    workflows: FakeWorkflows
    failures: FakeFailures
    calls: NodeCalls

    def started(self, execution: str, mode: str = "trigger", nonce: str | None = None) -> None:
        self.n8n.executions[execution] = ExecutionFacts(WORKFLOW, mode, None, nonce, "v1")

    async def call(self, execution: str, work: Any, node: str) -> object:
        return await self.calls.call(NodeCall(N8nExecutionId(execution), node, work))

    def errored(
        self, execution: str = "101", node: str = "Compare", message: str = "The agent is down"
    ) -> None:
        """n8n's record: the execution ended in an error at this block, with these words."""
        self.failures.errored.setdefault(WORKFLOW, []).append(execution)
        self.failures.words[execution] = (node, message)

    async def report(self, execution: str = "101", **said: str) -> FailureResult:
        """Report a failure, run by our error workflow's execution 900."""
        self.errored(execution, **said)
        self.n8n.executions[REPORTER] = ExecutionFacts(ERROR_WORKFLOW, "error", None, None, None)
        return await self.calls.report(REPORTER, N8nExecutionId(execution))

    async def runs(self) -> list[RunRecord]:
        async with self.h.db.transaction("orchestration") as uow:
            return await Store().list_runs(uow)

    async def state(self) -> RunState:
        [run] = await self.runs()
        return run.state

    async def test_run_at_the_gate(self) -> RunId:
        """A test run that passed up to the yes: n8n shows its Ask for a yes red (409)."""
        run_id = RunId("run_test")
        pending = Pending(run_id, 1, None, NOW)
        record = RunRecord(run_id, SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        async with self.h.db.transaction("orchestration") as uow:
            await Store().insert_run(uow, record, "portal:test")
            start = await CallBook().issue_start(uow, run_id, "test", WORKFLOW)
        self.started("101", "manual", start.nonce)
        self.workflows.holder = SPEC.owner
        await self.call("101", READ, "Read release")
        await self.call("101", PROPOSE, "Propose a change")
        await self.call("101", ASK, "Ask for a yes")
        return run_id


@pytest.fixture
async def r(postgres: PostgresUrls) -> AsyncIterator[Reports]:
    async with open_harness(postgres) as h:
        n8n, workflows, failures = FakeN8n(), FakeWorkflows(), FakeFailures()
        calls = NodeCalls(
            h.db,
            h.log,
            h.agent,
            mint,
            NodeCatalog(workflows, FakeSources(), [JIRA]),
            workflows,
            n8n,
            FakeSources(),
            {},
            failures=failures,
        )
        yield Reports(h, n8n, workflows, failures, calls)


async def test_a_report_fails_the_linked_run_with_the_blocks_words(r: Reports):
    r.started("101")
    await r.call("101", READ, "Read release")
    result = await r.report()
    [run] = await r.runs()
    assert result == FailedRun(run.run_id)
    assert isinstance(run.state, Failed)
    failure = run.state.failure
    assert failure.reason is FailureReason.WORKFLOW_NODE_ERROR
    assert failure.message == '"Compare" failed in n8n: The agent is down.'
    assert failure.retryable
    assert (await r.h.kinds(run.run_id))[-1] == "run_failed"


async def test_a_report_without_a_link_shows_the_run_that_stopped_before_reading(r: Reports):
    """The schedule fired, and Read could not reach our API, so no block ever called."""
    r.started("101")
    assert isinstance(await r.report(node="Read release", message="ECONNREFUSED"), FailedRun)
    [run] = await r.runs()
    assert run.spec.trigger == "schedule"
    assert isinstance(run.state, Failed)
    assert run.state.failure.message == (
        'Stopped before it read anything. "Read release" failed in n8n: ECONNREFUSED.'
    )
    assert await r.h.kinds(run.run_id) == ["run_created", "execution_linked", "run_failed"]


async def test_a_report_without_a_link_fails_the_pending_run_its_start_was_for(r: Reports):
    run_id = RunId("run_portal")
    pending = Pending(run_id, 1, None, NOW)
    async with r.h.db.transaction("orchestration") as uow:
        record = RunRecord(run_id, SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await Store().insert_run(uow, record, "portal:run-now")
        start = await CallBook().issue_start(uow, run_id, "run_now", WORKFLOW)
    r.started("101", "webhook", start.nonce)
    assert await r.report(node="Read release") == FailedRun(run_id)
    [run] = await r.runs()
    assert run.run_id == run_id and isinstance(run.state, Failed)


async def test_a_report_for_a_run_that_passed_its_test_up_to_the_yes_changes_nothing(r: Reports):
    """E2b's review: a test run ends with a 409 at the gate, so its execution ends in an error and
    the error workflow reports it."""
    run_id = await r.test_run_at_the_gate()
    result = await r.report(node="Ask for a yes", message="Test run passed up to the yes.")
    assert isinstance(result, LeftAsIs)
    assert await r.state() == Succeeded(run_id, Outcome.TEST_PASSED, ())


async def acting_with_a_write(r: Reports, in_flight: bool) -> RunState:
    """The run took its yes in execution 101, whose Make the approved changes has called."""
    r.started("101")
    await r.call("101", READ, "Read release")
    [run] = await r.runs()
    acting = Acting(
        run.run_id, ProposalId("prp_1"), ApprovalId("apr_1"), 1, N8nExecutionId("101"), NOW
    )
    answer = None if in_flight else json({"made": 1, "of": 2})
    async with r.h.db.transaction("orchestration") as uow:
        await Store().save_run(uow, run, acting)
        await uow.conn.execute(
            "INSERT INTO orchestration.node_calls (execution_id, node_name, run_id, kind, "
            "content_hash, attempts, outcome, call_id, claimed_at, answer, answered_at) "
            "VALUES ('101', 'Make the approved changes', %s, 'write', 'h', 1, %s, 'c_w', %s, "
            "%s, %s)",
            (
                run.run_id,
                "working" if in_flight else "answered",
                NOW,
                answer,
                None if in_flight else NOW,
            ),
        )
    return acting


async def test_a_report_during_a_live_write_leaves_the_run_to_the_writes_outcome(r: Reports):
    """The run never reads failed and retryable while its changes are being made."""
    acting = await acting_with_a_write(r, in_flight=True)
    assert isinstance(await r.report(node="Make the approved changes"), LeftAsIs)
    assert await r.state() == acting


async def test_a_report_for_an_acting_run_with_no_write_in_flight_fails_it(r: Reports):
    await acting_with_a_write(r, in_flight=False)
    assert isinstance(await r.report(node="Make the approved changes"), FailedRun)
    state = await r.state()
    assert isinstance(state, Failed) and state.stage is Stage.ACTING


async def test_a_report_for_a_run_that_succeeded_changes_nothing(r: Reports):
    r.started("101")
    await r.call("101", READ, "Read release")
    await r.call("101", ASK, "Ask for a yes")
    [run] = await r.runs()
    assert run.state == Succeeded(run.run_id, Outcome.NOTHING_TO_WRITE, ())
    assert isinstance(await r.report(node="Nothing to change"), LeftAsIs)
    assert await r.state() == run.state


async def test_a_repeated_report_leaves_the_first_failure(r: Reports):
    r.started("101")
    await r.call("101", READ, "Read release")
    await r.report()
    first = await r.state()
    assert isinstance(await r.report(message="Something else"), LeftAsIs)
    assert await r.state() == first


async def test_a_report_for_a_workflow_that_is_not_ours_makes_no_run(r: Reports):
    r.n8n.executions["101"] = ExecutionFacts("wf_theirs", "trigger", None, None, "v1")
    assert isinstance(await r.report(), LeftAsIs)
    assert await r.runs() == []


async def test_a_report_for_an_execution_n8n_does_not_know_yet_is_asked_again(r: Reports):
    r.n8n.executions[REPORTER] = ExecutionFacts(ERROR_WORKFLOW, "error", None, None, None)
    r.errored("101")
    assert isinstance(await r.calls.report(REPORTER, N8nExecutionId("101")), TryLater)
    assert await r.runs() == []


async def test_a_report_takes_the_block_and_its_words_from_n8n_never_from_the_body(r: Reports):
    """The body's block and words never reach the run: only n8n's own record does."""
    r.started("101")
    await r.call("101", READ, "Read release")
    await r.report(node="Read release", message="GitHub answered 503")
    state = await r.state()
    assert isinstance(state, Failed)
    assert state.failure.message == '"Read release" failed in n8n: GitHub answered 503.'


@pytest.mark.parametrize(
    "reporter_workflow",
    [WORKFLOW, "wf_someone_elses", ""],
    ids=["a-workflow-of-ours", "another-workflow", "n8n-not-read-yet"],
)
async def test_a_report_from_anything_but_our_error_workflow_is_refused(
    r: Reports, reporter_workflow: str
):
    """The node key alone is not enough to fail a run: the reporter must be our error workflow."""
    r.started("101")
    await r.call("101", READ, "Read release")
    r.errored("101")
    r.n8n.executions[REPORTER] = ExecutionFacts(reporter_workflow, "error", None, None, None)
    before = await r.state()
    assert await r.calls.report(REPORTER, N8nExecutionId("101")) == NOT_OUR_ERROR_WORKFLOW
    assert await r.state() == before


async def test_a_report_is_refused_while_our_error_workflow_is_not_known(r: Reports):
    """Until n8n's records are read (E3, E4), no report is trusted."""
    r.started("101")
    await r.call("101", READ, "Read release")
    r.failures.error_workflow = None
    r.errored("101")
    r.n8n.executions[REPORTER] = ExecutionFacts("", "", None, None, None)
    before = await r.state()
    assert await r.calls.report(REPORTER, N8nExecutionId("101")) == NOT_OUR_ERROR_WORKFLOW
    assert await r.state() == before


async def test_a_report_for_an_execution_n8n_does_not_say_failed_is_refused(r: Reports):
    r.started("101")
    await r.call("101", READ, "Read release")
    r.n8n.executions[REPORTER] = ExecutionFacts(ERROR_WORKFLOW, "error", None, None, None)
    before = await r.state()
    assert await r.calls.report(REPORTER, N8nExecutionId("101")) == NOT_FAILED
    assert await r.state() == before


async def test_a_platform_with_no_failure_reads_refuses_every_report(r: Reports):
    r.calls = NodeCalls(
        r.h.db,
        r.h.log,
        r.h.agent,
        mint,
        NodeCatalog(r.workflows, FakeSources(), [JIRA]),
        r.workflows,
        r.n8n,
        FakeSources(),
        {},
    )
    r.started("101")
    await r.call("101", READ, "Read release")
    before = await r.state()
    assert await r.report() == NOT_OUR_ERROR_WORKFLOW
    assert await r.state() == before


@pytest.mark.parametrize("now", ["pending", "acting"])
async def test_a_failure_of_an_earlier_attempt_never_fails_the_next_one(r: Reports, now: str):
    """Once 101's run moved on to an attempt nobody carries yet, a late failure of 101, from a
    report or the sweep, leaves it alone."""
    r.started("101")
    await r.call("101", READ, "Read release")
    [run] = await r.runs()
    next_attempt: RunState = (
        Pending(run.run_id, 2, None, NOW)
        if now == "pending"
        else Acting(run.run_id, ProposalId("prp_1"), ApprovalId("apr_1"), 1, None, NOW)
    )
    async with r.h.db.transaction("orchestration") as uow:
        await Store().save_run(uow, run, next_attempt)
    assert isinstance(await r.report(), LeftAsIs)
    assert await r.calls.sweep() == []
    assert await r.state() == next_attempt


async def test_the_sweep_fails_an_open_run_from_its_error_execution(r: Reports):
    """The fallback for a workflow held in a member's project and a failing run by hand, which
    reach no error workflow."""
    r.started("101")
    await r.call("101", READ, "Read release")
    r.failures.errored[WORKFLOW] = ["99", "101"]
    r.failures.words["101"] = ("Read release", "GitHub did not answer")
    [run] = await r.runs()
    assert await r.calls.sweep() == [run.run_id]
    state = await r.state()
    assert isinstance(state, Failed)
    assert state.failure.message == '"Read release" failed in n8n: GitHub did not answer.'
    assert r.failures.read == ["101"]
    assert await r.calls.sweep() == []


async def test_the_sweep_closes_a_run_whose_execution_ended_without_asking_for_a_yes(r: Reports):
    """A Tell-only workflow, or a branch that ended at Nothing to change: n8n ran to its end, and
    nothing waits for a change, so the run never times out (ENGINE-PLAN 2.3)."""
    r.started("101")
    await r.call("101", READ, "Read release")
    [run] = await r.runs()
    assert await r.calls.sweep() == [], "n8n still runs it"
    r.failures.finished.add("101")
    assert await r.calls.sweep() == [run.run_id]
    assert await r.state() == Succeeded(run.run_id, Outcome.NOTHING_TO_WRITE, ())
    assert (await r.h.kinds(run.run_id))[-1] == "run_succeeded"
    assert await r.calls.sweep() == []


async def test_the_sweep_fails_a_test_run_whose_execution_failed_before_any_block_called(
    r: Reports,
):
    """A failing run by hand reaches no error workflow (P7 Q22), so our API watches the test
    run's execution by the id n8n answered the run with."""
    run_id = RunId("run_test")
    claimed = Pending(run_id, 1, N8nExecutionId("101"), NOW)
    own = replace(SPEC, n8n=N8nTarget(WORKFLOW, "hook-1"))
    record = RunRecord(run_id, own, SPEC.owner, NOW, NOW, 1, claimed, (), None)
    async with r.h.db.transaction("orchestration") as uow:
        await Store().insert_run(uow, record, "portal:test")
    r.failures.errored[WORKFLOW] = ["101"]
    r.failures.words["101"] = ("Read release", "The node is not set up")
    assert await r.calls.sweep() == [run_id]
    state = await r.state()
    assert isinstance(state, Failed) and state.stage is Stage.PENDING
    assert state.failure.message == (
        'Stopped before it read anything. "Read release" failed in n8n: The node is not set up.'
    )


async def test_the_sweep_passes_a_test_run_n8n_finished_before_any_block_called(r: Reports):
    """It reached no yes and wrote nothing, so it is not left to time out."""
    run_id = RunId("run_test")
    claimed = Pending(run_id, 1, N8nExecutionId("101"), NOW)
    own = replace(SPEC, n8n=N8nTarget(WORKFLOW, "hook-1"))
    record = RunRecord(run_id, own, SPEC.owner, NOW, NOW, 1, claimed, (), None)
    async with r.h.db.transaction("orchestration") as uow:
        await Store().insert_run(uow, record, "portal:test")
    r.failures.finished.add("101")
    assert await r.calls.sweep() == [run_id]
    assert await r.state() == Succeeded(run_id, Outcome.TEST_PASSED, ())
    assert await r.calls.sweep() == []


async def test_the_sweep_never_fails_a_run_that_finished(r: Reports):
    run_id = await r.test_run_at_the_gate()
    r.failures.errored[WORKFLOW] = ["101"]
    assert await r.calls.sweep() == []
    assert await r.state() == Succeeded(run_id, Outcome.TEST_PASSED, ())
    assert r.failures.read == []


REPORT = {
    "execution_id": "900",
    "workflow_id": "wf_errors",
    "node_name": "Report a failure",
    "mode": "error",
    "failed_execution_id": "101",
    "failed_mode": "trigger",
    "retry_of": None,
    "last_node_executed": "Compare",
    "error_message": "The agent is down",
    "failed_workflow_id": "wf_7",
    "failed_workflow_name": "Release check",
}


@pytest.mark.parametrize(
    ("result", "status", "answer"),
    [
        (
            FailedRun(RunId("run_1")),
            200,
            {"status": "failed", "run_id": "run_1", "detail": "The run failed."},
        ),
        (LeftAsIs("The run is succeeded."), 200, {"status": "left_as_is", "run_id": None}),
        (TryLater("n8n has no record of this execution yet."), 503, {"retryable": True}),
        (NOT_OUR_ERROR_WORKFLOW, 403, {"detail": NOT_OUR_ERROR_WORKFLOW.detail}),
        (NOT_FAILED, 409, {"detail": NOT_FAILED.detail}),
    ],
    ids=["failed", "left-as-is", "try-later", "not-our-error-workflow", "not-failed"],
)
def test_the_failure_route_maps_the_error_triggers_item(
    result: FailureResult, status: int, answer: dict[str, Any]
):
    calls = FakeNodeCalls(failure=result)
    app = app_with(env=NODE_KEY_ENV, node_calls=calls)
    response = TestClient(app).post("/internal/v1/n8n/failures", headers=NODE_KEY, json=REPORT)
    assert response.status_code == status
    assert answer.items() <= response.json().items()
    declared_status(app, "POST", "/internal/v1/n8n/failures", response)
    assert calls.reports == [(REPORTER, N8nExecutionId("101"))], "only ids, never the words"


def test_the_failure_route_takes_reports_only_with_the_node_key():
    calls = FakeNodeCalls()
    client = TestClient(app_with(env=NODE_KEY_ENV, node_calls=calls))
    assert client.post("/internal/v1/n8n/failures", json=REPORT).status_code == 401
    assert calls.reports == []


def test_the_reports_words_are_dropped_at_the_route_and_never_checked_or_passed_on():
    calls = FakeNodeCalls()
    client = TestClient(app_with(env=NODE_KEY_ENV, node_calls=calls))
    body = {**REPORT, "error_message": "x" * 10_000, "last_node_executed": "Anything"}
    response = client.post("/internal/v1/n8n/failures", headers=NODE_KEY, json=body)
    assert response.status_code == 200
    assert calls.reports == [(REPORTER, N8nExecutionId("101"))]


def test_a_report_with_no_failed_execution_changes_nothing():
    calls = FakeNodeCalls()
    client = TestClient(app_with(env=NODE_KEY_ENV, node_calls=calls))
    body = {**REPORT, "failed_execution_id": None}
    response = client.post("/internal/v1/n8n/failures", headers=NODE_KEY, json=body)
    assert response.json()["status"] == "left_as_is"
    assert calls.reports == []
