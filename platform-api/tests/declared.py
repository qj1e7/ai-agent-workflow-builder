from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI

from platform_api.app import create_app
from platform_api.builder.watchlist import (
    NoSuchSoftware,
    NoWatchlist,
    RepoAddedAgainSinceRemoval,
    WatchlistFull,
)
from platform_api.shared import SoftwareId
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


class FakeWatchlist:
    async def view(self) -> None:
        return None

    async def add(self, principal: object, body: object) -> object:
        raise AssertionError("not asked in these tests")

    async def remove(self, software_id: str) -> object:
        return NoSuchSoftware(SoftwareId(software_id))

    async def restore(self, software_id: str) -> object:
        if software_id == "sw_again":
            return RepoAddedAgainSinceRemoval("langchain-ai/langgraph")
        if software_id == "sw_full":
            return WatchlistFull(100)
        return NoSuchSoftware(SoftwareId(software_id))

    async def save_schedule(self, principal: object, body: object) -> object:
        return NoWatchlist()

    async def turn_off_schedule(self) -> object:
        return NoWatchlist()


class FakeTicker:
    async def tick(self) -> list[Any]:
        return []


class FakeMockJira:
    async def tickets(self) -> list[Any]:
        return []

    async def mark_done(self, key: str) -> None:
        return None


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
    app.state.mock_jira = FakeMockJira()
    app.state.watchlist = FakeWatchlist()
    app.state.schedule_ticker = FakeTicker()
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
    components = schema["components"]["schemas"]
    declared_model = components[body_schema["$ref"].rsplit("/", 1)[1]]
    # A tagged union is a component that lists its variants under oneOf.
    refs = declared_model.get("oneOf", [])
    models = [components[r["$ref"].rsplit("/", 1)[1]] for r in refs] or [declared_model]
    body = response.json()
    # A tagged union answers with one of its variants, so the body has to fit one of them.
    assert any(
        set(body) <= set(m["properties"]) and set(m.get("required", [])) <= set(body)
        for m in models
    ), (body, [m["properties"] for m in models])
