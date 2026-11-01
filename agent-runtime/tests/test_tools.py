import json

import pytest
from pydantic import ValidationError

from agent_runtime.tools import BY_ID, BY_MODEL_NAME, TOOLS, tool_list, value_problem


def test_the_tool_list_is_the_four_tools_in_order():
    listed = tool_list()
    assert [(t.id, t.kind) for t in listed.tools] == [
        ("github.read_releases", "read"),
        ("jira.search", "read"),
        ("jira.read_ticket", "read"),
        ("jira.create_ticket", "write"),
    ]


def test_the_model_sees_the_id_with_underscores():
    assert set(BY_MODEL_NAME) == {
        "github_read_releases",
        "jira_search",
        "jira_read_ticket",
        "jira_create_ticket",
    }
    assert all(name.replace("_", "").isalnum() for name in BY_MODEL_NAME)


def test_a_write_tool_never_takes_its_target():
    schema = BY_ID["jira.create_ticket"].input_schema
    assert set(schema["properties"]) == {"title", "body"}
    assert BY_ID["jira.create_ticket"].target_kind == "jira_project"
    with pytest.raises(ValidationError):
        BY_ID["jira.create_ticket"].parse({"title": "t", "body": "b", "project": "ADMIN"})


def test_schemas_are_plain_with_no_references_titles_or_null_choices():
    for tool in TOOLS:
        text = json.dumps(tool.input_schema)
        assert "$ref" not in text and "$defs" not in text and '"null"' not in text
        assert '"title": "' not in text.replace('"title": {', "")
    search = BY_ID["jira.search"].input_schema
    assert search["required"] == ["project"]


def test_the_tool_list_schema_equals_what_a_run_validates_against():
    for spec in tool_list().tools:
        assert spec.input_schema == BY_ID[spec.id].input_schema


@pytest.mark.parametrize(
    ("kind", "value", "fits"),
    [
        ("github_repo", "langchain-ai/langgraph", True),
        ("github_repo", "../etc", False),
        ("github_repo", "owner/..", False),
        ("jira_project", "MOCK", True),
        ("jira_project", "mock", False),
        ("jira_project", "MOCK-1", False),
        ("jira_project", "AB_1", True),
        ("jira_project", "A" + "B" * 254, True),
        ("jira_project", "A" + "B" * 255, False),
        ("jira_project", "_AB", False),
        ("jira_project", "A", False),
        ("jira_project", "AB", True),
        ("jira_project", "1AB", False),
        ("text", "Support team", True),
        ("text", "", False),
        ("text", "two\nlines", False),
        ("text", "x" * 201, False),
    ],
)
def test_values_must_fit_their_kind(kind: str, value: str, fits: bool):
    assert (value_problem(kind, value) is None) is fits  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("key", "fits"),
    [
        ("MOCK-7", True),
        ("AB_1-12", True),
        ("AB_1", False),
        ("ab-1", False),
        ("_A-1", False),
        ("A-1", False),
        ("MOCK-0", False),
        ("MOCK-07", False),
        ("MOCK-123456789", True),
        ("MOCK-1234567890", False),
    ],
)
def test_ticket_keys_take_the_shapes_jira_allows(key: str, fits: bool):
    tool = BY_ID["jira.read_ticket"]
    if fits:
        tool.parse({"key": key})
    else:
        with pytest.raises(ValidationError):
            tool.parse({"key": key})


def test_a_search_takes_a_project_key_with_an_underscore():
    BY_ID["jira.search"].parse({"project": "AB_1"})
