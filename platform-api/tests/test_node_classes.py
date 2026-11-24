"""The class file (ADR 0045): what each block it knows may do, what the file may say, and the pin
check that keeps each of its rows true to the node types the pinned image serves. n8n loads every
built-in block (ADR 0051), so the file no longer decides what n8n loads."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from platform_api.orchestration.n8n_schedule import SCHEDULE_TRIGGER
from platform_api.orchestration.node_classes import (
    CLASS_FILE,
    NODE_CLASSES,
    NodeClasses,
    Off,
    Runs,
)
from platform_api.orchestration.workflow_check import TYPE_OF
from platform_api.pin_check import main as pin_check
from tests.support import FIXTURES

SERVED = Path(__file__).parent / "golden" / "n8n" / "served_types.json"
"""What n8n 2.42.6 serves at /types/nodes.json, cut down to the types the class file names, each
with its name, versions and the parameters that pick what it does. scripts/pack-smoke.sh checks
the image itself."""
PACK = FIXTURES.parent / "n8n" / "node-types.json"
OFF = {
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.code",
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.wait",
    "n8n-nodes-base.executeWorkflow",
    "n8n-nodes-base.respondToWebhook",
    "n8n-nodes-base.sort",
    "n8n-nodes-base.itemLists",
}

type Raw = dict[str, Any]


def served() -> list[Raw]:
    return json.loads(SERVED.read_text())


def the_file() -> Raw:
    return json.loads(CLASS_FILE.read_text())


def classes_from(raw: Raw, tmp_path: Path) -> NodeClasses:
    path = tmp_path / "node_classes.json"
    path.write_text(json.dumps(raw))
    return NodeClasses.read(path)


def test_the_file_classes_our_pack_n8n_s_triggers_flow_and_data_nodes_and_names_the_rest_off():
    included = set(NODE_CLASSES.blocks())
    pack = {entry["type"] for entry in json.loads(PACK.read_text())["nodes"]}
    assert {t for t in included if t.startswith("CUSTOM.")} == pack
    assert {
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.manualTrigger",
        "n8n-nodes-base.errorTrigger",
        "n8n-nodes-base.if",
        "n8n-nodes-base.merge",
        "n8n-nodes-base.noOp",
        "n8n-nodes-base.stickyNote",
    } < included
    assert not OFF & included
    assert set(the_file()) > OFF, "each is named off, with why"
    assert included > SYSTEMS
    assert len(included) == 37


SYSTEMS = {
    f"n8n-nodes-base.{name}"
    for name in ("jira", "github", "microsoftTeams", "microsoftOutlook", "gmail", "slack")
}
"""n8n's own nodes for outside systems that may read or post a notice (ADR 0045, E16)."""


def test_the_ai_tools_n8n_makes_of_the_classed_blocks_are_each_off():
    """n8n makes a tool of each block marked usable by an AI agent. AI agents are off (ADR 0023),
    so the file names each tool off."""
    made = {name for name in the_file() if name.endswith("Tool")}
    hitl = {f"{name}HitlTool" for name in SYSTEMS if "jira" not in name and "github" not in name}
    tools = {f"{name}Tool" for name in SYSTEMS}
    assert made == {"n8n-nodes-base.dateTimeTool", *tools, *hitl}
    for tool in made:
        assert isinstance(NODE_CLASSES.verdict(tool, 2, {}), Off)


@pytest.mark.parametrize(
    ("node_type", "version", "parameters", "on"),
    [
        ("jira", 1, {"operation": "getAll"}, "read"),
        ("jira", 1, {"resource": "issueComment", "operation": "getAll"}, "read"),
        ("github", 1.1, {"resource": "release", "operation": "getAll"}, "read"),
        ("github", 1, {"resource": "repository"}, "read"),
        ("slack", 2.7, {}, "notice"),
        ("slack", 2, {"resource": "message", "operation": "post"}, "notice"),
        ("microsoftTeams", 2, {"resource": "channelMessage", "operation": "create"}, "notice"),
        ("microsoftOutlook", 2, {"operation": "send"}, "notice"),
        ("gmail", 2.2, {"resource": "message", "operation": "send"}, "notice"),
    ],
)
def test_a_system_block_runs_for_what_its_row_classes(
    node_type: str, version: float, parameters: dict[str, Any], on: str
):
    verdict = NODE_CLASSES.verdict(f"n8n-nodes-base.{node_type}", version, parameters)
    assert isinstance(verdict, Runs) and verdict.on == on
    assert verdict.use is not None and verdict.use.approvers_min == 1


@pytest.mark.parametrize(
    ("node_type", "version", "parameters", "off"),
    [
        ("jira", 1, {}, Off("operation", "issue create")),
        ("jira", 1, {"operation": "update"}, Off("operation", "issue update")),
        ("jira", 1, {"resource": "issueComment"}, Off("operation", "issueComment add")),
        ("jira", 1, {"resource": "user", "operation": "delete"}, Off("operation", "user delete")),
        ("jira", 1, {"operation": "={{ $json.op }}"}, Off("expression", "={{ $json.op }}")),
        (
            "jira",
            1,
            {"resource": "={{ 'issue' }}", "operation": "get"},
            Off("expression", "={{ 'issue' }}"),
        ),
        ("jira", 1, {"resource": "sprint", "operation": "get"}, Off("operation", "sprint")),
        ("github", 1, {}, Off("operation", "issue create")),
        (
            "github",
            1,
            {"resource": "workflow", "operation": "dispatch"},
            Off("operation", "workflow dispatch"),
        ),
        ("slack", 2.7, {"operation": "update"}, Off("operation", "message update")),
        ("slack", 2.7, {"operation": "sendAndWait"}, Off("operation", "message sendAndWait")),
        (
            "slack",
            2.7,
            {"resource": "channel", "operation": "archive"},
            Off("operation", "channel archive"),
        ),
        ("slack", 1, {}, Off("version", "1")),
        ("microsoftTeams", 2, {}, Off("operation", "channel create")),
        ("microsoftTeams", 1.1, {"resource": "channelMessage"}, Off("version", "1.1")),
        ("microsoftOutlook", 2, {"operation": "delete"}, Off("operation", "message delete")),
        ("gmail", 2.1, {"operation": "reply"}, Off("operation", "message reply")),
        ("jira", 1, {"resource": "__CUSTOM_API_CALL__"}, Off("operation", "__CUSTOM_API_CALL__")),
        (
            "github",
            1,
            {"resource": "release", "operation": "__CUSTOM_API_CALL__"},
            Off("operation", "release __CUSTOM_API_CALL__"),
        ),
    ],
)
def test_a_system_block_is_off_for_anything_else(
    node_type: str, version: float, parameters: dict[str, Any], off: Off
):
    """A write on a node classed for reads, or anything its row leaves off, is off, and so is an
    expression where it picks what it does, which could pick a write when it runs."""
    assert NODE_CLASSES.verdict(f"n8n-nodes-base.{node_type}", version, parameters) == off


def test_the_schedule_block_is_the_type_the_schedule_reader_knows():
    assert TYPE_OF["schedule"] == SCHEDULE_TRIGGER


def test_the_pin_check_passes_on_what_the_pinned_image_serves():
    assert NODE_CLASSES.unclassed(served()) == []


def drop_operation(raw: Raw) -> None:
    del raw["n8n-nodes-base.dateTime"]["rows"][0]["operations"]["addToDate"]


def drop_version(raw: Raw) -> None:
    raw["n8n-nodes-base.if"]["rows"][0]["versions"].remove(2.3)


def drop_our_block(raw: Raw) -> None:
    del raw["CUSTOM.wabTell"]


def add_version(raw: Raw) -> None:
    raw["n8n-nodes-base.noOp"]["rows"][0]["versions"].append(2)


def add_operation(raw: Raw) -> None:
    raw["n8n-nodes-base.executionData"]["rows"][0]["operations"]["delete"] = "read"


def change_default(raw: Raw) -> None:
    raw["n8n-nodes-base.merge"]["rows"][0]["default"] = "combine"


def whole_where_n8n_picks(raw: Raw) -> None:
    raw["n8n-nodes-base.dateTime"]["rows"][0] = {"versions": [2], "class": "read"}


def drop_a_resource_operation(raw: Raw) -> None:
    del raw["n8n-nodes-base.jira"]["rows"][0]["resources"]["issue"]["operations"]["notify"]


def drop_a_resource(raw: Raw) -> None:
    del raw["n8n-nodes-base.slack"]["rows"][0]["resources"]["star"]


def change_a_resource_default(raw: Raw) -> None:
    raw["n8n-nodes-base.slack"]["rows"][0]["resources"]["message"]["default"] = "delete"


def by_operation_only(raw: Raw) -> None:
    row = raw["n8n-nodes-base.gmail"]["rows"][0]
    message = row.pop("resources")["message"]
    row.update(by="operation", default=message["default"], operations=message["operations"])


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (drop_operation, "n8n-nodes-base.dateTime version 2 can addToDate, which the class"),
        (drop_version, "n8n-nodes-base.if version 2.3 is not classed."),
        (drop_our_block, "n8n loads CUSTOM.wabTell, one of our blocks, which the class file"),
        (add_version, "classes n8n-nodes-base.noOp version 2, which n8n does not load."),
        (add_operation, "classes n8n-nodes-base.executionData version 1 delete, which n8n"),
        (change_default, "n8n's default for n8n-nodes-base.merge version 3 is append, not combine"),
        (
            whole_where_n8n_picks,
            "n8n-nodes-base.dateTime version 2 picks what it does by operation",
        ),
        (drop_a_resource_operation, "n8n-nodes-base.jira version 1 issue can notify, which"),
        (drop_a_resource, "n8n-nodes-base.slack version 2.7 can star, which the class"),
        (change_a_resource_default, "n8n's default for n8n-nodes-base.slack version 2 message"),
        (by_operation_only, "n8n-nodes-base.gmail version 2.2 picks what it does by resource"),
    ],
    ids=[
        "an-operation",
        "a-version",
        "one-of-ours",
        "a-version-n8n-lacks",
        "an-operation-n8n-lacks",
        "a-default",
        "a-whole-class",
        "a-resource-s-operation",
        "a-resource",
        "a-resource-s-default",
        "an-operation-without-its-resource",
    ],
)
def test_the_pin_check_fails_when_the_file_and_the_image_disagree(
    change: Callable[[Raw], None], says: str, tmp_path: Path
):
    raw = the_file()
    change(raw)
    problems = classes_from(raw, tmp_path).unclassed(served())
    assert any(says in problem for problem in problems), problems


def test_the_pin_check_asks_for_no_row_for_a_type_the_file_does_not_name(tmp_path: Path):
    """n8n loads every built-in block (ADR 0051), and the checker flags each one the file
    doesn't class, so only the file's own rows must match the image."""
    newer = [*served(), {"name": "n8n-nodes-base.airtable", "version": [1, 2], "properties": []}]
    assert NODE_CLASSES.unclassed(newer) == []
    raw = the_file()
    raw.pop("n8n-nodes-base.limit")
    assert classes_from(raw, tmp_path).unclassed(served()) == []


@pytest.mark.parametrize(
    "gone", ["n8n-nodes-base.dateTimeTool", "n8n-nodes-base.httpRequest", "n8n-nodes-base.limit"]
)
def test_the_pin_check_names_a_type_the_file_names_that_n8n_no_longer_loads(gone: str):
    left = [d for d in served() if d["name"] != gone]
    assert any(
        f"The class file names {gone}, which n8n does not load." in problem
        or f"The class file classes {gone} version" in problem
        for problem in NODE_CLASSES.unclassed(left)
    ), NODE_CLASSES.unclassed(left)


def test_the_pin_check_names_an_operation_a_new_image_adds(tmp_path: Path):
    newer = served()
    [save] = [d for d in newer if d["name"] == "n8n-nodes-base.executionData"]
    save["properties"][0]["options"].append({"value": "export"})
    assert NODE_CLASSES.unclassed(newer) == [
        "n8n-nodes-base.executionData version 1 can export, which the class file does not class.",
        "n8n-nodes-base.executionData version 1.1 can export, which the class file does not class.",
    ]


def test_the_pin_check_command_fails_on_an_unclassed_operation_and_passes_on_the_image(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    assert pin_check([str(SERVED)]) == 0
    newer = served()
    [dated] = [d for d in newer if d["name"] == "n8n-nodes-base.dateTime" and d["version"] == 2]
    dated["properties"][0]["options"].append({"value": "travelInTime"})
    path = tmp_path / "nodes.json"
    path.write_text(json.dumps(newer))
    assert pin_check([str(path)]) == 1
    assert "can travelInTime" in capsys.readouterr().err


def n8n_writes(raw: Raw) -> None:
    raw["n8n-nodes-base.limit"]["rows"][0]["class"] = "write"


def n8n_notices(raw: Raw) -> None:
    raw["n8n-nodes-base.limit"]["rows"][0]["class"] = "notice"


def another_writer(raw: Raw) -> None:
    raw["CUSTOM.wabTell"]["rows"][0]["class"] = "write"


def make_only_reads(raw: Raw) -> None:
    raw["CUSTOM.wabMakeApprovedChanges"]["rows"][0]["class"] = "read"


def on_but_all_off(raw: Raw) -> None:
    raw["n8n-nodes-base.limit"]["rows"][0]["class"] = "off"


def two_ifs(raw: Raw) -> None:
    raw["n8n-nodes-base.filter"]["block"] = "branch"


def both_ways(raw: Raw) -> None:
    raw["n8n-nodes-base.limit"]["rows"][0]["by"] = "operation"


def twice(raw: Raw) -> None:
    raw["n8n-nodes-base.if"]["rows"].append({"versions": [1], "class": "read"})


def says_what_n8n_loads(raw: Raw) -> None:
    """The file no longer decides what n8n loads (ADR 0051), so it has no field for it."""
    raw["n8n-nodes-base.dateTimeTool"]["loaded_with"] = "n8n-nodes-base.dateTime"


def default_unclassed(raw: Raw) -> None:
    raw["n8n-nodes-base.executionData"]["rows"][0]["default"] = "load"


def slack_writes(raw: Raw) -> None:
    raw["n8n-nodes-base.slack"]["rows"][0]["resources"]["message"]["operations"]["update"] = "write"


def a_notice_without_its_place(raw: Raw) -> None:
    raw["n8n-nodes-base.slack"]["rows"][0]["target"] = []


def a_notice_without_its_text(raw: Raw) -> None:
    """The checker reads every word a notice says, so a notice row names where its words are."""
    raw["n8n-nodes-base.microsoftTeams"]["rows"][0]["text"] = []


def reads_and_notices_in_one_row(raw: Raw) -> None:
    raw["n8n-nodes-base.slack"]["rows"][0]["resources"]["message"]["operations"]["search"] = "read"


def a_system_block_that_says_nothing(raw: Raw) -> None:
    row = raw["n8n-nodes-base.jira"]["rows"][0]
    for name in ("tag", "says", "target", "approvers_min"):
        del row[name]


def a_tag_without_the_rest(raw: Raw) -> None:
    del raw["n8n-nodes-base.github"]["rows"][0]["says"]


def a_shape_that_says(raw: Raw) -> None:
    raw["n8n-nodes-base.limit"]["rows"][0].update(
        tag="Posts", says="Posts", target=["x"], approvers_min=1
    )


def three_approvers(raw: Raw) -> None:
    raw["n8n-nodes-base.jira"]["rows"][0]["approvers_min"] = 3


def a_resource_default_unclassed(raw: Raw) -> None:
    raw["n8n-nodes-base.jira"]["rows"][0]["default"] = "sprint"


def picked_by_three(raw: Raw) -> None:
    raw["n8n-nodes-base.jira"]["rows"][0]["by"] = ["resource", "mode"]


def a_system_block_no_simulation_stands_in_for(raw: Raw) -> None:
    """A simulation must know whether a mock stands in for it or its output is pinned (ADR
    0054)."""
    del raw["n8n-nodes-base.jira"]["simulated"]


def a_shape_with_a_mock(raw: Raw) -> None:
    raw["n8n-nodes-base.limit"]["simulated"] = {"mock": "github"}


def a_mock_nobody_built(raw: Raw) -> None:
    raw["n8n-nodes-base.microsoftTeams"]["simulated"] = {"mock": "teams"}


def a_mock_and_a_pin(raw: Raw) -> None:
    raw["n8n-nodes-base.github"]["simulated"] = {"mock": "github", "pinned": "Both."}


def a_pin_without_why(raw: Raw) -> None:
    raw["n8n-nodes-base.gmail"]["simulated"] = {"pinned": ""}


@pytest.mark.parametrize(
    "change",
    [
        n8n_writes,
        n8n_notices,
        another_writer,
        make_only_reads,
        on_but_all_off,
        two_ifs,
        both_ways,
        twice,
        default_unclassed,
        says_what_n8n_loads,
        slack_writes,
        a_notice_without_its_place,
        a_notice_without_its_text,
        reads_and_notices_in_one_row,
        a_system_block_that_says_nothing,
        a_tag_without_the_rest,
        a_shape_that_says,
        three_approvers,
        a_resource_default_unclassed,
        picked_by_three,
        a_system_block_no_simulation_stands_in_for,
        a_shape_with_a_mock,
        a_mock_nobody_built,
        a_mock_and_a_pin,
        a_pin_without_why,
    ],
)
def test_the_file_may_not_break_a_safety_rule(change: Callable[[Raw], None], tmp_path: Path):
    """A row that breaks one fails every test and every start, so it cannot reach n8n."""
    raw = the_file()
    change(raw)
    with pytest.raises(ValueError):
        classes_from(raw, tmp_path)
