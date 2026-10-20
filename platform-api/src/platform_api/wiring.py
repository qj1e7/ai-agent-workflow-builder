"""Builds the three contexts' services from settings and hangs them on the app."""

import asyncio
from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI

from platform_api.builder import Builder
from platform_api.db import Database
from platform_api.monitoring import ActivityLog, callback_for
from platform_api.orchestration.agents import HttpAgentRuntime
from platform_api.orchestration.dispatch import N8nWebhooks, TeamsStub, webhook_path
from platform_api.orchestration.service import Orchestrator
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
    teams_stub: TeamsStub
    mock_jira: MockJiraConnector


def install(app: FastAPI, services: Services) -> None:
    app.state.settings = services.settings
    app.state.step_key = services.settings.step_key
    app.state.db = services.db
    app.state.activity_log = services.activity_log
    app.state.orchestrator = services.orchestrator
    app.state.builder = services.builder
    app.state.teams_stub = services.teams_stub
    app.state.mock_jira = services.mock_jira


async def build(settings: Settings) -> Services:
    db = Database(settings.database)
    await db.open()
    activity = ActivityLog(db)
    await activity.start()
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

    orchestrator = Orchestrator(
        db,
        activity,
        N8nWebhooks(settings.n8n_base_url, webhook_path),
        teams,
        HttpAgentRuntime(settings.agent_runtime_url, settings.agent_api_key),
        WriteGateway(db, [jira]),
        mint,
    )
    return Services(
        settings=settings,
        db=db,
        activity_log=activity,
        orchestrator=orchestrator,
        builder=Builder(db, orchestrator, settings.public_base_url),
        teams_stub=teams,
        mock_jira=jira,
    )


class Runner:
    """Runs the orchestrator's tick loop for the life of the app."""

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
