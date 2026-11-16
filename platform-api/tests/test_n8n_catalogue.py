"""The catalogue of n8n's blocks (ADR 0051, section 8) and the pin check of their code (section 2),
on small cut-down copies of what n8n 2.42.6 serves and ships. scripts/pack-smoke.sh runs both on
the image itself."""

import json
from pathlib import Path
from typing import Any

import pytest

from platform_api.n8n_catalogue import KNOWN, catalogue, dump, main, pin_problems, reaches

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
            "name": "n8n-nodes-base.git",
            "displayName": "Git",
            "description": "Control git.",
            "version": 1,
            "hidden": True,
            "properties": [],
        },
        {
            "name": "n8n-nodes-base.gitTool",
            "displayName": "Git Tool",
            "description": "Control git.",
            "version": 1,
            "properties": [],
        },
        {"name": "n8n-nodes-base.executeCommand", "version": 1, "properties": []},
        {"name": "@n8n/mcp-registry.airtable", "version": [1, 1.1], "properties": []},
        {
            "name": "@n8n/n8n-nodes-langchain.mcpRegistryClientTool",
            "version": [1, 1.1],
            "properties": [],
        },
    ]


OWN = {"n8n-nodes-base.jira", "n8n-nodes-base.merge", "n8n-nodes-base.git"}


@pytest.fixture
def made() -> Json:
    return catalogue(served(), PIN, OWN)


def test_it_holds_what_the_image_ships_and_our_blocks_and_leaves_out_the_rest(made: Json):
    assert made["image"] == PIN
    assert sorted(made["blocks"]) == [
        "CUSTOM.wabRead",
        "n8n-nodes-base.git",
        "n8n-nodes-base.gitTool",
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
    assert merge["held"] == [
        {"because": "It runs code.", "waits_for": "spike P9", "when": {"mode": ["combineBySql"]}}
    ]


def test_a_held_block_and_the_tool_made_of_it_are_both_marked(made: Json):
    disk = [{"because": "It reads or writes a path on n8n's disk.", "waits_for": "spike P9"}]

    assert made["blocks"]["n8n-nodes-base.git"]["held"] == disk
    assert made["blocks"]["n8n-nodes-base.git"]["hidden"] is True
    assert made["blocks"]["n8n-nodes-base.gitTool"]["held"] == disk
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


def a_package(root: Path, package: str, blocks: dict[str, tuple[str, str]]) -> None:
    """Writes a package as the image holds it: its list of blocks, and each block's code."""
    known = {}
    for short, (folder, code) in blocks.items():
        source = f"dist/nodes/{folder}/{short}.node.js"
        known[short] = {"className": short, "sourcePath": source}
        (root / package / source).parent.mkdir(parents=True, exist_ok=True)
        (root / package / source).write_text(code)
    (root / package / "dist" / "known").mkdir(parents=True, exist_ok=True)
    (root / package / "dist" / "known" / "nodes.json").write_text(json.dumps(known))


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    a_package(
        tmp_path,
        "n8n-nodes-base",
        {
            "webhook": ("Webhook", 'const fs_1 = require("fs");'),
            "mautic": ("Mautic", "displayName: 'Sandbox', isSandbox, enableSandbox"),
            "sort": ("Sort", 'require("../Code/JsTaskRunnerSandbox")'),
            "jira": ("Jira", "this.helpers.request()"),
        },
    )
    a_package(
        tmp_path,
        "@n8n/n8n-nodes-langchain",
        {"toolWorkflow": ("tools/ToolWorkflow", "await this.executeWorkflow(info, items)")},
    )
    return tmp_path


def test_the_pin_check_reads_what_each_block_s_code_reaches(sources: Path):
    assert reaches(sources) == {
        "n8n-nodes-base.webhook": {"fs"},
        "n8n-nodes-base.mautic": set(),
        "n8n-nodes-base.sort": {"code sandbox"},
        "n8n-nodes-base.jira": set(),
        "@n8n/n8n-nodes-langchain.toolWorkflow": {"another workflow"},
    }


def test_the_pin_check_passes_what_section_2_names(sources: Path):
    served = ["n8n-nodes-base.webhook", "n8n-nodes-base.jira", "n8n-nodes-base.jiraTool"]

    assert pin_problems(reaches(sources), [*served, "CUSTOM.wabRead"]) == []


@pytest.mark.parametrize(
    ("short", "code", "reached"),
    [
        ("webhook", 'require("node:child_process").exec(command)', "child_process"),
        ("jira", "const url = process.env.JIRA_URL", "process.env"),
        ("jira", "await this.helpers.writeContentToFile(path, data)", "file helpers"),
        ("jira", 'const vm = require("vm2")', "code sandbox"),
        ("jira", "new JavaScriptSandbox(context, code)", "code sandbox"),
        ("jira", "await this.helpers.executeWorkflow(info)", "another workflow"),
        ("jira", 'import { readFile } from "node:fs/promises"', "fs"),
    ],
)
def test_the_pin_check_fails_on_a_block_reaching_what_section_2_does_not_name_for_it(
    sources: Path, short: str, code: str, reached: str
):
    folder = "Jira" if short == "jira" else "Webhook"
    (sources / "n8n-nodes-base" / "dist" / "nodes" / folder / "Helpers.js").write_text(code)

    (problem,) = pin_problems(reaches(sources), [])

    assert problem.startswith(f"n8n-nodes-base.{short} reaches {reached}, which ADR 0051")


def test_a_block_whose_code_the_check_did_not_read_fails(sources: Path):
    assert pin_problems(reaches(sources), ["n8n-nodes-base.newThing"]) == [
        "n8n serves n8n-nodes-base.newThing, whose code the pin check didn't read."
    ]


def test_every_block_section_2_names_reaches_something():
    assert all(KNOWN.values())


def test_main_prints_the_catalogue_and_fails_on_a_pin_problem(
    sources: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    path = tmp_path / "served.json"
    path.write_text(json.dumps(served()[:1]))

    assert main([str(path), PIN, str(sources)]) == 0
    printed = capsys.readouterr()
    assert json.loads(printed.out)["blocks"]["n8n-nodes-base.jira"]["name"] == "Jira Software"

    (sources / "n8n-nodes-base" / "dist" / "nodes" / "Jira" / "Shell.js").write_text(
        'require("child_process")'
    )
    assert main([str(path), PIN, str(sources)]) == 1
    printed = capsys.readouterr()
    assert printed.out
    assert "pin check: n8n-nodes-base.jira reaches child_process" in printed.err
