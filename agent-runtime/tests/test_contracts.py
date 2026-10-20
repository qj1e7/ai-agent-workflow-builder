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
    TaskRequest,
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
    "callback-event.json": TypeAdapter(AgentEventPost),
    "agent-cards.json": TypeAdapter(AgentCards),
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
