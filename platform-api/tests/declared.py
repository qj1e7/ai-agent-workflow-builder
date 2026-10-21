from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI

from platform_api.app import create_app
from tests.support import LOCAL_ENV

ALICE = {"X-Dev-User": "alice"}
BOB = {"X-Dev-User": "bob"}
STEP_KEY = {"X-Step-Key": LOCAL_ENV["STEP_KEY"]}


class FakeOrchestrator:
    def __init__(self, retry: object = None, decide: object = None) -> None:
        self._retry = retry
        self._decide = decide

    async def list_runs(self) -> list[Any]:
        return []

    async def get_run(self, run_id: str) -> None:
        return None

    async def get_approval(self, approval_id: str, principal: object) -> None:
        return None

    async def retry(self, run_id: str, principal: object) -> object:
        return self._retry

    async def decide(self, *args: object) -> object:
        return self._decide


class FakeBuilder:
    def __init__(self, started: object = None) -> None:
        self._started = started

    async def get_use_case(self, use_case_id: str) -> None:
        return None

    async def start_run(self, *args: object) -> object:
        return self._started


class FakeLog:
    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or []
        self.database = SimpleNamespace(clock=lambda: None)

    async def read_after(self, run_id: str, after: int) -> list[Any]:
        return self._events


def app_with(orchestrator: object = None, builder: object = None, log: object = None) -> FastAPI:
    app = create_app(LOCAL_ENV)
    app.state.orchestrator = orchestrator or FakeOrchestrator()
    app.state.builder = builder or FakeBuilder()
    app.state.activity_log = log or FakeLog()
    return app


def declared_status(app: FastAPI, method: str, path: str, response: httpx.Response) -> None:
    """Checks the route declares the status it just answered, with a body of the declared shape."""
    schema = app.openapi()
    operation = schema["paths"][path][method.lower()]
    declared = operation["responses"].get(str(response.status_code))
    answered = response.status_code
    assert declared is not None, (
        f"{method} {path} answered {answered} but declares {sorted(operation['responses'])}"
    )
    assert "content" in declared, f"{method} {path} declares {response.status_code} with no body"
    body_schema = declared["content"]["application/json"]["schema"]
    model = schema["components"]["schemas"][body_schema["$ref"].rsplit("/", 1)[1]]
    body = response.json()
    assert set(body) <= set(model["properties"]), (body, model["properties"])
    assert set(model.get("required", [])) <= set(body), (body, model["required"])
