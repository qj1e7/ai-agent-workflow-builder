import hashlib
import hmac
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Protocol, Self

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import APIKeyHeader

from agent_runtime.addresses import AddressPolicy
from agent_runtime.card_runner import CardRunner
from agent_runtime.contract import (
    AgentCard,
    AgentCards,
    AgentEvent,
    AgentEventPost,
    CardsInputs,
    ChooseRequest,
    ChooseResult,
    ConnectRequest,
    ConnectResult,
    DraftRequest,
    DraftResult,
    Health,
    InputKind,
    ModelAccess,
    ModelProblem,
    ModelTestResult,
    TaskError,
    TaskFailed,
    TaskRequest,
    TaskResult,
    ToolList,
)
from agent_runtime.drafting import choose_agents, draft_card
from agent_runtime.events import Clock, EventLog, EventSink
from agent_runtime.github import GitHubReleaseSource
from agent_runtime.guarded import GuardedModels
from agent_runtime.jira import JiraReaderFor, PracticeJiraFor, no_jira
from agent_runtime.model_access import ModelProbe, chat_for, summarizer_for
from agent_runtime.origins import Origin, origin_of, parse_origin_list
from agent_runtime.planner import FixedPlanner, Planner, run_cards, run_task
from agent_runtime.summary import (
    ChatFor,
    ModelSummarizer,
    Summarizer,
    TemplateSummarizer,
    model_factory,
)
from agent_runtime.tools import tool_list, value_problem
from agent_runtime.version_checker import VersionChecker

log = logging.getLogger(__name__)

CALLBACK_TIMEOUT_SECONDS = 2.0
DEFAULT_GITHUB_API_BASE = "https://api.github.com"
TOKEN_HEADER = "X-Callback-Token"
KEY_HEADER = "X-Agent-Key"
# The staff are in Singapore, so "today" in an agent's prompt is the date there.
SINGAPORE = timezone(timedelta(hours=8))

AGENT_CARDS = AgentCards(
    agents=[
        AgentCard(
            id="planner",
            display="Planner",
            description="Reads the task and decides which specialist agents to bring in.",
            capabilities=["plan a task", "bring in specialists", "hand proposals to the platform"],
        ),
        AgentCard(
            id="version_checker",
            display="Version checker",
            description="Reads the releases of public GitHub repositories and finds the new ones, "
            "for one repository or for a list of watched software.",
            capabilities=[
                "read GitHub releases",
                "compare with the last known tag",
                "check a list of watched software",
            ],
        ),
    ]
)


MODEL_NEEDED = TaskError(
    type="ModelNeeded",
    message="Connect an AI model in Settings to run agents.",
    retryable=False,
)
NO_MODEL = ModelProblem(reason="failed", message="No AI model is connected.")


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
    model_base_url: str | None
    model_api_key: str | None
    model_private_hosts: frozenset[str] = frozenset()
    practice_jira_url: str | None = None

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
            model_base_url=env.get("AGENT_MODEL_BASE_URL") or None,
            model_api_key=env.get("AGENT_MODEL_API_KEY") or None,
            model_private_hosts=frozenset(
                host.strip().lower()
                for host in env.get("AGENT_MODEL_PRIVATE_HOSTS", "").split(",")
                if host.strip()
            ),
            practice_jira_url=env.get("PRACTICE_JIRA_URL") or None,
        )

    @property
    def address_policy(self) -> AddressPolicy:
        return AddressPolicy(listed_hosts=self.model_private_hosts)


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


type SummarizerFor = Callable[[ModelAccess], Summarizer]
# The chat model an agent runs on: the one in the request, else the runtime's own, else none.
type ChatSource = Callable[[ModelAccess | None], ChatFor | None]


def _summarizer_under_default_policy(access: ModelAccess) -> Summarizer:
    policy = AddressPolicy()
    return summarizer_for(access, policy, GuardedModels(policy))


def _chat_under_default_policy(access: ModelAccess | None) -> ChatFor | None:
    if access is None:
        return None
    policy = AddressPolicy()
    return chat_for(access, policy, GuardedModels(policy))


@dataclass(frozen=True)
class Runtime:
    checker: VersionChecker
    planner: Planner
    clock: Clock
    callbacks: Callbacks
    summarizer_for: SummarizerFor = field(default=_summarizer_under_default_policy)
    cards: CardRunner | None = None
    chat_source: ChatSource = field(default=_chat_under_default_policy)


def build_summarizer(settings: Settings) -> Summarizer:
    if settings.summary_model:
        factory = model_factory(settings.model_base_url, settings.model_api_key)
        return ModelSummarizer(settings.summary_model, factory=factory)
    return TemplateSummarizer()


def build_runtime(settings: Settings) -> Runtime:
    source = GitHubReleaseSource(settings.github_api_base, token=settings.github_token)
    policy = settings.address_policy
    models = GuardedModels(policy)

    def summarizer_under_policy(access: ModelAccess) -> Summarizer:
        return summarizer_for(access, policy, models)

    def chat_source(access: ModelAccess | None) -> ChatFor | None:
        if access is not None:
            return chat_for(access, policy, models)
        if settings.summary_model:
            name = settings.summary_model

            def from_settings(timeout: float):
                factory = model_factory(
                    settings.model_base_url, settings.model_api_key, timeout=timeout
                )
                return factory(name)

            return from_settings
        return None

    jira_for: JiraReaderFor = (
        PracticeJiraFor(settings.practice_jira_url) if settings.practice_jira_url else no_jira
    )
    return Runtime(
        checker=VersionChecker(source, build_summarizer(settings), sleep=time.sleep),
        planner=FixedPlanner(),
        clock=utc_now,
        callbacks=HttpCallbacks(),
        summarizer_for=summarizer_under_policy,
        cards=CardRunner(source, jira_for, sleep=time.sleep),
        chat_source=chat_source,
    )


class ModelChecks(Protocol):
    def connect(self, request: ConnectRequest) -> ConnectResult: ...

    def test(self, access: ModelAccess) -> ModelTestResult: ...


class TaskIdReused(Exception):
    pass


def fingerprint(request: TaskRequest) -> str:
    # The model is left out: a key replaced between two tries of one task is the same task.
    return hashlib.sha256(request.model_dump_json(exclude={"model"}).encode()).hexdigest()


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


def create_app(
    settings: Settings | None = None,
    runtime: Runtime | None = None,
    models: ModelChecks | None = None,
) -> FastAPI:
    config = settings or Settings.from_env(os.environ)
    active = runtime or build_runtime(config)
    probe = models or ModelProbe(config.address_policy)
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

        if isinstance(body.inputs, CardsInputs):
            return post_cards_task(body, body.inputs)

        checker = active.checker
        if body.model is not None:
            checker = checker.with_summarizer(active.summarizer_for(body.model))

        def run() -> TaskResult:
            events = EventLog(active.clock, active.callbacks.sink_for(body))
            return run_task(body, active.planner, checker, events)

        try:
            return store.run_once(body, run)
        except TaskIdReused as reused:
            raise HTTPException(
                status_code=409, detail="task_id was already used with a different request"
            ) from reused

    def post_cards_task(body: TaskRequest, inputs: CardsInputs) -> TaskResult:
        runner = active.cards
        if runner is None:
            raise HTTPException(status_code=501, detail="this runtime does not run agent cards")
        for agent in inputs.agents:
            kinds: dict[str, InputKind] = {item.name: item.kind for item in agent.card.inputs}
            for name, value in agent.values.items():
                if value_problem(kinds[name], value) is not None:
                    raise HTTPException(
                        status_code=422, detail=f"the value of {name} does not fit its kind"
                    )
        chat = active.chat_source(body.model)
        if chat is None:
            # Not stored: the same task id can run once a model is connected.
            return TaskFailed(task_id=body.task_id, error=MODEL_NEEDED, events=[])
        today = active.clock().astimezone(SINGAPORE).date()

        def run() -> TaskResult:
            events = EventLog(active.clock, active.callbacks.sink_for(body))
            return run_cards(body, inputs, active.planner, runner, chat, today, events)

        try:
            return store.run_once(body, run)
        except TaskIdReused as reused:
            raise HTTPException(
                status_code=409, detail="task_id was already used with a different request"
            ) from reused

    @app.get("/v1/tools", dependencies=[Depends(require_key)])
    def list_tools() -> ToolList:
        return tool_list()

    @app.post("/v1/cards/draft", dependencies=[Depends(require_key)])
    def draft(body: DraftRequest) -> DraftResult:
        chat = active.chat_source(body.model)
        return draft_card(body, chat) if chat else NO_MODEL

    @app.post("/v1/planner/choose", dependencies=[Depends(require_key)])
    def choose(body: ChooseRequest) -> ChooseResult:
        chat = active.chat_source(body.model)
        return choose_agents(body, chat) if chat else NO_MODEL

    @app.post("/v1/models/connect", dependencies=[Depends(require_key)])
    def connect_model(body: ConnectRequest) -> ConnectResult:
        return probe.connect(body)

    @app.post("/v1/models/test", dependencies=[Depends(require_key)])
    def test_model(body: ModelAccess) -> ModelTestResult:
        return probe.test(body)

    @app.get("/v1/agents")
    def list_agents() -> AgentCards:
        return AGENT_CARDS

    @app.get("/healthz")
    def healthz() -> Health:
        return Health()

    return app
