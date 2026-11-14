"""When n8n's Schedule Trigger fires, so the Portal can show a workflow's next run to the minute
(ENGINE-PLAN 2.4, P7 Q12).

n8n 2.42.6 turns each rule into a cron expression (`withIntervalDefaults` and `toCronExpression`
in the Schedule node's GenericFunctions.ts) and fires it with the `cron` 4.4.0 library. Some rules
also pass a filter that keeps state inside n8n (`recurrenceCheck`). Their next run cannot be
worked out from the document, so the Portal refuses them, except where the cron already spaces
the runs as the filter would. docs/evidence/prototypes/p7-n8n-engine-facts/cron_table.json holds
n8n's own answers.

Pure.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, JsonValue, ValidationError

from platform_api.orchestration.schedule import TIME_ZONE

SCHEDULE_TRIGGER = "n8n-nodes-base.scheduleTrigger"
CRON = "cronExpression"
DEFAULT_ZONE = "DEFAULT"
"""What n8n stores when a workflow uses the instance's time zone, which is Singapore's."""
UNREADABLE = "has a time the Portal cannot read."
SEARCH = timedelta(days=5 * 366)
BOUNDS = ((0, 59), (0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
"""Second, minute, hour, day of month, month and day of week, as the `cron` library bounds them.
Day of week 7 is Sunday, as 0 is."""
LONGEST_MONTHS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
PART = re.compile(r"([0-9]+)(?:-([0-9]+))?(?:/([0-9]+))?")


@dataclass(frozen=True)
class Rule:
    """One kind of rule: n8n's interval when it is left out, the intervals whose runs the cron
    alone spaces, and the parts of the time n8n picks itself when they are left out."""

    every_default: int
    shown_every: frozenset[int]
    misfit: str
    picked_parts: tuple[str, ...] = ()
    picked: str = ""


RULES: Mapping[str, Rule] = {
    "seconds": Rule(30, frozenset(), "runs every few seconds, which is too often."),
    "minutes": Rule(
        5,
        frozenset({1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30}),
        "runs every few minutes in a way that does not fit an hour.",
    ),
    "hours": Rule(
        1,
        frozenset({1, 2, 3, 4, 6, 8, 12}),
        "runs every few hours in a way that does not fit a day.",
        ("triggerAtMinute",),
        "leaves its minute for n8n to pick.",
    ),
    "days": Rule(
        1,
        frozenset({1}),
        "skips days, which n8n counts in a way the Portal cannot show.",
        ("triggerAtHour", "triggerAtMinute"),
        "leaves its hour or minute for n8n to pick.",
    ),
    "weeks": Rule(
        1,
        frozenset({1}),
        "skips weeks, which n8n counts in a way the Portal cannot show.",
        ("triggerAtHour", "triggerAtMinute"),
        "leaves its hour or minute for n8n to pick.",
    ),
    "months": Rule(
        1,
        frozenset({1, 2, 3, 4, 6, 12}),
        "runs every few months in a way that does not fit a year.",
        ("triggerAtDayOfMonth", "triggerAtHour", "triggerAtMinute"),
        "leaves its day, hour or minute for n8n to pick.",
    ),
}
"""Keyed by the rule's `field`. An interval outside `shown_every` runs every few seconds, fails
n8n's own check, or runs through `recurrenceCheck`, which skips runs by state the Portal cannot
see."""


def interval_problem(interval: Mapping[str, JsonValue]) -> str | None:
    """Why the Portal could not show or keep this rule, as the end of a sentence that starts with
    the block's quoted name. None when the Portal can show its next run."""
    field = _field(interval)
    rule = RULES.get(field)
    if rule is not None:
        if any(interval.get(part) is None for part in rule.picked_parts):
            return rule.picked
        if _whole(interval.get(f"{field}Interval"), rule.every_default) not in rule.shown_every:
            return rule.misfit
    try:
        # Any key will do: it only picks the second and the parts the checks above refuse to
        # leave out.
        _parse(cron_expression(interval, ""))
    except ValueError:
        return UNREADABLE
    return None


def cron_expression(interval: Mapping[str, JsonValue], node_key: str) -> str:
    """n8n's cron expression for one entry of a Schedule Trigger's `rule.interval`, exact for
    values of the types n8n's editor writes. `node_key` is "{workflowId}:{nodeId}". n8n hashes it
    to pick the second, and any minute, hour or day left out, the same every time."""
    field = _field(interval)
    if field == CRON:
        expression = interval.get("expression")
        return "" if expression is None else str(expression)
    every = _given(interval, f"{field}Interval", RULES[field].every_default)
    if field == "seconds":
        return f"*/{every} * * * * *"
    second = _stable_int(node_key, "second", 0, 60)
    if field == "minutes":
        return f"{second} */{every} * * * *" if _divides(60, every) else f"{second} * * * * *"
    minute = _given(interval, "triggerAtMinute", _stable_int(node_key, "minute", 0, 60))
    if field == "hours":
        hours = f"*/{every}" if _divides(24, every) else "*"
        return f"{second} {minute} {hours} * * *"
    hour = _given(interval, "triggerAtHour", _stable_int(node_key, "hour", 0, 24))
    if field == "days":
        return f"{second} {minute} {hour} * * *"
    if field == "weeks":
        return f"{second} {minute} {hour} * * {_weekdays(interval.get('triggerAtDay'))}"
    day = _given(interval, "triggerAtDayOfMonth", _stable_int(node_key, "dayOfMonth", 1, 29))
    months = f"*/{every}" if _divides(12, every) else "*"
    return f"{second} {minute} {hour} {day} {months} *"


def next_fire(expression: str, after: datetime, zone: ZoneInfo) -> datetime:
    """The first time a cron expression fires strictly after `after`, on the clock of `zone`, as
    the `cron` library finds it. Raises ValueError when the expression cannot be read, or when it
    does not fire within five years."""
    cron = _parse(expression)
    start = after.astimezone(zone).replace(tzinfo=None)
    day, last = start.date(), start.date() + SEARCH
    floor: time | None = start.time()
    while day <= last:
        if cron.fires_on(day) and (clock := cron.first_time(floor)) is not None:
            return datetime.combine(day, clock, tzinfo=zone)
        day += timedelta(days=1)
        floor = None
    raise ValueError(f"{expression!r} does not fire within five years")


def next_run(document: Mapping[str, Any], workflow_id: str, after: datetime) -> datetime | None:
    """The first time after `after` that any enabled Schedule Trigger in the n8n workflow fires.
    None when nothing schedules it, or when any of its rules is one the Portal cannot show, so the
    Portal never shows a time it cannot stand behind. It does not check that the workflow is on."""
    try:
        workflow = _Workflow.model_validate(document)
    except ValidationError:
        return None
    zone = _zone(workflow.settings)
    if zone is None:
        return None
    fires: list[datetime] = []
    for node in workflow.nodes:
        if node.type != SCHEDULE_TRIGGER or node.disabled:
            continue
        intervals = schedule_intervals(node.parameters)
        if not intervals or any(interval_problem(i) is not None for i in intervals):
            return None
        key = f"{workflow_id}:{node.id}"
        fires.extend(next_fire(cron_expression(i, key), after, zone) for i in intervals)
    return min(fires, default=None)


def schedule_intervals(parameters: Mapping[str, JsonValue]) -> list[Mapping[str, JsonValue]]:
    """A Schedule Trigger's rules, from its `rule.interval`. An entry that is not an object reads
    as an empty one, which n8n would fill in by itself."""
    rule = parameters.get("rule")
    intervals = rule.get("interval") if isinstance(rule, dict) else None
    if not isinstance(intervals, list):
        return []
    return [interval if isinstance(interval, dict) else {} for interval in intervals]


class _Node(BaseModel):
    id: str
    type: str = ""
    disabled: bool = False
    parameters: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class _Workflow(BaseModel):
    nodes: list[_Node]
    settings: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


def _zone(settings: Mapping[str, JsonValue]) -> ZoneInfo | None:
    name = settings.get("timezone")
    try:
        return ZoneInfo(name if isinstance(name, str) and name != DEFAULT_ZONE else TIME_ZONE)
    except ZoneInfoNotFoundError, ValueError:
        return None


def _field(interval: Mapping[str, JsonValue]) -> str:
    """n8n reads a rule whose field it does not know as days."""
    field = interval.get("field")
    return field if isinstance(field, str) and (field in RULES or field == CRON) else "days"


def _given(interval: Mapping[str, JsonValue], key: str, default: JsonValue) -> JsonValue:
    value = interval.get(key)
    return default if value is None else value


def _whole(value: JsonValue, default: int) -> int:
    """Anything that is not a whole number counts as 0, which no rule allows."""
    if value is None:
        return default
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _divides(whole: int, value: JsonValue) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and value != 0 and whole % value == 0
    )


def _weekdays(days: JsonValue) -> str:
    if days is None:
        return "0"
    if isinstance(days, list):
        return ",".join(str(day) for day in days) if days else "*"
    return str(days)


def _stable_int(node_key: str, label: str, low: int, high: int) -> int:
    """n8n's `stableInt`: a number in [low, high), the same every time for the same node."""
    digest = hashlib.sha256(f"{node_key}:{label}".encode()).digest()
    return low + int.from_bytes(digest[:4], "big") % (high - low)


@dataclass(frozen=True)
class _Cron:
    seconds: tuple[int, ...]
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    """Sunday is 0."""

    def fires_on(self, day: date) -> bool:
        """The `cron` library's rule: when both day fields are narrowed, either may match, and
        otherwise the narrowed one must."""
        if day.month not in self.months:
            return False
        on_day = day.day in self.days
        on_weekday = day.isoweekday() % 7 in self.weekdays
        if len(self.days) < 31 and len(self.weekdays) < 7:
            return on_day or on_weekday
        return on_day and on_weekday

    def first_time(self, after: time | None) -> time | None:
        """The first time of day it fires, strictly after `after` when there is one."""
        for hour in self.hours:
            if after is not None and hour < after.hour:
                continue
            for minute in self.minutes:
                if after is not None and (hour, minute) < (after.hour, after.minute):
                    continue
                for second in self.seconds:
                    clock = time(hour, minute, second)
                    if after is None or clock > after:
                        return clock
        return None


def _parse(expression: str) -> _Cron:
    """Reads what the `cron` library reads, except month and day names and presets such as
    @daily, which it refuses. A five-field expression has its second at 0, as in the library."""
    texts = expression.split()
    if len(texts) == len(BOUNDS) - 1:
        texts = ["0", *texts]
    if len(texts) != len(BOUNDS):
        raise ValueError(f"{expression!r} does not have five or six fields")
    seconds, minutes, hours, days, months, weekdays = (
        _values(text, low, high) for text, (low, high) in zip(texts, BOUNDS, strict=True)
    )
    weekdays = frozenset(day % 7 for day in weekdays)
    if len(weekdays) == 7 and not any(
        day <= LONGEST_MONTHS[month - 1] for day in days for month in months
    ):
        raise ValueError(f"{expression!r} names no day its months have")
    return _Cron(
        tuple(sorted(seconds)),
        tuple(sorted(minutes)),
        tuple(sorted(hours)),
        days,
        months,
        weekdays,
    )


def _values(text: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        match = PART.fullmatch(f"{low}-{high}{part[1:]}" if part.startswith("*") else part)
        if match is None:
            raise ValueError(f"cannot read {text!r}")
        first, last, step = match.groups()
        start = int(first)
        end = int(last) if last is not None else start if step is None else high
        every = 1 if step is None else int(step)
        if start < low or end > high or start > end or every == 0:
            raise ValueError(f"{text!r} is out of range")
        values.update(range(start, end + 1, every))
    return frozenset(values)
