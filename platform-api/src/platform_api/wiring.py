import asyncio
from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI

from platform_api.auth import DEV_PEOPLE, DevAuth, OidcAuth
from platform_api.builder import Builder, Watchlist
from platform_api.db import Database
from platform_api.monitoring import ActivityLog, callback_for
from platform_api.orchestration.agents import HttpAgentRuntime
from platform_api.orchestration.dispatch import N8nWebhooks, TeamsStub
from platform_api.orchestration.model_settings import KeyBox, ModelSettings
from platform_api.orchestration.people_store import People
from platform_api.orchestration.planning import CardPlanning
from platform_api.orchestration.runs import Leg
from platform_api.orchestration.schedule_store import ScheduleBook, ScheduleTicker
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.watch_store import WatchFacts
from platform_api.orchestration.workflows import load_all
from platform_api.orchestration.write_actions import MockJiraConnector, WriteGateway
from platform_api.settings import Settings
from platform_api.shared import RunId, TaskId


@dataclass(frozen=True)
class Services:
    settings: Settings
    db: Database
    activity_log: ActivityLog
    orchestrator: Orchestrator
    builder: Builder
    watchlist: Watchlist
    schedule_ticker: ScheduleTicker
    teams_stub: TeamsStub
    mock_jira: MockJiraConnector
    model_settings: ModelSettings
    people: People


def install(app: FastAPI, services: Services) -> None:
    app.state.settings = services.settings
    app.state.step_key = services.settings.step_key
    app.state.db = services.db
    app.state.activity_log = services.activity_log
    app.state.orchestrator = services.orchestrator
    app.state.builder = services.builder
    app.state.watchlist = services.watchlist
    app.state.schedule_ticker = services.schedule_ticker
    app.state.teams_stub = services.teams_stub
    app.state.mock_jira = services.mock_jira
    app.state.model_settings = services.model_settings
    app.state.people = services.people


async def build(settings: Settings) -> Services:
    db = Database(settings.database)
    await db.open()
    activity = ActivityLog(db)
    await activity.start()
    people = People(db)
    match settings.auth:
        case DevAuth():
            await people.seed_dev(DEV_PEOPLE)
        case OidcAuth():
            await people.seed_first(settings.first_people)
    jira = MockJiraConnector(db)
    teams = TeamsStub(db, settings.teams_channel)

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
    model_settings = ModelSettings(db, agents, KeyBox(secret) if secret else None)
    orchestrator = Orchestrator(
        db,
        activity,
        N8nWebhooks(settings.n8n_base_url, path_for),
        teams,
        agents,
        WriteGateway(db, [jira]),
        mint,
        models=model_settings,
    )
    schedules = ScheduleBook(db)
    watchlist = Watchlist(db, WatchFacts(db, jira), schedules)
    builder = Builder(
        db,
        orchestrator,
        watchlist,
        settings.public_base_url,
        CardPlanning(db, model_settings, agents),
    )
    return Services(
        settings=settings,
        db=db,
        activity_log=activity,
        orchestrator=orchestrator,
        builder=builder,
        watchlist=watchlist,
        schedule_ticker=ScheduleTicker(db, schedules, builder, orchestrator),
        teams_stub=teams,
        mock_jira=jira,
        model_settings=model_settings,
        people=people,
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
        await self._services.activity_log.stop()
        await self._services.db.close()
