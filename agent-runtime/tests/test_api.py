import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent_runtime.api import (
    HttpCallbacks,
    Runtime,
    Settings,
    SettingsError,
    build_runtime,
    build_summarizer,
    create_app,
)
from agent_runtime.contract import (
    AgentEventPost,
    Connected,
    ConnectRequest,
    ConnectResult,
    FoundModel,
    ModelAccess,
    ModelTestPassed,
    ModelTestResult,
    TaskFinished,
    TaskRequest,
    task_result_adapter,
)
from agent_runtime.contracts import SUMMARY, TICKET_TITLE, task_request
from agent_runtime.planner import FixedPlanner
from agent_runtime.summary import (
    ModelFactory,
    ModelSummarizer,
    Summarizer,
    TemplateSummarizer,
    model_factory,
)
from agent_runtime.version_checker import VersionChecker
from tests.fakes import FakeClock, FakeSource, langgraph_tags

KEY = "test-agent-key-not-a-secret"
ORIGIN = "http://platform-api:8000"
BASE_ENV = {"AGENT_API_KEY": KEY, "CALLBACK_ALLOWED_ORIGINS": ORIGIN}
SETTINGS = Settings.from_env(BASE_ENV)


class Posts:
    def __init__(self, status: int = 204, error: Exception | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.error = error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error:
            raise self.error
        return httpx.Response(self.status)


def make_runtime(source: FakeSource | None = None, posts: Posts | None = None) -> Runtime:
    clock = FakeClock()
    callbacks = HttpCallbacks(transport=httpx.MockTransport(posts or Posts()))
    checker = VersionChecker(
        source or FakeSource(langgraph_tags()), TemplateSummarizer(), sleep=clock.sleep
    )
    return Runtime(checker=checker, planner=FixedPlanner(), clock=clock, callbacks=callbacks)


def make_app(source: FakeSource, posts: Posts) -> TestClient:
    return TestClient(
        create_app(SETTINGS, make_runtime(source, posts)), headers={"X-Agent-Key": KEY}
    )


def request_body(run_id: str = "run_01JB8") -> dict[str, object]:
    return json.loads(task_request(run_id).model_dump_json())


def test_a_task_returns_the_full_result_with_every_event():
    client = make_app(FakeSource(langgraph_tags()), Posts())
    response = client.post("/v1/tasks", json=request_body())
    assert response.status_code == 200
    result = task_result_adapter.validate_python(response.json())
    assert result.status == "finished"
    assert result.task_id == "run_01JB8/work/1/1"
    assert len(result.events) == 6
    assert [p.fields["title"] for p in result.output.proposed] == [TICKET_TITLE]


def test_a_dead_upstream_is_a_failed_result_not_an_http_error():
    client = make_app(FakeSource(langgraph_tags(), failures=[503] * 3), Posts())
    response = client.post("/v1/tasks", json=request_body())
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"]["retryable"] is True


def test_every_event_is_posted_to_the_callback_with_the_token_in_a_header():
    posts = Posts()
    client = make_app(FakeSource(langgraph_tags()), posts)
    result = client.post("/v1/tasks", json=request_body()).json()
    callback = TaskRequest.model_validate(request_body()).callback
    assert len(posts.requests) == len(result["events"])
    for request, event in zip(posts.requests, result["events"], strict=True):
        assert str(request.url) == callback.url
        assert request.headers["x-callback-token"] == callback.token
        assert callback.token not in str(request.url)
        posted = AgentEventPost.model_validate_json(request.content)
        assert posted.task_id == "run_01JB8/work/1/1"
        assert posted.event.model_dump(mode="json") == event


@pytest.mark.parametrize(
    "posts",
    [
        Posts(error=httpx.ConnectError("refused")),
        Posts(error=httpx.ReadTimeout("slow")),
        Posts(status=500),
        Posts(status=401),
    ],
    ids=["refused", "timeout", "server error", "bad token"],
)
def test_a_failing_callback_never_fails_the_task(posts: Posts):
    client = make_app(FakeSource(langgraph_tags()), posts)
    response = client.post("/v1/tasks", json=request_body())
    assert response.status_code == 200
    assert response.json()["status"] == "finished"
    assert len(response.json()["events"]) == 6
    assert len(posts.requests) == 6


def test_the_same_task_id_returns_the_stored_result_without_running_again():
    source, posts = FakeSource(langgraph_tags()), Posts()
    client = make_app(source, posts)
    first = client.post("/v1/tasks", json=request_body())
    second = client.post("/v1/tasks", json=request_body())
    assert second.json() == first.json()
    assert len(source.calls) == 1
    assert len(posts.requests) == 6


def with_change(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    body = request_body()
    change(body)
    return body


@pytest.mark.parametrize(
    "changed",
    [
        with_change(lambda b: b.update(instruction="Check it twice.")),
        with_change(lambda b: b.update(run_id="run_other")),
        with_change(lambda b: b["inputs"]["software"][0]["source"].update(ref="o/other")),
        with_change(lambda b: b["inputs"]["software"][0].update(our_version="1.2.15")),
        with_change(lambda b: b["inputs"]["software"][0].update(our_version=None)),
        with_change(lambda b: b["callback"].update(token="another-token")),
        with_change(lambda b: b["callback"].update(url=ORIGIN + "/elsewhere")),
    ],
    ids=["instruction", "run id", "repo", "our version", "no version", "token", "callback url"],
)
def test_the_same_task_id_with_a_different_body_gets_409_and_does_not_run(
    changed: dict[str, Any],
):
    source, posts = FakeSource(langgraph_tags()), Posts()
    client = make_app(source, posts)
    first = client.post("/v1/tasks", json=request_body())
    second = client.post("/v1/tasks", json=changed)
    assert second.status_code == 409
    assert len(source.calls) == 1
    assert len(posts.requests) == 6
    assert client.post("/v1/tasks", json=request_body()).json() == first.json()


def test_the_same_body_with_its_keys_in_another_order_is_the_same_request():
    source = FakeSource(langgraph_tags())
    client = make_app(source, Posts())
    body = request_body()
    first = client.post("/v1/tasks", json=body)
    reordered = dict(reversed(list(body.items())))
    second = client.post("/v1/tasks", json=reordered)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(source.calls) == 1


def test_two_bodies_for_one_task_id_at_once_run_only_the_first():
    started = threading.Event()
    source = FakeSource(langgraph_tags())
    fetch = source.fetch

    def slow_fetch(repo: str):
        started.set()
        time.sleep(0.3)
        return fetch(repo)

    source.fetch = slow_fetch
    client = make_app(source, Posts())
    other = with_change(lambda b: b.update(instruction="Something else."))
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(client.post, "/v1/tasks", json=request_body())
        started.wait(2)
        second = pool.submit(client.post, "/v1/tasks", json=other)
        assert first.result().status_code == 200
        assert second.result().status_code == 409
    assert len(source.calls) == 1


def test_a_failed_task_id_is_stored_too():
    source = FakeSource(langgraph_tags(), failures=[503] * 3)
    client = make_app(source, Posts())
    first = client.post("/v1/tasks", json=request_body()).json()
    second = client.post("/v1/tasks", json=request_body()).json()
    assert first["status"] == second["status"] == "failed"
    assert len(source.calls) == 3


def test_two_calls_for_one_task_id_at_once_run_it_once():
    started = threading.Event()
    source = FakeSource(langgraph_tags())
    fetch = source.fetch

    def slow_fetch(repo: str):
        started.set()
        time.sleep(0.3)
        return fetch(repo)

    source.fetch = slow_fetch
    client = make_app(source, Posts())
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(client.post, "/v1/tasks", json=request_body())
        started.wait(2)
        second = pool.submit(client.post, "/v1/tasks", json=request_body())
        assert first.result().json() == second.result().json()
    assert len(source.calls) == 1


def test_different_task_ids_each_run():
    source = FakeSource(langgraph_tags())
    client = make_app(source, Posts())
    client.post("/v1/tasks", json=request_body("run_01JB8"))
    client.post("/v1/tasks", json=request_body("run_01JB9"))
    assert len(source.calls) == 2


def test_a_malformed_task_is_refused_before_anything_runs():
    source = FakeSource(langgraph_tags())
    client = make_app(source, Posts())
    body = request_body()
    del body["callback"]
    assert client.post("/v1/tasks", json=body).status_code == 422
    assert source.calls == []


def test_settings_default_to_the_public_api_and_no_model():
    settings = Settings.from_env(BASE_ENV)
    assert settings.github_api_base == "https://api.github.com"
    assert settings.github_token is None
    assert settings.summary_model is None
    assert settings.model_base_url is None
    assert settings.model_api_key is None
    assert isinstance(build_runtime(settings).checker, VersionChecker)


def test_settings_read_the_environment():
    settings = Settings.from_env(
        {
            **BASE_ENV,
            "GITHUB_API_BASE": "http://mock-github:8200",
            "GITHUB_TOKEN": "ghp_example",
            "AGENT_SUMMARY_MODEL": "openai:gpt-4o-mini",
            "AGENT_MODEL_BASE_URL": "https://gateway.example",
            "AGENT_MODEL_API_KEY": "sk-example",
        }
    )
    assert settings.github_api_base == "http://mock-github:8200"
    assert settings.github_token == "ghp_example"
    assert settings.summary_model == "openai:gpt-4o-mini"
    assert settings.model_base_url == "https://gateway.example"
    assert settings.model_api_key == "sk-example"


@pytest.mark.parametrize(
    ("env", "expected"),
    [({}, TemplateSummarizer), ({"AGENT_SUMMARY_MODEL": "x:y"}, ModelSummarizer)],
)
def test_a_model_is_used_only_when_one_is_named(env: dict[str, str], expected: type):
    assert isinstance(build_summarizer(Settings.from_env({**BASE_ENV, **env})), expected)


def test_the_summary_model_is_reached_through_the_gateway(monkeypatch: pytest.MonkeyPatch):
    gateways: list[tuple[str | None, str | None]] = []

    def factory_for(base_url: str | None, api_key: str | None) -> ModelFactory:
        gateways.append((base_url, api_key))
        return model_factory(base_url, api_key)

    monkeypatch.setattr("agent_runtime.api.model_factory", factory_for)
    env = {
        **BASE_ENV,
        "AGENT_SUMMARY_MODEL": "anthropic:claude-test",
        "AGENT_MODEL_BASE_URL": "https://gateway.example",
        "AGENT_MODEL_API_KEY": "sk-example",
    }
    build_summarizer(Settings.from_env(env))
    assert gateways == [("https://gateway.example", "sk-example")]


def body_with_callback(url: str) -> dict[str, object]:
    body = request_body()
    cast(dict[str, object], body["callback"])["url"] = url
    return body


RUN_PATH = "/internal/v1/runs/run_01JB8/agent-events?task=run_01JB8/work/1/1"


@pytest.mark.parametrize(
    "url",
    [
        "http://platform-api:8000" + RUN_PATH,
        "HTTP://PLATFORM-API:8000" + RUN_PATH,
        "http://platform-api:8000",
        "http://@platform-api:8000" + RUN_PATH,
    ],
    ids=["allowed origin", "same origin in capitals", "bare origin", "empty userinfo"],
)
def test_a_callback_at_an_allowed_origin_runs(url: str):
    source = FakeSource(langgraph_tags())
    client = make_app(source, Posts())
    assert client.post("/v1/tasks", json=body_with_callback(url)).status_code == 200
    assert len(source.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://evil:8000" + RUN_PATH,
        "http://platform-api.evil.com:8000" + RUN_PATH,
        "http://platform-api.:8000" + RUN_PATH,
        "http://169.254.169.254:8000" + RUN_PATH,
        "http://platform-api:8001" + RUN_PATH,
        "http://platform-api" + RUN_PATH,
        "http://platform-api:80" + RUN_PATH,
        "https://platform-api:8000" + RUN_PATH,
        "ftp://platform-api:8000" + RUN_PATH,
        "http://user:pw@platform-api:8000" + RUN_PATH,
        "http://platform-api:8000@evil" + RUN_PATH,
        "http://platform-api:8000\\@evil" + RUN_PATH,
        "http://evil/?http://platform-api:8000",
        "http://evil#@platform-api:8000",
        "//platform-api:8000" + RUN_PATH,
        RUN_PATH,
        "",
        "not a url",
    ],
    ids=[
        "different host",
        "host as a prefix of another",
        "trailing dot host",
        "metadata address",
        "different port",
        "no port",
        "other explicit port",
        "different scheme",
        "other scheme",
        "userinfo",
        "userinfo that hides the real host",
        "backslash that hides the real host",
        "allowed origin in the query",
        "allowed origin in the fragment",
        "no scheme",
        "relative path",
        "empty",
        "garbage",
    ],
)
def test_a_callback_outside_the_allowed_origins_gets_422_and_nothing_runs(url: str):
    source, posts = FakeSource(langgraph_tags()), Posts()
    client = make_app(source, posts)
    response = client.post("/v1/tasks", json=body_with_callback(url))
    assert response.status_code == 422
    assert source.calls == []
    assert posts.requests == []


def test_a_refused_callback_leaves_nothing_stored_for_the_task_id():
    source = FakeSource(langgraph_tags())
    client = make_app(source, Posts())
    assert client.post("/v1/tasks", json=body_with_callback("http://evil/")).status_code == 422
    assert client.post("/v1/tasks", json=request_body()).status_code == 200
    assert len(source.calls) == 1


def test_a_redirect_from_the_callback_is_never_followed():
    seen: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})

    callbacks = HttpCallbacks(transport=httpx.MockTransport(redirect))
    runtime = replace(make_runtime(), callbacks=callbacks)
    client = TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})
    response = client.post("/v1/tasks", json=request_body())
    assert response.status_code == 200
    assert response.json()["status"] == "finished"
    assert {request.url.host for request in seen} == {"platform-api"}
    assert len(seen) == 6


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "  ",
        ",",
        " , ",
        "platform-api:8000",
        "http://",
        "ftp://x",
        "http://x/path",
        "http://x?q=1",
        "http://u@x",
        "*",
    ],
)
def test_the_app_refuses_to_start_without_usable_callback_origins(
    raw: str | None, monkeypatch: pytest.MonkeyPatch
):
    env = {"AGENT_API_KEY": KEY}
    if raw is not None:
        env["CALLBACK_ALLOWED_ORIGINS"] = raw
    with pytest.raises(SettingsError, match="CALLBACK_ALLOWED_ORIGINS"):
        Settings.from_env(env)
    monkeypatch.setattr("os.environ", env)
    with pytest.raises(SettingsError, match="CALLBACK_ALLOWED_ORIGINS"):
        create_app()


def test_several_origins_can_be_allowed():
    env = {**BASE_ENV, "CALLBACK_ALLOWED_ORIGINS": f" {ORIGIN}/ , https://hooks.example "}
    client = TestClient(
        create_app(Settings.from_env(env), make_runtime()), headers={"X-Agent-Key": KEY}
    )
    for number, url in enumerate((ORIGIN + RUN_PATH, "https://hooks.example" + RUN_PATH)):
        body = body_with_callback(url)
        body["task_id"] = f"task-{number}"
        assert client.post("/v1/tasks", json=body).status_code == 200


def without_key(client: TestClient) -> TestClient:
    return TestClient(client.app)


@pytest.mark.parametrize(
    ("headers", "label"),
    [
        ({}, "no key"),
        ({b"X-Agent-Key": b""}, "empty key"),
        ({b"X-Agent-Key": b"wrong"}, "wrong key"),
        ({b"X-Agent-Key": KEY.encode() + b"x"}, "key with extra"),
        ({b"X-Agent-Key": KEY.encode()[:-1]}, "key cut short"),
        ({b"X-Agent-Key": b"k\xe9y"}, "non ascii key"),
        ({b"Authorization": b"Bearer " + KEY.encode()}, "key in the wrong header"),
    ],
)
def test_a_task_without_the_right_key_gets_401_and_does_not_run(
    headers: dict[bytes, bytes], label: str
):
    source, posts = FakeSource(langgraph_tags()), Posts()
    client = without_key(make_app(source, posts))
    response = client.post("/v1/tasks", json=request_body(), headers=headers)
    assert response.status_code == 401, label
    assert source.calls == []
    assert posts.requests == []


def test_the_right_key_runs_the_task():
    client = without_key(make_app(FakeSource(langgraph_tags()), Posts()))
    response = client.post("/v1/tasks", json=request_body(), headers={"X-Agent-Key": KEY})
    assert response.status_code == 200


def test_a_bad_key_is_refused_before_the_body_is_read():
    client = without_key(make_app(FakeSource(langgraph_tags()), Posts()))
    assert client.post("/v1/tasks", json={}).status_code == 401


@pytest.mark.parametrize("path", ["/healthz", "/v1/agents"])
def test_the_static_endpoints_stay_open(path: str):
    client = without_key(make_app(FakeSource(langgraph_tags()), Posts()))
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("env", [{}, {"AGENT_API_KEY": ""}, {"AGENT_API_KEY": "   "}])
def test_the_app_refuses_to_start_without_an_api_key(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
):
    with pytest.raises(SettingsError, match="AGENT_API_KEY"):
        Settings.from_env(env)
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    monkeypatch.setattr("os.environ", env)
    with pytest.raises(SettingsError, match="AGENT_API_KEY"):
        create_app()


def test_the_task_endpoint_documents_the_key_header():
    schema = create_app(SETTINGS).openapi()
    assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Agent-Key",
    }
    assert schema["paths"]["/v1/tasks"]["post"]["security"] == [{"APIKeyHeader": []}]
    assert "security" not in schema["paths"]["/healthz"]["get"]
    assert "security" not in schema["paths"]["/v1/agents"]["get"]


def test_langsmith_tracing_is_off_unless_its_variables_are_set(monkeypatch: pytest.MonkeyPatch):
    from langsmith import utils

    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGCHAIN_TRACING_V2"):
        monkeypatch.delenv(name, raising=False)
    assert not utils.tracing_is_enabled()


GATEWAY_MODEL: dict[str, object] = {
    "style": "anthropic",
    "base_url": "https://llm-gateway.example",
    "model": "claude-haiku-5-5",
    "api_key": "sk-first-key-not-real",
}


def from_the_model(sentence: str, used: list[ModelAccess]) -> Callable[[ModelAccess], Summarizer]:
    def summarizer_for(access: ModelAccess) -> Summarizer:
        used.append(access)

        def factory(name: str) -> BaseChatModel:
            return GenericFakeChatModel(messages=iter([AIMessage(content=sentence)]))

        return ModelSummarizer(access.model, factory=factory)

    return summarizer_for


def test_a_task_that_names_a_model_writes_its_summary_with_that_model():
    used: list[ModelAccess] = []
    runtime = replace(make_runtime(), summarizer_for=from_the_model("From the model.", used))
    client = TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})
    body = request_body()
    body["model"] = GATEWAY_MODEL
    result = task_result_adapter.validate_python(client.post("/v1/tasks", json=body).json())
    assert isinstance(result, TaskFinished)
    assert result.output.summary == "From the model."
    assert [(a.style, a.model) for a in used] == [("anthropic", "claude-haiku-5-5")]


def test_a_task_without_a_model_keeps_the_runtimes_own_summary():
    used: list[ModelAccess] = []
    runtime = replace(make_runtime(), summarizer_for=from_the_model("From the model.", used))
    client = TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})
    result = task_result_adapter.validate_python(
        client.post("/v1/tasks", json=request_body()).json()
    )
    assert isinstance(result, TaskFinished)
    assert result.output.summary == SUMMARY
    assert used == []


def test_a_key_replaced_between_two_tries_of_one_task_is_the_same_task():
    used: list[ModelAccess] = []
    runtime = replace(make_runtime(), summarizer_for=from_the_model("From the model.", used))
    client = TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})
    first = request_body()
    first["model"] = GATEWAY_MODEL
    second = request_body()
    second["model"] = {**GATEWAY_MODEL, "api_key": "sk-second-key-not-real"}
    answer = client.post("/v1/tasks", json=first)
    again = client.post("/v1/tasks", json=second)
    assert again.status_code == 200
    assert again.json() == answer.json()


class FakeModels:
    def __init__(self) -> None:
        self.connected: list[ConnectRequest] = []
        self.tested: list[ModelAccess] = []

    def connect(self, request: ConnectRequest) -> ConnectResult:
        self.connected.append(request)
        return Connected(
            style="openai",
            base_url="https://api.example/v1",
            models=[FoundModel(id="gpt-5-mini", display="gpt-5-mini", suggested=True)],
        )

    def test(self, access: ModelAccess) -> ModelTestResult:
        self.tested.append(access)
        return ModelTestPassed(seconds=1.2, text="Two new releases came out.")


def test_connect_and_test_need_the_agent_key():
    client = TestClient(create_app(SETTINGS, make_runtime(), models=FakeModels()))
    connect = {"base_url": "https://api.example", "api_key": "sk-x"}
    assert client.post("/v1/models/connect", json=connect).status_code == 401
    assert client.post("/v1/models/test", json=GATEWAY_MODEL).status_code == 401


def test_connect_and_test_answer_with_what_the_probe_found():
    models = FakeModels()
    client = TestClient(
        create_app(SETTINGS, make_runtime(), models=models), headers={"X-Agent-Key": KEY}
    )
    connected = client.post(
        "/v1/models/connect", json={"base_url": "https://api.example", "api_key": "sk-x"}
    )
    tested = client.post("/v1/models/test", json=GATEWAY_MODEL)
    assert connected.json()["status"] == "connected"
    assert connected.json()["models"][0]["id"] == "gpt-5-mini"
    assert tested.json() == {
        "status": "passed",
        "seconds": 1.2,
        "text": "Two new releases came out.",
    }
    assert [r.base_url for r in models.connected] == ["https://api.example"]
    assert [a.model for a in models.tested] == ["claude-haiku-5-5"]


def test_settings_read_the_private_model_hosts():
    env = {**BASE_ENV, "AGENT_MODEL_PRIVATE_HOSTS": " Host.Docker.Internal , ollama.lan ,"}
    settings = Settings.from_env(env)
    assert settings.model_private_hosts == frozenset({"host.docker.internal", "ollama.lan"})
    assert settings.address_policy.listed_hosts == settings.model_private_hosts
    assert Settings.from_env(BASE_ENV).model_private_hosts == frozenset()
