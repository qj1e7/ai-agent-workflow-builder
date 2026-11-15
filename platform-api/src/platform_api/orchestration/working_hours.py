"""ADR 0024's waits count working hours only, Monday to Friday from 9am to 6pm, in the team's time
zone."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DAY_STARTS, DAY_ENDS = 9, 18

EXPIRES_AFTER = timedelta(hours=2 * (DAY_ENDS - DAY_STARTS))
"""ADR 0024's default second wait, two working days."""


def after_working_time(start: datetime, wait: timedelta, zone: ZoneInfo) -> datetime:
    """The moment `wait` of working time has passed since `start`."""
    at, left = start.astimezone(zone), wait
    while True:
        if at.weekday() >= 5 or at.hour >= DAY_ENDS:
            at = _morning(at + timedelta(days=1))
            continue
        at = max(at, _morning(at))
        today = at.replace(hour=DAY_ENDS, minute=0, second=0, microsecond=0) - at
        if left <= today:
            return (at + left).astimezone(start.tzinfo)
        left -= today
        at = _morning(at + timedelta(days=1))


def _morning(day: datetime) -> datetime:
    return day.replace(hour=DAY_STARTS, minute=0, second=0, microsecond=0)
