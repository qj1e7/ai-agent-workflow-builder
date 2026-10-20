import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_runtime.api import (
    HttpCallbacks,
    Runtime,
    Settings,
    build_runtime,
    build_summarizer,
    create_app,
)
from agent_runtime.contract import AgentEventPost, TaskRequest, task_result_adapter
from agent_runtime.contracts import task_request
from agent_runtime.release_checker import ReleaseChecker
from agent_runtime.room import FixedRoomLead
from agent_runtime.summary import ModelSummarizer, TemplateSummarizer
from tests.fakes import FakeClock, FakeSource, langgraph_tags


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


def make_app(source: FakeSource, posts: Posts) -> TestClient:
    clock = FakeClock()
    callbacks = HttpCallbacks(client=httpx.Client(transport=httpx.MockTransport(posts)))
    checker = ReleaseChecker(source, TemplateSummarizer(), sleep=clock.sleep)
    runtime = Runtime(checker=checker, lead=FixedRoomLead(), clock=clock, callbacks=callbacks)
    return TestClient(create_app(runtime))


def request_body(run_id: str = "run_01JB8") -> dict[str, object]:
    return json.loads(task_request(run_id).model_dump_json())


def test_a_task_returns_the_full_result_with_every_event():
    client = make_app(FakeSource(langgraph_tags()), Posts())
    response = client.post("/v1/tasks", json=request_body())
    assert response.status_code == 200
    result = task_result_adapter.validate_python(response.json())
    assert result.status == "finished"
    assert result.task_id == "run_01JB8/work/1/1"
    assert len(result.events) == 8
    assert result.output.new_tags == ["1.2.16", "1.2.15"]


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
    assert len(response.json()["events"]) == 8
    assert len(posts.requests) == 8


def test_the_same_task_id_returns_the_stored_result_without_running_again():
    source, posts = FakeSource(langgraph_tags()), Posts()
    client = make_app(source, posts)
    first = client.post("/v1/tasks", json=request_body())
    second = client.post("/v1/tasks", json=request_body())
    assert second.json() == first.json()
    assert len(source.calls) == 1
    assert len(posts.requests) == 8


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
    settings = Settings.from_env({})
    assert settings.github_api_base == "https://api.github.com"
    assert settings.github_token is None
    assert settings.summary_model is None
    assert isinstance(build_runtime(settings).checker, ReleaseChecker)


def test_settings_read_the_environment():
    settings = Settings.from_env(
        {
            "GITHUB_API_BASE": "http://mock-github:8200",
            "GITHUB_TOKEN": "ghp_example",
            "AGENT_SUMMARY_MODEL": "openai:gpt-4o-mini",
        }
    )
    assert settings.github_api_base == "http://mock-github:8200"
    assert settings.github_token == "ghp_example"
    assert settings.summary_model == "openai:gpt-4o-mini"


@pytest.mark.parametrize(
    ("env", "expected"),
    [({}, TemplateSummarizer), ({"AGENT_SUMMARY_MODEL": "x:y"}, ModelSummarizer)],
)
def test_a_model_is_used_only_when_one_is_named(env: dict[str, str], expected: type):
    assert isinstance(build_summarizer(Settings.from_env(env)), expected)


def test_langsmith_tracing_is_off_unless_its_variables_are_set(monkeypatch: pytest.MonkeyPatch):
    from langsmith import utils

    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGCHAIN_TRACING_V2"):
        monkeypatch.delenv(name, raising=False)
    assert not utils.tracing_is_enabled()
