import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, Self

import httpx
from fastapi import FastAPI

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
from agent_runtime.release_checker import ReleaseChecker
from agent_runtime.room import FixedRoomLead, RoomLead, run_task
from agent_runtime.summary import ModelSummarizer, Summarizer, TemplateSummarizer

log = logging.getLogger(__name__)

CALLBACK_TIMEOUT_SECONDS = 2.0
DEFAULT_GITHUB_API_BASE = "https://api.github.com"
TOKEN_HEADER = "X-Callback-Token"

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


@dataclass(frozen=True)
class Settings:
    github_api_base: str
    github_token: str | None
    summary_model: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        return cls(
            github_api_base=env.get("GITHUB_API_BASE") or DEFAULT_GITHUB_API_BASE,
            github_token=env.get("GITHUB_TOKEN") or None,
            summary_model=env.get("AGENT_SUMMARY_MODEL") or None,
        )


class Callbacks(Protocol):
    def sink_for(self, request: TaskRequest) -> EventSink: ...


class HttpCallbacks:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=CALLBACK_TIMEOUT_SECONDS)

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


# In memory: results are lost on restart and the dict grows with every task id.
class TaskStore:
    def __init__(self) -> None:
        self._results: dict[str, TaskResult] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def run_once(self, task_id: str, run: Callable[[], TaskResult]) -> TaskResult:
        with self._guard:
            lock = self._locks.setdefault(task_id, threading.Lock())
        with lock:
            if task_id not in self._results:
                self._results[task_id] = run()
            return self._results[task_id]


def create_app(runtime: Runtime | None = None) -> FastAPI:
    active = runtime or build_runtime(Settings.from_env(os.environ))
    store = TaskStore()
    app = FastAPI(title="Agent API", version="0.1.0")

    @app.post("/v1/tasks")
    def post_task(body: TaskRequest) -> TaskResult:
        def run() -> TaskResult:
            events = EventLog(active.clock, active.callbacks.sink_for(body))
            return run_task(body, active.lead, active.checker, events)

        return store.run_once(body.task_id, run)

    @app.get("/v1/agents")
    def list_agents() -> AgentCards:
        return AGENT_CARDS

    @app.get("/healthz")
    def healthz() -> Health:
        return Health()

    return app
