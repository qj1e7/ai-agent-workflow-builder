"""The class file (ADR 0045): what n8n is allowed to load, what the file may say, and the pin check
that keeps it complete against the node types the pinned image serves."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from platform_api.orchestration.n8n_schedule import SCHEDULE_TRIGGER
from platform_api.orchestration.node_classes import CLASS_FILE, NODE_CLASSES, NodeClasses, Off
from platform_api.orchestration.workflow_check import TYPE_OF
from platform_api.pin_check import main as pin_check
from tests.support import FIXTURES

SERVED = Path(__file__).parent / "golden" / "n8n" / "served_types.json"
"""What n8n 2.42.6 serves at /types/nodes.json with the allow list on, cut down to each type's
name, versions and the parameters that pick what it does. scripts/pack-smoke.sh checks the
image itself."""
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


def test_n8n_loads_our_pack_n8n_s_triggers_and_flow_nodes_and_its_data_nodes_and_nothing_off():
    included = set(NODE_CLASSES.included())
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
    assert len(included) == 31


def test_n8n_also_loads_the_ai_tool_it_makes_from_date_and_time_which_is_off():
    """n8n makes a tool of each node marked usable by an AI agent after NODES_INCLUDE has picked
    the nodes, so the list cannot leave it out. It has no main input, and AI agents are off."""
    tool = "n8n-nodes-base.dateTimeTool"
    assert set(NODE_CLASSES.loaded()) - set(NODE_CLASSES.included()) == {tool}
    assert isinstance(NODE_CLASSES.verdict(tool, 2, {}), Off)


def test_the_schedule_block_is_the_type_the_schedule_reader_knows():
    assert TYPE_OF["schedule"] == SCHEDULE_TRIGGER


def test_the_pin_check_passes_on_what_the_pinned_image_serves():
    assert NODE_CLASSES.unclassed(served()) == []


def drop_operation(raw: Raw) -> None:
    del raw["n8n-nodes-base.dateTime"]["rows"][0]["operations"]["addToDate"]


def drop_type(raw: Raw) -> None:
    del raw["n8n-nodes-base.limit"]


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


def drop_the_made_tool(raw: Raw) -> None:
    del raw["n8n-nodes-base.dateTimeTool"]


def whole_where_n8n_picks(raw: Raw) -> None:
    raw["n8n-nodes-base.dateTime"]["rows"][0] = {"versions": [2], "class": "read"}


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (drop_operation, "n8n-nodes-base.dateTime version 2 can addToDate, which the class"),
        (drop_type, "n8n loads n8n-nodes-base.limit, which the class file does not turn on."),
        (drop_version, "n8n-nodes-base.if version 2.3 is not classed."),
        (drop_our_block, "n8n loads CUSTOM.wabTell, which the class file does not turn on."),
        (add_version, "classes n8n-nodes-base.noOp version 2, which n8n does not load."),
        (add_operation, "classes n8n-nodes-base.executionData version 1 delete, which n8n"),
        (change_default, "n8n's default for n8n-nodes-base.merge version 3 is append, not combine"),
        (
            whole_where_n8n_picks,
            "n8n-nodes-base.dateTime version 2 picks what it does by operation",
        ),
        (drop_the_made_tool, "n8n loads n8n-nodes-base.dateTimeTool, which the class file"),
    ],
    ids=[
        "an-operation",
        "a-type",
        "a-version",
        "one-of-ours",
        "a-version-n8n-lacks",
        "an-operation-n8n-lacks",
        "a-default",
        "a-whole-class",
        "a-type-n8n-makes",
    ],
)
def test_the_pin_check_fails_when_the_file_and_the_image_disagree(
    change: Callable[[Raw], None], says: str, tmp_path: Path
):
    raw = the_file()
    change(raw)
    problems = classes_from(raw, tmp_path).unclassed(served())
    assert any(says in problem for problem in problems), problems


def test_the_pin_check_names_a_type_n8n_loads_that_the_file_turns_off():
    """As when n8n runs without the allow list."""
    leaky = [*served(), {"name": "n8n-nodes-base.httpRequest", "version": 4.2, "properties": []}]
    assert NODE_CLASSES.unclassed(leaky) == [
        "n8n loads n8n-nodes-base.httpRequest, which the class file does not turn on."
    ]


def test_the_pin_check_names_a_made_type_n8n_no_longer_makes():
    gone = [d for d in served() if d["name"] != "n8n-nodes-base.dateTimeTool"]
    assert NODE_CLASSES.unclassed(gone) == [
        "The class file says n8n makes n8n-nodes-base.dateTimeTool, which n8n does not load."
    ]


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


def made_from_an_off_type(raw: Raw) -> None:
    raw["n8n-nodes-base.dateTimeTool"]["loaded_with"] = "n8n-nodes-base.sort"


def default_unclassed(raw: Raw) -> None:
    raw["n8n-nodes-base.executionData"]["rows"][0]["default"] = "load"


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
        made_from_an_off_type,
    ],
)
def test_the_file_may_not_break_a_safety_rule(change: Callable[[Raw], None], tmp_path: Path):
    """A row that breaks one fails every test and every start, so it cannot reach n8n."""
    raw = the_file()
    change(raw)
    with pytest.raises(ValueError):
        classes_from(raw, tmp_path)
