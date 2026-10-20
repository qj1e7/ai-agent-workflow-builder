import pytest
from pydantic import ValidationError

from agent_runtime.contract import ReleaseCheckInputs

REPO = "langchain-ai/langgraph"
VETTED = r"^\d+\.\d+\.\d+$"


def test_the_vetted_pattern_is_accepted():
    assert ReleaseCheckInputs(repo=REPO, tag_pattern=VETTED).tag_pattern == VETTED


@pytest.mark.parametrize(
    "pattern",
    ["(a+)+$", "", "^" + "a" * 5000, VETTED + " ", r"\d+\.\d+\.\d+", "^cli==", "("],
    ids=["redos", "empty", "long", "vetted plus space", "vetted unanchored", "other", "invalid"],
)
def test_any_other_pattern_is_refused(pattern: str):
    with pytest.raises(ValidationError, match="tag_pattern"):
        ReleaseCheckInputs(repo=REPO, tag_pattern=pattern)
