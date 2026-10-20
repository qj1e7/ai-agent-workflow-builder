import pytest
from pydantic import ValidationError

from agent_runtime.contract import ReleaseCheckInputs

PATTERN = r"^\d+\.\d+\.\d+$"


@pytest.mark.parametrize(
    "repo",
    [
        "../x",
        "a/..",
        "a/.",
        "a/b/c",
        "a",
        "",
        "/",
        "a/",
        "/b",
        "%2e%2e/x",
        "a/%2e%2e",
        "a/b%2fc",
        "a" * 40 + "/repo",
        "-a/repo",
        "a b/repo",
        "a/b?x=1",
        "a/b#x",
    ],
)
def test_a_repo_that_is_not_owner_slash_name_is_refused(repo: str):
    with pytest.raises(ValidationError):
        ReleaseCheckInputs(repo=repo, tag_pattern=PATTERN)


@pytest.mark.parametrize(
    "repo", ["langchain-ai/langgraph", "a/b", "a" * 39 + "/x", "o/.github", "o/my.repo_1-x"]
)
def test_a_real_repo_name_is_accepted(repo: str):
    assert ReleaseCheckInputs(repo=repo, tag_pattern=PATTERN).repo == repo
