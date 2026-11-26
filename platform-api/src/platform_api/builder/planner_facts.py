"""The facts snapshot for a question about the person's own data (ADR 0042).

Each section is built from the code the screen it names uses, so one fact has one source: the
Software page's rows, the Workflows page's workflows and their newest runs, and the counts Home
shows under Needs you. A section that cannot be read, or would not fit the cap, is left out, and
the Planner then says it could not answer rather than guess. Every workflow's name is sent, so a
request that names one is never read as asking for something new. Only the state and last run
are capped, and the workflows the request names get theirs first."""

import logging
import re
from collections.abc import Awaitable, Sequence
from typing import Final, Protocol

from platform_api.builder.home import HomeOut
from platform_api.builder.models import (
    UseCaseList,
    UseCaseView,
    WatchedSoftwareView,
    WatchlistView,
)
from platform_api.orchestration import (
    OTHER_WORKFLOWS,
    WORKFLOW_FACTS,
    NeedsYouFact,
    PlannerFacts,
    Status,
    WatchedFact,
    WatchlistScheduleFact,
    WorkflowFact,
)
from platform_api.shared import Principal
from platform_api.wire import RunState

log = logging.getLogger(__name__)

WATCHED_CAP: Final = 100

STATUS_WORDS: Final[dict[Status, str]] = {
    "cant_check": "Can’t check",
    "behind": "New version",
    "awaiting_approval": "Ticket waiting for approval",
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
    "awaiting_approval": "Waiting for approval",
    "succeeded": "Done",
    "rejected": "Declined",
    "failed": "Stopped",
    "skipped": "Skipped",
    "expired": "No answer",
    "lost": "Lost",
}
"""A run's state in the Workflows page's words: its pill while it needs someone or is going, and
its last-run line once it is over (`pillOf` and `lastRunLine` in the Portal)."""


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


def _says_whole(request: str, name: str) -> bool:
    """Whether the request writes the workflow's whole name, so "Check 1" is not "Check 12"."""
    said = name.strip().casefold()
    whole = rf"(?<!\w){re.escape(said)}(?!\w)"
    return bool(said) and re.search(whole, request.casefold()) is not None


def _fact(u: UseCaseView) -> WorkflowFact:
    return WorkflowFact(
        name=u.name,
        state=u.state,
        last_run=None if u.last_run is None else RUN_WORDS[u.last_run.state],
        last_run_at=None if u.last_run is None else u.last_run.at,
    )


NEEDS_SOMEONE: Final[frozenset[RunState]] = frozenset(
    {"failed", "lost", "expired", "awaiting_approval"}
)
"""Last runs a person has to see to: Stopped, Lost, No answer and Waiting for approval."""


def _needs_someone(u: UseCaseView) -> bool:
    stuck = u.last_run is not None and u.last_run.state in NEEDS_SOMEONE
    return stuck or u.state == "paused" or u.grade not in (None, "safe")


def workflows_facts(use_cases: Sequence[UseCaseView], request: str) -> PlannerFacts:
    """The workflows part of the facts: the Workflows page's workflows in its order, the first
    `WORKFLOW_FACTS` with their state and last run. Past that many, the ones the request names by
    their whole name come first, then the ones that need someone, so a question about what
    stopped or what is paused is answered from them. The next `OTHER_WORKFLOWS` come by name,
    and the rest are counted, so the Planner can say it read only some. A name the facts can't
    hold fails here, inside the section."""
    ordered = list(use_cases)
    if len(ordered) > WORKFLOW_FACTS:
        named = {u.use_case_id for u in ordered if _says_whole(request, u.name)}
        ordered.sort(key=lambda u: (u.use_case_id not in named, not _needs_someone(u)))
    rest = ordered[WORKFLOW_FACTS:]
    others = [u.name for u in rest[:OTHER_WORKFLOWS]]
    return PlannerFacts(
        workflows=[_fact(u) for u in ordered[:WORKFLOW_FACTS]],
        other_workflows=others or None,
        left_out_workflows=len(rest) - len(others) or None,
    )


def needs_you_fact(home: HomeOut) -> NeedsYouFact:
    """The same sum Home's Needs you shows (`needsTotal` in the Portal), with every part named."""
    approvals = home.approvals_total
    confirmations = len(home.confirmations)
    stopped = home.stopped_total
    connections = len(home.connections)
    addresses = len(home.addresses)
    replies = len(home.replied)
    declined = home.declined_total
    questions = home.questions_for_me_total
    fixes = len(home.fixes)
    setups = len(home.setup_approvals)
    return NeedsYouFact(
        approvals=approvals,
        confirmations=confirmations,
        stopped=stopped,
        connections=connections,
        addresses=addresses,
        replies=replies,
        declined=declined,
        questions=questions,
        fixes=fixes,
        setups=setups,
        total=approvals
        + confirmations
        + stopped
        + connections
        + addresses
        + replies
        + declined
        + questions
        + fixes
        + setups,
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

    async def read(self, viewer: Principal, request: str) -> PlannerFacts:
        workflows = await self._section("workflows", self._read_workflows(request))
        return PlannerFacts(
            watchlist=await self._section("watchlist", self._read_watchlist()),
            workflows=None if workflows is None else workflows.workflows,
            other_workflows=None if workflows is None else workflows.other_workflows,
            left_out_workflows=None if workflows is None else workflows.left_out_workflows,
            needs_you=await self._section("needs_you", self._read_needs_you(viewer)),
            watchlist_schedule=await self._section("schedule", self._read_schedule()),
            watchlist_project=await self._section("project", self._read_project()),
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

    async def _read_schedule(self) -> WatchlistScheduleFact | None:
        """When the Software watchlist checks, so a watch request that names the same time is
        no cross. None while it is off or paused."""
        view = await self._watchlist.view()
        if view is None or view.schedule is None or view.state != "on":
            return None
        return WatchlistScheduleFact(day=view.schedule.day, at=view.schedule.at)

    async def _read_project(self) -> str | None:
        """The Jira project the Software watchlist raises its upgrade tickets in, paused or
        not, so a ticket asked for in another project is never shown as its own."""
        view = await self._watchlist.view()
        return None if view is None else view.ticket_project

    async def _read_workflows(self, request: str) -> PlannerFacts:
        return workflows_facts((await self._workflows.list_use_cases()).use_cases, request)

    async def _read_needs_you(self, viewer: Principal) -> NeedsYouFact:
        return needs_you_fact(await self._home.for_person(viewer))
