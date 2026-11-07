import re

import pytest
from pydantic import ValidationError

from agent_runtime.contract import WatchlistInputs
from agent_runtime.contracts import langgraph

RELEASE = r"^(?:[vV]|docker-v|n8n@|langchain==)?\d+\.\d+\.\d+$"
V_ONLY = r"^[vV]?\d+\.\d+\.\d+$"
PLAIN = r"^\d+\.\d+\.\d+$"


@pytest.mark.parametrize(
    "pattern",
    [RELEASE, V_ONLY, PLAIN],
    ids=["release", "v only, from older runs", "plain, from older runs"],
)
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
        r"^(?:[vV]|docker-v|n8n@|langchain==|cli==)?\d+\.\d+\.\d+$",
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
        "a prefix nobody vetted",
        "other",
        "invalid",
    ],
)
def test_any_other_pattern_is_refused(pattern: str):
    with pytest.raises(ValidationError, match="tag_pattern"):
        WatchlistInputs(tag_pattern=pattern, software=[langgraph()])


@pytest.mark.parametrize(
    ("tag", "counts"),
    [
        ("1.2.14", True),
        ("v2.14.2", True),
        ("V2.14.2", True),
        ("docker-v29.1.0", True),
        ("n8n@2.4.2", True),
        ("langchain==0.3.1", True),
        ("docker-v29.1.0-rc.1", False),
        ("n8n@2.4.2-beta.1", False),
        ("langchain-core==0.3.1", False),
        ("langchain-openai==0.3.1", False),
        ("cli==0.4.37", False),
        ("sdk==0.2.4", False),
        ("docker-29.1.0", False),
        ("n8n@2.4", False),
        ("n8n@2.4.2\n", False),
    ],
)
def test_the_release_pattern_counts_the_main_product_tag_of_each_project(tag: str, counts: bool):
    assert (re.fullmatch(RELEASE, tag, re.ASCII) is not None) is counts
