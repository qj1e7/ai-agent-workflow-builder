"""A workflow's versions. Changing when it runs publishes a new version, and Undo publishes the
version before again, so the list only grows. Version 1 is the one it was set up with. The
watchlist publishes its own versions when its software changes (watchlist.py), with no change
recorded here. For a workflow n8n carries, a version published in n8n's editor, a roll back and
the yes put back are versions too (ENGINE-PLAN 2.5), each with the workflow n8n holds for it."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from platform_api.builder.layout import CRON_DAYS
from platform_api.builder.models import (
    ScheduleChangeView,
    VersionChange,
    VersionMade,
    VersionSchedule,
    VersionView,
    Via,
)
from platform_api.db import Connection, UnitOfWork, json
from platform_api.orchestration import (
    Day,
    Grade,
    Schedule,
    Unreadable,
    read_flow,
    schedule_intervals,
    zone_name,
)
from platform_api.shared import UserId

type Where = Literal["portal", "n8n"]


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
class Made:
    """How a version that is not a schedule change came about. `by` and `via` are the Portal
    person and place, None for a version published in n8n."""

    kind: VersionMade
    by: UserId | None
    via: Via | None
    back_to: int | None = None


@dataclass(frozen=True)
class Publication:
    """Who put a version live, and from where (D5). `by` is None for a publish in n8n by
    someone the People list can't match."""

    by: UserId | None
    where: Where


@dataclass(frozen=True)
class Held:
    """The workflow n8n holds for a version, as the platform keeps it, and its grade."""

    version_id: str
    document: dict[str, Any]
    grade: Grade
    findings: tuple[str, ...] = ()
    """Why it is not safe, in the safety checker's words."""


@dataclass(frozen=True)
class Version:
    number: int
    at: datetime
    change: ScheduleChange | None
    """None for the version it was set up with, and for a version the watchlist published."""
    made: Made | None = None
    held: Held | None = None
    """None for a workflow on the shared n8n workflow."""
    published: Publication | None = None
    """None for a version nobody has put live."""
    also: tuple[Publication, ...] = ()
    """Every earlier author of the workflow it puts back in use (ADR 0026)."""


def authors_of(version: Version) -> tuple[Publication, ...]:
    """Whose work a version's workflow is: its earlier authors, then its publisher. A version
    that puts it back in use keeps them all, so none of them can approve its runs."""
    found = (*version.also, *(() if version.published is None else (version.published,)))
    return tuple(dict.fromkeys(found))


def authors_json(authors: Sequence[Publication]) -> object:
    return json([{"by": a.by, "in": a.where} for a in authors])


def authors_from(value: object) -> tuple[Publication, ...]:
    rows = cast(list[dict[str, Any]], value) if isinstance(value, list) else []
    return tuple(
        Publication(None if row.get("by") is None else UserId(row["by"]), row["in"]) for row in rows
    )


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
    """A later version exists than the one the change was made from, so making it would throw
    that version away."""


@dataclass(frozen=True)
class InUseChanged:
    """Another version is in use than the one the person saw, so nothing changed."""


@dataclass(frozen=True)
class NotSafeToPublish:
    """The version would not pass the safety check now, so it is not put in use."""

    findings: tuple[str, ...]


@dataclass(frozen=True)
class DeletedInN8n:
    """n8n no longer has the workflow, so nothing can change there."""


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


def version_view(version: Version, running: int, before: Version | None = None) -> VersionView:
    """`before` is the version before it, whose workflow a version published in n8n is compared
    with."""
    change, made, held, published = version.change, version.made, version.held, version.published
    published_there = made is not None and made.kind == "published_in_n8n"
    in_n8n = made is not None and made.kind in ("published_in_n8n", "settings_changed_in_n8n")
    by = change.by if change is not None else made.by if made is not None else None
    if published_there and published is not None:
        by = published.by
    changes: list[str] = []
    if in_n8n and held is not None:
        changes = changes_between(None if before is None else _document(before), held.document)
    return VersionView(
        version=version.number,
        at=version.at,
        by=by,
        via=change.via if change is not None else None if made is None else made.via,
        change=None
        if change is None
        else VersionChange(
            schedule=ScheduleChangeView(
                before=_schedule_view(change.before), after=_schedule_view(change.after)
            )
        ),
        undid=None if change is None else change.undid,
        running=version.number == running,
        made=None if made is None else made.kind,
        grade=None if held is None else held.grade,
        changes=changes,
        rolled_back_to=None if made is None else made.back_to,
        publisher_unknown=published_there and published is not None and published.by is None,
    )


def _document(version: Version) -> dict[str, Any] | None:
    return None if version.held is None else version.held.document


SCHEDULE_TYPE = "n8n-nodes-base.scheduleTrigger"
DAY_WORDS: Mapping[str, str] = {
    "every_day": "every day",
    "weekdays": "every weekday",
    "monday": "every Monday",
    "tuesday": "every Tuesday",
    "wednesday": "every Wednesday",
    "thursday": "every Thursday",
    "friday": "every Friday",
    "saturday": "every Saturday",
    "sunday": "every Sunday",
}
_DAY_OF_CRON: Mapping[tuple[object, ...], Day] = {
    tuple(days): day for day, days in CRON_DAYS.items()
}


def schedule_of(document: Mapping[str, Any] | None, team_zone: str) -> Schedule | None:
    """When the workflow runs, read back from its one Schedule Trigger and the zone it runs on,
    for a rule the Planner could have laid out: every day, or on days of the week, at an hour and
    minute. None for no schedule, or for a rule the Portal's schedule can't hold."""
    when = _when(document)
    if when is None or document is None:
        return None
    return Schedule(*when, zone_name(_object(document.get("settings")), team_zone))


def _when(document: Mapping[str, Any] | None) -> tuple[Day, str] | None:
    """The day and time of day of its one Schedule Trigger."""
    triggers = [
        node
        for node in _objects(None if document is None else document.get("nodes"))
        if node.get("type") == SCHEDULE_TYPE and not node.get("disabled")
    ]
    if len(triggers) != 1:
        return None
    intervals = schedule_intervals(_object(triggers[0].get("parameters")))
    if len(intervals) != 1:
        return None
    interval = intervals[0]
    hour, minute = interval.get("triggerAtHour"), interval.get("triggerAtMinute")
    if not isinstance(hour, int) or not isinstance(minute, int):
        return None
    at = f"{hour:02d}:{minute:02d}"
    field = interval.get("field", "days")
    if field == "days" and interval.get("daysInterval", 1) == 1:
        return "every_day", at
    days = interval.get("triggerAtDay")
    if field == "weeks" and interval.get("weeksInterval", 1) == 1 and isinstance(days, list):
        day = _DAY_OF_CRON.get(tuple(cast(list[object], days)))
        return None if day is None else (day, at)
    return None


def _object(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _objects(value: object) -> list[dict[str, Any]]:
    items = cast(list[object], value) if isinstance(value, list) else []
    return [_object(item) for item in items if _object(item)]


def schedule_words(day: Day, at: str) -> str:
    """As "every day at 7:30"."""
    hour, minute = at.split(":")
    return f"{DAY_WORDS[day]} at {int(hour)}:{minute}"


SETTING_WORDS: Mapping[str, str] = {
    "errorWorkflow": "the error workflow",
    "timezone": "the time zone",
    "saveManualExecutions": "keeping its test runs",
    "saveExecutionProgress": "saving its progress",
    "callerPolicy": "who may call it",
    "executionTimeout": "its time limit",
    "executionOrder": "the order its blocks run in",
}


SETTING_FILLS: Mapping[str, Any] = {"binaryMode": "separate"}
"""Settings n8n's editor writes in on every save, at the value n8n runs a workflow without them.
It writes executionOrder "v1" too, but n8n runs a workflow without one in the old order."""

PARAMETER_FILLS: Mapping[str, Mapping[str, Any]] = {
    "CUSTOM.wabRead": {"source": "github_releases"},
    "n8n-nodes-base.if": {"conditions": {"options": {"leftValue": ""}}},
}
"""n8n's own value for a parameter a block leaves out, which n8n fills in before it runs. Its
editor leaves a parameter at that value out as it saves, or writes it in, so a block nobody
touched would read as changed. Only the blocks a layout writes otherwise than the editor saves
them, as docs/evidence/n8n-editor-save shows."""


def _settings(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Settings as n8n runs with them: a setting with no value is one left out."""
    given = {key: value for key, value in (settings or {}).items() if value is not None}
    return {**SETTING_FILLS, **given}


def _as_n8n_runs(document: Mapping[str, Any]) -> dict[str, Any]:
    """The workflow with n8n's own value wherever a block leaves one out, so two workflows n8n
    runs the same way compare equal however its editor saved them."""
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return dict(document)
    return {**document, "nodes": [_node_as_n8n_runs(node) for node in cast(list[object], nodes)]}


def _node_as_n8n_runs(node: object) -> object:
    given = _object(node)
    kind, parameters = given.get("type"), given.get("parameters")
    if not isinstance(kind, str) or not isinstance(parameters, dict):
        return node
    filled = _filled(PARAMETER_FILLS.get(kind, {}), cast(dict[str, Any], parameters))
    if kind == SCHEDULE_TYPE:
        filled["rule"] = {**_object(filled.get("rule")), "interval": schedule_intervals(filled)}
    return {**given, "parameters": filled}


def _filled(fills: Mapping[str, Any], given: Mapping[str, Any]) -> dict[str, Any]:
    filled = {**fills, **given}
    for key, fill in fills.items():
        value = given.get(key)
        if isinstance(fill, Mapping) and isinstance(value, Mapping):
            filled[key] = _filled(cast(Mapping[str, Any], fill), cast(Mapping[str, Any], value))
    return filled


def settings_changed(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> str | None:
    """Which settings differ, in plain words, the safety checker's first, or None when none do.
    The order n8n keeps them in is no change."""
    old, new = _settings(before), _settings(after)
    keys = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    if not keys:
        return None
    named = [key for key in SETTING_WORDS if key in keys]
    others = sorted(keys - set(SETTING_WORDS))
    return ", ".join([*(SETTING_WORDS[key] for key in named), *(f"“{key}”" for key in others)])


def changes_between(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> list[str]:
    """What a version published in n8n changed, in the Changed in n8n card's words: when it
    runs, each block deleted, added or changed by name, then how the blocks connect and its
    settings. A plain comparison of the two workflows as n8n runs them, never a guess at why."""
    after = _as_n8n_runs(after)
    before = None if before is None else _as_n8n_runs(before)
    try:
        new = read_flow(after)
        old = None if before is None else read_flow(before)
    except Unreadable:
        return ["Changed in a way our platform can't read."]
    if old is None:
        return ["Published in n8n."]
    lines: list[str] = []
    when_before, when_after = _when(before), _when(after)
    if when_before != when_after:
        lines.append(
            "No longer runs on a schedule."
            if when_after is None
            else f"Now runs {schedule_words(*when_after)}."
        )
    schedule_said = when_before != when_after and when_after is not None
    lines.extend(f"Deleted “{name}”." for name in old.blocks if name not in new.blocks)
    for name, block in new.blocks.items():
        was = old.blocks.get(name)
        if was is None:
            lines.append(f"Added “{name}”.")
            continue
        changed = (was.type, dict(was.parameters)) != (block.type, dict(block.parameters))
        said = schedule_said and block.type == SCHEDULE_TYPE == was.type
        if changed and not said:
            lines.append(f"Changed “{name}”.")
    if set(old.blocks) == set(new.blocks) and set(old.edges) != set(new.edges):
        lines.append("Changed how the blocks connect.")
    if (settings := settings_changed(old.settings, new.settings)) is not None:
        lines.append(f"Changed its settings: {settings}.")
    return lines or ["Published again, with no change to its blocks."]


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


def _made_of(row: Mapping[str, Any]) -> Made | None:
    if row["made"] is None:
        return None
    by = None if row["made_by"] is None else UserId(row["made_by"])
    return Made(row["made"], by, row["made_via"], row["back_to"])


async def versions_of(conn: Connection, use_case_id: str) -> list[Version]:
    """Newest first."""
    rows = await (
        await conn.execute(
            "SELECT v.version, v.created_at, c.changed_by, c.via, c.schedule_before,"
            " c.schedule_after, c.undid, v.made, v.made_by, v.made_via, v.back_to,"
            " v.n8n_version_id, v.document, v.grade, v.published_by, v.published_in, v.findings,"
            " v.also"
            " FROM builder.use_case_versions v"
            " LEFT JOIN builder.use_case_version_changes c"
            " ON c.use_case_id = v.use_case_id AND c.version = v.version"
            " WHERE v.use_case_id = %s ORDER BY v.version DESC",
            (use_case_id,),
        )
    ).fetchall()
    versions: list[Version] = []
    for row in rows:
        held = None
        if row["n8n_version_id"] is not None:
            findings = tuple(row["findings"] or ())
            held = Held(row["n8n_version_id"], row["document"], row["grade"], findings)
        published = None
        if row["published_in"] is not None:
            by = None if row["published_by"] is None else UserId(row["published_by"])
            published = Publication(by, row["published_in"])
        versions.append(
            Version(
                row["version"],
                row["created_at"],
                _version_of(row).change,
                _made_of(row),
                held,
                published,
                authors_from(row["also"]),
            )
        )
    return versions


async def add_version(
    uow: UnitOfWork,
    use_case_id: str,
    newest: int,
    source: int,
    held: Held,
    made: Made,
    published: Publication | None,
    also: Sequence[Publication],
    draft: str,
) -> int:
    """Writes the version after `newest`, the current one, as a copy of version `source`, its
    agents included, holding the workflow n8n holds now, and makes it the current one. `also` is
    every author of the workflow it puts back, who join its runs (ADR 0026). `draft` is n8n's
    draft after it. The caller holds the use case's row."""
    version = newest + 1
    await uow.conn.execute(
        "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
        " instruction, params, created_at, n8n_version_id, document, grade, published_by,"
        " published_in, made, made_by, made_via, back_to, also, findings)"
        " SELECT use_case_id, %s, template, name, instruction, params, %s, %s, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s, %s FROM builder.use_case_versions"
        " WHERE use_case_id = %s AND version = %s",
        (
            version,
            uow.now,
            held.version_id,
            json(held.document),
            held.grade,
            None if published is None else published.by,
            None if published is None else published.where,
            made.kind,
            made.by,
            made.via,
            made.back_to,
            authors_json(also),
            json(list(held.findings)),
            use_case_id,
            source,
        ),
    )
    await uow.conn.execute(
        "INSERT INTO builder.use_case_cards (use_case_id, version, position, card_id,"
        ' card_version, "values") SELECT use_case_id, %s, position, card_id, card_version,'
        ' "values" FROM builder.use_case_cards WHERE use_case_id = %s AND version = %s',
        (version, use_case_id, source),
    )
    await uow.conn.execute(
        "UPDATE builder.use_cases SET current_version = %s, n8n_draft_id = %s"
        " WHERE use_case_id = %s",
        (version, draft, use_case_id),
    )
    return version


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
