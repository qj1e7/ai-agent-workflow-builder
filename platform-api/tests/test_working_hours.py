from datetime import datetime, timedelta

import pytest

from platform_api.orchestration.dispatch import WakePolicy, resume_path
from platform_api.orchestration.working_hours import EXPIRES_AFTER, after_working_time
from platform_api.shared import TEAM_TIME_ZONE, N8nExecutionId

SG = TEAM_TIME_ZONE


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A time in November 2026, Singapore time. The 2nd is a Monday."""
    return datetime(2026, 11, day, hour, minute, tzinfo=SG)


@pytest.mark.parametrize(
    ("start", "wait", "end"),
    [
        pytest.param(at(3, 10, 14), EXPIRES_AFTER, at(5, 10, 14), id="two-working-days"),
        pytest.param(at(3, 10), timedelta(hours=4), at(3, 14), id="same-day"),
        pytest.param(at(3, 16), timedelta(hours=4), at(4, 11), id="over-the-night"),
        pytest.param(at(6, 17), EXPIRES_AFTER, at(10, 17), id="over-the-weekend"),
        pytest.param(at(7, 11), timedelta(hours=1), at(9, 10), id="asked-on-saturday"),
        pytest.param(at(3, 7), timedelta(hours=1), at(3, 10), id="asked-before-nine"),
        pytest.param(at(3, 19), timedelta(hours=1), at(4, 10), id="asked-after-six"),
        pytest.param(at(3, 17), timedelta(hours=1), at(3, 18), id="ends-at-six"),
    ],
)
def test_waits_count_working_hours_only(start: datetime, wait: timedelta, end: datetime):
    assert after_working_time(start, wait, SG) == end


def test_a_wake_tries_again_quickly_then_every_five_minutes_for_a_day():
    policy, first = WakePolicy(), at(3, 10)
    tries = [policy.next_try(n, first, first) for n in (1, 5, 6, 40)]
    assert [t - first for t in tries if t is not None] == [
        timedelta(seconds=2),
        timedelta(seconds=60),
        timedelta(minutes=5),
        timedelta(minutes=5),
    ]
    assert policy.next_try(300, first, first + timedelta(hours=24)) is None


@pytest.mark.parametrize(
    ("url", "path"),
    [
        ("http://n8n:5678/webhook-waiting/41?signature=abc", "/webhook-waiting/41?signature=abc"),
        ("https://evil.example/webhook-waiting/41", "/webhook-waiting/41"),
        ("http://n8n:5678/webhook-waiting/42?signature=abc", None),
        ("http://n8n:5678/webhook/41", None),
        ("file:///webhook-waiting/41", None),
    ],
)
def test_a_wake_goes_only_to_our_n8n_for_the_execution_that_asked(url: str, path: str | None):
    assert resume_path(url, N8nExecutionId("41")) == path
