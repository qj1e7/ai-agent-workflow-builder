import pytest

from platform_api.orchestration.schedule import parse_at


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
