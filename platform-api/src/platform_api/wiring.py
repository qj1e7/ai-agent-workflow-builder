import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx
from fastapi import FastAPI

from platform_api.auth import DEV_PEOPLE, DevAuth, OidcAuth
from platform_api.builder import Builder, Home, Watchlist
from platform_api.db import Database
from platform_api.monitoring import ActivityLog, Copier, CosmosEvents, callback_for
from platform_api.orchestration.agents import HttpAgentRuntime
from platform_api.orchestration.dispatch import ApprovalChannel, N8nWebhooks
from platform_api.orchestration.jira import JiraWriteConnector
from platform_api.orchestration.jira_rest import JiraAuth, JiraRestAdapter
from platform_api.orchestration.model_settings import KeyBox, ModelSettings
from platform_api.orchestration.people_store import People
from platform_api.orchestration.planning import CardPlanning
from platform_api.orchestration.runs import Leg
from platform_api.orchestration.schedule_store import ScheduleBook, ScheduleTicker
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.teams import TeamsStub, TeamsWorkflowsWebhook
from platform_api.orchestration.watch_store import WatchFacts
from platform_api.orchestration.workflows import load_all
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.practice_jira import PRACTICE_EMAIL, PracticeJira, practice_token
from platform_api.settings import Settings
from platform_api.shared import RunId, TaskId


@dataclass(frozen=True)
class Services:
    settings: Settings
    db: Database
    activity_log: ActivityLog
    orchestrator: Orchestrator
    builder: Builder
    home: Home
    watchlist: Watchlist
    schedule_ticker: ScheduleTicker
    teams_stub: TeamsStub
    jira: JiraRestAdapter
    jira_client: httpx.AsyncClient
    model_settings: ModelSettings
    people: People
    copier: Copier | None = None
    cosmos: CosmosEvents | None = None
    teams_webhook: TeamsWorkflowsWebhook | None = None
    practice_jira: PracticeJira | None = None


JIRA_TIMEOUT_SECONDS = 10.0


def jira_for(
    settings: Settings, db: Database, client: httpx.AsyncClient
) -> tuple[JiraRestAdapter, PracticeJira | None]:
    """The one Jira adapter (ADR 0035). With no JIRA_BASE_URL it calls the practice Jira that
    platform-api serves itself, over HTTP at its own internal address, as it would call a real
    Jira. The practice Jira's token comes from the callback signing key."""
    jira = settings.jira
    if jira.base_url is None:
        token = practice_token(settings.callback_signing_key)
        practice = PracticeJira(db, token, settings.public_base_url)
        base_url = f"{settings.platform_internal_url}/practice-jira"
        auth = JiraAuth.of(jira.flavor, token, PRACTICE_EMAIL)
    else:
        practice = None
        base_url = jira.base_url
        auth = JiraAuth.of(jira.flavor, jira.token or "", jira.email)
    adapter = JiraRestAdapter(
        base_url, jira.flavor, auth, client, issue_type=jira.issue_type, browse_url=jira.browse_url
    )
    return adapter, practice


def install(app: FastAPI, services: Services) -> None:
    app.state.settings = services.settings
    app.state.step_key = services.settings.step_key
    app.state.db = services.db
    app.state.activity_log = services.activity_log
    app.state.copier = services.copier
    app.state.orchestrator = services.orchestrator
    app.state.builder = services.builder
    app.state.home = services.home
    app.state.watchlist = services.watchlist
    app.state.schedule_ticker = services.schedule_ticker
    app.state.teams_stub = services.teams_stub
    app.state.teams_webhook = services.teams_webhook
    app.state.jira = services.jira
    app.state.practice_jira = services.practice_jira
    app.state.model_settings = services.model_settings
    app.state.people = services.people


def approval_channel(
    settings: Settings, practice: TeamsStub, client: httpx.AsyncClient | None = None
) -> tuple[ApprovalChannel, TeamsWorkflowsWebhook | None]:
    """Where approval cards go (ADR 0036): the practice copy, or real Teams when
    TEAMS_WEBHOOK_URL is set. Returns the channel, and the webhook adapter to close on shutdown."""
    if settings.teams_webhook_url is None:
        return practice, None
    # httpx and httpcore log every request's full address at INFO, and the webhook's address
    # carries its own signature. So with a webhook set, they log only warnings, for every client
    # in this process, n8n's and the agent runtime's too. Their warnings and errors still show.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    webhook = TeamsWorkflowsWebhook(settings.teams_webhook_url, settings.teams_channel, client)
    return webhook, webhook


async def build(settings: Settings) -> Services:
    db = Database(settings.database)
    await db.open()
    cosmos = None if settings.cosmos is None else CosmosEvents.connect(settings.cosmos)
    copier = None if cosmos is None else Copier(db, cosmos)
    if settings.activity_reader == "cosmos" and cosmos is not None:
        activity = ActivityLog(db, copy=cosmos, status=copier)
    else:
        activity = ActivityLog(db)
    await activity.start()
    if copier is not None:
        await copier.start()
    people = People(db)
    match settings.auth:
        case DevAuth():
            await people.seed_dev(DEV_PEOPLE)
        case OidcAuth():
            await people.seed_first(settings.first_people)
    jira_client = httpx.AsyncClient(timeout=JIRA_TIMEOUT_SECONDS, follow_redirects=False)
    jira, practice_jira = jira_for(settings, db, jira_client)
    teams = TeamsStub(db, settings.teams_channel)
    channel, webhook = approval_channel(settings, teams)

    def mint(run_id: RunId, task_id: TaskId, expires_at: datetime) -> tuple[str, str]:
        callback = callback_for(
            settings.callback_signing_key,
            settings.platform_internal_url,
            run_id,
            task_id,
            expires_at,
        )
        return callback.url, callback.token

    definitions = {d.name: d for d in load_all()}

    def path_for(workflow: str, leg: Leg) -> str:
        return definitions[workflow].webhook_path(leg)

    agents = HttpAgentRuntime(settings.agent_runtime_url, settings.agent_api_key)
    secret = settings.settings_encryption_key
    model_settings = ModelSettings(db, agents, KeyBox(secret) if secret else None, people=people)
    orchestrator = Orchestrator(
        db,
        activity,
        N8nWebhooks(settings.n8n_base_url, path_for),
        channel,
        agents,
        WriteGateway(db, [JiraWriteConnector(jira, db)]),
        mint,
        models=model_settings,
        people=people,
        public_base_url=settings.public_base_url,
    )
    schedules = ScheduleBook(db)
    watchlist = Watchlist(db, WatchFacts(db, jira), schedules, settings.watchlist_jira_project)
    await watchlist.adopt_ticket_project()
    builder = Builder(
        db,
        orchestrator,
        watchlist,
        settings.public_base_url,
        CardPlanning(db, model_settings, agents),
        schedules,
    )
    return Services(
        settings=settings,
        db=db,
        activity_log=activity,
        orchestrator=orchestrator,
        builder=builder,
        home=Home(builder, orchestrator, people),
        watchlist=watchlist,
        schedule_ticker=ScheduleTicker(db, schedules, builder, orchestrator),
        teams_stub=teams,
        jira=jira,
        jira_client=jira_client,
        practice_jira=practice_jira,
        model_settings=model_settings,
        people=people,
        copier=copier,
        cosmos=cosmos,
        teams_webhook=webhook,
    )


class Runner:
    def __init__(self, services: Services) -> None:
        self._services = services
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._services.orchestrator.run_forever(self._stop))

    async def stop(self) -> None:
        self._stop.set()
        self._services.orchestrator.nudge()
        if self._task is not None:
            await self._task
        if self._services.teams_webhook is not None:
            await self._services.teams_webhook.close()
        if self._services.copier is not None:
            await self._services.copier.stop()
        await self._services.activity_log.stop()
        await self._services.jira_client.aclose()
        if self._services.cosmos is not None:
            await self._services.cosmos.close()
        await self._services.db.close()
