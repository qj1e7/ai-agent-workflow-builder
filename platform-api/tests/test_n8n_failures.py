"""Failures reported through Report a failure, or found by the sweep (ENGINE-PLAN 2.3.9 and 2.8):
each fails the run its execution carried, with the block's words, and never a run that ended."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from platform_api.orchestration.n8n_call_service import (
    CallBook,
    FailedRun,
    FailureResult,
    LeftAsIs,
    NodeCalls,
)
from platform_api.orchestration.n8n_calls import (
    AskCall,
    ExecutionFacts,
    FailedExecution,
    NodeCall,
    NodeCatalog,
    ProposeCall,
    ReadCall,
    TryLater,
)
from platform_api.orchestration.runs import (
    Failed,
    FailureReason,
    Outcome,
    Pending,
    RunState,
    Succeeded,
)
from platform_api.orchestration.store import RunRecord, Store
from platform_api.shared import N8nExecutionId, RunId
from tests.conftest import PostgresUrls
from tests.declared import NODE_KEY, NODE_KEY_ENV, FakeNodeCalls, app_with, declared_status
from tests.support import NOW, SPEC
from tests.test_n8n_calls import JIRA, REPO, WORKFLOW, FakeN8n, FakeSources, FakeWorkflows
from tests.test_orchestrator import Harness, mint, open_harness

pytestmark = pytest.mark.anyio

READ = ReadCall("github_releases", REPO, None)
PROPOSE = ProposeCall("jira.create_ticket", "MOCK", "Upgrade LangGraph", "1.2.16 is out.", None)
ASK = AskCall("http://n8n:5678/webhook-waiting/101?signature=abc")


def failed_at(execution: str, node: str = "Compare", message: str = "The agent is down") -> Any:
    return FailedExecution(N8nExecutionId(execution), node, message)


@dataclass
class FakeFailures:
    """n8n's failed executions, as the public API lists them, and what each one's data says."""

    errored: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    read: list[str] = field(default_factory=list[str])

    async def failed_executions(self, workflow_id: str) -> Sequence[N8nExecutionId]:
        return [N8nExecutionId(e) for e in self.errored.get(workflow_id, [])]

    async def failure(self, execution_id: N8nExecutionId) -> FailedExecution | None:
        self.read.append(execution_id)
        return failed_at(execution_id, "Read release", "GitHub did not answer")


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

    async def report(self, execution: str = "101", **said: str) -> FailureResult:
        return await self.calls.failed(failed_at(execution, **said))

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
            start_secret="test-start-secret",
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
    assert isinstance(await r.report(), TryLater)
    assert await r.runs() == []


async def test_the_sweep_fails_an_open_run_from_its_error_execution(r: Reports):
    """The fallback for a workflow held in a member's project and a failing run by hand, which
    reach no error workflow."""
    r.started("101")
    await r.call("101", READ, "Read release")
    r.failures.errored[WORKFLOW] = ["99", "101"]
    [run] = await r.runs()
    assert await r.calls.sweep() == [run.run_id]
    state = await r.state()
    assert isinstance(state, Failed)
    assert state.failure.message == '"Read release" failed in n8n: GitHub did not answer.'
    assert r.failures.read == ["101"]
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
    ],
    ids=["failed", "left-as-is", "try-later"],
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
    assert calls.failures == [
        FailedExecution(N8nExecutionId("101"), "Compare", "The agent is down")
    ]


def test_the_failure_route_takes_reports_only_with_the_node_key():
    calls = FakeNodeCalls()
    client = TestClient(app_with(env=NODE_KEY_ENV, node_calls=calls))
    assert client.post("/internal/v1/n8n/failures", json=REPORT).status_code == 401
    assert calls.failures == []


def test_a_report_with_no_failed_execution_changes_nothing():
    calls = FakeNodeCalls()
    client = TestClient(app_with(env=NODE_KEY_ENV, node_calls=calls))
    body = {**REPORT, "failed_execution_id": None}
    response = client.post("/internal/v1/n8n/failures", headers=NODE_KEY, json=body)
    assert response.json()["status"] == "left_as_is"
    assert calls.failures == []
