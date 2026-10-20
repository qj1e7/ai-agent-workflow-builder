import pytest

from platform_api.builder import TAG_PATTERN, TEMPLATES
from platform_api.builder.templates import (
    ParamErrors,
    ValidParams,
    suggest_template,
    validate_params,
)

RELEASE_CHECK = TEMPLATES["release_check"]

FULL = {
    "repo": "langchain-ai/langgraph",
    "tag_pattern": TAG_PATTERN,
    "ticket_project": "MOCK",
    "last_seen_tag": "1.2.14",
}


def with_(**changes: str) -> dict[str, str]:
    return {**FULL, **changes}


def without(*names: str) -> dict[str, str]:
    return {k: v for k, v in FULL.items() if k not in names}


def test_full_params_are_accepted_as_given():
    assert validate_params(RELEASE_CHECK, FULL) == ValidParams(FULL)


def test_optional_params_may_be_left_out_and_the_pattern_is_filled_in():
    result = validate_params(RELEASE_CHECK, without("tag_pattern", "last_seen_tag"))
    assert result == ValidParams(
        {"repo": "langchain-ai/langgraph", "ticket_project": "MOCK", "tag_pattern": TAG_PATTERN}
    )


def test_an_empty_last_seen_tag_means_start_from_the_newest_release():
    result = validate_params(RELEASE_CHECK, with_(last_seen_tag=""))
    assert isinstance(result, ValidParams)
    assert "last_seen_tag" not in result.values


@pytest.mark.parametrize(
    ("params", "field"),
    [
        (without("repo"), "repo"),
        (with_(repo="owner"), "repo"),
        (with_(repo="owner/"), "repo"),
        (with_(repo="a" * 40 + "/repo"), "repo"),
        (with_(repo="owner/.."), "repo"),
        (with_(repo="owner/."), "repo"),
        (with_(repo="owner/re po"), "repo"),
        (with_(repo="owner/repo/extra"), "repo"),
        (without("ticket_project"), "ticket_project"),
        (with_(ticket_project="mock"), "ticket_project"),
        (with_(ticket_project="1ABC"), "ticket_project"),
        (with_(ticket_project="A" * 11), "ticket_project"),
        (with_(tag_pattern=r"^v.*$"), "tag_pattern"),
        (with_(last_seen_tag="v1.2.3"), "last_seen_tag"),
        ({**FULL, "colour": "red"}, "colour"),
    ],
)
def test_bad_params_are_rejected_with_the_field_named(params: dict[str, str], field: str):
    result = validate_params(RELEASE_CHECK, params)
    assert isinstance(result, ParamErrors)
    assert [name for name, _ in result.errors] == [field]


def test_the_tag_pattern_error_says_which_value_is_allowed():
    result = validate_params(RELEASE_CHECK, with_(tag_pattern="x"))
    assert isinstance(result, ParamErrors)
    assert TAG_PATTERN in result.errors[0][1]


def test_every_bad_field_is_reported_at_once():
    result = validate_params(RELEASE_CHECK, {"repo": "nope", "ticket_project": "x"})
    assert isinstance(result, ParamErrors)
    assert sorted(name for name, _ in result.errors) == ["repo", "ticket_project"]


def test_the_ticket_project_comes_from_the_params_into_the_binding():
    binding = RELEASE_CHECK.bindings_for({"ticket_project": "OPS"})["create_ticket"]
    assert (binding.connector, binding.operation) == ("jira", "create_ticket")
    assert dict(binding.target) == {"project": "OPS"}


@pytest.mark.parametrize(
    ("text", "template", "terms"),
    [
        (
            "Check langchain-ai/langgraph for new releases and open a ticket for the team.",
            "release_check",
            ["releases", "ticket"],
        ),
        ("water the plants", None, []),
        ("a new github tag", "release_check", ["github", "tag"]),
        ("Tag the GitHub TAG", "release_check", ["tag", "github"]),
        ("only a ticket", None, ["ticket"]),
    ],
)
def test_suggest_needs_two_matching_words(text: str, template: str | None, terms: list[str]):
    found, matched = suggest_template(text)
    assert (found.key if found else None, matched) == (template, terms)
