"""A workflow's versions. Changing when it runs publishes a new version, and Undo publishes the
version before again, so the list only grows. Version 1 is the one it was set up with. The
watchlist publishes its own versions when its software changes (watchlist.py), with no change
recorded here."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from platform_api.builder.models import (
    ScheduleChangeView,
    VersionChange,
    VersionSchedule,
    VersionView,
    Via,
)
from platform_api.db import Connection, UnitOfWork, json
from platform_api.orchestration import Schedule
from platform_api.shared import UserId


@dataclass(frozen=True)
class ScheduleChange:
    """A change of when the workflow runs. None is no schedule: a workflow set up without one,
    or an Undo back to that."""

    by: UserId
    via: Via
    before: Schedule | None
    after: Schedule | None
    undid: int | None = None


@dataclass(frozen=True)
class Version:
    number: int
    at: datetime
    change: ScheduleChange | None
    """None for the version it was set up with, and for a version the watchlist published."""


@dataclass(frozen=True)
class Publish:
    """Publish a new version that runs on this schedule."""

    after: Schedule | None
    undid: int | None = None


@dataclass(frozen=True)
class AlreadyUndone:
    """The newest version is the Undo of the one asked, so asking again changes nothing."""


@dataclass(frozen=True)
class NoSuchVersion:
    pass


@dataclass(frozen=True)
class NotAScheduleChange:
    pass


@dataclass(frozen=True)
class ChangedSince:
    """A later version exists, and Undo would throw it away."""


type Undo = Publish | AlreadyUndone | NoSuchVersion | NotAScheduleChange | ChangedSince


def undo(versions: Sequence[Version], asked: int) -> Undo:
    """What Undo of version `asked` does, given the versions newest first. Only the newest
    version is undone, so Undo never throws away someone else's later change."""
    target = next((version for version in versions if version.number == asked), None)
    if target is None:
        return NoSuchVersion()
    if target.change is None:
        return NotAScheduleChange()
    newest = versions[0]
    if newest.number == asked:
        return Publish(target.change.before, undid=asked)
    if newest.change is not None and newest.change.undid == asked:
        return AlreadyUndone()
    return ChangedSince()


def _schedule_view(schedule: Schedule | None) -> VersionSchedule | None:
    if schedule is None:
        return None
    return VersionSchedule(day=schedule.day, at=schedule.at, time_zone=schedule.time_zone)


def version_view(version: Version, running: int) -> VersionView:
    change = version.change
    return VersionView(
        version=version.number,
        at=version.at,
        by=None if change is None else change.by,
        via=None if change is None else change.via,
        change=None
        if change is None
        else VersionChange(
            schedule=ScheduleChangeView(
                before=_schedule_view(change.before), after=_schedule_view(change.after)
            )
        ),
        undid=None if change is None else change.undid,
        running=version.number == running,
    )


def _schedule_json(schedule: Schedule | None) -> object:
    if schedule is None:
        return None
    return json({"day": schedule.day, "at": schedule.at, "time_zone": schedule.time_zone})


def _schedule_of(value: Mapping[str, Any] | None) -> Schedule | None:
    if value is None:
        return None
    return Schedule(value["day"], value["at"], value["time_zone"])


def _version_of(row: Mapping[str, Any]) -> Version:
    change = (
        None
        if row["changed_by"] is None
        else ScheduleChange(
            UserId(row["changed_by"]),
            row["via"],
            _schedule_of(row["schedule_before"]),
            _schedule_of(row["schedule_after"]),
            row["undid"],
        )
    )
    return Version(row["version"], row["created_at"], change)


async def versions_of(conn: Connection, use_case_id: str) -> list[Version]:
    """Newest first."""
    rows = await (
        await conn.execute(
            "SELECT v.version, v.created_at, c.changed_by, c.via, c.schedule_before,"
            " c.schedule_after, c.undid FROM builder.use_case_versions v"
            " LEFT JOIN builder.use_case_version_changes c"
            " ON c.use_case_id = v.use_case_id AND c.version = v.version"
            " WHERE v.use_case_id = %s ORDER BY v.version DESC",
            (use_case_id,),
        )
    ).fetchall()
    return [_version_of(row) for row in rows]


async def publish(uow: UnitOfWork, use_case_id: str, newest: int, change: ScheduleChange) -> None:
    """Writes the version after `newest` as a copy of it, agents included, with the change, and
    makes it the current one. The caller holds the use case's row."""
    version = newest + 1
    await uow.conn.execute(
        "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
        " instruction, params, created_at) SELECT use_case_id, %s, template, name, instruction,"
        " params, %s FROM builder.use_case_versions WHERE use_case_id = %s AND version = %s",
        (version, uow.now, use_case_id, newest),
    )
    await uow.conn.execute(
        "INSERT INTO builder.use_case_cards (use_case_id, version, position, card_id,"
        ' card_version, "values") SELECT use_case_id, %s, position, card_id, card_version,'
        ' "values" FROM builder.use_case_cards WHERE use_case_id = %s AND version = %s',
        (version, use_case_id, newest),
    )
    await uow.conn.execute(
        "INSERT INTO builder.use_case_version_changes (use_case_id, version, changed_by, via,"
        " schedule_before, schedule_after, undid) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            use_case_id,
            version,
            change.by,
            change.via,
            _schedule_json(change.before),
            _schedule_json(change.after),
            change.undid,
        ),
    )
    await uow.conn.execute(
        "UPDATE builder.use_cases SET current_version = %s WHERE use_case_id = %s",
        (version, use_case_id),
    )
