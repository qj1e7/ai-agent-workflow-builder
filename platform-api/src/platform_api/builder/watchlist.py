"""The team's software watchlist: one use case of the software_watchlist template.

The list of what is watched lives here, in the builder. What the platform has learned about
each software (our version, the newest release, tickets) comes from orchestration through
the WatchlistFacts port, and the two are composed into the view the Portal shows.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from platform_api.builder import layout
from platform_api.builder.in_n8n import discard, write_in_n8n
from platform_api.builder.lifecycle import (
    RESTORE_WINDOW,
    Lifecycle,
    On,
    TooLate,
    is_on,
    lifecycle_of,
)
from platform_api.builder.models import (
    AddressChangeView,
    AddSoftware,
    FindOut,
    FoundProjects,
    LastCheckView,
    NoProjectChecked,
    NoProjectKnown,
    ProjectGuess,
    ScheduleSaveIn,
    ScheduleView,
    SourceView,
    VersionSourceView,
    WatchedSoftwareView,
    WatchlistView,
)
from platform_api.builder.n8n_draft import Checked as Laid
from platform_api.builder.n8n_draft import DraftRefused, N8nNotReady, check_draft
from platform_api.builder.n8n_holds import HeldInN8n, Holding
from platform_api.builder.templates import (
    SOFTWARE_WATCHLIST,
    WATCHLIST_INSTRUCTION,
    WATCHLIST_LIMIT,
    WATCHLIST_NAME,
    WATCHLIST_PROJECT,
)
from platform_api.builder.versions import ChangedSince
from platform_api.db import Connection, Database, UnitOfWork, hold_workflow, json
from platform_api.orchestration import (
    ATTENTION_ORDER,
    ChangedInN8n,
    Checked,
    CouldNotCheck,
    FindSoftwareResult,
    FoundSoftware,
    FromFirstCheck,
    FromTicketDone,
    Given,
    LastCheck,
    LatestCheck,
    N8nDrafts,
    N8nError,
    OpenRuns,
    RuntimeDown,
    SavedSchedule,
    Schedule,
    ScheduleBook,
    SoftwareNotChecked,
    SoftwareNotKnown,
    SoftwareSource,
    Standing,
    WatchedSoftware,
    WatchlistFacts,
    WatchlistStanding,
    WatchlistTask,
    Written,
    next_run,
)
from platform_api.shared import (
    TEAM_TIME_ZONE,
    Principal,
    RunId,
    SoftwareId,
    UseCaseId,
    UserId,
    new_id,
)

log = logging.getLogger(__name__)


class ProjectFinder(Protocol):
    async def find(self, name: str, tag_pattern: str) -> FindSoftwareResult | RuntimeDown: ...


class NoFinder:
    """Stands in until a finder is wired, so the answer is plain: nothing was checked."""

    async def find(self, name: str, tag_pattern: str) -> FindSoftwareResult | RuntimeDown:
        return RuntimeDown("no finder is wired")


NOT_ASKED = (
    "I couldn't ask the agent runtime just now, so I can't check {name} yet. Try again, or "
    "type the GitHub address instead, as owner/name."
)


@dataclass(frozen=True)
class ListedSoftware:
    id: SoftwareId
    name: str
    source: SoftwareSource
    starting_version: str | None
    added_by: UserId
    added_at: datetime

    @property
    def given(self) -> Given | None:
        if self.starting_version is None:
            return None
        return Given(self.starting_version, self.added_at)


@dataclass(frozen=True)
class InN8n:
    """The watchlist's own n8n workflow, and the version of it the records hold."""

    workflow_id: str
    version_id: str | None
    document: Mapping[str, Any] | None
    draft: str | None = None
    """n8n's draft as the platform last saw it, which the version compare checks."""


@dataclass(frozen=True)
class WatchlistRecord:
    use_case_id: UseCaseId
    version: int
    owner: UserId
    ticket_project: str
    software: tuple[ListedSoftware, ...]
    lifecycle: Lifecycle
    n8n: InN8n | None = None
    """None while the watchlist still runs on the shared run workflow (ENGINE-PLAN 2.6)."""
    left_in_n8n: str | None = None
    """A workflow a move made and named before it was cut off, while the watchlist still runs on
    the shared run workflow. The next move removes it."""


@dataclass(frozen=True)
class OnN8n:
    """What the watchlist needs to run as its own n8n workflow."""

    drafts: N8nDrafts
    runs: OpenRuns
    software_page: str
    """The Software page's address, which the workflow's note links to."""
    holding: Holding | None = None


@dataclass(frozen=True)
class MovedToN8n:
    workflow_id: str
    version: int


@dataclass(frozen=True)
class AlreadyOnN8n:
    pass


@dataclass(frozen=True)
class WaitsForRun:
    """A run of the watchlist has not ended, so the watchlist stays where it is until it ends,
    and nothing that run waits for is lost."""

    run_id: RunId


@dataclass(frozen=True)
class RepoAlreadyWatched:
    ref: str


@dataclass(frozen=True)
class NoSuchSoftware:
    software_id: SoftwareId


@dataclass(frozen=True)
class RepoAddedAgainSinceRemoval:
    ref: str


@dataclass(frozen=True)
class WatchlistFull:
    limit: int


@dataclass(frozen=True)
class NoMoveReported:
    """GitHub has not told the latest check that this software moved to that address."""

    software_id: SoftwareId


@dataclass(frozen=True)
class NeverAtThatAddress:
    ref: str


def source_url(source: SoftwareSource) -> str:
    """The page a person opens to see the versions the check reads."""
    match source.kind:
        case "github":
            return f"https://github.com/{source.ref}/releases"
        case "maven":
            group, _, artifact = source.ref.partition(":")
            return f"https://central.sonatype.com/artifact/{group}/{artifact}/versions"
        case "npm":
            return f"https://www.npmjs.com/package/{source.ref}?activeTab=versions"


def source_view(source: SoftwareSource) -> SourceView:
    return SourceView(kind=source.kind, ref=source.ref, url=source_url(source))


def same_source(a: SoftwareSource, b: SoftwareSource) -> bool:
    """A change of case is the same repository or package."""
    return a.kind == b.kind and a.ref.casefold() == b.ref.casefold()


def moved_to(listed: ListedSoftware, check: LatestCheck | None) -> str | None:
    """The repository GitHub answered for the saved one, when it is another one. A change of
    case is the same repository. Only a GitHub repository can move this way."""
    if listed.source.kind != "github":
        return None
    named = None if check is None else check.github_name
    if named is None or named.casefold() == listed.source.ref.casefold():
        return None
    return named


def software_view(
    listed: ListedSoftware,
    standing: Standing,
    changes: Sequence[AddressChangeView] = (),
) -> WatchedSoftwareView:
    facts = standing.facts
    ours: str | None = None
    compared_from: str | None = None
    match facts.our_version:
        case None:
            our_source = None
        case Given(version, at):
            ours = version
            our_source = VersionSourceView(kind="given", at=at, ticket=None)
        case FromFirstCheck(version, at):
            compared_from = version
            our_source = VersionSourceView(kind="first_check", at=at, ticket=None)
        case FromTicketDone(version, at, ticket):
            ours = version
            our_source = VersionSourceView(kind="ticket_done", at=at, ticket=ticket)
    moved = moved_to(listed, facts.latest_check)
    match facts.latest_check:
        case None:
            newest, read_at, checked_at, problem = None, None, None, None
        case Checked(_, at, newest_version):
            newest, read_at, checked_at, problem = newest_version, at, at, None
        case CouldNotCheck(_, at, why, last_read):
            newest = None if last_read is None else last_read.version
            read_at = None if last_read is None else last_read.at
            checked_at, problem = at, why
    return WatchedSoftwareView(
        id=listed.id,
        name=listed.name,
        source=source_view(listed.source),
        our_version=ours,
        our_version_source=our_source,
        compared_from=compared_from,
        newest_version=newest,
        newest_read_at=read_at,
        checked_at=checked_at,
        status=standing.status,
        problem=problem,
        open_ticket=None if facts.open_ticket is None else facts.open_ticket.key,
        approval_id=None if facts.pending is None else facts.pending.approval_id,
        moved_to=moved,
        not_found=isinstance(facts.latest_check, CouldNotCheck) and facts.latest_check.not_found,
        address_changes=list(changes[:ADDRESS_CHANGES_SHOWN]),
        added_by=listed.added_by,
        added_at=listed.added_at,
    )


def attention_first(views: Sequence[WatchedSoftwareView]) -> list[WatchedSoftwareView]:
    return sorted(views, key=lambda v: (ATTENTION_ORDER.index(v.status), v.name.casefold()))


def last_check_view(last: LastCheck | None) -> LastCheckView | None:
    if last is None:
        return None
    return LastCheckView(run_id=last.run_id, state=last.state, started_at=last.started_at)


@dataclass(frozen=True)
class NoWatchlist:
    pass


type ScheduleRefused = N8nNotReady | DraftRefused | ChangedInN8n | ChangedSince | HeldInN8n
type Move = MovedToN8n | AlreadyOnN8n | WaitsForRun | NoWatchlist | N8nNotReady | DraftRefused


def schedule_view(
    saved: SavedSchedule | None,
    now: datetime,
    on: bool,
    team_zone: str,
    n8n: InN8n | None = None,
) -> ScheduleView | None:
    """The next check is when its own n8n workflow's Schedule Trigger fires, to the second n8n
    adds to it (ENGINE-PLAN 2.4). Still on the shared run workflow, it starts none until it
    moves, and a held schedule starts none until an Operator takes it over."""
    if saved is None:
        return None
    next_at = None
    if n8n is not None and n8n.document is not None:
        next_at = next_run(n8n.document, n8n.workflow_id, now, team_zone)
    return ScheduleView(
        day=saved.schedule.day,
        at=saved.schedule.at,
        time_zone=saved.schedule.time_zone,
        owner=saved.owner,
        owner_name=saved.owner_name,
        saved_at=saved.saved_at,
        next_at=next_at if on and saved.held is None else None,
        held=saved.held,
        held_words=saved.held_words,
    )


def view(
    record: WatchlistRecord,
    standing: WatchlistStanding,
    schedule: ScheduleView | None = None,
    changes: Mapping[SoftwareId, Sequence[AddressChangeView]] | None = None,
    moving: bool = False,
) -> WatchlistView:
    return WatchlistView(
        use_case_id=record.use_case_id,
        version=record.version,
        ticket_project=record.ticket_project,
        state="on" if is_on(record.lifecycle) else "paused",
        software=attention_first(
            [
                software_view(
                    listed, standing.software[listed.id], (changes or {}).get(listed.id, ())
                )
                for listed in record.software
            ]
        ),
        last_check=last_check_view(standing.last_check),
        schedule=schedule,
        moving_to_n8n=moving,
    )


def task(record: WatchlistRecord, standing: WatchlistStanding) -> WatchlistTask:
    """What the check tells the agents: for each software, our version as the platform knows
    it, the open ticket, and whether a ticket already awaits an Approver."""
    software: list[WatchedSoftware] = []
    for listed in record.software:
        facts = standing.software[listed.id].facts
        software.append(
            WatchedSoftware(
                id=listed.id,
                name=listed.name,
                source=listed.source,
                our_version=None if facts.our_version is None else facts.our_version.version,
                open_ticket=None if facts.open_ticket is None else facts.open_ticket.key,
                awaiting_approval=facts.pending is not None,
                from_first_check=isinstance(facts.our_version, FromFirstCheck),
            )
        )
    return WatchlistTask(tag_pattern=SOFTWARE_WATCHLIST.tag_pattern, software=tuple(software))


def given_versions(record: WatchlistRecord) -> Mapping[SoftwareId, Given | None]:
    return {listed.id: listed.given for listed in record.software}


_CURRENT = """
    SELECT u.use_case_id, u.owner, u.paused_at, u.paused_by, u.deleted_at, u.deleted_by,
           u.draft, u.engine, u.n8n_workflow_id, u.n8n_draft_id, v.version, v.params,
           v.n8n_version_id, v.document
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
    WHERE v.template = %s
"""
_SOFTWARE_COLUMNS = (
    "software_id, name, source_kind, source_ref, starting_version, added_by, added_at"
)


def _listed(row: Mapping[str, Any]) -> ListedSoftware:
    return ListedSoftware(
        SoftwareId(row["software_id"]),
        row["name"],
        SoftwareSource(row["source_ref"], row["source_kind"]),
        row["starting_version"],
        UserId(row["added_by"]),
        row["added_at"],
    )


async def _software_of(
    conn: Connection, use_case_id: UseCaseId, version: int
) -> tuple[ListedSoftware, ...]:
    rows = await (
        await conn.execute(
            f"SELECT {_SOFTWARE_COLUMNS} FROM builder.watched_software "
            "WHERE use_case_id = %s AND version = %s ORDER BY position",
            (use_case_id, version),
        )
    ).fetchall()
    return tuple(_listed(row) for row in rows)


@dataclass(frozen=True)
class Removal:
    listed: ListedSoftware
    at: datetime


async def _last_removal(
    conn: Connection, use_case_id: UseCaseId, software_id: SoftwareId
) -> Removal | None:
    row = await (
        await conn.execute(
            f"SELECT {_SOFTWARE_COLUMNS}, (SELECT v.created_at FROM builder.use_case_versions v "
            "WHERE v.use_case_id = s.use_case_id AND v.version = s.version + 1) AS removed_at "
            "FROM builder.watched_software s WHERE s.use_case_id = %s AND s.software_id = %s "
            "ORDER BY s.version DESC LIMIT 1",
            (use_case_id, software_id),
        )
    ).fetchone()
    if row is None or row["removed_at"] is None:
        return None
    return Removal(_listed(row), row["removed_at"])


def _listed_in(record: WatchlistRecord, software_id: SoftwareId) -> ListedSoftware | None:
    return next((s for s in record.software if s.id == software_id), None)


def _watched_elsewhere(record: WatchlistRecord, software_id: SoftwareId, ref: str) -> bool:
    """Whether another row watches this GitHub repository. Only GitHub addresses change."""
    wanted = SoftwareSource(ref)
    return any(s.id != software_id and same_source(s.source, wanted) for s in record.software)


def _with_ref(
    record: WatchlistRecord, software_id: SoftwareId, source: SoftwareSource
) -> tuple[ListedSoftware, ...]:
    return tuple(replace(s, source=source) if s.id == software_id else s for s in record.software)


ADDRESS_CHANGES_SHOWN = 10


async def _address_changes(
    conn: Connection, use_case_id: UseCaseId
) -> dict[SoftwareId, list[AddressChangeView]]:
    rows = await (
        await conn.execute(
            "SELECT software_id, kind, from_ref, to_ref, changed_by, changed_at "
            "FROM builder.software_address_changes WHERE use_case_id = %s ORDER BY change_id DESC",
            (use_case_id,),
        )
    ).fetchall()
    found: dict[SoftwareId, list[AddressChangeView]] = {}
    for row in rows:
        found.setdefault(SoftwareId(row["software_id"]), []).append(
            AddressChangeView(
                kind=row["kind"],
                from_repo=row["from_ref"],
                to_repo=row["to_ref"],
                by=UserId(row["changed_by"]),
                at=row["changed_at"],
            )
        )
    return found


async def _record_address_change(
    uow: UnitOfWork,
    use_case_id: UseCaseId,
    software_id: SoftwareId,
    kind: str,
    old: str,
    new: str,
    by: UserId,
) -> None:
    await uow.conn.execute(
        "INSERT INTO builder.software_address_changes (use_case_id, software_id, kind, "
        "from_ref, to_ref, changed_by, changed_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (use_case_id, software_id, kind, old, new, by, uow.now),
    )


@dataclass(frozen=True)
class AddressSwitch:
    at: datetime
    before: tuple[str, ...]


async def _last_switch(
    conn: Connection, use_case_id: UseCaseId, software_id: SoftwareId
) -> AddressSwitch | None:
    """When the software's saved repository last changed, and the repositories it had before,
    newest first. None when it has only ever had one."""
    rows = await (
        await conn.execute(
            "SELECT s.version, s.source_ref, v.created_at FROM builder.watched_software s "
            "JOIN builder.use_case_versions v "
            "ON v.use_case_id = s.use_case_id AND v.version = s.version "
            "WHERE s.use_case_id = %s AND s.software_id = %s ORDER BY s.version DESC",
            (use_case_id, software_id),
        )
    ).fetchall()
    if not rows:
        return None
    current = str(rows[0]["source_ref"]).casefold()
    since = rows[0]["created_at"]
    index = 0
    while index < len(rows) and str(rows[index]["source_ref"]).casefold() == current:
        since = rows[index]["created_at"]
        index += 1
    before: list[str] = []
    for row in rows[index:]:
        ref = str(row["source_ref"])
        if ref.casefold() != current and ref not in before:
            before.append(ref)
    return AddressSwitch(since, tuple(before)) if before else None


async def _current(conn: Connection, lock: bool) -> WatchlistRecord | None:
    suffix = " ORDER BY u.created_at LIMIT 1" + (" FOR UPDATE OF u" if lock else "")
    row = await (await conn.execute(_CURRENT + suffix, (SOFTWARE_WATCHLIST.key,))).fetchone()
    if row is None:
        return None
    use_case_id = UseCaseId(row["use_case_id"])
    own = row["engine"] == "own"
    workflow_id: str | None = row["n8n_workflow_id"]
    return WatchlistRecord(
        use_case_id,
        int(row["version"]),
        UserId(row["owner"]),
        str(row["params"]["ticket_project"]),
        await _software_of(conn, use_case_id, int(row["version"])),
        lifecycle_of(row),
        InN8n(workflow_id, row["n8n_version_id"], row["document"], row["n8n_draft_id"])
        if own and workflow_id
        else None,
        None if own else workflow_id,
    )


async def _name_in_n8n(uow: UnitOfWork, use_case_id: UseCaseId, workflow_id: str | None) -> None:
    await uow.conn.execute(
        "UPDATE builder.use_cases SET n8n_workflow_id = %s WHERE use_case_id = %s",
        (workflow_id, use_case_id),
    )


async def _keep_in_n8n(
    uow: UnitOfWork,
    use_case_id: UseCaseId,
    version: int,
    held: Written,
    grade: str,
    published_by: UserId | None,
) -> None:
    """The version keeps what n8n holds of it, and who put it live from the Portal, whose
    scheduled checks are their work (D5). A version not put live has no publisher yet. The layout
    is the template's, which nobody edits in n8n, so it has no earlier authors. n8n's draft is
    this layout now."""
    await uow.conn.execute(
        "UPDATE builder.use_cases SET n8n_draft_id = %s WHERE use_case_id = %s",
        (held.version_id, use_case_id),
    )
    await uow.conn.execute(
        "UPDATE builder.use_case_versions SET n8n_version_id = %s, document = %s, grade = %s,"
        " published_by = %s, published_in = %s, also = '[]'::jsonb, findings = NULL"
        " WHERE use_case_id = %s AND version = %s",
        (
            held.version_id,
            json(held.document),
            grade,
            published_by,
            None if published_by is None else "portal",
            use_case_id,
            version,
        ),
    )


async def _write_list(
    uow: UnitOfWork, use_case_id: UseCaseId, version: int, software: Sequence[ListedSoftware]
) -> None:
    for position, listed in enumerate(software):
        await uow.conn.execute(
            "INSERT INTO builder.watched_software (use_case_id, version, software_id, position, "
            f"{_SOFTWARE_COLUMNS.replace('software_id, ', '')}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                use_case_id,
                version,
                listed.id,
                position,
                listed.name,
                listed.source.kind,
                listed.source.ref,
                listed.starting_version,
                listed.added_by,
                listed.added_at,
            ),
        )


class Watchlist:
    def __init__(
        self,
        db: Database,
        facts: WatchlistFacts,
        schedules: ScheduleBook,
        ticket_project: str = WATCHLIST_PROJECT,
        finder: ProjectFinder | None = None,
        n8n: OnN8n | None = None,
        time_zone: ZoneInfo = TEAM_TIME_ZONE,
    ) -> None:
        self._db = db
        self._zone = time_zone.key
        """The team time zone: the schedule's, and the one its own n8n workflow runs on."""
        self._facts = facts
        self._schedules = schedules
        self._project = ticket_project
        self._finder = finder or NoFinder()
        self._n8n = n8n

    async def find(self, name: str) -> FindOut:
        """The GitHub projects a name could mean, each checked just now, and which the watchlist
        already holds. It writes nothing. The tag rule is the watchlist's own, so a match
        offered here is one the watch can compare."""
        found = await self._finder.find(name, SOFTWARE_WATCHLIST.tag_pattern)
        match found:
            case RuntimeDown(detail):
                log.warning("finding %r failed: %s", name, detail)
                return NoProjectChecked(message=NOT_ASKED.format(name=name))
            case SoftwareNotKnown(message=message):
                return NoProjectKnown(message=message)
            case SoftwareNotChecked(message=message):
                return NoProjectChecked(message=message)
            case FoundSoftware(matches=matches):
                async with self._db.connection("builder") as conn:
                    record = await _current(conn, lock=False)
                held = (
                    {}
                    if record is None
                    else {(s.source.kind, s.source.ref.casefold()): s.name for s in record.software}
                )
                return FoundProjects(
                    matches=[
                        ProjectGuess(
                            kind=match.kind,
                            repo=match.repo,
                            what=match.what,
                            why=match.why,
                            releases=match.releases,
                            newest=match.newest,
                            already_listed=held.get((match.kind, match.repo.casefold())),
                        )
                        for match in matches
                    ]
                )

    async def adopt_ticket_project(self) -> None:
        """Moves the watchlist to the Jira project the deploy names (WATCHLIST_JIRA_PROJECT), in a
        new version, as a change to the list would. Until the Portal can set the project, the
        setting wins (ADR 0035). Nothing changes when there is no watchlist or it is there."""
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute("SELECT pg_advisory_xact_lock(hashtext('builder.watchlist'))")
            record = await _current(uow.conn, lock=True)
            if record is None or record.ticket_project == self._project:
                return
            moved = await self._next_version(
                uow, record, record.software, ticket_project=self._project
            )
        log.info(
            "watchlist moved from %s to %s by the deploy setting WATCHLIST_JIRA_PROJECT, "
            "version %d",
            record.ticket_project,
            moved.ticket_project,
            moved.version,
        )

    async def view(self) -> WatchlistView | None:
        async with self._db.connection("builder") as conn:
            record = await _current(conn, lock=False)
        return None if record is None else await self._view_of(record)

    async def needing_attention(self) -> list[WatchedSoftwareView]:
        """The rows whose repository GitHub moved or cannot find, in the Software page's order."""
        watchlist = await self.view()
        if watchlist is None:
            return []
        return [row for row in watchlist.software if row.moved_to is not None or row.not_found]

    async def add(
        self, principal: Principal, body: AddSoftware
    ) -> WatchlistView | RepoAlreadyWatched | WatchlistFull:
        async with self._db.transaction("builder") as uow:
            # One watchlist per team: the first two Operators to add software at once must not
            # each make one, so adding takes a lock that exists before the row does.
            await uow.conn.execute("SELECT pg_advisory_xact_lock(hashtext('builder.watchlist'))")
            record = await _current(uow.conn, lock=True)
            source = SoftwareSource(body.source_ref, body.source_kind)
            if record is not None:
                if any(same_source(s.source, source) for s in record.software):
                    return RepoAlreadyWatched(source.ref)
                if len(record.software) >= WATCHLIST_LIMIT:
                    return WatchlistFull(WATCHLIST_LIMIT)
            listed = ListedSoftware(
                SoftwareId(new_id("sw")),
                body.name,
                source,
                body.our_version,
                principal.user_id,
                uow.now,
            )
            created = record is None
            if record is None:
                record = await self._create(uow, principal, listed)
            else:
                record = await self._next_version(uow, record, (*record.software, listed))
        if created:
            await self._schedules.save_default(record.use_case_id, principal, self._zone)
            if self._n8n is not None:
                await self.move_to_n8n()
                record = await self._record() or record
        return await self._view_of(record)

    async def save_schedule(
        self, principal: Principal, body: ScheduleSaveIn
    ) -> WatchlistView | NoWatchlist | ScheduleRefused:
        """Saving makes the caller the schedule owner, and the owner cannot approve its checks."""
        schedule = Schedule(body.day, body.at, self._zone)
        return await self._schedule(principal, schedule, body.expected_version)

    async def turn_off_schedule(
        self, principal: Principal, expected: int
    ) -> WatchlistView | NoWatchlist | ScheduleRefused:
        return await self._schedule(principal, None, expected)

    async def _schedule(
        self, principal: Principal, schedule: Schedule | None, expected: int
    ) -> WatchlistView | NoWatchlist | ScheduleRefused:
        """On its own n8n workflow, the Schedule Trigger changes first, under the version compare
        (ENGINE-PLAN 2.5). Nothing is saved here when n8n does not take it, or when the change
        was made from a version that is no longer in use."""
        async with self._db.transaction("builder") as uow:
            record = await self._hold(uow)
            if record is None:
                return NoWatchlist()
            if record.version != expected:
                return ChangedSince()
            if record.n8n is not None:
                refused = await self._schedule_in_n8n(uow, record, record.n8n, principal, schedule)
                if refused is not None:
                    return refused
        if schedule is None:
            await self._schedules.delete(record.use_case_id)
        else:
            await self._schedules.save(record.use_case_id, schedule, principal)
        return await self._view_of(await self._record() or record)

    async def _schedule_in_n8n(
        self,
        uow: UnitOfWork,
        record: WatchlistRecord,
        n8n: InN8n,
        principal: Principal,
        schedule: Schedule | None,
    ) -> ScheduleRefused | None:
        if self._n8n is None:
            return N8nNotReady("This platform is not connected to n8n.")
        if self._n8n.holding is not None:
            held = await self._n8n.holding.refused_while_held(
                uow.conn, record.use_case_id, principal.user_id
            )
            if held is not None:
                return held
        laid = await self._laid_out(self._n8n, record.use_case_id, schedule)
        if not isinstance(laid, Laid):
            return laid
        if laid.document == n8n.document:
            return None
        in_use = n8n.version_id
        if in_use is None:
            return N8nNotReady("This version is not saved in n8n, so it cannot be changed there.")
        live = is_on(record.lifecycle)
        written = await write_in_n8n(
            self._n8n.drafts, n8n.workflow_id, n8n.draft or in_use, in_use, laid.document, live
        )
        if not isinstance(written, Written):
            return written
        moved = await self._next_version(uow, record, record.software)
        publisher = principal.user_id if live else None
        await _keep_in_n8n(
            uow, record.use_case_id, moved.version, written, laid.graded.grade, publisher
        )
        return None

    async def move_to_n8n(self) -> Move:
        """Puts the watchlist on its own n8n workflow, with its schedule in the Schedule Trigger,
        in a new version (ENGINE-PLAN 2.6). Asking again changes nothing. A watchlist with a run
        that has not ended stays as it is, so nothing that run waits for is lost; it moves the next
        time it is asked.

        The records name the new workflow before it can run, so a move cut off at any point leaves
        nothing in n8n that the next move does not find and remove."""
        if self._n8n is None:
            return N8nNotReady("This platform is not connected to n8n.")
        on = self._n8n
        async with self._db.transaction("builder") as uow:
            record = await self._hold(uow)
            if record is None:
                return NoWatchlist()
            if record.n8n is not None:
                return AlreadyOnN8n()
            if (open_run := await on.runs.open_run(record.use_case_id)) is not None:
                log.info("the watchlist moves to n8n once run %s ends", open_run)
                return WaitsForRun(open_run)
            if record.left_in_n8n is not None:
                await discard(on.drafts, record.left_in_n8n)
            saved = await self._schedules.get(record.use_case_id)
            schedule = None if saved is None else saved.schedule
            laid = await self._laid_out(on, record.use_case_id, schedule)
            if not isinstance(laid, Laid):
                return laid
            try:
                draft = await on.drafts.save_draft(laid.document)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not take the watchlist's workflow: %s", error)
                return N8nNotReady("n8n did not take the watchlist's workflow. It runs as before.")
            await _name_in_n8n(uow, record.use_case_id, draft.workflow_id)
        async with self._db.transaction("builder") as uow:
            record = await self._hold(uow)
            if record is None or record.left_in_n8n != draft.workflow_id:
                return AlreadyOnN8n()
            live = is_on(record.lifecycle)
            try:
                if live:
                    await on.drafts.go_live(draft.workflow_id, draft.version_id)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not put the watchlist's workflow live: %s", error)
                await discard(on.drafts, draft.workflow_id)
                await _name_in_n8n(uow, record.use_case_id, None)
                return N8nNotReady(
                    "n8n did not turn the watchlist's workflow on. It runs as before."
                )
            moved = await self._next_version(uow, record, record.software)
            publisher = (record.owner if saved is None else saved.owner) if live else None
            held = Written(draft.version_id, draft.document)
            await _keep_in_n8n(
                uow, record.use_case_id, moved.version, held, laid.graded.grade, publisher
            )
            await uow.conn.execute(
                "UPDATE builder.use_cases SET engine = 'own' WHERE use_case_id = %s",
                (record.use_case_id,),
            )
        log.info(
            "the watchlist runs as n8n workflow %s from version %d",
            draft.workflow_id,
            moved.version,
        )
        return MovedToN8n(draft.workflow_id, moved.version)

    async def _hold(self, uow: UnitOfWork) -> WatchlistRecord | None:
        """The watchlist, locked in the order a list change and a pause take their locks, so a
        move or a schedule change never crosses either."""
        await uow.conn.execute("SELECT pg_advisory_xact_lock(hashtext('builder.watchlist'))")
        found = await _current(uow.conn, lock=False)
        if found is None:
            return None
        await hold_workflow(uow.conn, found.use_case_id, alone=True)
        return await _current(uow.conn, lock=True)

    async def _laid_out(
        self, on: OnN8n, use_case_id: UseCaseId, schedule: Schedule | None
    ) -> Laid | DraftRefused | N8nNotReady:
        error_workflow = await on.drafts.error_workflow_id()
        if error_workflow is None:
            return N8nNotReady("n8n is not ready yet: its error workflow is not loaded.")
        plan = layout.LayoutPlan(
            use_case_id, WATCHLIST_NAME, on.software_page, schedule, (), error_workflow, self._zone
        )
        checked = check_draft(layout.watchlist(plan), use_case_id, error_workflow, self._zone)
        if isinstance(checked, DraftRefused):
            log.error("the safety checker refused the watchlist's layout: %s", checked)
        return checked

    async def _record(self) -> WatchlistRecord | None:
        async with self._db.connection("builder") as conn:
            return await _current(conn, lock=False)

    async def remove(
        self, principal: Principal, software_id: SoftwareId
    ) -> WatchlistView | NoSuchSoftware:
        async with self._db.transaction("builder") as uow:
            record = await _current(uow.conn, lock=True)
            listed = None if record is None else _listed_in(record, software_id)
            if record is None or listed is None:
                return NoSuchSoftware(software_id)
            kept = tuple(s for s in record.software if s.id != software_id)
            record = await self._next_version(uow, record, kept)
        log.info(
            "%s removed %s (%s) from the watchlist, version %d",
            principal.user_id,
            software_id,
            listed.source.ref,
            record.version,
        )
        return await self._view_of(record)

    async def restore(
        self, principal: Principal, software_id: SoftwareId
    ) -> WatchlistView | NoSuchSoftware | TooLate | RepoAddedAgainSinceRemoval | WatchlistFull:
        async with self._db.transaction("builder") as uow:
            record = await _current(uow.conn, lock=True)
            if record is None:
                return NoSuchSoftware(software_id)
            if all(s.id != software_id for s in record.software):
                removal = await _last_removal(uow.conn, record.use_case_id, software_id)
                if removal is None:
                    return NoSuchSoftware(software_id)
                until = removal.at + RESTORE_WINDOW
                if uow.now > until:
                    return TooLate(until)
                removed = removal.listed
                if any(same_source(s.source, removed.source) for s in record.software):
                    return RepoAddedAgainSinceRemoval(removed.source.ref)
                if len(record.software) >= WATCHLIST_LIMIT:
                    return WatchlistFull(WATCHLIST_LIMIT)
                record = await self._next_version(uow, record, (*record.software, removed))
                log.info(
                    "%s put %s (%s) back on the watchlist, version %d",
                    principal.user_id,
                    software_id,
                    removed.source.ref,
                    record.version,
                )
        return await self._view_of(record)

    async def use_new_address(
        self, principal: Principal, software_id: SoftwareId, repo: str
    ) -> WatchlistView | NoSuchSoftware | NoMoveReported | RepoAlreadyWatched:
        """Replaces the saved repository of one software with the one GitHub reported at the
        latest check, in a new version of the list. Only our own watchlist changes: nothing is
        written to GitHub or Jira. The caller names the address it saw, so a report that has
        changed since is refused instead of applied."""
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute("SELECT pg_advisory_xact_lock(hashtext('builder.watchlist'))")
            record = await _current(uow.conn, lock=True)
            listed = None if record is None else _listed_in(record, software_id)
            if record is None or listed is None:
                return NoSuchSoftware(software_id)
            if listed.source.ref.casefold() == repo.casefold():
                return await self._view_of(record)
            standing = await self._facts.standings(record.use_case_id, given_versions(record))
            reported = moved_to(listed, standing.software[software_id].facts.latest_check)
            if reported is None or reported.casefold() != repo.casefold():
                return NoMoveReported(software_id)
            if _watched_elsewhere(record, software_id, reported):
                return RepoAlreadyWatched(reported)
            record = await self._next_version(
                uow, record, _with_ref(record, software_id, SoftwareSource(reported))
            )
            await _record_address_change(
                uow,
                record.use_case_id,
                software_id,
                "use",
                listed.source.ref,
                reported,
                principal.user_id,
            )
        log.info(
            "%s switched %s from %s to %s, version %d",
            principal.user_id,
            software_id,
            listed.source.ref,
            reported,
            record.version,
        )
        return await self._view_of(record)

    async def put_address_back(
        self, principal: Principal, software_id: SoftwareId, repo: str
    ) -> WatchlistView | NoSuchSoftware | NeverAtThatAddress | TooLate | RepoAlreadyWatched:
        """Undo of use_new_address: the software goes back to an address it had before, within a
        day of the switch, as a restore does. Asking for the address it has changes nothing."""
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute("SELECT pg_advisory_xact_lock(hashtext('builder.watchlist'))")
            record = await _current(uow.conn, lock=True)
            listed = None if record is None else _listed_in(record, software_id)
            if record is None or listed is None:
                return NoSuchSoftware(software_id)
            if listed.source.ref.casefold() == repo.casefold():
                return await self._view_of(record)
            switch = await _last_switch(uow.conn, record.use_case_id, software_id)
            old = None
            if switch is not None:
                old = next((b for b in switch.before if b.casefold() == repo.casefold()), None)
            if switch is None or old is None:
                return NeverAtThatAddress(repo)
            until = switch.at + RESTORE_WINDOW
            if uow.now > until:
                return TooLate(until)
            if _watched_elsewhere(record, software_id, old):
                return RepoAlreadyWatched(old)
            record = await self._next_version(
                uow, record, _with_ref(record, software_id, SoftwareSource(old))
            )
            await _record_address_change(
                uow,
                record.use_case_id,
                software_id,
                "undo",
                listed.source.ref,
                old,
                principal.user_id,
            )
        log.info(
            "%s put %s back from %s to %s, version %d",
            principal.user_id,
            software_id,
            listed.source.ref,
            old,
            record.version,
        )
        return await self._view_of(record)

    async def task_for(self, use_case_id: UseCaseId, version: int) -> WatchlistTask | None:
        """The agents' task for a check of this version, or None when nothing is watched."""
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT u.owner, u.paused_at, u.paused_by, u.deleted_at, u.deleted_by, "
                    "u.draft, v.params FROM builder.use_cases u "
                    "JOIN builder.use_case_versions v ON v.use_case_id = u.use_case_id "
                    "WHERE u.use_case_id = %s AND v.version = %s",
                    (use_case_id, version),
                )
            ).fetchone()
            if row is None:
                return None
            software = await _software_of(conn, use_case_id, version)
        if not software:
            return None
        record = WatchlistRecord(
            use_case_id,
            version,
            UserId(row["owner"]),
            str(row["params"]["ticket_project"]),
            software,
            lifecycle_of(row),
        )
        return task(record, await self._facts.standings(use_case_id, given_versions(record)))

    async def _view_of(self, record: WatchlistRecord) -> WatchlistView:
        standing = await self._facts.standings(record.use_case_id, given_versions(record))
        saved = await self._schedules.get(record.use_case_id)
        on = is_on(record.lifecycle)
        async with self._db.connection("builder") as conn:
            changes = await _address_changes(conn, record.use_case_id)
        now = self._db.clock()
        return view(
            record,
            standing,
            schedule_view(saved, now, on, self._zone, record.n8n),
            changes,
            moving=await self._moving(record),
        )

    async def _moving(self, record: WatchlistRecord) -> bool:
        """Still on the shared run workflow only because a run has not ended."""
        if self._n8n is None or record.n8n is not None:
            return False
        return await self._n8n.runs.open_run(record.use_case_id) is not None

    async def _create(
        self, uow: UnitOfWork, principal: Principal, first: ListedSoftware
    ) -> WatchlistRecord:
        use_case_id = UseCaseId(new_id("uc"))
        await uow.conn.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version) "
            "VALUES (%s, %s, %s, 1)",
            (use_case_id, principal.user_id, uow.now),
        )
        await uow.conn.execute(
            "INSERT INTO builder.use_case_versions (use_case_id, version, template, name, "
            "instruction, params, created_at) VALUES (%s, 1, %s, %s, %s, %s, %s)",
            (
                use_case_id,
                SOFTWARE_WATCHLIST.key,
                WATCHLIST_NAME,
                WATCHLIST_INSTRUCTION,
                json({"ticket_project": self._project}),
                uow.now,
            ),
        )
        await _write_list(uow, use_case_id, 1, (first,))
        return WatchlistRecord(use_case_id, 1, principal.user_id, self._project, (first,), On())

    async def _next_version(
        self,
        uow: UnitOfWork,
        record: WatchlistRecord,
        software: tuple[ListedSoftware, ...],
        ticket_project: str | None = None,
    ) -> WatchlistRecord:
        """The list belongs to the use case version, so a change is a new version that every
        later check records as the version it used. The project moves only when one is given."""
        version = record.version + 1
        project = record.ticket_project if ticket_project is None else ticket_project
        await uow.conn.execute(
            "INSERT INTO builder.use_case_versions (use_case_id, version, template, name, "
            "instruction, params, created_at, n8n_version_id, document, grade, published_by, "
            "published_in, also, findings) "
            "SELECT use_case_id, %s, template, name, instruction, "
            "jsonb_set(params, '{ticket_project}', to_jsonb(%s::text)), %s, n8n_version_id, "
            "document, grade, published_by, published_in, also, findings "
            "FROM builder.use_case_versions WHERE use_case_id = %s AND version = %s",
            (version, project, uow.now, record.use_case_id, record.version),
        )
        await uow.conn.execute(
            "UPDATE builder.use_cases SET current_version = %s WHERE use_case_id = %s",
            (version, record.use_case_id),
        )
        await _write_list(uow, record.use_case_id, version, software)
        return replace(record, version=version, ticket_project=project, software=software)
