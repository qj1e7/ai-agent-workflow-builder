from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from platform_api.orchestration.schedule import Schedule, due_slot, parse_at, slots

SGT = ZoneInfo("Asia/Singapore")


def sgt(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=SGT)


# 26 Oct 2026 is a Monday.
MONDAY_9 = Schedule("monday", "09:00")
EVERY_DAY_9 = Schedule("every_day", "09:00")


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("09:00", True),
        ("23:55", True),
        ("00:00", True),
        ("09:03", False),
        ("24:00", False),
        ("9:00", False),
        ("09:60", False),
        ("0900", False),
        ("ab:cd", False),
        ("", False),
    ],
)
def test_a_time_is_hh_mm_on_a_five_minute_step(text: str, ok: bool):
    assert (parse_at(text) is not None) is ok


def test_before_this_weeks_slot_the_latest_is_last_weeks_and_the_next_is_today_s():
    found = slots(MONDAY_9, sgt(26, 8, 59))
    assert (found.latest, found.next) == (sgt(19, 9), sgt(26, 9))


def test_at_the_slot_it_is_the_latest_and_the_next_is_a_week_on():
    found = slots(MONDAY_9, sgt(26, 9))
    assert (found.latest, found.next) == (sgt(26, 9), sgt(2, 9, month=11))


def test_after_this_weeks_slot_the_latest_is_today_s():
    found = slots(MONDAY_9, sgt(28, 14, 30))
    assert (found.latest, found.next) == (sgt(26, 9), sgt(2, 9, month=11))


def test_every_day_has_a_slot_each_day():
    assert slots(EVERY_DAY_9, sgt(27, 10)) == slots(EVERY_DAY_9, sgt(27, 9))
    before = slots(EVERY_DAY_9, sgt(27, 8))
    assert (before.latest, before.next) == (sgt(26, 9), sgt(27, 9))
    after = slots(EVERY_DAY_9, sgt(27, 10))
    assert (after.latest, after.next) == (sgt(27, 9), sgt(28, 9))


@pytest.mark.parametrize(
    "day", ["tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
)
def test_each_weekday_finds_its_own_day(day: str):
    found = slots(Schedule(day, "09:00"), sgt(26, 12))  # type: ignore[arg-type]
    assert found.latest.strftime("%A").lower() == day
    assert found.latest <= sgt(26, 12) < found.next
    assert found.next - found.latest == timedelta(days=7)


def test_singapore_time_decides_the_day_not_utc():
    # Monday 07:30 in Singapore is still Sunday 23:30 in UTC.
    now = datetime(2026, 10, 25, 23, 30, tzinfo=UTC)
    found = slots(Schedule("monday", "07:00"), now)
    assert found.latest == sgt(26, 7)
    assert found.latest == datetime(2026, 10, 25, 23, 0, tzinfo=UTC)
    assert found.next == sgt(2, 7, month=11)


def test_a_slot_just_after_utc_midnight_is_still_the_singapore_morning():
    schedule = Schedule("every_day", "00:30")
    now = datetime(2026, 10, 25, 16, 20, tzinfo=UTC)  # 00:20 on Monday in Singapore
    found = slots(schedule, now)
    assert found.latest == sgt(25, 0, 30)
    assert found.next == datetime(2026, 10, 25, 16, 30, tzinfo=UTC)


def test_a_schedule_saved_after_today_s_slot_waits_for_the_next_one():
    saved = sgt(26, 10)
    assert due_slot(MONDAY_9, saved, None, sgt(26, 11)) is None
    assert due_slot(MONDAY_9, saved, None, sgt(2, 8, 55, month=11)) is None
    assert due_slot(MONDAY_9, saved, None, sgt(2, 9, month=11)) == sgt(2, 9, month=11)


def test_a_schedule_saved_exactly_at_a_slot_does_not_start_that_slot():
    assert due_slot(MONDAY_9, sgt(26, 9), None, sgt(26, 9, 5)) is None


def test_a_schedule_saved_before_the_slot_is_due_once_the_slot_has_come():
    saved = sgt(26, 8)
    assert due_slot(MONDAY_9, saved, None, sgt(26, 8, 55)) is None
    assert due_slot(MONDAY_9, saved, None, sgt(26, 9)) == sgt(26, 9)


def test_several_missed_slots_start_one_check_for_the_latest():
    saved = sgt(1, 0)
    last = sgt(20, 9)
    assert due_slot(EVERY_DAY_9, saved, last, sgt(27, 9, 5)) == sgt(27, 9)
    assert due_slot(EVERY_DAY_9, saved, None, sgt(27, 9, 5)) == sgt(27, 9)


def test_a_repeated_tick_in_the_same_slot_is_not_due():
    saved = sgt(1, 0)
    slot = sgt(27, 9)
    assert due_slot(EVERY_DAY_9, saved, slot, sgt(27, 9, 5)) is None
    assert due_slot(EVERY_DAY_9, saved, slot, sgt(27, 23, 55)) is None
    assert due_slot(EVERY_DAY_9, saved, slot, sgt(28, 9)) == sgt(28, 9)


def test_a_late_tick_after_a_later_slot_was_started_does_not_go_back():
    assert due_slot(EVERY_DAY_9, sgt(1, 0), sgt(28, 9), sgt(28, 9, 5)) is None
