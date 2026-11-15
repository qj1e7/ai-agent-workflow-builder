"""When a workflow runs, as the Portal saves it: a day and a time in a time zone. Its own n8n
workflow's Schedule Trigger runs it (n8n_schedule.py). Pure; the store is schedule_store.py."""

from dataclasses import dataclass
from datetime import time
from typing import Literal

type Day = Literal[
    "every_day",
    "weekdays",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

DAYS: tuple[Day, ...] = (
    "every_day",
    "weekdays",
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
SATURDAY = 5
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
