"""The catalogue reader (ADR 0051, section 8), on the catalogue scripts/n8n-catalogue.sh made from
the pinned n8n image. CI mounts contracts/ into the test image, where it is /contracts."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_runtime.catalogue import Catalogue, NotInCatalogue

CATALOGUE = Path(__file__).resolve().parents[2] / "contracts" / "n8n" / "catalogue.json"
JIRA = "n8n-nodes-base.jira"
SLACK = "n8n-nodes-base.slack"
GITHUB = "n8n-nodes-base.github"

type Json = dict[str, Any]


@pytest.fixture(scope="module")
def raw() -> Json:
    return json.loads(CATALOGUE.read_bytes())


@pytest.fixture(scope="module")
def catalogue(raw: Json) -> Catalogue:
    return Catalogue(raw)


def names(parameters: list[Json]) -> list[str]:
    return [p["name"] for p in parameters]


def only_for_others(parameter: Json, resource: str, operation: str) -> bool:
    """Whether n8n shows the parameter only for another resource or operation."""
    show = (parameter.get("displayOptions") or {}).get("show") or {}
    return any(
        key in show and all(isinstance(v, str) for v in show[key]) and value not in show[key]
        for key, value in (("resource", resource), ("operation", operation))
    )


def test_it_is_made_from_the_pinned_image(catalogue: Catalogue):
    assert catalogue.image.startswith("n8nio/n8n:2.42.6@sha256:")


def test_jira_is_described_one_operation_at_a_time_and_never_whole(catalogue: Catalogue, raw: Json):
    whole = raw["blocks"][JIRA]["versions"][0]
    create = catalogue.describe_block(JIRA, 1, "issue", "create")

    assert names(create["parameters"]) == [
        "jiraVersion",
        "site",
        "project",
        "issueType",
        "summary",
        "additionalFields",
    ]
    assert len(json.dumps(create)) * 5 < len(json.dumps(whole))
    assert create["action"] == "Create an issue"
    assert create["class"] == "off"
    assert "tag" not in create
    assert create["key"] == {"system": "jira", "for": "read"}

    get = catalogue.describe_block(JIRA, 1, "issue", "get")
    assert "issueKey" in names(get["parameters"])
    assert "summary" not in names(get["parameters"])
    assert (get["class"], get["tag"], get["says"]) == ("read", "Reads Jira", "Reads Jira issues")


@pytest.mark.parametrize("node_type", [JIRA, SLACK, GITHUB])
def test_no_operation_of_a_keyed_block_gets_a_parameter_n8n_shows_only_for_another(
    catalogue: Catalogue, raw: Json, node_type: str
):
    block = raw["blocks"][node_type]
    for group in block["versions"]:
        version = group["versions"][-1]
        everything = names(group["parameters"])
        for operation in group["operations"]:
            resource, value = operation["resource"], operation["value"]
            described = catalogue.describe_block(node_type, version, resource, value)
            shown = described["parameters"]
            assert len(shown) < len(everything)
            assert set(names(shown)) <= set(everything)
            assert not {"resource", "operation"} & set(names(shown))
            for parameter in shown:
                assert not only_for_others(parameter, resource, value), parameter["name"]
                left = (parameter.get("displayOptions") or {}).get("show") or {}
                assert not {"resource", "operation", "@version"} & set(left)


def test_n8n_s_version_conditions_decide_too(catalogue: Catalogue):
    older = catalogue.describe_block(SLACK, 2.6, "message", "search")
    newer = catalogue.describe_block(SLACK, 2.7, "message", "search")

    assert "returnAll" in names(older["parameters"])
    assert "returnAll" not in names(newer["parameters"])
    assert names(newer["parameters"]).count("limit") == 1


def test_what_n8n_shows_only_in_an_ai_agent_s_tool_is_left_out_of_the_block(
    catalogue: Catalogue,
):
    http = catalogue.describe_block("n8n-nodes-base.httpRequest", 4.5)

    assert "url" in names(http["parameters"])
    assert "optimizeResponse" not in names(http["parameters"])


def test_a_condition_on_another_parameter_stays_on_it(catalogue: Catalogue):
    get = catalogue.describe_block(JIRA, 1, "issue", "get")
    site = next(p for p in get["parameters"] if p["name"] == "site")

    assert site["displayOptions"] == {"show": {"jiraVersion": ["cloudServiceAccount"]}}


def test_without_a_choice_it_offers_the_choices_and_no_parameters(catalogue: Catalogue):
    choices = catalogue.describe_block(JIRA)

    assert choices["version"] == 1
    assert "parameters" not in choices
    assert "issue" in [r["value"] for r in choices["resources"]]

    issue = catalogue.describe_block(JIRA, 1, "issue")
    assert "parameters" not in issue
    assert {o["resource"] for o in issue["operations"]} == {"issue"}


@pytest.mark.parametrize(
    ("asked", "said"),
    [
        ((JIRA, 3, "issue", "create"), "Jira Software has no version 3. It has 1."),
        ((JIRA, 1, "ticket", "create"), "has no resource 'ticket'. It has issue, "),
        ((JIRA, 1, "issue", "close"), "has no operation 'close' for issue. It has changelog, "),
        (("n8n-nodes-base.nothing", 1, None, None), "n8n has no block 'n8n-nodes-base.nothing'"),
    ],
)
def test_what_the_catalogue_does_not_have_names_what_it_has(
    catalogue: Catalogue, asked: tuple[str, float, str | None, str | None], said: str
):
    with pytest.raises(NotInCatalogue, match=said.replace(".", r"\.")):
        catalogue.describe_block(*asked)


def test_a_tool_n8n_made_is_its_block_with_the_tool_s_own_parameters_and_class(
    catalogue: Catalogue,
):
    tool = catalogue.describe_block("n8n-nodes-base.jiraTool", 1, "issue", "get")
    block = catalogue.describe_block(JIRA, 1, "issue", "get")

    assert tool["tool_of"] == JIRA
    assert names(tool["parameters"]) == [
        "descriptionType",
        "toolDescription",
        *names(block["parameters"]),
    ]
    assert tool["class"] == "off"
    assert "tag" not in tool


def test_a_block_classed_by_mode_and_held_in_one_mode_says_both(catalogue: Catalogue):
    merge = catalogue.describe_block("n8n-nodes-base.merge")

    assert merge["class_by"]["parameter"] == "mode"
    assert merge["class_by"]["classes"]["combineBySql"] == "off"
    assert merge["held"] == [
        {"because": "It runs code.", "waits_for": "spike P9", "when": {"mode": ["combineBySql"]}}
    ]


def test_our_own_blocks_are_in_it(catalogue: Catalogue):
    read = catalogue.describe_block("CUSTOM.wabRead")

    assert read["class"] == "read"
    assert names(read["parameters"]) == ["source", "place", "query"]


def test_find_puts_our_blocks_first_then_the_classed_ones(catalogue: Catalogue):
    found = catalogue.find_blocks("read jira issues")

    assert [b["type"] for b in found[:2]] == ["CUSTOM.wabRead", JIRA]
    jira = found[1]
    assert jira["key"] == {"system": "jira", "for": "read"}
    assert {o["class"] for o in jira["operations"]} == {"read"}
    assert len(catalogue.find_blocks("read jira issues", limit=3)) == 3


def test_find_shows_the_operation_that_matches(catalogue: Catalogue):
    slack = catalogue.find_blocks("post a message in slack")[0]

    assert slack["type"] == SLACK
    assert slack["operations"][0] == {
        "resource": "message",
        "value": "post",
        "name": "Send",
        "class": "notice",
    }


@pytest.mark.parametrize(
    ("words", "node_type"),
    [("curl", "n8n-nodes-base.httpRequest"), ("cron", "n8n-nodes-base.scheduleTrigger")],
)
def test_find_knows_n8n_s_other_words_for_a_block(catalogue: Catalogue, words: str, node_type: str):
    assert catalogue.find_blocks(words, limit=1)[0]["type"] == node_type


def test_find_marks_a_held_block(catalogue: Catalogue):
    found = {b["type"]: b for b in catalogue.find_blocks("write a file to disk")}

    assert found["n8n-nodes-base.readWriteFile"]["held"][0]["waits_for"] == "spike P9"


def test_find_with_no_telling_word_finds_nothing(catalogue: Catalogue):
    assert catalogue.find_blocks("the and of") == []
