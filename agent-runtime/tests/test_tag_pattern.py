import pytest
from pydantic import ValidationError

from agent_runtime.contract import WatchlistInputs
from agent_runtime.contracts import langgraph

VETTED = r"^\d+\.\d+\.\d+$"


def test_the_vetted_pattern_is_accepted():
    assert WatchlistInputs(tag_pattern=VETTED, software=[langgraph()]).tag_pattern == VETTED


@pytest.mark.parametrize(
    "pattern",
    ["(a+)+$", "", "^" + "a" * 5000, VETTED + " ", r"\d+\.\d+\.\d+", "^cli==", "("],
    ids=["redos", "empty", "long", "vetted plus space", "vetted unanchored", "other", "invalid"],
)
def test_any_other_pattern_is_refused(pattern: str):
    with pytest.raises(ValidationError, match="tag_pattern"):
        WatchlistInputs(tag_pattern=pattern, software=[langgraph()])
