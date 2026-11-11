"""The facts snapshot for a question about the person's own data (ADR 0042).

Each section is built from the code the screen it names uses, so one fact has one source: the
Software page's rows, the Workflows page's workflows and their newest runs, and the counts Home
shows under Needs you. A section that cannot be read, or would not fit the cap, is left out, and
the Planner then says it could not answer rather than guess."""

import logging
from collections.abc import Awaitable, Sequence
from typing import Final, Protocol

from platform_api.builder.home import HomeOut
from platform_api.builder.models import UseCaseList, WatchedSoftwareView, WatchlistView
from platform_api.orchestration import (
    NeedsYouFact,
    PlannerFacts,
    Status,
    WatchedFact,
    WorkflowFact,
)
from platform_api.shared import Principal
from platform_api.wire import RunState

log = logging.getLogger(__name__)

WATCHED_CAP: Final = 100
WORKFLOW_CAP: Final = 50

STATUS_WORDS: Final[dict[Status, str]] = {
    "cant_check": "Can’t check",
    "behind": "New version",
    "awaiting_approval": "Ticket waiting for a yes",
    "ticket_open": "Ticket open",
    "up_to_date": "Up to date",
    "not_checked": "Not checked yet",
}
"""The Software page's words for a row's state (`statusLabel` in the Portal)."""

RUN_WORDS: Final[dict[RunState, str]] = {
    "pending": "Running",
    "working": "Running",
    "proposed": "Running",
    "acting": "Running",
    "awaiting_approval": "Needs a yes",
    "succeeded": "Done",
    "rejected": "Declined",
    "failed": "Stopped",
}
"""The Workflows page's words for a run (`runFact` in the Portal)."""


class WatchlistSource(Protocol):
    async def view(self) -> WatchlistView | None: ...


class WorkflowSource(Protocol):
    async def list_use_cases(self) -> UseCaseList: ...


class HomeSource(Protocol):
    async def for_person(self, viewer: Principal) -> HomeOut: ...


def status_words(row: WatchedSoftwareView) -> str:
    """Up to date needs a version to be up to date with, as on the Software page."""
    if row.status == "up_to_date" and row.our_version is None:
        return "Nothing newer yet"
    return STATUS_WORDS[row.status]


def watched_facts(software: Sequence[WatchedSoftwareView]) -> list[WatchedFact]:
    return [
        WatchedFact(
            name=s.name,
            repo=s.source.ref,
            our_version=s.our_version,
            newest_version=s.newest_version,
            state=status_words(s),
            checked_at=s.checked_at,
            open_ticket=s.open_ticket,
            awaiting_approval=s.approval_id is not None,
            problem=s.problem,
            our_version_source=None if s.our_version_source is None else s.our_version_source.kind,
            our_version_ticket=None
            if s.our_version_source is None
            else s.our_version_source.ticket,
        )
        for s in software
    ]


def needs_you_fact(home: HomeOut) -> NeedsYouFact:
    """The same sum Home's Needs you shows (`needsTotal` in the Portal)."""
    approvals = home.approvals_total
    confirmations = len(home.confirmations)
    stopped = home.stopped_total
    connections = len(home.connections)
    addresses = len(home.addresses)
    replies = len(home.replied)
    return NeedsYouFact(
        approvals=approvals,
        confirmations=confirmations,
        stopped=stopped,
        connections=connections,
        addresses=addresses,
        replies=replies,
        total=approvals + confirmations + stopped + connections + addresses + replies,
    )


class PlannerFactsReader:
    def __init__(
        self,
        watchlist: WatchlistSource,
        workflows: WorkflowSource,
        home: HomeSource,
    ) -> None:
        self._watchlist = watchlist
        self._workflows = workflows
        self._home = home

    async def read(self, viewer: Principal) -> PlannerFacts:
        return PlannerFacts(
            watchlist=await self._section("watchlist", self._read_watchlist()),
            workflows=await self._section("workflows", self._read_workflows()),
            needs_you=await self._section("needs_you", self._read_needs_you(viewer)),
        )

    async def _section[T](self, name: str, reading: Awaitable[T]) -> T | None:
        try:
            return await reading
        except Exception:
            log.warning(
                "The Planner's facts left out %s: it could not be read", name, exc_info=True
            )
            return None

    async def _read_watchlist(self) -> list[WatchedFact] | None:
        view = await self._watchlist.view()
        if view is None or len(view.software) > WATCHED_CAP:
            return None
        return watched_facts(view.software)

    async def _read_workflows(self) -> list[WorkflowFact] | None:
        use_cases = (await self._workflows.list_use_cases()).use_cases
        if len(use_cases) > WORKFLOW_CAP:
            return None
        return [
            WorkflowFact(
                name=u.name,
                state=u.state,
                last_run=None if u.last_run is None else RUN_WORDS[u.last_run.state],
                last_run_at=None if u.last_run is None else u.last_run.at,
            )
            for u in use_cases
        ]

    async def _read_needs_you(self, viewer: Principal) -> NeedsYouFact:
        return needs_you_fact(await self._home.for_person(viewer))
