import json
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_runtime.api import HttpCallbacks, Runtime, Settings, SettingsError, create_app
from agent_runtime.card_runner import CardRunner
from agent_runtime.contract import (
    Answered,
    DidntFollowAnswer,
    ModelProblem,
    ReplyEnvelope,
    RequestPart,
)
from agent_runtime.contracts import answered_cant, card_request, traced_answer_request
from agent_runtime.monitoring.langfuse_tracing import LangfuseSettings, LangfuseTracing
from agent_runtime.monitoring.masking import Masker
from agent_runtime.monitoring.tracing import CodeFlag, NoTracing, TurnOutcome, code_flags
from agent_runtime.planner import FixedPlanner
from agent_runtime.reply_verifier import Verdict
from agent_runtime.summary import TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from tests.fakes import FakeClock, FakeJira, FakeSource, ScriptedChat, langgraph_tags
from tests.test_api import BASE_ENV, KEY, SETTINGS, Posts
from tests.test_free_reply import HELPFUL, WEATHER
from tests.test_questions import reading

CLEAN = Verdict(says_it_happened=False, skips_a_yes=False, claims_unbuilt=False)
CLAIMS_DONE = ReplyEnvelope(form="answer", text="I've created a ticket for you.")


class Recorded:
    """A Langfuse adapter whose spans and scores stay in the test."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.spans = InMemorySpanExporter()
        self.posts: list[tuple[str, Any]] = []
        self.tracing = LangfuseTracing(
            LangfuseSettings(
                # Langfuse keeps one client per public key for the whole process.
                public_key=f"pk-lf-{uuid.uuid4().hex}",
                secret_key="sk-lf-test-not-a-secret",
                base_url="http://langfuse.invalid",
                environment="test",
                release="test",
            ),
            Masker.from_env(env or {}),
            span_exporter=self.spans,
            httpx_client=httpx.Client(transport=httpx.MockTransport(self._post)),
        )

    def _post(self, request: httpx.Request) -> httpx.Response:
        self.posts.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    def exported(self) -> list[ReadableSpan]:
        self.tracing.flush()
        return list(self.spans.get_finished_spans())

    def scores(self) -> list[dict[str, Any]]:
        self.tracing.flush()
        # The client sends its scores in batches, as a list.
        return [
            score for path, batch in self.posts if path == "/api/public/scores" for score in batch
        ]

    def root(self, name: str) -> ReadableSpan:
        [span] = [s for s in self.exported() if s.name == name]
        return span


def trace_of(span: ReadableSpan) -> str:
    context = span.get_span_context()
    assert context is not None
    return format(context.trace_id, "032x")


@pytest.fixture
def recorded() -> Iterator[Recorded]:
    recording = Recorded()
    yield recording
    recording.tracing.shutdown()


def app_with(recorded: Recorded, chat: BaseChatModel) -> TestClient:
    clock = FakeClock()
    runtime = Runtime(
        checker=VersionChecker(
            FakeSource(langgraph_tags()), TemplateSummarizer(), sleep=clock.sleep
        ),
        planner=FixedPlanner(),
        clock=clock,
        callbacks=HttpCallbacks(transport=httpx.MockTransport(Posts())),
        cards=CardRunner(FakeSource(langgraph_tags()[:8]), lambda _: FakeJira(), sleep=clock.sleep),
        chat_source=lambda access: (lambda timeout: chat) if access else None,
    )
    client = create_app(SETTINGS, runtime, tracing=recorded.tracing)
    return TestClient(client, headers={"X-Agent-Key": KEY})


def turn(task: str = WEATHER) -> dict[str, Any]:
    return json.loads(traced_answer_request().model_copy(update={"task": task}).model_dump_json())


def test_a_turn_is_one_trace_under_the_platforms_id_naming_the_person_only_by_pseudonym(
    recorded: Recorded,
):
    chat = ScriptedChat(structured=[reading(), HELPFUL, CLEAN])
    app_with(recorded, chat).post("/v1/planner/answer", json=turn())
    trace = traced_answer_request().trace
    assert trace is not None
    root = recorded.root("planner-turn")
    attributes = root.attributes or {}
    assert trace_of(root) == trace.id
    assert attributes["user.id"] == trace.person
    assert attributes["session.id"] == trace.chat
    assert attributes["langfuse.observation.input"] == WEATHER
    assert json.loads(str(attributes["langfuse.trace.metadata.answer_kind"])) == "reply"
    assert attributes["langfuse.trace.tags"] == ("reply",)
    assert "langfuse.trace.metadata.flagged" not in attributes
    assert recorded.scores() == []


def test_each_model_call_of_the_turn_is_in_the_turns_trace(recorded: Recorded):
    chat = ScriptedChat(script=[AIMessage("hello")])
    request = traced_answer_request()
    assert request.trace is not None
    with recorded.tracing.turn(request) as traced:
        traced.models(lambda timeout: chat)(5).invoke("hi")
        traced.answered(Answered(answer=DidntFollowAnswer(), parts=[]))
    spans = recorded.exported()
    root = recorded.root("planner-turn")
    [call] = [s for s in spans if s.name != "planner-turn"]
    root_context = root.get_span_context()
    assert call.parent is not None and root_context is not None
    assert call.parent.span_id == root_context.span_id
    assert {trace_of(s) for s in spans} == {request.trace.id}


def test_a_free_reply_the_guard_rejects_writes_its_flags_and_why(recorded: Recorded):
    chat = ScriptedChat(structured=[reading(), CLAIMS_DONE])
    app_with(recorded, chat).post("/v1/planner/answer", json=turn())
    trace = traced_answer_request().trace
    trace_id = trace.id if trace else None
    assert sorted((s["name"], s["id"], s["value"], s["dataType"]) for s in recorded.scores()) == [
        (name, f"{trace_id}-{name}", 1.0, "BOOLEAN")
        for name in ("flag_didnt_follow", "flag_fallback", "flag_parts_crossed")
    ]
    attributes = recorded.root("planner-turn").attributes or {}
    assert json.loads(str(attributes["langfuse.trace.metadata.fell_back"])) == "claims_done"
    assert json.loads(str(attributes["langfuse.trace.metadata.flagged"])) == "true"


def test_a_free_reply_whose_call_failed_fell_back_but_was_not_rejected(recorded: Recorded):
    chat = ScriptedChat(structured=[reading(), RuntimeError("boom")])
    app_with(recorded, chat).post("/v1/planner/answer", json=turn())
    assert sorted(s["name"] for s in recorded.scores()) == [
        "flag_didnt_follow",
        "flag_parts_crossed",
    ]
    attributes = recorded.root("planner-turn").attributes or {}
    assert json.loads(str(attributes["langfuse.trace.metadata.fell_back"])) == "call"


def test_a_turn_with_no_trace_from_the_platform_is_traced_without_a_person(recorded: Recorded):
    chat = ScriptedChat(structured=[reading(), HELPFUL, CLEAN])
    body = turn()
    body["trace"] = None
    app_with(recorded, chat).post("/v1/planner/answer", json=body)
    attributes = recorded.root("planner-turn").attributes or {}
    assert "user.id" not in attributes and "session.id" not in attributes


def test_an_agent_task_is_one_trace_in_its_runs_session(recorded: Recorded):
    chat = ScriptedChat(script=[AIMessage("Nothing to do.")])
    body = json.loads(card_request("run_01JD1").model_dump_json())
    body["model"] = json.loads(traced_answer_request().model.model_dump_json())
    assert app_with(recorded, chat).post("/v1/tasks", json=body).json()["status"] == "finished"
    root = recorded.root("agent-run")
    assert (root.attributes or {})["session.id"] == "run_01JD1"
    assert len(recorded.exported()) == 2


def test_turned_off_the_chat_models_are_the_same_and_nothing_is_recorded():
    chat = ScriptedChat(script=[AIMessage("hello")])
    with NoTracing().turn(traced_answer_request()) as traced:
        assert traced.models(lambda timeout: chat)(5) is chat
        traced.answered(Answered(answer=DidntFollowAnswer(), parts=[]))


CROSSED = [RequestPart(text="email me", mark="cant", reason="cant_do", note="No email.")]
DONE = [RequestPart(text="check it", mark="will_do")]


@pytest.mark.parametrize(
    ("outcome", "flags"),
    [
        (TurnOutcome(Answered(answer=DidntFollowAnswer(), parts=DONE), 2.0), ["flag_didnt_follow"]),
        (
            TurnOutcome(Answered(answer=DidntFollowAnswer(), parts=[]), 2.0, "claims_done"),
            ["flag_didnt_follow", "flag_fallback"],
        ),
        (
            TurnOutcome(
                Answered(answer=DidntFollowAnswer(), parts=[]), 2.0, "verifier_says_it_happened"
            ),
            ["flag_didnt_follow", "flag_fallback"],
        ),
        (
            TurnOutcome(Answered(answer=DidntFollowAnswer(), parts=[]), 2.0, "call"),
            ["flag_didnt_follow"],
        ),
        (
            TurnOutcome(Answered(answer=answered_cant().answer, parts=CROSSED), 1.0),
            ["flag_parts_crossed"],
        ),
        (TurnOutcome(Answered(answer=answered_cant().answer, parts=DONE), 13.5), ["flag_slow"]),
        (TurnOutcome(ModelProblem(reason="failed", message="No."), 13.0), []),
        (TurnOutcome(ModelProblem(reason="too_slow", message="Slow."), 13.01), ["flag_slow"]),
    ],
)
def test_each_code_flag_is_raised_only_by_its_own_fact(outcome: TurnOutcome, flags: list[CodeFlag]):
    assert code_flags(outcome) == flags


LANGFUSE_ENV = {
    "LANGFUSE_PUBLIC_KEY": "pk-lf-settings",
    "LANGFUSE_SECRET_KEY": "sk-lf-settings-not-a-secret",
    "LANGFUSE_BASE_URL": "http://langfuse-web:3000",
}


def test_tracing_is_off_unless_the_three_langfuse_settings_are_set():
    assert Settings.from_env(BASE_ENV).langfuse is None
    on = Settings.from_env(
        {
            **BASE_ENV,
            **LANGFUSE_ENV,
            "LANGFUSE_TRACING_ENVIRONMENT": "local",
            "LANGFUSE_RELEASE": "abc",
        }
    )
    assert on.langfuse == LangfuseSettings(
        public_key="pk-lf-settings",
        secret_key="sk-lf-settings-not-a-secret",
        base_url="http://langfuse-web:3000",
        environment="local",
        release="abc",
    )


@pytest.mark.parametrize("left_out", sorted(LANGFUSE_ENV))
def test_a_langfuse_setting_left_out_is_refused_by_name(left_out: str):
    env = {**BASE_ENV, **LANGFUSE_ENV, left_out: ""}
    with pytest.raises(SettingsError, match=left_out):
        Settings.from_env(env)


@pytest.mark.parametrize(
    ("address", "allowed"),
    [
        ("http://langfuse-web:3000", True),
        ("https://langfuse.example.org", True),
        ("http://langfuse.example.org", False),
        ("ftp://langfuse-web", False),
        ("langfuse-web:3000", False),
    ],
)
def test_the_secret_key_goes_only_over_https_or_inside_the_stack(address: str, allowed: bool):
    env = {**BASE_ENV, **LANGFUSE_ENV, "LANGFUSE_BASE_URL": address}
    if allowed:
        assert Settings.from_env(env).langfuse is not None
    else:
        with pytest.raises(SettingsError, match="LANGFUSE_BASE_URL"):
            Settings.from_env(env)
