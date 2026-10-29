from datetime import timedelta

import pytest

from platform_api.builder.lifecycle import (
    RESTORE_WINDOW,
    Columns,
    Deleted,
    Gone,
    Lifecycle,
    On,
    Paused,
    TooLate,
    delete,
    from_columns,
    name_of,
    pause,
    restore,
    resume,
    runs,
    to_columns,
)
from platform_api.shared import UserId
from tests.support import NOW

ALICE_ID = UserId("alice")
CAROL_ID = UserId("carol")
LATER = NOW + timedelta(minutes=5)


def test_pausing_keeps_who_paused_and_when_and_a_second_pause_changes_nothing():
    paused = Paused(NOW, ALICE_ID)
    assert pause(On(), NOW, ALICE_ID) == paused
    assert pause(paused, LATER, CAROL_ID) == paused


def test_resuming_turns_it_on_and_resuming_one_that_is_on_changes_nothing():
    assert resume(Paused(NOW, ALICE_ID)) == On()
    assert resume(On()) == On()


def test_a_deleted_use_case_cannot_be_paused_or_resumed():
    deleted = Deleted(NOW, ALICE_ID, On())
    assert pause(deleted, LATER, ALICE_ID) == Gone()
    assert resume(deleted) == Gone()


def test_deleting_twice_keeps_the_first_time():
    deleted = delete(On(), NOW, ALICE_ID)
    assert deleted == Deleted(NOW, ALICE_ID, On())
    assert delete(deleted, LATER, CAROL_ID) == deleted


def test_restoring_inside_the_day_puts_back_the_state_it_had():
    paused = Paused(NOW, CAROL_ID)
    deleted = delete(paused, LATER, ALICE_ID)
    assert restore(deleted, LATER + RESTORE_WINDOW) == paused
    assert restore(delete(On(), NOW, ALICE_ID), NOW + timedelta(hours=23)) == On()


def test_restoring_after_the_day_is_too_late():
    deleted = delete(On(), NOW, ALICE_ID)
    late = NOW + RESTORE_WINDOW + timedelta(seconds=1)
    assert restore(deleted, late) == TooLate(NOW + RESTORE_WINDOW)


def test_restoring_one_that_is_not_deleted_changes_nothing():
    assert restore(On(), NOW) == On()
    assert restore(Paused(NOW, ALICE_ID), LATER) == Paused(NOW, ALICE_ID)


@pytest.mark.parametrize(
    ("state", "name", "running"),
    [
        (On(), "on", True),
        (Paused(NOW, ALICE_ID), "paused", False),
        (Deleted(NOW, ALICE_ID, On()), "deleted", False),
    ],
)
def test_only_a_use_case_that_is_on_runs(state: Lifecycle, name: str, running: bool):
    assert (name_of(state), runs(state)) == (name, running)


@pytest.mark.parametrize(
    "state",
    [
        On(),
        Paused(NOW, ALICE_ID),
        Deleted(LATER, CAROL_ID, On()),
        Deleted(LATER, CAROL_ID, Paused(NOW, ALICE_ID)),
    ],
)
def test_every_state_round_trips_through_its_columns(state: Lifecycle):
    assert from_columns(to_columns(state)) == state


def test_the_columns_of_a_deleted_paused_use_case_keep_both_times():
    assert to_columns(Deleted(LATER, CAROL_ID, Paused(NOW, ALICE_ID))) == Columns(
        NOW, ALICE_ID, LATER, CAROL_ID
    )
