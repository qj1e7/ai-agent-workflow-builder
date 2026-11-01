"""The practice Jira for tests: its store, served over in-process HTTP, and the one adapter and
write connector that call it, as wiring sets them up (ADR 0035)."""

from collections.abc import Collection, Mapping
from datetime import datetime

import httpx
from fastapi import FastAPI

from platform_api.db import Database
from platform_api.orchestration.jira import JiraFlavor, JiraWriteConnector
from platform_api.orchestration.jira_rest import JiraAuth, JiraRestAdapter
from platform_api.orchestration.write_actions import WriteAction, WriteKey
from platform_api.practice_jira import PRACTICE_EMAIL, PracticeJira, PracticeTicket, practice_token
from platform_api.practice_jira import router as practice_router

SIGNING_KEY = "test-callback-key"
BASE = "http://platform-api:8000/practice-jira"


async def no_wait(seconds: float) -> None:
    return None


class PracticeKit:
    """A WriteConnector and a TicketStatusPort, like the ones wiring builds, plus the store."""

    name = "jira"
    operations = JiraWriteConnector.operations

    def __init__(self, db: Database, flavor: JiraFlavor = "datacenter") -> None:
        token = practice_token(SIGNING_KEY)
        self.store = PracticeJira(db, token, "http://localhost:8080")
        app = FastAPI()
        app.state.practice_jira = self.store
        app.include_router(practice_router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
        auth = JiraAuth.of(flavor, token, PRACTICE_EMAIL)
        self.jira = JiraRestAdapter(BASE, flavor, auth, self.client, sleep=no_wait)
        self.connector = JiraWriteConnector(self.jira, db)

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        return await self.connector.execute(action, key)

    async def done_tickets(self, keys: Collection[str]) -> Mapping[str, datetime]:
        return await self.jira.done_tickets(keys)

    async def tickets(self) -> list[PracticeTicket]:
        return await self.store.tickets()

    async def mark_done(self, key: str) -> PracticeTicket | None:
        return await self.store.mark_done(key)
