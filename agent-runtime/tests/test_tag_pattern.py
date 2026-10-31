import pytest
from pydantic import ValidationError

from agent_runtime.contract import WatchlistInputs
from agent_runtime.contracts import langgraph

RELEASE = r"^[vV]?\d+\.\d+\.\d+$"
PLAIN = r"^\d+\.\d+\.\d+$"


@pytest.mark.parametrize("pattern", [RELEASE, PLAIN], ids=["release", "plain, from older runs"])
def test_a_vetted_pattern_is_accepted(pattern: str):
    assert WatchlistInputs(tag_pattern=pattern, software=[langgraph()]).tag_pattern == pattern


@pytest.mark.parametrize(
    "pattern",
    [
        "(a+)+$",
        "",
        "^" + "a" * 5000,
        PLAIN + " ",
        r"\d+\.\d+\.\d+",
        r"^v?\d+\.\d+\.\d+$",
        "^cli==",
        "(",
    ],
    ids=[
        "redos",
        "empty",
        "long",
        "vetted plus space",
        "vetted unanchored",
        "near miss",
        "other",
        "invalid",
    ],
)
def test_any_other_pattern_is_refused(pattern: str):
    with pytest.raises(ValidationError, match="tag_pattern"):
        WatchlistInputs(tag_pattern=pattern, software=[langgraph()])
