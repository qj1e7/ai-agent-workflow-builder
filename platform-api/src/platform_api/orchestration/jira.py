"""Jira, as the platform sees it (ADR 0035): one port, and the write connector built on it.

The write gateway's connector, the watchlist's Done check and the agents' reads all go through the
JiraPort. One adapter, JiraRestAdapter, speaks Jira's REST API to a real Jira or to the practice
Jira. Nothing here decides whether a write may happen: only an AuthorizedWrite reaches the
gateway, and the gateway alone calls the connector.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

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

    async def find_by_label(self, project: str, label: str) -> str | None: ...

    async def done_tickets(self, keys: Collection[str]) -> Mapping[str, datetime]: ...

    async def move_to_done(self, key: str) -> None: ...

    def browse_url(self, key: str) -> str: ...


def write_label(key: WriteKey) -> str:
    """Our write key as a Jira label. Jira has no idempotency key, so this label is how a retry
    finds the ticket an earlier try made."""
    return "wab-" + key.text.replace("/", "-")


class JiraWriteConnector:
    """Creates a ticket for an approved write, at most once for each write key."""

    name = "jira"
    operations = frozenset({"create_ticket"})

    def __init__(self, jira: JiraPort) -> None:
        self._jira = jira

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        project = str(action.target.get("project", ""))
        label = write_label(key)
        try:
            found = await self._jira.find_by_label(project, label)
            if found is not None:
                return found
            return await self._jira.create_issue(
                NewIssue(
                    project,
                    str(action.fields.get("title", "")),
                    str(action.fields.get("body", "")),
                    (label,),
                )
            )
        except JiraRefused as refused:
            raise WriteRefused(str(refused)) from refused
