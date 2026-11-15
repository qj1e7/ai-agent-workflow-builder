import pytest

from platform_api.orchestration.schedule import parse_at
from platform_api.orchestration.schedule_store import held_words


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


def test_a_held_schedule_says_why_and_how_it_runs_again_and_names_an_unnamed_owner_its_owner():
    """The one source of these words: every view carries them, and the Portal shows them."""
    assert held_words("owner_removed", "Carol") == (
        "Not running: Carol is no longer on the People list. "
        "An Operator can take it over by saving the schedule."
    )
    assert held_words("owner_not_an_operator", " ") == (
        "Not running: its owner can no longer run workflows. "
        "An Operator can take it over by saving the schedule."
    )
