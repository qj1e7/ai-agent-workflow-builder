"""The gate of ADR 0050: no planted key reaches an exported span. Tracing stays off in every
environment until this passes in CI, and a later failure blocks the merge."""

import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_runtime.api import HttpCallbacks, Runtime, create_app
from agent_runtime.card_runner import CardRunner
from agent_runtime.contract import Answered, AnswerRequest, DidntFollowAnswer, ModelAccess
from agent_runtime.contracts import GATEWAY, REPO, card_request, traced_answer_request
from agent_runtime.jira import JiraTicket
from agent_runtime.monitoring.langfuse_tracing import (
    LONGEST_EXPORT_WAIT,
    LangfuseSettings,
    LangfuseTracing,
)
from agent_runtime.monitoring.masking import GRACE_SECONDS, MASKED, Masker
from agent_runtime.planner import FixedPlanner
from agent_runtime.summary import TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from tests.fakes import FakeClock, FakeJira, FakeSource, ScriptedChat, asks, call, langgraph_tags
from tests.test_api import KEY, SETTINGS, Posts

MARKER = "PLANTMARKER-visible"
IN_MESSAGE = "sk-ant-api03-plantedINmessage0123456789abcdefXYZ"
MODEL_KEY = "gw-plantedmodelkey-7f3a9c2e1b5d"
IN_SETTINGS = "settingsecret-plantedgithub-91ab77"
CALLBACK_TOKEN = "cbtoken-planted-in-tool-result-55e1c0"
IN_HEADER = "plantedheaderbearer0123456789abcd"
IN_METADATA = "ghp_plantedINmetadata01"
IN_ERROR = "sk-ant-api03-plantedINerror0123456789abcdefXYZ"
IN_EXCEPTION = "sk-ant-api03-plantedINexception0123456789abcdef"

PLANTED = (
    IN_MESSAGE,
    MODEL_KEY,
    IN_SETTINGS,
    CALLBACK_TOKEN,
    IN_HEADER,
    IN_METADATA,
    IN_ERROR,
    IN_EXCEPTION,
)
ENV = {"GITHUB_TOKEN": IN_SETTINGS, "AGENT_API_KEY": KEY}


class ToolChat(ScriptedChat):
    """A scripted chat whose structured answers go through the model call, as a real
    provider's do, so the callbacks see them."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> Runnable[Any, AIMessage]:  # type: ignore[override]
        return self  # type: ignore[return-value]

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:  # type: ignore[override]
        return BaseChatModel.with_structured_output(self, schema, **kwargs)


def everything_in(span: ReadableSpan) -> str:
    """All of a span that an exporter sends: its name, attributes, status, events, links and
    resource."""
    lines = [span.name, span.status.description or ""]
    lines += [f"{k}={v}" for k, v in (span.attributes or {}).items()]
    for event in span.events:
        lines += [event.name, *(f"{k}={v}" for k, v in (event.attributes or {}).items())]
    for link in span.links:
        lines += [f"{k}={v}" for k, v in (link.attributes or {}).items()]
    lines += [f"{k}={v}" for k, v in span.resource.attributes.items()]
    return "\n".join(lines)


def langfuse(masker: Masker, exporter: SpanExporter) -> LangfuseTracing:
    return LangfuseTracing(
        LangfuseSettings(
            # Langfuse keeps one client per public key for the whole process.
            public_key=f"pk-lf-{uuid.uuid4().hex}",
            secret_key="sk-lf-masking-test-not-a-secret",
            base_url="http://langfuse.invalid",
            environment="test",
            release="test",
        ),
        masker,
        span_exporter=exporter,
        httpx_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(207))),
    )


@pytest.fixture
def exported() -> Iterator[tuple[LangfuseTracing, InMemorySpanExporter]]:
    exporter = InMemorySpanExporter()
    tracing = langfuse(Masker.from_env(ENV), exporter)
    yield tracing, exporter
    tracing.shutdown()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Lost(SpanExporter):
    """An exporter that never gets a span out, as when Langfuse is down."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return SpanExportResult.FAILURE


def sent(tracing: LangfuseTracing, exporter: InMemorySpanExporter) -> str:
    tracing.flush()
    spans = exporter.get_finished_spans()
    assert spans, "nothing was exported, so the test proves nothing"
    return "\n".join(everything_in(span) for span in spans)


def app_with(tracing: LangfuseTracing, chat: BaseChatModel) -> TestClient:
    clock = FakeClock()
    jira = FakeJira(
        [JiraTicket(key="MOCK-7", project="MOCK", title=f"Rotate {CALLBACK_TOKEN}", status="Open")]
    )
    runtime = Runtime(
        checker=VersionChecker(
            FakeSource(langgraph_tags()), TemplateSummarizer(), sleep=clock.sleep
        ),
        planner=FixedPlanner(),
        clock=clock,
        callbacks=HttpCallbacks(transport=httpx.MockTransport(Posts())),
        cards=CardRunner(FakeSource(langgraph_tags()[:8]), lambda _: jira, sleep=clock.sleep),
        chat_source=lambda access: (lambda timeout: chat) if access else None,
    )
    return TestClient(create_app(SETTINGS, runtime, tracing=tracing), headers={"X-Agent-Key": KEY})


def planted_turn() -> dict[str, Any]:
    request = traced_answer_request().model_copy(
        update={
            "task": f"{MARKER} add {IN_MESSAGE} to the watchlist",
            "model": ModelAccess(
                style="anthropic", base_url=GATEWAY, model="claude-sonnet-5-5", api_key=MODEL_KEY
            ),
        }
    )
    return json.loads(request.model_dump_json())


def test_no_planted_key_in_a_planner_turn_reaches_an_exported_span(exported: Any):
    tracing, exporter = exported
    chat = ToolChat(
        script=[
            RuntimeError(f"401 from the gateway for {IN_ERROR}"),
            AIMessage(f"I read your key {MODEL_KEY} and the token {IN_SETTINGS}"),
        ]
    )
    client = app_with(tracing, chat)
    for _ in range(2):
        assert client.post("/v1/planner/answer", json=planted_turn()).status_code == 200
    assert chat.script == []
    text = sent(tracing, exporter)
    assert MARKER in text
    assert [p for p in PLANTED if p in text] == []


def test_no_planted_key_in_an_agent_run_reaches_an_exported_span(exported: Any):
    tracing, exporter = exported
    header = {"Authorization": f"Bearer {IN_HEADER}"}
    chat = ScriptedChat(
        script=[
            asks(call("github_read_releases", {"repo": REPO, "headers": header}, "t1")),
            asks(call("jira_search", {"project": "MOCK", "text": MARKER}, "t2")),
            AIMessage(f"Done. The model key was {MODEL_KEY}."),
        ]
    )
    body = json.loads(card_request("run_01JD1").model_dump_json())
    body["callback"]["token"] = CALLBACK_TOKEN
    body["model"] = {
        "style": "anthropic",
        "base_url": GATEWAY,
        "model": "claude-sonnet-5-5",
        "api_key": MODEL_KEY,
    }
    assert app_with(tracing, chat).post("/v1/tasks", json=body).json()["status"] == "finished"
    text = sent(tracing, exporter)
    assert MARKER in text
    assert [p for p in PLANTED if p in text] == []


def test_no_planted_key_in_run_metadata_or_a_raised_error_reaches_an_exported_span(exported: Any):
    tracing, exporter = exported
    chat = ScriptedChat(script=[AIMessage(MARKER)])
    request = AnswerRequest.model_validate(planted_turn())
    with pytest.raises(RuntimeError), tracing.turn(request) as turn:
        model = turn.models(lambda timeout: chat)(10)
        model.invoke("hello", config={"metadata": {"ticket_note": IN_METADATA}})
        raise RuntimeError(f"the provider said {IN_EXCEPTION}")
    with pytest.raises(RuntimeError), tracing.run(card_request("run_01JD1")):
        raise RuntimeError(f"the tool said {IN_EXCEPTION}")
    text = sent(tracing, exporter)
    assert MARKER in text
    assert [p for p in PLANTED if p in text] == []


def test_a_secret_stays_masked_while_its_trace_is_open_however_many_tasks_come_and_go():
    clock = Clock()
    exporter = InMemorySpanExporter()
    tracing = langfuse(Masker(clock=clock), exporter)
    request = AnswerRequest.model_validate(planted_turn())

    def another_task(n: int) -> None:
        task = card_request(f"run_{n:04}")
        task.callback.token = f"another-callback-token-{n:04}"
        with tracing.run(task):
            clock.now += 1

    chat = ScriptedChat(script=[AIMessage(f"{MARKER} the key was {MODEL_KEY}")])
    with tracing.turn(request) as turn:
        # Other requests run on other threads, each its own trace, and leave first. Together they
        # take longer than a released secret's grace.
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(another_task, range(int(GRACE_SECONDS) + 100)))
        tracing.flush()
        turn.models(lambda timeout: chat)(10).invoke("hello")
        turn.answered(Answered(answer=DidntFollowAnswer(), parts=[]))
    text = sent(tracing, exporter)
    tracing.shutdown()
    assert MARKER in text
    assert MODEL_KEY not in text


def test_a_trace_whose_span_never_starts_holds_its_secret_only_for_the_grace(
    monkeypatch: pytest.MonkeyPatch,
):
    clock = Clock()
    masker = Masker(clock=clock)
    tracing = langfuse(masker, InMemorySpanExporter())

    def refused(**_: Any) -> Any:
        raise RuntimeError("no span")

    monkeypatch.setattr(tracing._client, "start_as_current_observation", refused)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError), tracing.turn(AnswerRequest.model_validate(planted_turn())):
        pass
    assert masker.holding == 1
    clock.now += GRACE_SECONDS
    assert masker.holding == 0
    tracing.shutdown()


def test_a_trace_that_is_never_exported_holds_its_secret_only_for_the_grace():
    clock = Clock()
    masker = Masker(clock=clock)
    tracing = langfuse(masker, Lost())
    chat = ScriptedChat(script=[AIMessage(f"the key was {MODEL_KEY}")])
    with tracing.turn(AnswerRequest.model_validate(planted_turn())) as turn:
        turn.models(lambda timeout: chat)(10).invoke("hello")
        clock.now += GRACE_SECONDS * 2
        assert masker.mask(MODEL_KEY) == MASKED
    tracing.flush()
    clock.now += GRACE_SECONDS - 1
    assert masker.mask(MODEL_KEY) == MASKED
    clock.now += 1
    assert masker.holding == 0
    tracing.shutdown()


def test_when_the_masker_is_full_a_trace_is_not_sent_rather_than_anything_unmasked(
    caplog: pytest.LogCaptureFixture,
):
    exporter = InMemorySpanExporter()
    masker = Masker(limit=1)
    tracing = langfuse(masker, exporter)
    first = AnswerRequest.model_validate(planted_turn())
    second_gateway = "gw-second-turn-key-0b9e"
    second = first.model_copy(
        update={
            "task": "the second turn",
            "model": first.model.model_copy(update={"api_key": second_gateway}),
        }
    )
    chat = ScriptedChat(
        script=[AIMessage(f"second {second_gateway}"), AIMessage(f"{MARKER} {MODEL_KEY}")]
    )
    with tracing.turn(first) as first_turn:
        with caplog.at_level(logging.WARNING), tracing.turn(second) as second_turn:
            second_turn.models(lambda timeout: chat)(10).invoke("hello")
            second_turn.answered(Answered(answer=DidntFollowAnswer(), parts=[]))
        first_turn.models(lambda timeout: chat)(10).invoke("hello")
        first_turn.answered(Answered(answer=DidntFollowAnswer(), parts=[]))
    text = sent(tracing, exporter)
    tracing.shutdown()
    assert MARKER in text
    assert "the second turn" not in text and second_gateway not in text and MODEL_KEY not in text
    assert [r.getMessage() for r in caplog.records if r.name.endswith("langfuse_tracing")] == [
        "Not traced: the masker already holds 1 secrets"
    ]


def test_a_released_secret_outlasts_the_longest_a_span_can_wait_to_be_masked():
    assert GRACE_SECONDS >= 4 * LONGEST_EXPORT_WAIT
