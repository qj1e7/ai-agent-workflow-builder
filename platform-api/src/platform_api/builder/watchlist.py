"""The team's software watchlist: one use case of the software_watchlist template.

The list of what is watched lives here, in the builder. What the platform has learned about
each software (our version, the newest release, tickets) comes from orchestration through
the WatchlistFacts port, and the two are composed into the view the Portal shows.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from platform_api.builder.lifecycle import (
    RESTORE_WINDOW,
    Lifecycle,
    On,
    TooLate,
    is_on,
    lifecycle_of,
)
from platform_api.builder.models import (
    AddSoftware,
    LastCheckView,
    ScheduleIn,
    ScheduleView,
    SourceView,
    VersionSourceView,
    WatchedSoftwareView,
    WatchlistView,
)
from platform_api.builder.templates import (
    SOFTWARE_WATCHLIST,
    WATCHLIST_INSTRUCTION,
    WATCHLIST_LIMIT,
    WATCHLIST_NAME,
    WATCHLIST_PARAMS,
)
from platform_api.db import Connection, Database, UnitOfWork, json
from platform_api.orchestration import (
    ATTENTION_ORDER,
    Checked,
    CouldNotCheck,
    FromFirstCheck,
    FromTicketDone,
    Given,
    LastCheck,
    SavedSchedule,
    Schedule,
    ScheduleBook,
    SoftwareSource,
    Standing,
    WatchedSoftware,
    WatchlistFacts,
    WatchlistStanding,
    WatchlistTask,
)
from platform_api.shared import Principal, SoftwareId, UseCaseId, UserId, new_id


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
class WatchlistRecord:
    use_case_id: UseCaseId
    version: int
    owner: UserId
    ticket_project: str
    software: tuple[ListedSoftware, ...]
    lifecycle: Lifecycle


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


def source_view(source: SoftwareSource) -> SourceView:
    return SourceView(
        kind=source.kind, ref=source.ref, url=f"https://github.com/{source.ref}/releases"
    )


def software_view(listed: ListedSoftware, standing: Standing) -> WatchedSoftwareView:
    facts = standing.facts
    match facts.our_version:
        case None:
            our_source = None
        case Given(_, at):
            our_source = VersionSourceView(kind="given", at=at, ticket=None)
        case FromFirstCheck(_, at):
            our_source = VersionSourceView(kind="first_check", at=at, ticket=None)
        case FromTicketDone(_, at, ticket):
            our_source = VersionSourceView(kind="ticket_done", at=at, ticket=ticket)
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
        our_version=None if facts.our_version is None else facts.our_version.version,
        our_version_source=our_source,
        newest_version=newest,
        newest_read_at=read_at,
        checked_at=checked_at,
        status=standing.status,
        problem=problem,
        open_ticket=None if facts.open_ticket is None else facts.open_ticket.key,
        approval_id=None if facts.pending is None else facts.pending.approval_id,
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


def schedule_view(saved: SavedSchedule | None, now: datetime, on: bool) -> ScheduleView | None:
    if saved is None:
        return None
    return ScheduleView(
        day=saved.schedule.day,
        at=saved.schedule.at,
        time_zone=saved.schedule.time_zone,
        owner=saved.owner,
        owner_name=saved.owner_name,
        saved_at=saved.saved_at,
        next_at=saved.slots(now).next if on else None,
    )


def view(
    record: WatchlistRecord, standing: WatchlistStanding, schedule: ScheduleView | None = None
) -> WatchlistView:
    return WatchlistView(
        use_case_id=record.use_case_id,
        version=record.version,
        ticket_project=record.ticket_project,
        state="on" if is_on(record.lifecycle) else "paused",
        software=attention_first(
            [software_view(listed, standing.software[listed.id]) for listed in record.software]
        ),
        last_check=last_check_view(standing.last_check),
        schedule=schedule,
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
            )
        )
    return WatchlistTask(tag_pattern=SOFTWARE_WATCHLIST.tag_pattern, software=tuple(software))


def given_versions(record: WatchlistRecord) -> Mapping[SoftwareId, Given | None]:
    return {listed.id: listed.given for listed in record.software}


_CURRENT = """
    SELECT u.use_case_id, u.owner, u.paused_at, u.paused_by, u.deleted_at, u.deleted_by,
           v.version, v.params
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
        SoftwareSource(row["source_ref"]),
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


async def _current(conn: Connection, lock: bool) -> WatchlistRecord | None:
    suffix = " ORDER BY u.created_at LIMIT 1" + (" FOR UPDATE OF u" if lock else "")
    row = await (await conn.execute(_CURRENT + suffix, (SOFTWARE_WATCHLIST.key,))).fetchone()
    if row is None:
        return None
    use_case_id = UseCaseId(row["use_case_id"])
    return WatchlistRecord(
        use_case_id,
        int(row["version"]),
        UserId(row["owner"]),
        str(row["params"]["ticket_project"]),
        await _software_of(conn, use_case_id, int(row["version"])),
        lifecycle_of(row),
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
    def __init__(self, db: Database, facts: WatchlistFacts, schedules: ScheduleBook) -> None:
        self._db = db
        self._facts = facts
        self._schedules = schedules

    async def view(self) -> WatchlistView | None:
        async with self._db.connection("builder") as conn:
            record = await _current(conn, lock=False)
        return None if record is None else await self._view_of(record)

    async def add(
        self, principal: Principal, body: AddSoftware
    ) -> WatchlistView | RepoAlreadyWatched | WatchlistFull:
        async with self._db.transaction("builder") as uow:
            # One watchlist per team: the first two Operators to add software at once must not
            # each make one, so adding takes a lock that exists before the row does.
            await uow.conn.execute("SELECT pg_advisory_xact_lock(hashtext('builder.watchlist'))")
            record = await _current(uow.conn, lock=True)
            if record is not None:
                if any(s.source.ref.casefold() == body.repo.casefold() for s in record.software):
                    return RepoAlreadyWatched(body.repo)
                if len(record.software) >= WATCHLIST_LIMIT:
                    return WatchlistFull(WATCHLIST_LIMIT)
            listed = ListedSoftware(
                SoftwareId(new_id("sw")),
                body.name,
                SoftwareSource(body.repo),
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
            await self._schedules.save_default(record.use_case_id, principal)
        return await self._view_of(record)

    async def save_schedule(
        self, principal: Principal, body: ScheduleIn
    ) -> WatchlistView | NoWatchlist:
        """Saving makes the caller the schedule owner, and the owner cannot approve its checks."""
        async with self._db.connection("builder") as conn:
            record = await _current(conn, lock=False)
        if record is None:
            return NoWatchlist()
        await self._schedules.save(record.use_case_id, Schedule(body.day, body.at), principal)
        return await self._view_of(record)

    async def turn_off_schedule(self) -> WatchlistView | NoWatchlist:
        async with self._db.connection("builder") as conn:
            record = await _current(conn, lock=False)
        if record is None:
            return NoWatchlist()
        await self._schedules.delete(record.use_case_id)
        return await self._view_of(record)

    async def remove(self, software_id: SoftwareId) -> WatchlistView | NoSuchSoftware:
        async with self._db.transaction("builder") as uow:
            record = await _current(uow.conn, lock=True)
            if record is None or all(s.id != software_id for s in record.software):
                return NoSuchSoftware(software_id)
            kept = tuple(s for s in record.software if s.id != software_id)
            record = await self._next_version(uow, record, kept)
        return await self._view_of(record)

    async def restore(
        self, software_id: SoftwareId
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
                ref = removed.source.ref.casefold()
                if any(s.source.ref.casefold() == ref for s in record.software):
                    return RepoAddedAgainSinceRemoval(removed.source.ref)
                if len(record.software) >= WATCHLIST_LIMIT:
                    return WatchlistFull(WATCHLIST_LIMIT)
                record = await self._next_version(uow, record, (*record.software, removed))
        return await self._view_of(record)

    async def task_for(self, use_case_id: UseCaseId, version: int) -> WatchlistTask | None:
        """The agents' task for a check of this version, or None when nothing is watched."""
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT u.owner, u.paused_at, u.paused_by, u.deleted_at, u.deleted_by, "
                    "v.params FROM builder.use_cases u "
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
        return view(record, standing, schedule_view(saved, self._db.clock(), on))

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
                json(dict(WATCHLIST_PARAMS)),
                uow.now,
            ),
        )
        await _write_list(uow, use_case_id, 1, (first,))
        return WatchlistRecord(
            use_case_id, 1, principal.user_id, WATCHLIST_PARAMS["ticket_project"], (first,), On()
        )

    async def _next_version(
        self, uow: UnitOfWork, record: WatchlistRecord, software: tuple[ListedSoftware, ...]
    ) -> WatchlistRecord:
        """The list belongs to the use case version, so a change is a new version that every
        later check records as the version it used."""
        version = record.version + 1
        await uow.conn.execute(
            "INSERT INTO builder.use_case_versions (use_case_id, version, template, name, "
            "instruction, params, created_at) "
            "SELECT use_case_id, %s, template, name, instruction, params, %s "
            "FROM builder.use_case_versions WHERE use_case_id = %s AND version = %s",
            (version, uow.now, record.use_case_id, record.version),
        )
        await uow.conn.execute(
            "UPDATE builder.use_cases SET current_version = %s WHERE use_case_id = %s",
            (version, record.use_case_id),
        )
        await _write_list(uow, record.use_case_id, version, software)
        return WatchlistRecord(
            record.use_case_id,
            version,
            record.owner,
            record.ticket_project,
            software,
            record.lifecycle,
        )
