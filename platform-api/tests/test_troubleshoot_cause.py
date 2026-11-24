"""The AI troubleshooter's model version (ADR 0032, ADR 0055 section 10), behind
GET /api/v1/runs/{run_id}/troubleshoot?find_cause=true. The rule table answers as it always has,
and the model's cause and failed part ride beside it only when code checked them."""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, get_args

import httpx
import pytest
from fastapi import FastAPI

from platform_api.monitoring import (
    PLATFORM,
    ActivityLog,
    AskedCause,
    CauseFinder,
    CauseSystem,
    FailureKind,
    FoundCause,
    PendingEvent,
    RunCreatedData,
    RunFailedData,
    cause_words,
)
from platform_api.orchestration.agents import HttpAgentRuntime, ModelAccess
from platform_api.orchestration.n8n_run_view import NodeState, RunInN8n
from platform_api.orchestration.run_causes import RunCauses
from platform_api.shared import RunId, UserId
from platform_api.wire import FailureReason, FailureStage
from tests.conftest import PostgresUrls
from tests.test_monitoring_http import ALICE, RUN, app_for, append, pending

pytestmark = pytest.mark.anyio

ACCESS = ModelAccess(
    style="anthropic",
    base_url="https://llm-gateway.aisg.sg",
    model="claude-haiku-5-5",
    api_key="sk-" + "example-key-not-real-x7",
)
CAUSE = "The Read releases block stopped because GitHub can't find fastapi/fastapy."
FOUND = {
    "kind": "found",
    "failed_part": ["Read releases"],
    "system": "github",
    "failure_kind": "not_found",
    "detail": "fastapi/fastapy",
}
BYPASSES = [
    "The fix is to delete the Read releases block.",
    "The approval step is broken, as the Read releases block shows.",
]
"""The review of PR #362 got both past the runtime's word guard. Now the runtime answers in
fields, and code here writes the sentence, so neither reaches anyone."""
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
    """The agent runtime's cause route. With a gate, it answers only once the gate opens."""

    status: int = 200
    answer: object = field(default_factory=lambda: FOUND)
    times_out: bool = False
    gate: asyncio.Event | None = None
    asked: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, Any]])

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append((request.url.path, json.loads(request.content)))
        if self.gate is not None:
            await asyncio.wait_for(self.gate.wait(), 5)
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
    async def find(self, asked: AskedCause) -> FoundCause | None:
        raise RuntimeError("the finder broke")


class Slow:
    async def find(self, asked: AskedCause) -> FoundCause | None:
        await asyncio.sleep(5)
        return FoundCause(cause=CAUSE, failed_part=["Read releases"])


class AllIn:
    """The finder, which opens the gate once this many asks are inside it, so they overlap."""

    def __init__(self, finder: CauseFinder, gate: asyncio.Event, asks: int) -> None:
        self._finder = finder
        self._gate = gate
        self._left = asks

    async def find(self, asked: AskedCause) -> FoundCause | None:
        self._left -= 1
        if self._left == 0:
            self._gate.set()
        return await self._finder.find(asked)


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
    within = body.pop("within_seconds")
    assert 2 <= within < 10, "the runtime gets what is left of the ten seconds"
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
        (Runtime(answer={"kind": "kept", "why": "not_a_system"}), ACCESS, NODES),
        (Runtime(answer={"kind": "kept", "why": "made_up"}), ACCESS, NODES),
        (Runtime(answer={"status": "problem", "reason": "failed", "message": "x"}), ACCESS, NODES),
        (Runtime(status=500), ACCESS, NODES),
        (Runtime(status=422), ACCESS, NODES),
        (Runtime(times_out=True), ACCESS, NODES),
        (Runtime(answer={"kind": "found"}), ACCESS, NODES),
        (Runtime(answer={**FOUND, "failed_part": ["Start from the Portal"]}), ACCESS, NODES),
        (Runtime(answer={**FOUND, "failure_kind": "broken"}), ACCESS, NODES),
        (Runtime(answer={**FOUND, "system": "n8n"}), ACCESS, NODES),
        (Runtime(answer={**FOUND, "detail": "fast api"}), ACCESS, NODES),
        (Runtime(), None, NODES),
        (Runtime(), ACCESS, {"Read releases": "done"}),
        (Runtime(), ACCESS, None),
    ],
    ids=[
        "kept",
        "kept-for-a-reason-it-doesnt-know",
        "model-problem",
        "runtime-down",
        "runtime-refused",
        "runtime-slow",
        "unparsable",
        "not-where-it-stopped",
        "not-a-kind",
        "not-a-system",
        "not-one-name",
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


async def test_the_model_is_asked_once_for_each_stop(client: httpx.AsyncClient, app: FastAPI):
    runtime = finds(app)
    await append(app, RUN, stop())
    first = await troubleshoot(client, find_cause=True)
    assert await troubleshoot(client, find_cause=True) == first
    assert first["found"] is not None
    assert len(runtime.asked) == 1


async def test_a_kept_answer_is_not_asked_for_again(client: httpx.AsyncClient, app: FastAPI):
    runtime = finds(app, Runtime(answer={"kind": "kept", "why": "not_a_system"}))
    await append(app, RUN, stop())
    await troubleshoot(client, find_cause=True)
    await troubleshoot(client, find_cause=True)
    assert len(runtime.asked) == 1


@pytest.mark.parametrize(
    "answering",
    [{"status": 500}, {"times_out": True}, {"answer": {"kind": "kept", "why": "call"}}],
    ids=["runtime-down", "runtime-slow", "model-call-failed"],
)
async def test_a_call_that_failed_is_asked_again(
    client: httpx.AsyncClient, app: FastAPI, answering: dict[str, Any]
):
    runtime = finds(app, Runtime(**answering))
    await append(app, RUN, stop())
    await troubleshoot(client, find_cause=True)
    await troubleshoot(client, find_cause=True)
    assert len(runtime.asked) == 2


async def test_a_new_stop_after_a_retry_is_asked_about_again(
    client: httpx.AsyncClient, app: FastAPI
):
    runtime = finds(app)
    await append(app, RUN, stop())
    await troubleshoot(client, find_cause=True)
    await append(app, RUN, pending(2), stop())
    await troubleshoot(client, find_cause=True)
    assert len(runtime.asked) == 2


async def test_too_little_of_the_ten_seconds_left_asks_no_model(
    client: httpx.AsyncClient, app: FastAPI
):
    runtime = finds(app)
    app.state.cause_wait_seconds = 1.0
    await append(app, RUN, stop())
    assert (await troubleshoot(client, find_cause=True))["found"] is None
    assert runtime.asked == []


@pytest.mark.parametrize(
    "answering",
    [
        {},
        {"answer": {"kind": "kept", "why": "call"}},
        {"answer": {"kind": "kept", "why": "not_a_detail"}},
        {"status": 500},
        {"times_out": True},
    ],
    ids=["found", "model-call-failed", "kept", "runtime-down", "runtime-slow"],
)
async def test_three_requests_for_the_same_stop_make_exactly_one_model_call(
    client: httpx.AsyncClient, app: FastAPI, answering: dict[str, Any]
):
    gate = asyncio.Event()
    runtime = finds(app, Runtime(**answering, gate=gate))
    app.state.cause_finder = AllIn(app.state.cause_finder, gate, 3)
    await append(app, RUN, stop())
    answered = await asyncio.gather(*(troubleshoot(client, find_cause=True) for _ in range(3)))
    assert len(runtime.asked) == 1
    assert answered[0] == answered[1] == answered[2]


async def test_the_cause_shown_is_codes_sentence_from_the_fields(
    client: httpx.AsyncClient, app: FastAPI
):
    finds(app, Runtime(answer={**FOUND, "system": None, "failure_kind": "refused"}))
    await append(app, RUN, stop())
    answered = await troubleshoot(client, find_cause=True)
    assert answered["found"] == {
        "cause": "The Read releases block stopped because a service refuses the request for "
        "fastapi/fastapy.",
        "failed_part": ["Read releases"],
    }


@pytest.mark.parametrize("sentence", BYPASSES, ids=["an-order-inside", "lowercase-blame"])
@pytest.mark.parametrize("field_name", ["cause", "detail", "system", "failure_kind"])
async def test_no_sentence_the_runtime_sends_reaches_anyone(
    client: httpx.AsyncClient, app: FastAPI, sentence: str, field_name: str
):
    finds(app, Runtime(answer={**FOUND, field_name: sentence}))
    await append(app, RUN, stop())
    answered = await troubleshoot(client, find_cause=True)
    assert answered["found"] is None
    assert sentence not in json.dumps(answered)


ONE = ["Read releases"]
TWO = ["Read releases", "Read the changelog"]
WORDS: list[tuple[list[str], CauseSystem | None, FailureKind, str | None, str]] = [
    (ONE, "github", "not_found", "fastapi/fastapy",
     "The Read releases block stopped because GitHub can't find fastapi/fastapy."),
    (ONE, "github", "not_found", None,
     "The Read releases block stopped because GitHub can't find what was asked for."),
    (ONE, "jira", "refused", "MOCK",
     "The Read releases block stopped because Jira refuses the request for MOCK."),
    (ONE, "jira", "refused", None,
     "The Read releases block stopped because Jira refuses the request."),
    (ONE, "github", "no_answer", "fastapi/fastapy",
     "The Read releases block stopped because GitHub doesn't answer the request for "
     "fastapi/fastapy."),
    (ONE, "github", "no_answer", None,
     "The Read releases block stopped because GitHub doesn't answer."),
    (ONE, "github", "wrong_value", "LangGraph",
     "The Read releases block stopped because GitHub sends a value for LangGraph that the "
     "block can't use."),
    (ONE, "github", "wrong_value", None,
     "The Read releases block stopped because GitHub sends a value the block can't use."),
    (ONE, "github", "changed_field", "tag_name",
     "The Read releases block stopped because the answer from GitHub is missing the field "
     "tag_name."),
    (ONE, "github", "changed_field", None,
     "The Read releases block stopped because the answer from GitHub is missing a field."),
    (ONE, "jira", "permission", "MOCK",
     "The Read releases block stopped because Jira doesn't give the block access to MOCK."),
    (ONE, "jira", "permission", None,
     "The Read releases block stopped because Jira doesn't give the block access."),
    (ONE, "github", "limit", "fastapi/fastapy",
     "The Read releases block stopped because GitHub is limiting requests for "
     "fastapi/fastapy."),
    (ONE, "github", "limit", None,
     "The Read releases block stopped because GitHub is limiting how often it can be asked."),
    (ONE, "github", "unknown", "fastapi/fastapy",
     "The Read releases block stopped on an error from GitHub about fastapi/fastapy."),
    (ONE, "github", "unknown", None, "The Read releases block stopped on an error from GitHub."),
    (ONE, None, "unknown", "fastapi/fastapy",
     "The Read releases block stopped on an error about fastapi/fastapy."),
    (ONE, None, "unknown", None, "The Read releases block stopped on an error."),
    (ONE, None, "not_found", "MOCK",
     "The Read releases block stopped because a service can't find MOCK."),
    (TWO, "github", "not_found", "fastapi/fastapy",
     "The Read releases and Read the changelog blocks stopped because GitHub can't find "
     "fastapi/fastapy."),
    (TWO, "github", "permission", None,
     "The Read releases and Read the changelog blocks stopped because GitHub doesn't give the "
     "blocks access."),
    ([*TWO, "Newer?"], None, "unknown", None,
     "The Read releases, Read the changelog and Newer? blocks stopped on an error."),
]  # fmt: skip


@pytest.mark.parametrize(
    ("part", "system", "kind", "detail", "words"),
    WORDS,
    ids=[f"{len(w[0])}-{w[1]}-{w[2]}-{w[3] is not None}" for w in WORDS],
)
def test_code_writes_the_cause_from_a_template_for_each_kind(
    part: list[str], system: CauseSystem | None, kind: FailureKind, detail: str | None, words: str
):
    assert cause_words(part, system, kind, detail) == words


def test_every_kind_and_system_has_one_sentence_of_its_words():
    for kind in get_args(FailureKind.__value__):
        for system in [*get_args(CauseSystem.__value__), None]:
            for detail in ["X-1", None]:
                said = cause_words(ONE, system, kind, detail)
                assert said.startswith("The Read releases block stopped ")
                assert said.endswith(".") and said.count(".") == 1
