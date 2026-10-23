import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx
import pytest
from fastapi import FastAPI
from starlette.types import Message

from platform_api.app import create_app
from platform_api.auth import DevAuth
from platform_api.db import Database
from platform_api.monitoring import (
    PLATFORM,
    ActivityLog,
    PendingEvent,
    RunFailedData,
    RunRetriedData,
    activity_events_adapter,
    callback_for,
)
from platform_api.settings import Settings
from platform_api.shared import RunId, TaskId
from tests.conftest import PostgresUrls
from tests.support import FIXTURES, LOCAL_ENV

pytestmark = pytest.mark.anyio

LOCAL = {**LOCAL_ENV, "CALLBACK_SIGNING_KEY": "test-signing-key"}
ALICE = {"X-Dev-User": "alice"}
KEY = "test-signing-key"
INTERNAL = "http://platform-api:8000"
RUN = RunId("run_01TEST")
TASK = TaskId("run_01TEST/work/1/1")
KEEPALIVE = 0.2
SOON = datetime.now(UTC) + timedelta(hours=2)


def pending(n: int) -> PendingEvent:
    return PendingEvent(
        PLATFORM, "run_retried", f"event {n}", RunRetriedData(leg="work", attempt=n)
    )


def failed(retryable: bool) -> PendingEvent:
    return PendingEvent(
        PLATFORM,
        "run_failed",
        "The run failed.",
        RunFailedData(stage="working", reason="AgentError", retryable=retryable, message="m"),
    )


@pytest.fixture
async def app(db: Database, postgres: PostgresUrls) -> AsyncIterator[FastAPI]:
    application = create_app(LOCAL)
    log = ActivityLog(db)
    await log.start()
    application.state.activity_log = log
    application.state.settings = Settings(
        auth=DevAuth("http://localhost:8000"),
        public_base_url="http://localhost:8000",
        database=postgres.contexts,
        agent_runtime_url="http://agent-runtime:8100",
        agent_api_key="agent-key",
        n8n_base_url="http://n8n:5678",
        step_key="step-key",
        platform_internal_url=INTERNAL,
        callback_signing_key=KEY,
        teams_channel="CODESparks Ops",
    )
    application.state.sse_keepalive_seconds = KEEPALIVE
    try:
        yield application
    finally:
        await log.stop()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def append(app: FastAPI, run_id: RunId, *events: PendingEvent) -> list[int]:
    log: ActivityLog = app.state.activity_log
    async with log.database.transaction("orchestration") as uow:
        return [e.seq for e in await log.append(uow, run_id, events)]


class SseConnection:
    """Drives the ASGI app directly, because httpx's ASGI transport buffers the whole body."""

    def __init__(self, app: FastAPI, path: str, headers: Mapping[str, str]) -> None:
        self._app = app
        self._scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path.split("?")[0],
            "raw_path": path.split("?")[0].encode(),
            "query_string": path.split("?")[1].encode() if "?" in path else b"",
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "server": ("test", 80),
            "client": ("127.0.0.1", 1234),
        }
        self._inbox: asyncio.Queue[Message] = asyncio.Queue()
        self._chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._started = asyncio.Event()
        self._buffer = b""
        self.status = 0
        self.headers: dict[str, str] = {}

    async def __aenter__(self) -> SseConnection:
        self._task = asyncio.create_task(self._app(self._scope, self._receive, self._send))
        await asyncio.wait_for(self._started.wait(), 5)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()

    async def _receive(self) -> Message:
        return await self._inbox.get()

    async def _send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = {k.decode(): v.decode() for k, v in message["headers"]}
            self._started.set()
        elif message["type"] == "http.response.body":
            await self._chunks.put(message.get("body", b""))
            if not message.get("more_body", False):
                await self._chunks.put(None)

    async def frame(self, timeout: float = 5) -> str:
        while b"\n\n" not in self._buffer:
            chunk = await asyncio.wait_for(self._chunks.get(), timeout)
            if chunk is None:
                raise EOFError("stream ended")
            self._buffer += chunk
        frame, _, self._buffer = self._buffer.partition(b"\n\n")
        return frame.decode()

    async def disconnect(self) -> None:
        if self._task.done():
            return
        await self._inbox.put({"type": "http.disconnect"})
        await asyncio.wait_for(self._task, 5)


def event_in(frame: str) -> tuple[int, dict[str, Any]]:
    lines = dict(line.split(": ", 1) for line in frame.splitlines())
    assert lines["event"] == "activity"
    return int(lines["id"]), json.loads(lines["data"])


async def test_the_json_page_returns_events_after_a_seq(client: httpx.AsyncClient, app: FastAPI):
    await append(app, RUN, pending(1), pending(2), pending(3))
    r = await client.get(f"/api/v1/runs/{RUN}/events", params={"after": 1}, headers=ALICE)
    assert r.status_code == 200
    assert [e["seq"] for e in r.json()["events"]] == [2, 3]
    assert r.headers["content-type"].startswith("application/json")


async def test_an_unknown_run_has_an_empty_page(client: httpx.AsyncClient):
    r = await client.get("/api/v1/runs/run_nobody/events", headers=ALICE)
    assert (r.status_code, r.json()) == (200, {"events": []})


async def test_the_events_route_needs_a_signed_in_user(client: httpx.AsyncClient):
    assert (await client.get(f"/api/v1/runs/{RUN}/events")).status_code == 401


async def test_the_stream_resumes_after_last_event_id_then_follows_and_keeps_alive(app: FastAPI):
    await append(app, RUN, pending(1), pending(2), pending(3))
    headers = {**ALICE, "Accept": "text/event-stream", "Last-Event-ID": "2"}
    async with SseConnection(app, f"/api/v1/runs/{RUN}/events", headers) as stream:
        assert stream.status == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["cache-control"] == "no-cache"
        assert stream.headers["x-accel-buffering"] == "no"

        seq, event = event_in(await stream.frame())
        assert (seq, event["seq"], event["summary"]) == (3, 3, "event 3")

        await append(app, RUN, pending(4), pending(5))
        assert [event_in(await stream.frame())[0] for _ in range(2)] == [4, 5]

        assert await stream.frame(timeout=KEEPALIVE * 5) == ": keep-alive"
        assert await stream.frame(timeout=KEEPALIVE * 5) == ": keep-alive"


async def test_the_stream_falls_back_to_after_when_last_event_id_is_not_a_number(app: FastAPI):
    await append(app, RUN, pending(1), pending(2), pending(3))
    headers = {**ALICE, "Accept": "text/event-stream", "Last-Event-ID": "abc"}
    async with SseConnection(app, f"/api/v1/runs/{RUN}/events?after=2", headers) as stream:
        assert event_in(await stream.frame())[0] == 3
    plain = {**ALICE, "Accept": "text/event-stream"}
    async with SseConnection(app, f"/api/v1/runs/{RUN}/events", plain) as stream:
        assert [event_in(await stream.frame())[0] for _ in range(3)] == [1, 2, 3]


async def test_a_disconnected_stream_stops_the_handler(app: FastAPI):
    headers = {**ALICE, "Accept": "text/event-stream"}
    async with SseConnection(app, f"/api/v1/runs/{RUN}/events", headers) as stream:
        with anyio.fail_after(5):
            await stream.disconnect()


def callback_headers(token: str | None = None) -> dict[str, str]:
    expires = datetime.now(UTC) + timedelta(hours=2)
    minted = token if token is not None else callback_for(KEY, INTERNAL, RUN, TASK, expires).token
    return {"X-Callback-Token": minted}


def callback_post(agent_seq: int = 1) -> dict[str, Any]:
    post = json.loads((FIXTURES / "agent" / "callback-event.json").read_text())
    post["task_id"] = TASK
    post["event"]["agent_seq"] = agent_seq
    return post


async def test_a_signed_callback_is_stored_once(client: httpx.AsyncClient, app: FastAPI):
    url = f"/internal/v1/runs/{RUN}/agent-events"
    request = {"params": {"task": TASK}, "json": callback_post(), "headers": callback_headers()}
    first = await client.post(url, **request)
    again = await client.post(url, **request)
    assert (first.status_code, again.status_code) == (202, 202)

    log: ActivityLog = app.state.activity_log
    stored = await log.read_after(RUN, 0)
    assert [(e.seq, e.kind, e.actor.id) for e in stored] == [(1, "agent_joined", "room_lead")]


@pytest.mark.parametrize(
    ("token", "task"),
    [
        ("not-a-token", TASK),
        (callback_for(KEY, INTERNAL, RUN, TaskId("run_01TEST/work/2/1"), SOON).token, TASK),
        (None, "run_01TEST/work/2/1"),
    ],
)
async def test_a_bad_callback_is_refused_without_detail(
    client: httpx.AsyncClient, app: FastAPI, token: str | None, task: str
):
    r = await client.post(
        f"/internal/v1/runs/{RUN}/agent-events",
        params={"task": task},
        json=callback_post(),
        headers=callback_headers(token),
    )
    assert r.status_code == 401
    assert r.json() == {"detail": "Unauthorized"}
    log: ActivityLog = app.state.activity_log
    assert await log.read_after(RUN, 0) == []


async def test_troubleshoot_answers_404_for_an_unknown_run(client: httpx.AsyncClient):
    r = await client.get("/api/v1/runs/run_nobody/troubleshoot", headers=ALICE)
    assert r.status_code == 404


async def test_troubleshoot_answers_409_when_the_run_has_not_failed(
    client: httpx.AsyncClient, app: FastAPI
):
    await append(app, RUN, pending(1))
    r = await client.get(f"/api/v1/runs/{RUN}/troubleshoot", headers=ALICE)
    assert r.status_code == 409


async def test_troubleshoot_answers_409_once_the_failed_run_is_retried(
    client: httpx.AsyncClient, app: FastAPI
):
    await append(app, RUN, failed(True), pending(2))
    r = await client.get(f"/api/v1/runs/{RUN}/troubleshoot", headers=ALICE)
    assert r.status_code == 409


async def test_troubleshoot_matches_the_recorded_answer(client: httpx.AsyncClient, app: FastAPI):
    story = activity_events_adapter.validate_python(
        json.loads((FIXTURES / "runs" / "failure.json").read_text())
    )
    run_id = story[0].run_id
    await append(
        app, run_id, *(PendingEvent(e.actor, e.kind, e.summary, e.data, ts=e.ts) for e in story)
    )
    r = await client.get(f"/api/v1/runs/{run_id}/troubleshoot", headers=ALICE)
    assert r.status_code == 200
    assert r.json() == json.loads((FIXTURES / "troubleshooting" / "failure.json").read_text())


async def test_troubleshoot_tells_a_refused_agent_apart_from_an_outage(
    client: httpx.AsyncClient, app: FastAPI
):
    await append(app, RUN, failed(False))
    r = await client.get(f"/api/v1/runs/{RUN}/troubleshoot", headers=ALICE)
    assert r.status_code == 200
    assert r.json()["advice"]["suggested_action"] == "ask_maintainer"
    assert r.json()["failure"]["retryable"] is False
