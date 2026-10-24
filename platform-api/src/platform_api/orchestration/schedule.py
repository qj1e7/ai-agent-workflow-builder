"""When a watchlist is checked: the schedule, its slots and when a check is due.

Everything here is pure. The store and the tick that act on it are in schedule_store.py.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

type Day = Literal[
    "every_day", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]

DAYS: tuple[Day, ...] = (
    "every_day",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
WEEKDAY: dict[Day, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
TIME_ZONE = "Asia/Singapore"
STEP_MINUTES = 5
DEFAULT_DAY: Day = "monday"
DEFAULT_AT = "09:00"
AT_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][05]$"


def parse_at(text: str) -> time | None:
    """ "HH:MM" on a 5-minute step, or None."""
    if len(text) != 5 or text[2] != ":" or not (text[:2] + text[3:]).isdigit():
        return None
    hour, minute = int(text[:2]), int(text[3:])
    if hour > 23 or minute > 59 or minute % STEP_MINUTES != 0:
        return None
    return time(hour, minute)


@dataclass(frozen=True)
class Schedule:
    day: Day
    at: str
    time_zone: str = TIME_ZONE

    @property
    def time_of_day(self) -> time:
        parsed = parse_at(self.at)
        if parsed is None:
            raise ValueError(f"not a schedule time: {self.at!r}")
        return parsed


@dataclass(frozen=True)
class Slots:
    latest: datetime
    """The newest slot at or before now."""
    next: datetime
    """The first slot after now."""


def slots(schedule: Schedule, now: datetime) -> Slots:
    """The slots on either side of now, in the schedule's own time zone, so 9:00 stays 9:00."""
    zone = ZoneInfo(schedule.time_zone)
    local_now = now.astimezone(zone)
    at = schedule.time_of_day

    def slot_on(offset: int) -> datetime | None:
        date = (local_now + timedelta(days=offset)).date()
        if schedule.day != "every_day" and date.weekday() != WEEKDAY[schedule.day]:
            return None
        return datetime.combine(date, at, tzinfo=zone)

    latest = next(s for o in range(0, -8, -1) if (s := slot_on(o)) is not None and s <= now)
    upcoming = next(s for o in range(0, 8) if (s := slot_on(o)) is not None and s > now)
    return Slots(latest, upcoming)


def due_slot(
    schedule: Schedule, saved_at: datetime, last_started: datetime | None, now: datetime
) -> datetime | None:
    """The slot to start a check for, or None. A slot is due when it is the latest one by now
    and later than both the last slot started and the time the schedule was saved, so a
    schedule saved after today's slot waits for the next one, and several missed slots start
    one check for the newest."""
    latest = slots(schedule, now).latest
    if latest <= saved_at or (last_started is not None and latest <= last_started):
        return None
    return latest
