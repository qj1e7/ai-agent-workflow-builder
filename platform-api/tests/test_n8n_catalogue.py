"""The catalogue of n8n's blocks (ADR 0051, section 8), on small cut-down copies of what n8n
2.42.6 serves. scripts/pack-smoke.sh runs it on the image itself."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from platform_api.n8n_catalogue import PINS, catalogue, dump, main, pin_problems
from platform_api.n8n_code_check import Scan, scan
from platform_api.n8n_defaults_check import CONFIGS
from platform_api.orchestration.n8n_blocks import CALLS
from tests.test_n8n_code_check import a_package
from tests.test_n8n_defaults_check import PINS as TWO_PINS
from tests.test_n8n_defaults_check import sources as sources_of_defaults

PIN = "n8nio/n8n:2.42.6@sha256:526daa38b68e923cc00c5280d18b4da5d489f115a73bdbf3b8e452b184197a9a"

type Json = dict[str, Any]


def choice(name: str, value: str, **more: str) -> Json:
    return {"name": name, "value": value, **more}


JIRA_PROPERTIES: list[Json] = [
    {
        "displayName": "Resource",
        "name": "resource",
        "type": "options",
        "noDataExpression": True,
        "options": [choice("Issue", "issue", description="An issue"), choice("User", "user")],
        "default": "issue",
    },
    {
        "displayName": "Operation",
        "name": "operation",
        "type": "options",
        "displayOptions": {"show": {"resource": ["issue"]}},
        "options": [
            choice("Create", "create", action="Create an issue"),
            choice("Get", "get", action="Get an issue"),
        ],
        "default": "create",
    },
    {
        "displayName": "Operation",
        "name": "operation",
        "type": "options",
        "displayOptions": {"show": {"resource": ["user"]}},
        "options": [choice("Get", "get", action="Get a user")],
        "default": "get",
    },
    {
        "displayName": "Read the docs first",
        "name": "notice",
        "type": "notice",
        "default": "",
    },
    {
        "displayName": "Summary",
        "name": "summary",
        "type": "string",
        "required": True,
        "default": "",
        "hint": "Shown under the field",
        "routing": {"send": {"type": "body"}},
        "typeOptions": {"rows": 2, "loadOptionsMethod": "getSummaries"},
        "displayOptions": {"show": {"resource": ["issue"], "operation": ["create"]}},
    },
    {
        "displayName": "Additional Fields",
        "name": "additionalFields",
        "type": "collection",
        "default": {},
        "options": [
            {"displayName": "Labels", "name": "labels", "type": "string", "default": ""},
            {"displayName": "Say this", "name": "said", "type": "notice", "default": ""},
        ],
    },
]


def served() -> list[Json]:
    """What n8n serves, cut down: two blocks of n8n's with a key, the tool n8n makes of one, one of
    our blocks, a block held in one mode, a held block and the tool made of it, and what the
    catalogue leaves out."""
    return [
        {
            "name": "n8n-nodes-base.jira",
            "displayName": "Jira Software",
            "description": "Consume Jira Software API",
            "version": 1,
            "codex": {"alias": ["ticket", 7]},
            "properties": JIRA_PROPERTIES,
        },
        {
            "name": "n8n-nodes-base.jiraTool",
            "displayName": "Jira Software Tool",
            "description": "Consume Jira Software API",
            "version": 1,
            "properties": [
                {"displayName": "Description", "name": "toolDescription", "type": "string"},
                *JIRA_PROPERTIES,
            ],
        },
        {
            "name": "CUSTOM.wabRead",
            "displayName": "Read",
            "description": "Our block.",
            "version": 1,
            "properties": [],
        },
        {
            "name": "n8n-nodes-base.merge",
            "displayName": "Merge",
            "description": "Merges data",
            "version": [3, 3.1, 3.2],
            "defaultVersion": 3.2,
            "properties": [],
        },
        {
            "name": "n8n-nodes-base.merge",
            "displayName": "Merge (old)",
            "description": "Merges data",
            "version": 1,
            "defaultVersion": 3.2,
            "properties": [],
        },
        {
            "name": "n8n-nodes-base.executeWorkflow",
            "displayName": "Execute Sub-workflow",
            "description": "Runs another workflow.",
            "version": 1,
            "hidden": True,
            "properties": [],
        },
        {
            "name": "n8n-nodes-base.executeWorkflowTool",
            "displayName": "Execute Sub-workflow Tool",
            "description": "Runs another workflow.",
            "version": 1,
            "properties": [],
        },
        {"name": "n8n-nodes-base.executeCommand", "version": 1, "properties": []},
        {"name": "n8n-nodes-base.git", "version": 1, "properties": []},
        {"name": "@n8n/mcp-registry.airtable", "version": [1, 1.1], "properties": []},
        {
            "name": "@n8n/n8n-nodes-langchain.mcpRegistryClientTool",
            "version": [1, 1.1],
            "properties": [],
        },
    ]


OWN = {"n8n-nodes-base.jira", "n8n-nodes-base.merge", "n8n-nodes-base.executeWorkflow"}


@pytest.fixture
def made() -> Json:
    return catalogue(served(), PIN, OWN)


def test_it_holds_what_the_image_ships_and_our_blocks_and_leaves_out_the_rest(made: Json):
    assert made["image"] == PIN
    assert sorted(made["blocks"]) == [
        "CUSTOM.wabRead",
        "n8n-nodes-base.executeWorkflow",
        "n8n-nodes-base.executeWorkflowTool",
        "n8n-nodes-base.jira",
        "n8n-nodes-base.jiraTool",
        "n8n-nodes-base.merge",
    ]


def test_a_community_node_fails_rather_than_slipping_in():
    with pytest.raises(ValueError, match="n8n-nodes-community.thing, from n8n-nodes-community"):
        catalogue([{"name": "n8n-nodes-community.thing", "version": 1}], PIN, set())


def test_a_block_has_its_words_operations_classes_and_key(made: Json):
    jira = made["blocks"]["n8n-nodes-base.jira"]

    assert {k: v for k, v in jira.items() if k != "versions"} == {
        "name": "Jira Software",
        "description": "Consume Jira Software API",
        "aliases": ["ticket"],
        "default_version": 1,
        "key": {"system": "jira", "for": "read"},
    }
    (version,) = jira["versions"]
    assert version["resources"] == [
        {"name": "Issue", "value": "issue"},
        {"name": "User", "value": "user"},
    ]
    assert version["operations"] == [
        {
            "resource": "issue",
            "value": "create",
            "name": "Create",
            "action": "Create an issue",
            "class": "off",
        },
        {
            "resource": "issue",
            "value": "get",
            "name": "Get",
            "action": "Get an issue",
            "class": "read",
            "tag": "Reads Jira",
            "says": "Reads Jira issues",
        },
        {
            "resource": "user",
            "value": "get",
            "name": "Get",
            "action": "Get a user",
            "class": "read",
            "tag": "Reads Jira",
            "says": "Reads Jira issues",
        },
    ]


def test_parameters_keep_what_says_what_a_value_may_be_and_when_n8n_shows_it(made: Json):
    parameters = made["blocks"]["n8n-nodes-base.jira"]["versions"][0]["parameters"]

    assert [p["name"] for p in parameters] == [
        "resource",
        "operation",
        "operation",
        "summary",
        "additionalFields",
    ]
    assert parameters[3] == {
        "displayName": "Summary",
        "name": "summary",
        "type": "string",
        "required": True,
        "default": "",
        "typeOptions": {"loadOptionsMethod": "getSummaries"},
        "displayOptions": {"show": {"resource": ["issue"], "operation": ["create"]}},
    }
    assert parameters[4]["options"] == [
        {"displayName": "Labels", "name": "labels", "type": "string", "default": ""}
    ]


def test_a_tool_n8n_makes_keeps_only_what_it_adds_and_its_own_class(made: Json):
    tool = made["blocks"]["n8n-nodes-base.jiraTool"]

    assert tool["tool_of"] == "n8n-nodes-base.jira"
    assert "key" not in tool
    assert tool["versions"] == [
        {
            "versions": [1],
            "class": "off",
            "tool_parameters": [
                {"displayName": "Description", "name": "toolDescription", "type": "string"}
            ],
        }
    ]


def test_a_block_classed_by_another_parameter_says_so_and_each_version_is_kept(made: Json):
    merge = made["blocks"]["n8n-nodes-base.merge"]

    assert merge["default_version"] == 3.2
    assert merge["name"] == "Merge"
    assert [v["versions"] for v in merge["versions"]] == [[1], [3, 3.1, 3.2]]
    assert merge["versions"][1]["class_by"] == {
        "parameter": "mode",
        "classes": {
            "append": "read",
            "combine": "read",
            "combineBySql": "off",
            "chooseBranch": "read",
        },
    }
    assert "held" not in merge, "its SQL mode loads after spike P9, and the class file flags it"


def test_a_held_block_and_the_tool_made_of_it_are_both_marked(made: Json):
    calls = [CALLS.as_json()]

    assert made["blocks"]["n8n-nodes-base.executeWorkflow"]["held"] == calls
    assert made["blocks"]["n8n-nodes-base.executeWorkflow"]["hidden"] is True
    assert made["blocks"]["n8n-nodes-base.executeWorkflowTool"]["held"] == calls
    assert "held" not in made["blocks"]["n8n-nodes-base.jira"]


def test_the_file_is_the_same_whatever_order_n8n_serves_in_with_one_block_a_line():
    forwards = dump(catalogue(served(), PIN, OWN))
    backwards = dump(catalogue(list(reversed(served())), PIN, OWN))
    twice = dump(catalogue([*served(), *served()], PIN, OWN))

    assert forwards == backwards == twice
    lines = forwards.splitlines()
    assert lines[0] == '{"blocks": {'
    assert lines[1].startswith('"CUSTOM.wabRead": {')
    assert lines[-1] == f'}}, "image":"{PIN}"}}'
    assert len(lines) == 2 + 6
    assert json.loads(forwards) == catalogue(served(), PIN, OWN)


def test_propose_a_change_lists_the_writes_the_editor_would_load_and_other_choices_stay_open():
    """n8n loads Propose a change's changes from our API while it runs (`getWriteActions`). They
    are the same for every team, so the catalogue lists them for the drafter. Places are the
    team's own and stay open."""
    loaded = {"type": "options", "default": "", "options": []}
    propose = {
        "name": "CUSTOM.wabProposeChange",
        "displayName": "Propose a change",
        "version": 1,
        "properties": [
            {**loaded, "name": "action", "typeOptions": {"loadOptionsMethod": "getWriteActions"}},
            {**loaded, "name": "place", "typeOptions": {"loadOptionsMethod": "getPlaces"}},
        ],
    }
    theirs = {
        "name": "n8n-nodes-base.jira",
        "version": 1,
        "properties": [
            {**loaded, "name": "project", "typeOptions": {"loadOptionsMethod": "getWriteActions"}}
        ],
    }

    made = catalogue([propose, theirs], PIN, {"n8n-nodes-base.jira"})
    action, place = made["blocks"]["CUSTOM.wabProposeChange"]["versions"][0]["parameters"]

    assert action["options"] == [{"name": "Create a Jira ticket", "value": "jira.create_ticket"}]
    assert action["typeOptions"] == {"loadOptionsMethod": "getWriteActions"}
    assert place["options"] == []
    (project,) = made["blocks"]["n8n-nodes-base.jira"]["versions"][0]["parameters"]
    assert project["options"] == []


MERGE_INPUTS = (
    "={{((parameters) => {\n    return Array.from({ length: parameters.numberInputs || 2 }, "
    "(_, i) => ({\n        type: 'main',\n        displayName: `Input ${(i + 1).toString()}`,\n"
    "    }));\n})($parameter)}}"
)


def test_each_version_has_n8n_s_inputs_and_outputs_and_their_names_or_the_expression():
    """How blocks join, as the image serves it: a list, with the names n8n gives, or the
    expression n8n computes it with from the block's parameters, word for word."""
    branch = {
        "name": "n8n-nodes-base.if",
        "version": [2, 2.1],
        "inputs": ["main"],
        "outputs": ["main", "main"],
        "outputNames": ["true", "false"],
        "properties": [],
    }
    merge = {
        "name": "n8n-nodes-base.merge",
        "version": [3, 3.1],
        "inputs": MERGE_INPUTS,
        "outputs": ["main"],
        "properties": [],
    }
    agent_input = {
        "type": "ai_languageModel",
        "displayName": "Chat Model",
        "required": True,
        "maxConnections": 1,
        "filter": {"excludedNodes": ["@n8n/n8n-nodes-langchain.lmCohere"]},
    }
    chain = {
        "name": "@n8n/n8n-nodes-langchain.chainRetrievalQa",
        "version": 1,
        "inputs": [{"type": "main"}, agent_input],
        "inputNames": ["", "Model"],
        "outputs": ["main"],
        "properties": [],
    }
    names = {b["name"] for b in (branch, merge, chain)}

    made = catalogue([branch, merge, chain], PIN, names)["blocks"]

    (version,) = made["n8n-nodes-base.if"]["versions"]
    assert {k: version[k] for k in ("inputs", "outputs", "outputNames")} == {
        "inputs": ["main"],
        "outputs": ["main", "main"],
        "outputNames": ["true", "false"],
    }
    assert "inputNames" not in version
    (version,) = made["n8n-nodes-base.merge"]["versions"]
    assert version["inputs"] == MERGE_INPUTS
    (version,) = made["@n8n/n8n-nodes-langchain.chainRetrievalQa"]["versions"]
    assert version["inputs"] == [
        {"type": "main"},
        {
            "type": "ai_languageModel",
            "displayName": "Chat Model",
            "required": True,
            "maxConnections": 1,
        },
    ]
    assert version["inputNames"] == ["", "Model"]


def test_an_operation_only_some_versions_offer_names_them():
    notion = {
        "name": "n8n-nodes-base.notion",
        "displayName": "Notion",
        "version": [1, 2],
        "properties": [
            {
                "name": "resource",
                "type": "options",
                "options": [choice("Page", "page"), choice("Old", "old")],
            },
            {
                "name": "resource",
                "type": "options",
                "displayOptions": {"show": {"@version": [{"_cnd": {"gte": 2}}]}},
                "options": [choice("Data source", "dataSource")],
            },
            {
                "name": "operation",
                "type": "options",
                "displayOptions": {"show": {"resource": ["page"]}, "hide": {"@version": [1]}},
                "options": [choice("Create", "create"), choice("Get", "get")],
            },
            {
                "name": "operation",
                "type": "options",
                "displayOptions": {"show": {"resource": ["page"], "@version": [1]}},
                "options": [choice("Create", "create")],
            },
        ],
    }

    made = catalogue([notion], PIN, {"n8n-nodes-base.notion"})
    (version,) = made["blocks"]["n8n-nodes-base.notion"]["versions"]

    assert version["resources"] == [
        {"name": "Page", "value": "page"},
        {"name": "Old", "value": "old"},
        {"name": "Data source", "value": "dataSource", "versions": [2]},
    ]
    assert version["operations"] == [
        {"value": "create", "name": "Create", "resource": "page"},
        {"value": "get", "name": "Get", "resource": "page", "versions": [2]},
    ]


def test_main_prints_the_catalogue_and_fails_on_a_pin_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    a_package(tmp_path, "n8n-nodes-base", {"jira": ("Jira", "this.helpers.request()")})
    a_package(tmp_path, "@n8n/n8n-nodes-langchain", {})
    defaults(tmp_path)
    path = tmp_path / "served.json"
    path.write_text(json.dumps(served()[:1]))

    assert main([str(path), PIN, str(tmp_path)]) == 0
    printed = capsys.readouterr()
    assert json.loads(printed.out)["blocks"]["n8n-nodes-base.jira"]["name"] == "Jira Software"

    (tmp_path / "n8n-nodes-base" / "dist" / "nodes" / "Jira" / "Shell.js").write_text(
        'require("child_process")'
    )
    assert main([str(path), PIN, str(tmp_path)]) == 1
    printed = capsys.readouterr()
    assert printed.out
    assert "pin check: n8n-nodes-base.jira reaches child_process" in printed.err


def defaults(root: Path) -> None:
    """The n8n defaults, the runner's config and the pins, as the images and the repo hold them."""
    sources_of_defaults(root)
    (root / PINS).write_text(json.dumps(TWO_PINS))


def test_main_fails_when_a_default_spike_p9_rests_on_moves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    a_package(tmp_path, "n8n-nodes-base", {"jira": ("Jira", "")})
    a_package(tmp_path, "@n8n/n8n-nodes-langchain", {})
    defaults(tmp_path)
    nodes = tmp_path / CONFIGS["nodes"]
    nodes.write_text(nodes.read_text().replace("blockDeprecated = true", "blockDeprecated = false"))
    path = tmp_path / "served.json"
    path.write_text(json.dumps(served()[:1]))

    assert main([str(path), PIN, str(tmp_path)]) == 1
    assert "N8N_DEPRECATED_NODES_BLOCK no longer defaults to on" in capsys.readouterr().err


def test_main_fails_when_the_runner_is_not_n8n_s_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    a_package(tmp_path, "n8n-nodes-base", {"jira": ("Jira", "")})
    a_package(tmp_path, "@n8n/n8n-nodes-langchain", {})
    defaults(tmp_path)
    pins = deepcopy(TWO_PINS)
    pins["n8n-runners"]["tag"] = "2.41.0"
    (tmp_path / PINS).write_text(json.dumps(pins))
    path = tmp_path / "served.json"
    path.write_text(json.dumps(served()[:1]))

    assert main([str(path), PIN, str(tmp_path)]) == 1
    assert "The runner must match n8n's version" in capsys.readouterr().err


def test_a_block_whose_code_the_check_did_not_read_fails(tmp_path: Path):
    a_package(tmp_path, "n8n-nodes-base", {"jira": ("Jira", "")})
    a_package(tmp_path, "@n8n/n8n-nodes-langchain", {})
    served = ["n8n-nodes-base.jira", "n8n-nodes-base.jiraTool", "n8n-nodes-base.newThing"]

    assert pin_problems(scan(tmp_path), [*served, "CUSTOM.wabRead"], []) == [
        "n8n serves n8n-nodes-base.newThing, whose code the pin check didn't read."
    ]


def test_a_block_that_runs_shell_commands_must_be_left_out_at_load_time():
    """The security review of step 12: a block that reaches child_process can run anything in
    n8n's container, so the pin check fails until NODES_EXCLUDE leaves it out."""
    found = Scan(
        blocks={
            "n8n-nodes-base.executeCommand": frozenset({"child_process"}),
            "n8n-nodes-base.shellNew": frozenset({"child_process"}),
        },
        shared={},
        imports=frozenset(),
    )
    said = pin_problems(found, ["n8n-nodes-base.executeCommand", "n8n-nodes-base.shellNew"], [])
    assert [p for p in said if "LEFT_OUT" in p] == [
        "n8n-nodes-base.shellNew reaches child_process, so it can run anything in n8n's container. "
        "Add it to LEFT_OUT in platform_api/orchestration/n8n_blocks.py, which NODES_EXCLUDE and "
        "bootstrap's check follow."
    ]
