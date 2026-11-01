"""Jira, as the platform sees it (ADR 0035): one port, and the write connector built on it.

The write gateway's connector, the watchlist's Done check and the agents' reads all go through the
JiraPort. One adapter, JiraRestAdapter, speaks Jira's REST API to a real Jira or to the practice
Jira. Nothing here decides whether a write may happen: only an AuthorizedWrite reaches the
gateway, and the gateway alone calls the connector.
"""

import asyncio
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from platform_api.db import Database
from platform_api.orchestration.write_actions import (
    CONNECTOR_TIMEOUT,
    WriteAction,
    WriteKey,
    WriteRefused,
)
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


SUMMARY_LIMIT = 255


def jira_summary(title: str) -> str:
    """A title as Jira's summary: one line of at most 255 characters."""
    return " ".join(title.split())[:SUMMARY_LIMIT]


_WRITE_LABEL = re.compile(r"^wab-run_[A-Za-z0-9]+-prp_[A-Za-z0-9]+-[0-9]+$")


def write_label(key: WriteKey) -> str:
    """Our write key as a Jira label. It is only a hint for finding a ticket after a crash: anyone
    who can edit tickets in the project can add it, so it never proves a ticket is ours."""
    return "wab-" + key.text.replace("/", "-")


RECOVERY_SKEW = timedelta(minutes=2)
"""How far Jira's clock may run behind ours when a ticket found after a crash is checked."""
CONNECTOR_DEADLINE = timedelta(seconds=20)
"""The longest one connector call may take, recovery and create together, whatever Jira does.
Without it, one search could take 3 tries of 10 seconds and 2 waits of 5, which is 40 seconds."""
CLAIM_LEASE = timedelta(seconds=25)
"""How long a try's claim on a write key holds. It outlives the try's deadline, and ends before
the gateway's in-flight timeout, so a second try starts only after the first has stopped."""
assert CONNECTOR_DEADLINE < CLAIM_LEASE < CONNECTOR_TIMEOUT


@dataclass(frozen=True)
class JiraWrite:
    started_at: datetime
    ticket_key: str | None
    claimed_at: datetime | None = None


@dataclass(frozen=True)
class Claim:
    started_at: datetime
    fresh: bool
    """True when no earlier try of this key began, so there is nothing in Jira to look for."""


class JiraWriteRecords:
    """The connector's own record of each write key, in our database (ADR 0035)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> JiraWrite | None:
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT started_at, ticket_key, claimed_at FROM orchestration.jira_writes "
                    "WHERE idempotency_key = %s",
                    (key,),
                )
            ).fetchone()
        if row is None:
            return None
        return JiraWrite(row["started_at"], row["ticket_key"], row["claimed_at"])

    async def claim(self, key: str) -> Claim | None:
        """Claims the key for this try, in one statement. None when another try holds a live
        claim, or the ticket is already noted. An earlier try's start is kept, so a ticket it
        made still counts as made after the write began."""
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "INSERT INTO orchestration.jira_writes "
                    "(idempotency_key, started_at, claimed_at) VALUES (%s, %s, %s) "
                    "ON CONFLICT (idempotency_key) DO UPDATE SET claimed_at = EXCLUDED.claimed_at "
                    "WHERE orchestration.jira_writes.ticket_key IS NULL "
                    "AND (orchestration.jira_writes.claimed_at IS NULL "
                    "OR orchestration.jira_writes.claimed_at <= %s) "
                    "RETURNING started_at, (xmax = 0) AS fresh",
                    (key, uow.now, uow.now, uow.now - CLAIM_LEASE),
                )
            ).fetchone()
        return None if row is None else Claim(row["started_at"], bool(row["fresh"]))

    async def release(self, key: str) -> None:
        """Ends this try's claim. A noted ticket or a dropped row is left as it is."""
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.jira_writes SET claimed_at = NULL "
                "WHERE idempotency_key = %s AND ticket_key IS NULL",
                (key,),
            )

    async def recorded_for(self, ticket: str) -> str | None:
        """The write key our record gives this ticket, if any."""
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT idempotency_key FROM orchestration.jira_writes WHERE ticket_key = %s "
                    "LIMIT 1",
                    (ticket,),
                )
            ).fetchone()
        return None if row is None else str(row["idempotency_key"])

    async def made(self, key: str, ticket: str) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.jira_writes SET ticket_key = %s, claimed_at = NULL "
                "WHERE idempotency_key = %s",
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

    def __init__(
        self, jira: JiraPort, db: Database, deadline: timedelta = CONNECTOR_DEADLINE
    ) -> None:
        self._jira = jira
        self._deadline = deadline
        self.records = JiraWriteRecords(db)

    def link(self, reference: str) -> str:
        return self._jira.browse_url(reference)

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        try:
            return await self._execute(action, key)
        except JiraRefused as refused:
            raise WriteRefused(str(refused)) from refused

    async def _execute(self, action: WriteAction, key: WriteKey) -> str:
        record = await self.records.get(key.text)
        if record is not None and record.ticket_key is not None:
            return record.ticket_key
        claim = await self.records.claim(key.text)
        if claim is None:
            again = await self.records.get(key.text)
            if again is not None and again.ticket_key is not None:
                return again.ticket_key
            raise JiraUnavailable("Another try of this write is in progress.")
        try:
            async with asyncio.timeout(self._deadline.total_seconds()):
                return await self._write(action, key, claim)
        except TimeoutError as late:
            seconds = round(self._deadline.total_seconds())
            raise JiraUnavailable(f"Jira did not finish within {seconds} seconds.") from late
        finally:
            await self.records.release(key.text)

    async def _write(self, action: WriteAction, key: WriteKey, claim: Claim) -> str:
        project = str(action.target.get("project", ""))
        label = write_label(key)
        title = str(action.fields.get("title", ""))
        if not claim.fresh:
            found = await self._jira.find_by_label(project, label)
            if found is not None:
                await self._accept(found, key, label, title, claim.started_at)
                await self.records.made(key.text, found.key)
                return found.key
        try:
            ticket = await self._jira.create_issue(
                NewIssue(project, title, str(action.fields.get("body", "")), (label,))
            )
        except JiraError as error:
            # A 4xx answer means Jira made nothing. A 5xx or no answer may hide a made ticket.
            if error.status is not None and error.status < 500:
                await self.records.forget(key.text)
            raise
        await self.records.made(key.text, ticket)
        return ticket

    async def _accept(
        self, found: JiraIssue, key: WriteKey, label: str, title: str, started_at: datetime
    ) -> None:
        """Refuses, for a person to check, a ticket found by this write's label that the
        platform can't prove it made for this write: made by another account, or by no
        account; made before the write began; already recorded for another write; carrying
        another write's label; or with another title."""

        def refuse(why: str) -> WriteRefused:
            return WriteRefused(
                f"Jira already has {found.key} with this write's label, but {why}. A person "
                "needs to check that ticket, then start a new run."
            )

        if found.creator is None or found.creator != await self._jira.whoami():
            raise refuse("the platform did not make it")
        if found.created_at < started_at - RECOVERY_SKEW:
            raise refuse("it was made before this write began")
        recorded = await self.records.recorded_for(found.key)
        if recorded is not None and recorded != key.text:
            raise refuse("the platform made it for another write")
        if any(_WRITE_LABEL.match(other) and other != label for other in found.labels):
            raise refuse("it also carries another write's label")
        if found.title != jira_summary(title):
            raise refuse("its title is not this write's title")
