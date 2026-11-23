"""The AI troubleshooter's model version (ADR 0032, ADR 0055 section 10), behind
GET /api/v1/runs/{run_id}/troubleshoot?find_cause=true. The rule table answers as it always has,
and the model's cause and failed part ride beside it only when code checked them."""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from platform_api.monitoring import (
    PLATFORM,
    ActivityLog,
    FoundCause,
    PendingEvent,
    RunCreatedData,
    RunFailedData,
)
from platform_api.orchestration.agents import HttpAgentRuntime, ModelAccess
from platform_api.orchestration.n8n_run_view import NodeState, RunInN8n
from platform_api.orchestration.run_causes import RunCauses
from platform_api.shared import RunId, UserId
from platform_api.wire import FailureReason, FailureStage
from tests.conftest import PostgresUrls
from tests.test_monitoring_http import ALICE, RUN, app_for, append

pytestmark = pytest.mark.anyio

ACCESS = ModelAccess(
    style="anthropic",
    base_url="https://llm-gateway.aisg.sg",
    model="claude-haiku-5-5",
    api_key="sk-" + "example-key-not-real-x7",
)
CAUSE = "GitHub can't find the repository fastapi/fastapy that the Read releases block reads."
FOUND = {"kind": "found", "cause": CAUSE, "failed_part": ["Read releases"]}
NODES: Mapping[str, NodeState] = {
    "Every day at 8:00": "done",
    "Start from the Portal": "done",
    "Read releases": "failed",
}
NODE_FAILURE = (
    "The n8n workflow 'FastAPI release check' failed at its step 'Read releases': "
    "GitHub answered 404 Not Found for fastapi/fastapy"
)
PATH = f"/api/v1/runs/{RUN}/troubleshoot"


@dataclass
class Runtime:
    """The agent runtime's cause route."""

    status: int = 200
    answer: object = field(default_factory=lambda: FOUND)
    times_out: bool = False
    asked: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, Any]])

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append((request.url.path, json.loads(request.content)))
        if self.times_out:
            raise httpx.ReadTimeout("no answer", request=request)
        return httpx.Response(self.status, json=self.answer)


class Connected:
    def __init__(self, model: ModelAccess | None) -> None:
        self._model = model

    async def access(self, uow: object) -> ModelAccess | None:
        return self._model


class Record:
    """The run as n8n carried it: each block it reached, and how that block ended."""

    def __init__(self, nodes: Mapping[str, NodeState] | None) -> None:
        self._nodes = nodes

    async def read(self, run_id: RunId) -> RunInN8n | None:
        if self._nodes is None:
            return None
        return RunInN8n(run_id, "uc_fastapi", "Failed", "211", "wf_1", "v_1", self._nodes, True)


class Raises:
    async def find(
        self, run_id: RunId, failure: RunFailedData, events: Sequence[str]
    ) -> FoundCause | None:
        raise RuntimeError("the finder broke")


class Slow:
    async def find(
        self, run_id: RunId, failure: RunFailedData, events: Sequence[str]
    ) -> FoundCause | None:
        await asyncio.sleep(5)
        return FoundCause(cause=CAUSE, failed_part=["Read releases"])


def stop(
    reason: FailureReason = "WorkflowNodeError",
    retryable: bool = True,
    message: str = NODE_FAILURE,
    stage: FailureStage = "working",
) -> PendingEvent:
    data = RunFailedData(stage=stage, reason=reason, retryable=retryable, message=message)
    return PendingEvent(PLATFORM, "run_failed", "The run failed.", data)


def started() -> PendingEvent:
    data = RunCreatedData(use_case_id="uc_fastapi", use_case_version=1, started_by=UserId("alice"))
    return PendingEvent(
        PLATFORM, "run_created", "Alice started a run of FastAPI release check.", data
    )


@pytest.fixture
async def app(activity_log: ActivityLog, postgres: PostgresUrls) -> AsyncIterator[FastAPI]:
    yield app_for(activity_log, postgres)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def finds(
    app: FastAPI,
    runtime: Runtime | None = None,
    model: ModelAccess | None = ACCESS,
    nodes: Mapping[str, NodeState] | None = NODES,
) -> Runtime:
    answering = runtime or Runtime()
    client = httpx.AsyncClient(transport=httpx.MockTransport(answering.handle))
    agents = HttpAgentRuntime("http://agent-runtime:8100", "agent-key-not-real", client=client)
    log: ActivityLog = app.state.activity_log
    app.state.cause_finder = RunCauses(log.database, Connected(model), agents, Record(nodes))
    return answering


async def troubleshoot(client: httpx.AsyncClient, find_cause: bool | None = None) -> Any:
    query = {} if find_cause is None else {"find_cause": str(find_cause).lower()}
    answered = await client.get(PATH, headers=ALICE, params=query)
    assert answered.status_code == 200, answered.text
    return answered.json()


async def test_without_find_cause_the_rule_table_answers_and_no_model_is_asked(
    client: httpx.AsyncClient, app: FastAPI
):
    runtime = finds(app)
    await append(app, RUN, stop())
    answered = await troubleshoot(client)
    assert answered["found"] is None
    assert answered["advice"]["suggested_action"] == "retry"
    assert runtime.asked == []


async def test_a_block_that_failed_in_n8n_gets_the_models_cause_beside_the_rule_table(
    client: httpx.AsyncClient, app: FastAPI
):
    finds(app)
    await append(app, RUN, stop())
    plain = await troubleshoot(client)
    answered = await troubleshoot(client, find_cause=True)
    assert answered["found"] == {"cause": CAUSE, "failed_part": ["Read releases"]}
    assert {**answered, "found": None} == plain, "the rule table's answer is unchanged"


async def test_an_agent_stop_of_a_kind_the_rule_table_doesnt_know_gets_the_models_cause(
    client: httpx.AsyncClient, app: FastAPI
):
    finds(app)
    message = "UpstreamRejected: Could not check LangGraph: GitHub answered 404 Not Found"
    await append(app, RUN, stop("AgentError", retryable=False, message=message))
    answered = await troubleshoot(client, find_cause=True)
    assert answered["found"] == {"cause": CAUSE, "failed_part": ["Read releases"]}


@pytest.mark.parametrize(
    "known",
    [
        stop("AgentError", retryable=False, message="JiraNotConnected: Connect Jira in Settings."),
        stop("AgentError", message="UpstreamUnavailable: GitHub returned 503 three times"),
        stop("WriteFailed", retryable=False, message="Jira refused the write", stage="acting"),
        stop("TimedOut", message="The workflow engine did not answer"),
        stop("SafetyDenied", retryable=False, message="digest_mismatch"),
    ],
    ids=["known-agent-stop", "outage", "refused-write", "timed-out", "safety-checker"],
)
async def test_a_cause_the_rule_table_knows_asks_no_model(
    client: httpx.AsyncClient, app: FastAPI, known: PendingEvent
):
    runtime = finds(app)
    await append(app, RUN, known)
    answered = await troubleshoot(client, find_cause=True)
    assert answered["found"] is None
    assert runtime.asked == []


async def test_the_runtime_gets_the_stop_the_blocks_where_it_stopped_and_the_activity(
    client: httpx.AsyncClient, app: FastAPI
):
    runtime = finds(app)
    await append(app, RUN, started(), stop())
    await troubleshoot(client, find_cause=True)
    [(path, body)] = runtime.asked
    assert path == "/v1/troubleshooter/cause"
    assert body == {
        "model": ACCESS.model_dump(mode="json"),
        "stop": {
            "stage": "working",
            "reason": "WorkflowNodeError",
            "retryable": True,
            "message": NODE_FAILURE,
        },
        "events": ["Alice started a run of FastAPI release check.", "The run failed."],
        "blocks": list(NODES),
        "stopped_at": ["Read releases"],
    }


@pytest.mark.parametrize(
    ("runtime", "model", "nodes"),
    [
        (Runtime(answer={"kind": "kept", "why": "made_up"}), ACCESS, NODES),
        (Runtime(answer={"status": "problem", "reason": "failed", "message": "x"}), ACCESS, NODES),
        (Runtime(status=500), ACCESS, NODES),
        (Runtime(status=422), ACCESS, NODES),
        (Runtime(times_out=True), ACCESS, NODES),
        (Runtime(answer={"kind": "found"}), ACCESS, NODES),
        (Runtime(answer={**FOUND, "failed_part": ["Start from the Portal"]}), ACCESS, NODES),
        (Runtime(), None, NODES),
        (Runtime(), ACCESS, {"Read releases": "done"}),
        (Runtime(), ACCESS, None),
    ],
    ids=[
        "kept",
        "model-problem",
        "runtime-down",
        "runtime-refused",
        "runtime-slow",
        "unparsable",
        "not-where-it-stopped",
        "no-model",
        "no-failed-block",
        "no-record",
    ],
)
async def test_any_doubt_gives_exactly_the_rule_tables_answer(
    client: httpx.AsyncClient,
    app: FastAPI,
    runtime: Runtime,
    model: ModelAccess | None,
    nodes: Mapping[str, NodeState] | None,
):
    finds(app, runtime, model, nodes)
    await append(app, RUN, stop())
    plain = await troubleshoot(client)
    assert await troubleshoot(client, find_cause=True) == plain
    assert plain["found"] is None


@pytest.mark.parametrize("finder", [Raises(), Slow(), None], ids=["raises", "slow", "none"])
async def test_a_finder_that_breaks_or_is_slow_or_missing_gives_the_rule_tables_answer(
    client: httpx.AsyncClient, app: FastAPI, finder: Raises | Slow | None
):
    app.state.cause_finder = finder
    app.state.cause_wait_seconds = 0.05
    await append(app, RUN, stop())
    plain = await troubleshoot(client)
    assert await troubleshoot(client, find_cause=True) == plain


async def test_finding_the_cause_writes_nothing(client: httpx.AsyncClient, app: FastAPI):
    runtime = finds(app)
    await append(app, RUN, started(), stop())
    log: ActivityLog = app.state.activity_log
    before = await log.read_after(RUN, 0)
    await troubleshoot(client, find_cause=True)
    assert await log.read_after(RUN, 0) == before
    assert [path for path, _ in runtime.asked] == ["/v1/troubleshooter/cause"]
