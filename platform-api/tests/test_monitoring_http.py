import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx
import pytest
from fastapi import FastAPI
from starlette.types import Message

from platform_api.app import create_app
from platform_api.auth import DevAuth, InMemoryPeople
from platform_api.monitoring import (
    PLATFORM,
    ActivityLog,
    PendingEvent,
    RunFailedData,
    RunRetriedData,
    activity_events_adapter,
    callback_for,
)
from platform_api.orchestration.agents import TaskError
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.runs import DEADLINES, Acting, StepName
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.write_actions import Site, WriteAction, WriteGateway, WriteKey
from platform_api.settings import Settings
from platform_api.shared import N8nExecutionId, RunId, TaskId, UserId
from platform_api.wire import FailureReason, FailureStage
from tests.conftest import PostgresUrls
from tests.practice import PracticeKit
from tests.support import ALICE as ALICE_PRINCIPAL
from tests.support import BOB, FIXTURES, LOCAL_ENV, SPEC
from tests.test_orchestrator import (
    PUBLIC_BASE_URL,
    Harness,
    mint,
    open_harness,
    work_leg_to_approval,
)

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


def app_for(log: ActivityLog, postgres: PostgresUrls) -> FastAPI:
    application = create_app(LOCAL)
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
    return application


@pytest.fixture
async def app(activity_log: ActivityLog, postgres: PostgresUrls) -> AsyncIterator[FastAPI]:
    yield app_for(activity_log, postgres)


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


async def test_the_stream_closes_once_the_person_leaves_the_list(app: FastAPI):
    app.state.person_recheck_seconds = KEEPALIVE / 2
    people: InMemoryPeople = app.state.people
    await append(app, RUN, pending(1))
    headers = {**ALICE, "Accept": "text/event-stream"}
    async with SseConnection(app, f"/api/v1/runs/{RUN}/events", headers) as stream:
        assert event_in(await stream.frame())[0] == 1
        await append(app, RUN, pending(2))
        assert event_in(await stream.frame())[0] == 2
        people.remove(UserId("alice"))
        with pytest.raises(EOFError), anyio.fail_after(KEEPALIVE * 10):
            while True:
                await stream.frame()
    assert (await app.state.people.person(UserId("alice"))) is None


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
    assert [(e.seq, e.kind, e.actor.id) for e in stored] == [(1, "agent_joined", "planner")]


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


def failed_at(stage: FailureStage, reason: FailureReason, retryable: bool) -> PendingEvent:
    return PendingEvent(
        PLATFORM,
        "run_failed",
        "The run failed.",
        RunFailedData(stage=stage, reason=reason, retryable=retryable, message="m"),
    )


async def test_troubleshoot_answers_the_three_questions_for_a_failed_work_leg(
    client: httpx.AsyncClient, app: FastAPI
):
    await append(app, RUN, failed_at("working", "AgentError", True))
    r = await client.get(f"/api/v1/runs/{RUN}/troubleshoot", headers=ALICE)
    assert r.status_code == 200
    answers = r.json()["answers"]
    assert answers["what_happened"] == r.json()["advice"]["explanation"]
    assert answers["what_affected"] == "Nothing was written."
    assert answers["retry"] == {"possible": True, "asks_again": True}
    assert answers["next"] == "retry"
    assert answers["safe_to_retry"].startswith("Yes. A retry runs the work again")
    assert "can_fix" not in answers


async def test_troubleshoot_sends_a_refused_write_to_support(
    client: httpx.AsyncClient, app: FastAPI
):
    await append(app, RUN, failed_at("acting", "WriteFailed", False))
    answers = (await client.get(f"/api/v1/runs/{RUN}/troubleshoot", headers=ALICE)).json()[
        "answers"
    ]
    assert answers["what_affected"] == "The approved write may or may not have reached Jira."
    assert answers["retry"] == {"possible": False, "asks_again": False}
    assert answers["next"] == "report"
    assert answers["safe_to_retry"].startswith("No. ")


async def troubleshoot_run(h: Harness, postgres: PostgresUrls, run_id: RunId) -> dict[str, Any]:
    transport = httpx.ASGITransport(app=app_for(h.log, postgres))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/api/v1/runs/{run_id}/troubleshoot", headers=ALICE)
    assert r.status_code == 200
    return r.json()


async def approved(h: Harness) -> RunId:
    """Bob says yes, and the act leg waits to be handed to the workflow engine."""
    run_id, _, approval_id = await work_leg_to_approval(h)
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    await h.orchestrator.decide(approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest)
    assert isinstance(await h.state(run_id), Acting)
    return run_id


class MadeThenLost:
    """The practice Jira, behind a write step that loses Jira's answer after the ticket is made,
    as a dropped connection does."""

    def __init__(self, jira: PracticeKit) -> None:
        self.jira = jira

    @property
    def name(self) -> str:
        return self.jira.name

    @property
    def operations(self) -> frozenset[str]:
        return self.jira.operations

    @property
    def site(self) -> Site:
        return self.jira.site

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        await self.jira.execute(action, key)
        raise httpx.ReadTimeout("read timed out")

    def link(self, reference: str) -> str:
        return self.jira.link(reference)


async def test_troubleshoot_never_says_nothing_was_written_when_jira_made_the_ticket(
    postgres: PostgresUrls,
):
    async with open_harness(postgres) as h:
        run_id = await approved(h)
        await h.orchestrator.tick()
        lossy = Orchestrator(
            h.db,
            h.log,
            h.engine,
            h.teams,
            h.agent,
            WriteGateway(h.db, [MadeThenLost(h.jira)], poll=0.05),
            mint,
            public_base_url=PUBLIC_BASE_URL,
        )
        reply = await lossy.on_step(run_id, StepName.WRITE_ACTION, N8nExecutionId("42"))
        assert reply.outcome == "failed"
        assert len(await h.jira.tickets()) == 1
        got = await troubleshoot_run(h, postgres, run_id)
    assert (got["failure"]["stage"], got["failure"]["reason"]) == ("acting", "WriteFailed")
    answers = got["answers"]
    assert answers["what_affected"] == "The approved write may or may not have reached Jira."
    assert answers["retry"] == {"possible": True, "asks_again": False}
    assert answers["next"] == "retry"
    assert "finds a ticket an earlier try made" in answers["safe_to_retry"]


async def engine_timed_out(h: Harness) -> None:
    await h.orchestrator.tick()
    h.advance(DEADLINES[Acting] + timedelta(seconds=1))
    await h.orchestrator.tick()


async def engine_failed_at_the_write(h: Harness) -> None:
    await h.orchestrator.tick()
    await h.orchestrator.on_workflow_failure(
        N8nExecutionId("42"), "run", "Do write action", "timed out"
    )


async def engine_down(h: Harness) -> None:
    h.engine.down = True
    for _ in range(20):
        h.advance(timedelta(seconds=10))
        await h.orchestrator.tick()


@pytest.mark.parametrize(
    ("stop", "reason"),
    [
        (engine_timed_out, "TimedOut"),
        (engine_failed_at_the_write, "WorkflowNodeError"),
        (engine_down, "DispatchFailed"),
    ],
    ids=["timed-out", "workflow-node-error", "dispatch-failed"],
)
async def test_troubleshoot_carries_on_after_the_yes_when_the_engine_fails_the_write_step(
    postgres: PostgresUrls, stop: Callable[[Harness], Awaitable[None]], reason: FailureReason
):
    async with open_harness(postgres) as h:
        run_id = await approved(h)
        await stop(h)
        got = await troubleshoot_run(h, postgres, run_id)
    assert (got["failure"]["stage"], got["failure"]["reason"]) == ("acting", reason)
    answers = got["answers"]
    assert answers["retry"] == {"possible": True, "asks_again": False}
    assert answers["what_affected"] == "The approved write may or may not have reached Jira."


@pytest.mark.parametrize(
    ("error", "said"),
    [
        (
            TaskError(
                type="ModelNeeded",
                message="Connect an AI model in Settings to run agents.",
                retryable=False,
            ),
            "No AI model is connected, so the agents couldn't start.",
        ),
        (
            TaskError(
                type="AgentTooSlow",
                message="Release reader ran out of time. A task has 50 seconds.",
                retryable=False,
            ),
            "An agent ran out of time before it finished.",
        ),
        (
            TaskError(
                type="UpstreamRejected", message="GitHub answered 404 Not Found", retryable=False
            ),
            "The agents couldn't finish this step.",
        ),
    ],
    ids=["model-needed", "too-slow", "upstream-rejected"],
)
async def test_troubleshoot_says_only_what_the_agents_stop_carries(
    postgres: PostgresUrls, error: TaskError, said: str
):
    async with open_harness(postgres) as h:
        h.agent.mode = "failed"
        h.agent.error = error
        started = await h.orchestrator.start_run(SPEC, ALICE_PRINCIPAL, "key-1")
        await h.orchestrator.tick()
        await h.orchestrator.on_step(started.run_id, StepName.RUN_AGENTS, N8nExecutionId("41"))
        got = await troubleshoot_run(h, postgres, started.run_id)
    assert (got["failure"]["stage"], got["failure"]["retryable"]) == ("working", False)
    answers = got["answers"]
    assert answers["what_happened"] == said
    assert answers["what_affected"] == "Nothing was written."
    assert answers["retry"] == {"possible": False, "asks_again": False}
    assert answers["next"] == "report"
    assert answers["safe_to_retry"].startswith("No. ")
