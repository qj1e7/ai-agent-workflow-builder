import hashlib
import hmac
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Self

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import APIKeyHeader

from agent_runtime.contract import (
    AgentCard,
    AgentCards,
    AgentEvent,
    AgentEventPost,
    Health,
    TaskRequest,
    TaskResult,
)
from agent_runtime.events import Clock, EventLog, EventSink
from agent_runtime.github import GitHubReleaseSource
from agent_runtime.origins import Origin, origin_of, parse_origin_list
from agent_runtime.release_checker import ReleaseChecker
from agent_runtime.room import FixedRoomLead, RoomLead, run_task
from agent_runtime.summary import ModelSummarizer, Summarizer, TemplateSummarizer

log = logging.getLogger(__name__)

CALLBACK_TIMEOUT_SECONDS = 2.0
DEFAULT_GITHUB_API_BASE = "https://api.github.com"
TOKEN_HEADER = "X-Callback-Token"
KEY_HEADER = "X-Agent-Key"

AGENT_CARDS = AgentCards(
    agents=[
        AgentCard(
            id="room_lead",
            display="Room lead",
            description="Reads the task and decides which specialist agents to bring in.",
            capabilities=["plan a task", "bring in specialists", "hand proposals to the platform"],
        ),
        AgentCard(
            id="release_checker",
            display="Release checker",
            description="Reads a public GitHub repository's releases and finds the new ones.",
            capabilities=["read GitHub releases", "compare with the last known tag"],
        ),
    ]
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class SettingsError(ValueError):
    pass


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise SettingsError(f"{name} must be set")
    return value


@dataclass(frozen=True)
class Settings:
    agent_api_key: str
    callback_allowed_origins: frozenset[Origin]
    github_api_base: str
    github_token: str | None
    summary_model: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        api_key = _required(env, "AGENT_API_KEY")
        raw_origins = _required(env, "CALLBACK_ALLOWED_ORIGINS")
        try:
            origins = parse_origin_list(raw_origins)
        except ValueError as bad_origins:
            raise SettingsError(f"CALLBACK_ALLOWED_ORIGINS: {bad_origins}") from bad_origins
        return cls(
            agent_api_key=api_key,
            callback_allowed_origins=origins,
            github_api_base=env.get("GITHUB_API_BASE") or DEFAULT_GITHUB_API_BASE,
            github_token=env.get("GITHUB_TOKEN") or None,
            summary_model=env.get("AGENT_SUMMARY_MODEL") or None,
        )


class Callbacks(Protocol):
    def sink_for(self, request: TaskRequest) -> EventSink: ...


class HttpCallbacks:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            transport=transport, timeout=CALLBACK_TIMEOUT_SECONDS, follow_redirects=False
        )

    def sink_for(self, request: TaskRequest) -> EventSink:
        def post(event: AgentEvent) -> None:
            body = AgentEventPost(task_id=request.task_id, event=event)
            try:
                response = self._client.post(
                    request.callback.url,
                    content=body.model_dump_json(),
                    headers={
                        "Content-Type": "application/json",
                        TOKEN_HEADER: request.callback.token,
                    },
                )
                if response.status_code >= 300:
                    log.warning(
                        "callback for task %s answered %s", request.task_id, response.status_code
                    )
            except httpx.HTTPError as error:
                log.warning(
                    "callback for task %s failed: %s", request.task_id, type(error).__name__
                )

        return post


@dataclass(frozen=True)
class Runtime:
    checker: ReleaseChecker
    lead: RoomLead
    clock: Clock
    callbacks: Callbacks


def build_summarizer(settings: Settings) -> Summarizer:
    if settings.summary_model:
        return ModelSummarizer(settings.summary_model)
    return TemplateSummarizer()


def build_runtime(settings: Settings) -> Runtime:
    source = GitHubReleaseSource(settings.github_api_base, token=settings.github_token)
    return Runtime(
        checker=ReleaseChecker(source, build_summarizer(settings), sleep=time.sleep),
        lead=FixedRoomLead(),
        clock=utc_now,
        callbacks=HttpCallbacks(),
    )


class TaskIdReused(Exception):
    pass


def fingerprint(request: TaskRequest) -> str:
    return hashlib.sha256(request.model_dump_json().encode()).hexdigest()


# In memory: results are lost on restart and the dict grows with every task id.
class TaskStore:
    def __init__(self) -> None:
        self._results: dict[str, tuple[str, TaskResult]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def run_once(self, request: TaskRequest, run: Callable[[], TaskResult]) -> TaskResult:
        digest = fingerprint(request)
        with self._guard:
            lock = self._locks.setdefault(request.task_id, threading.Lock())
        with lock:
            if request.task_id not in self._results:
                self._results[request.task_id] = (digest, run())
            stored_digest, result = self._results[request.task_id]
            if stored_digest != digest:
                raise TaskIdReused(request.task_id)
            return result


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    config = settings or Settings.from_env(os.environ)
    active = runtime or build_runtime(config)
    store = TaskStore()
    app = FastAPI(title="Agent API", version="0.1.0")
    expected_key = config.agent_api_key.encode()
    key_header = APIKeyHeader(name=KEY_HEADER, auto_error=False)

    def require_key(supplied: str | None = Depends(key_header)) -> None:
        if not hmac.compare_digest((supplied or "").encode(), expected_key):
            raise HTTPException(status_code=401, detail="Missing or wrong agent key")

    @app.post("/v1/tasks", dependencies=[Depends(require_key)])
    def post_task(body: TaskRequest) -> TaskResult:
        if origin_of(body.callback.url) not in config.callback_allowed_origins:
            raise HTTPException(status_code=422, detail="callback.url is not at an allowed origin")

        def run() -> TaskResult:
            events = EventLog(active.clock, active.callbacks.sink_for(body))
            return run_task(body, active.lead, active.checker, events)

        try:
            return store.run_once(body, run)
        except TaskIdReused as reused:
            raise HTTPException(
                status_code=409, detail="task_id was already used with a different request"
            ) from reused

    @app.get("/v1/agents")
    def list_agents() -> AgentCards:
        return AGENT_CARDS

    @app.get("/healthz")
    def healthz() -> Health:
        return Health()

    return app
