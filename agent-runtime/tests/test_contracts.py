import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from agent_runtime.api import Settings, create_app
from agent_runtime.contract import (
    AgentCards,
    AgentEventPost,
    ChooseRequest,
    ChooseResult,
    ConnectRequest,
    ConnectResult,
    DraftRequest,
    DraftResult,
    ModelAccess,
    ModelTestResult,
    TaskRequest,
    ToolList,
    task_result_adapter,
)

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "agent"

pytestmark = pytest.mark.skipif(
    not FIXTURES.exists(), reason="contracts/ is not in the test image. CI runs this on the host."
)

PARSERS: dict[str, TypeAdapter[Any]] = {
    "task-request.json": TypeAdapter(TaskRequest),
    "task-finished.json": task_result_adapter,
    "task-failed.json": task_result_adapter,
    "watchlist-task-request.json": TypeAdapter(TaskRequest),
    "watchlist-task-finished.json": task_result_adapter,
    "callback-event.json": TypeAdapter(AgentEventPost),
    "agent-cards.json": TypeAdapter(AgentCards),
    "model-connect-request.json": TypeAdapter(ConnectRequest),
    "model-connected.json": TypeAdapter(ConnectResult),
    "model-test-request.json": TypeAdapter(ModelAccess),
    "model-test-passed.json": TypeAdapter(ModelTestResult),
    "model-problem.json": TypeAdapter(ModelTestResult),
    "tools.json": TypeAdapter(ToolList),
    "card-task-request.json": TypeAdapter(TaskRequest),
    "card-task-finished.json": task_result_adapter,
    "card-draft-request.json": TypeAdapter(DraftRequest),
    "card-drafted.json": TypeAdapter(DraftResult),
    "room-choose-request.json": TypeAdapter(ChooseRequest),
    "room-chosen.json": TypeAdapter(ChooseResult),
}


def load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_fixture_parses(name: str):
    PARSERS[name].validate_python(load(name))


def test_every_fixture_file_has_a_parser():
    assert {p.name for p in FIXTURES.glob("*.json")} == set(PARSERS)


def test_callback_token_travels_in_a_header_not_the_url():
    request = TaskRequest.model_validate(load("task-request.json"))
    assert request.callback.token not in request.callback.url
    assert "token" not in request.callback.url and "sig" not in request.callback.url


def client_tools() -> object:
    client = TestClient(
        create_app(
            Settings.from_env(
                {
                    "AGENT_API_KEY": "test-agent-key-not-a-secret",
                    "CALLBACK_ALLOWED_ORIGINS": "http://platform-api:8000",
                }
            )
        ),
        headers={"X-Agent-Key": "test-agent-key-not-a-secret"},
    )
    return client.get("/v1/tools").json()


def test_app_serves_the_cards_and_health():
    client = TestClient(
        create_app(
            Settings.from_env(
                {
                    "AGENT_API_KEY": "test-agent-key-not-a-secret",
                    "CALLBACK_ALLOWED_ORIGINS": "http://platform-api:8000",
                }
            )
        )
    )
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/v1/agents").json() == load("agent-cards.json")


def test_the_tool_fixture_is_the_runtimes_tool_list():
    assert client_tools() == load("tools.json")


def test_the_card_task_request_runs_a_card_with_its_values():
    request = TaskRequest.model_validate(load("card-task-request.json"))
    assert request.inputs.kind == "cards"


def test_no_fixture_holds_a_model_key_that_looks_real():
    for path in FIXTURES.glob("*.json"):
        assert "sk-" not in path.read_text()
