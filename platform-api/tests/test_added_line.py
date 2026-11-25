import pytest

from platform_api.builder.n8n_draft import added_line

STEP = "I added an approval step. Before {} is made, an Approver must approve it in Teams."


@pytest.mark.parametrize(
    ("write", "noun"),
    [
        ("Create ticket", "each ticket"),
        ("Create tickets", "each ticket"),
        ("Update page", "each page update"),
        ("Close issues", "each change"),
    ],
)
def test_the_approval_step_says_who_says_yes_and_where_with_the_writes_own_noun(
    write: str, noun: str
):
    assert added_line(write) == STEP.format(noun)
    assert "a yes before" not in added_line(write)
