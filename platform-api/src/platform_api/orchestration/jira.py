"""Jira, as the platform sees it (ADR 0035): one port, and the write connector built on it.

The write gateway's connector, the watchlist's Done check and the agents' reads all go through the
JiraPort. One adapter, JiraRestAdapter, speaks Jira's REST API to a real Jira or to the practice
Jira. Nothing here decides whether a write may happen: only an AuthorizedWrite reaches the
gateway, and the gateway alone calls the connector.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from platform_api.db import Database
from platform_api.orchestration.write_actions import WriteAction, WriteKey, WriteRefused
from platform_api.shared import TicketStatus

type JiraFlavor = Literal["datacenter", "cloud"]

JIRA_FLAVORS: tuple[JiraFlavor, ...] = ("datacenter", "cloud")
SEARCH_LIMIT = 50


@dataclass(frozen=True)
class JiraIssue:
    key: str
    project: str
    title: str
    body: str
    status: TicketStatus
    created_at: datetime
    done_at: datetime | None
    labels: tuple[str, ...] = ()
    creator: str | None = None
    """The account that made the ticket: Cloud's accountId, or Data Center's user name."""


@dataclass(frozen=True)
class NewIssue:
    project: str
    title: str
    body: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class IssueSearch:
    """Tickets in these projects that match any of the words, newest first."""

    projects: tuple[str, ...]
    words: tuple[str, ...] = ()
    status: TicketStatus | None = None
    done_since: datetime | None = None
    limit: int = SEARCH_LIMIT


class JiraError(Exception):
    """Jira did not do what was asked. The message is plain words, safe to show a person."""

    retryable: bool = True

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class JiraRefused(JiraError):
    """Jira said the request itself is wrong (400, 403, 404). Trying again changes nothing."""

    retryable = False


class JiraUnavailable(JiraError):
    """Jira was busy, down, unreachable, or refused the token. A later try may work."""

    retryable = True


class JiraPort(Protocol):
    async def create_issue(self, issue: NewIssue) -> str: ...

    async def get_issue(self, key: str) -> JiraIssue | None: ...

    async def search(self, query: IssueSearch) -> list[JiraIssue]: ...

    async def find_by_label(self, project: str, label: str) -> JiraIssue | None: ...

    async def whoami(self) -> str: ...

    async def done_tickets(self, keys: Collection[str]) -> Mapping[str, datetime]: ...

    async def move_to_done(self, key: str) -> None: ...

    def browse_url(self, key: str) -> str: ...


def write_label(key: WriteKey) -> str:
    """Our write key as a Jira label. It is only a hint for finding a ticket after a crash: anyone
    who can edit tickets in the project can add it, so it never proves a ticket is ours."""
    return "wab-" + key.text.replace("/", "-")


RECOVERY_SKEW = timedelta(minutes=2)
"""How far Jira's clock may run behind ours when a ticket found after a crash is checked."""


@dataclass(frozen=True)
class JiraWrite:
    started_at: datetime
    ticket_key: str | None


class JiraWriteRecords:
    """The connector's own record of each write key, in our database (ADR 0035)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> JiraWrite | None:
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT started_at, ticket_key FROM orchestration.jira_writes "
                    "WHERE idempotency_key = %s",
                    (key,),
                )
            ).fetchone()
        return None if row is None else JiraWrite(row["started_at"], row["ticket_key"])

    async def creating(self, key: str) -> None:
        """Notes that a ticket for this key may be made from now on. An earlier note is kept,
        so a ticket made by an earlier try still counts as made after the write began."""
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.jira_writes (idempotency_key, started_at) "
                "VALUES (%s, %s) ON CONFLICT (idempotency_key) DO NOTHING",
                (key, uow.now),
            )

    async def made(self, key: str, ticket: str) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.jira_writes SET ticket_key = %s WHERE idempotency_key = %s",
                (ticket, key),
            )

    async def forget(self, key: str) -> None:
        """Jira answered that it made nothing, so the next try starts fresh."""
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "DELETE FROM orchestration.jira_writes "
                "WHERE idempotency_key = %s AND ticket_key IS NULL",
                (key,),
            )


class JiraWriteConnector:
    """Creates a ticket for an approved write, at most once for each write key.

    Our own record decides. A retry after a made ticket answers that ticket and asks Jira nothing.
    Only when our record shows a try began and has no key, as after a crash between Jira's 201
    and our note, does the connector look for the write's label. It accepts a ticket it finds only
    when the platform's own Jira account made it after the write began. Any other ticket with that
    label needs a person, and the write is refused for good."""

    name = "jira"
    operations = frozenset({"create_ticket"})

    def __init__(self, jira: JiraPort, db: Database) -> None:
        self._jira = jira
        self.records = JiraWriteRecords(db)

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        try:
            return await self._execute(action, key)
        except JiraRefused as refused:
            raise WriteRefused(str(refused)) from refused

    async def _execute(self, action: WriteAction, key: WriteKey) -> str:
        project = str(action.target.get("project", ""))
        label = write_label(key)
        record = await self.records.get(key.text)
        if record is not None and record.ticket_key is not None:
            return record.ticket_key
        if record is not None:
            found = await self._jira.find_by_label(project, label)
            if found is not None:
                ours = found.creator is not None and found.creator == await self._jira.whoami()
                if not ours or found.created_at < record.started_at - RECOVERY_SKEW:
                    raise WriteRefused(
                        f"Jira already has {found.key} with this write's label, but the "
                        "platform did not make it. A person needs to check that ticket, then "
                        "start a new run."
                    )
                await self.records.made(key.text, found.key)
                return found.key
        await self.records.creating(key.text)
        try:
            ticket = await self._jira.create_issue(
                NewIssue(
                    project,
                    str(action.fields.get("title", "")),
                    str(action.fields.get("body", "")),
                    (label,),
                )
            )
        except JiraError as error:
            # A 4xx answer means Jira made nothing. A 5xx or no answer may hide a made ticket.
            if error.status is not None and error.status < 500:
                await self.records.forget(key.text)
            raise
        await self.records.made(key.text, ticket)
        return ticket
