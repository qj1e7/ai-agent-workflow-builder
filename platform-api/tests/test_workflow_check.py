"""The safety checker's grade for a workflow in n8n, on the sketch's cases (safe, gate removed,
unknown node, no trigger) and on each of its rules (ENGINE-PLAN 2.4)."""

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from platform_api.orchestration import (
    ASK_EXITS,
    NODE_TYPES,
    KnownOptions,
    add_yes,
    grade,
)
from platform_api.orchestration.workflow_check import ERROR_WORKFLOW as ERROR_WORKFLOW_NAME
from platform_api.orchestration.workflow_check import (
    PLATFORM_SHAPES,
    PLATFORM_WORKFLOWS_DIR,
    SELF_TEST,
    check_platform,
)
from tests.support import FIXTURES, TEAM_ZONE

GOLDEN = Path(__file__).parent / "golden" / "n8n"
PACK = FIXTURES.parent / "n8n" / "node-types.json"
"""The node pack's types, as the pack's own test keeps contracts/ in step with it."""
ERROR_WORKFLOW = "wfErrorReporter01"

type Doc = dict[str, Any]


def release_check() -> Doc:
    return json.loads((GOLDEN / "release_check.json").read_text())


def node(document: Doc, name: str) -> dict[str, Any]:
    return next(n for n in document["nodes"] if n["name"] == name)


def without(document: Doc, *names: str) -> Doc:
    document["nodes"] = [n for n in document["nodes"] if n["name"] not in names]
    for name in names:
        document["connections"].pop(name, None)
    for outputs in document["connections"].values():
        outputs["main"] = [
            [t for t in targets if t["node"] not in names] for targets in outputs["main"]
        ]
    return document


def link(document: Doc, source: str, target: str, exit_index: int = 0) -> Doc:
    outputs = document["connections"].setdefault(source, {"main": []})["main"]
    while len(outputs) <= exit_index:
        outputs.append([])
    outputs[exit_index].append({"node": target, "type": "main", "index": 0})
    return document


def with_block(
    document: Doc,
    block_type: str,
    name: str = "Extra",
    after: str = "Compare",
    version: object = 1,
    parameters: dict[str, Any] | None = None,
) -> Doc:
    document["nodes"].append(
        {
            "id": "x",
            "name": name,
            "type": block_type,
            "typeVersion": version,
            "parameters": parameters or {},
        }
    )
    return link(document, after, name)


def gate_removed() -> Doc:
    return link(without(release_check(), "Ask for a yes"), "Newer?", "Create ticket")


def graded(document: Doc) -> str:
    return grade(document, ERROR_WORKFLOW, TEAM_ZONE).grade


def findings(document: Doc) -> list[str]:
    return [f.text for f in grade(document, ERROR_WORKFLOW, TEAM_ZONE).findings]


def test_the_release_check_as_the_platform_saves_it_is_safe() -> None:
    assert grade(release_check(), ERROR_WORKFLOW, TEAM_ZONE).findings == ()


def test_a_write_with_its_gate_removed_never_grades_safe() -> None:
    result = grade(gate_removed(), ERROR_WORKFLOW, TEAM_ZONE)
    assert result.grade == "writes_refused"
    assert [f.block for f in result.findings] == ["Create ticket"]


@pytest.mark.parametrize("exit_name", ["No answer", "No", "Nothing to change"])
def test_a_write_after_any_exit_but_yes_has_no_yes(exit_name: str) -> None:
    document = release_check()
    link(document, "Ask for a yes", "Create ticket", ASK_EXITS.index(exit_name))
    assert graded(document) == "writes_refused"


def test_a_write_reached_by_a_second_path_around_the_yes_has_no_yes() -> None:
    document = link(release_check(), "Compare", "Create ticket")
    assert graded(document) == "writes_refused"


def test_a_second_yes_on_one_path_needs_a_fix() -> None:
    document = release_check()
    document["nodes"].append(
        {
            "id": "y",
            "name": "Ask again",
            "type": "CUSTOM.wabAskForYes",
            "typeVersion": 1,
            "parameters": {},
        }
    )
    link(without(document, "Create ticket"), "Ask for a yes", "Ask again", 1)
    assert graded(document) == "needs_a_fix"


@pytest.mark.parametrize(
    "block_type",
    [
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.jira",
        "wab.read",
        "",
    ],
)
def test_a_block_that_is_not_on_the_allow_list_needs_a_fix(block_type: str) -> None:
    assert graded(with_block(release_check(), block_type)) == "needs_a_fix"


DATA_NODES = {
    "Filter": ("n8n-nodes-base.filter", 2.3),
    "Switch": ("n8n-nodes-base.switch", 3.4),
    "Edit Fields": ("n8n-nodes-base.set", 3.5),
    "Limit": ("n8n-nodes-base.limit", 1),
    "Aggregate": ("n8n-nodes-base.aggregate", 1),
    "Split Out": ("n8n-nodes-base.splitOut", 1),
    "Remove Duplicates": ("n8n-nodes-base.removeDuplicates", 2),
    "Summarize": ("n8n-nodes-base.summarize", 1.1),
    "Rename Keys": ("n8n-nodes-base.renameKeys", 1),
    "Date & Time": ("n8n-nodes-base.dateTime", 2),
    "Compare Datasets": ("n8n-nodes-base.compareDatasets", 2.3),
    "Loop Over Items": ("n8n-nodes-base.splitInBatches", 3),
    "XML": ("n8n-nodes-base.xml", 1),
    "Markdown": ("n8n-nodes-base.markdown", 1),
    "Execution Data": ("n8n-nodes-base.executionData", 1.1),
    "Stop and Error": ("n8n-nodes-base.stopAndError", 1),
}
"""P7 Q10's data nodes, which only reshape items, at their newest version in the pinned n8n."""


@pytest.mark.parametrize(("block_type", "version"), DATA_NODES.values(), ids=list(DATA_NODES))
def test_each_of_n8n_s_data_nodes_is_on(block_type: str, version: float) -> None:
    shaped = with_block(release_check(), block_type, "Shape it", version=version)
    assert findings(shaped) == []


@pytest.mark.parametrize(
    "block_type",
    [
        "n8n-nodes-base.sort",
        "n8n-nodes-base.itemLists",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.wait",
        "n8n-nodes-base.executeWorkflow",
        "n8n-nodes-base.respondToWebhook",
    ],
)
def test_sort_and_every_block_that_can_reach_out_or_run_code_is_off(block_type: str) -> None:
    assert findings(with_block(release_check(), block_type, "Off")) == [
        f'"Off" uses a block that is off: {block_type}.'
    ]


@pytest.mark.parametrize(
    ("version", "parameters", "says"),
    [
        (9, {}, '"Date" uses version 9 of n8n-nodes-base.dateTime, which is off.'),
        (None, {}, '"Date" uses version None of n8n-nodes-base.dateTime, which is off.'),
        ("2", {}, '"Date" uses version 2 of n8n-nodes-base.dateTime, which is off.'),
        (1, {}, '"Date" uses version 1 of n8n-nodes-base.dateTime, which is off.'),
        (2, {"operation": "teleport"}, '"Date" does something that is off: teleport.'),
        (2, {"operation": 3}, '"Date" does something that is off: 3.'),
    ],
    ids=["unknown-version", "no-version", "version-as-text", "version-off", "unknown", "no-text"],
)
def test_an_unknown_version_or_operation_is_off(
    version: object, parameters: dict[str, Any], says: str
) -> None:
    dated = with_block(
        release_check(), "n8n-nodes-base.dateTime", "Date", version=version, parameters=parameters
    )
    assert findings(dated) == [says]


def test_an_operation_classed_off_is_off_and_the_default_is_the_one_n8n_runs() -> None:
    kept = with_block(release_check(), "n8n-nodes-base.removeDuplicates", "Dedupe", version=2)
    assert findings(kept) == [], "it removes duplicate items, n8n's default"
    node(kept, "Dedupe")["parameters"] = {"operation": "clearDeduplicationHistory"}
    assert findings(kept) == ['"Dedupe" does something that is off: clearDeduplicationHistory.']


@pytest.mark.parametrize(
    ("block_type", "version", "parameters"),
    [
        ("n8n-nodes-base.dateTime", 2, {"operation": "={{ 'formatDate' }}"}),
        ("n8n-nodes-base.dateTime", 2, {"operation": "=getCurrentDate"}),
        ("n8n-nodes-base.merge", 3.2, {"mode": "={{ $json.mode }}"}),
    ],
    ids=["date-and-time", "a-plain-expression", "merge"],
)
def test_an_expression_in_what_a_block_does_is_off(
    block_type: str, version: float, parameters: dict[str, Any]
) -> None:
    """It could pick anything when it runs, a mode the file turns off among them."""
    picked = with_block(
        release_check(), block_type, "Picked", version=version, parameters=parameters
    )
    assert findings(picked) == ['"Picked" picks what it does with an expression, so it is off.']


def test_a_workflow_that_nothing_starts_needs_a_fix() -> None:
    document = without(release_check(), "Daily 8:00", "Start from the Portal")
    assert graded(document) == "needs_a_fix"


def test_a_manual_trigger_alone_does_not_start_a_platform_run() -> None:
    document = without(release_check(), "Daily 8:00", "Start from the Portal")
    with_block(document, "n8n-nodes-base.manualTrigger", "Run by hand", after="Run by hand")
    assert graded(link(document, "Run by hand", "Read release")) == "needs_a_fix"


def test_a_write_reached_from_a_manual_trigger_needs_its_yes_too() -> None:
    document = release_check()
    document["nodes"].append(
        {"id": "m", "name": "Run by hand", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1}
    )
    assert graded(link(document, "Run by hand", "Create ticket")) == "writes_refused"


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(errorWorkflow="someone else's"),
        lambda s: s.pop("errorWorkflow"),
        lambda s: s.update(timezone="UTC"),
        lambda s: s.update(saveExecutionProgress=False),
        lambda s: s.pop("saveManualExecutions"),
    ],
)
def test_settings_the_run_link_and_the_error_workflow_rely_on(
    change: Callable[[dict[str, Any]], object],
) -> None:
    document = release_check()
    change(document["settings"])
    assert graded(document) == "needs_a_fix"


def test_a_workflow_runs_on_the_team_time_zone_whichever_it_is() -> None:
    london = release_check()
    london["settings"]["timezone"] = "Europe/London"
    assert grade(london, ERROR_WORKFLOW, "Europe/London").grade == "safe"
    singapore = grade(release_check(), ERROR_WORKFLOW, "Europe/London")
    assert (singapore.grade, [f.text for f in singapore.findings]) == (
        "needs_a_fix",
        ["It does not run on London time."],
    )
    assert findings(london) == ["It does not run on Singapore time."]


def test_an_unknown_error_workflow_is_never_taken_for_the_platform_s() -> None:
    assert grade(release_check(), None, TEAM_ZONE).grade == "needs_a_fix"


@pytest.mark.parametrize(
    "interval",
    [
        {"field": "days", "daysInterval": 2, "triggerAtHour": 8, "triggerAtMinute": 0},
        {"field": "hours", "hoursInterval": 5, "triggerAtMinute": 0},
        {"field": "days", "triggerAtHour": 8},
        {"field": "weeks", "triggerAtDay": [1], "triggerAtMinute": 0},
        {"field": "hours", "hoursInterval": 1},
        {
            "field": "weeks",
            "weeksInterval": 2,
            "triggerAtDay": [1],
            "triggerAtHour": 9,
            "triggerAtMinute": 0,
        },
        {"field": "minutes", "minutesInterval": 7},
        {
            "field": "months",
            "monthsInterval": 5,
            "triggerAtDayOfMonth": 1,
            "triggerAtHour": 9,
            "triggerAtMinute": 0,
        },
        {"field": "months", "triggerAtHour": 9, "triggerAtMinute": 0},
        {"field": "seconds", "secondsInterval": 30},
        {"field": "cronExpression", "expression": "at nine on weekdays"},
    ],
)
def test_a_schedule_whose_next_run_n8n_decides_needs_a_fix(interval: dict[str, Any]) -> None:
    document = release_check()
    node(document, "Daily 8:00")["parameters"] = {"rule": {"interval": [interval]}}
    assert graded(document) == "needs_a_fix"


@pytest.mark.parametrize(
    "interval",
    [
        {"field": "hours", "hoursInterval": 6, "triggerAtMinute": 15},
        {
            "field": "weeks",
            "triggerAtDay": [1, 2, 3, 4, 5],
            "triggerAtHour": 7,
            "triggerAtMinute": 30,
        },
        {"field": "minutes", "minutesInterval": 15},
        {
            "field": "months",
            "monthsInterval": 3,
            "triggerAtDayOfMonth": 1,
            "triggerAtHour": 9,
            "triggerAtMinute": 0,
        },
        {"field": "cronExpression", "expression": "0 30 7 * * 1-5"},
    ],
)
def test_a_schedule_the_portal_can_show_to_the_minute_is_fine(interval: dict[str, Any]) -> None:
    document = release_check()
    node(document, "Daily 8:00")["parameters"] = {"rule": {"interval": [interval]}}
    assert graded(document) == "safe"


def test_a_merge_by_sql_needs_a_fix() -> None:
    merge = with_block(release_check(), "n8n-nodes-base.merge", "Merge", version=3.2)
    assert graded(merge) == "safe", "it appends, n8n's default, when the mode is left out"
    node(merge, "Merge")["parameters"] = {"mode": "combineBySql"}
    assert findings(merge) == ['"Merge" does something that is off: combineBySql.']


def test_a_tell_elsewhere_needs_a_fix() -> None:
    tell = with_block(release_check(), "CUSTOM.wabTell", "Tell you")
    node(tell, "Tell you")["parameters"] = {"where": "https://example.com/hook"}
    assert graded(tell) == "needs_a_fix"


def test_a_block_naming_an_option_the_editor_does_not_list_needs_a_fix() -> None:
    known = KnownOptions(
        frozenset({"crd_version_checker"}),
        {"github_releases": frozenset({"langchain-ai/langgraph"})},
        {"jira.create_ticket": frozenset({"MOCK"})},
        {"crd_version_checker": {"GitHub repository": None, "Jira project": frozenset({"MOCK"})}},
    )
    assert grade(release_check(), ERROR_WORKFLOW, TEAM_ZONE, known).grade == "safe"
    elsewhere = release_check()
    node(elsewhere, "Read release")["parameters"]["place"] = "someone/else"
    assert grade(elsewhere, ERROR_WORKFLOW, TEAM_ZONE, known).grade == "needs_a_fix"
    stranger = release_check()
    node(stranger, "Compare")["parameters"]["agent"] = "crd_unknown"
    assert grade(stranger, ERROR_WORKFLOW, TEAM_ZONE, known).grade == "needs_a_fix"
    elsewhere = release_check()
    node(elsewhere, "Compare")["parameters"]["inputs"]["input"][1]["value"] = "PROD"
    assert grade(elsewhere, ERROR_WORKFLOW, TEAM_ZONE, known).grade == "needs_a_fix"
    unknown_input = release_check()
    node(unknown_input, "Compare")["parameters"]["inputs"]["input"].append(
        {"name": "Repo", "value": "evil/repo"}
    )
    assert grade(unknown_input, ERROR_WORKFLOW, TEAM_ZONE, known).grade == "needs_a_fix"


def test_something_that_is_not_a_workflow_needs_a_fix() -> None:
    assert graded({"nodes": "none"}) == "needs_a_fix"
    broken = link(release_check(), "Compare", "Not there")
    assert graded(broken) == "needs_a_fix"


def test_the_checker_puts_back_a_removed_gate_and_the_result_is_safe() -> None:
    with_yes = add_yes(gate_removed(), "uc_01JB8RELEASE")
    assert with_yes.added_before == ("Create ticket",)
    assert graded(with_yes.document) == "safe"
    asks = [n for n in with_yes.document["nodes"] if n["type"] == "CUSTOM.wabAskForYes"]
    assert len(asks) == 1


def test_the_checker_leaves_a_safe_workflow_as_it_is() -> None:
    document = release_check()
    with_yes = add_yes(document, "uc_01JB8RELEASE")
    assert (with_yes.document, with_yes.added_before) == (document, ())


def test_every_block_in_the_node_pack_is_on_the_allow_list_with_its_retries() -> None:
    pack = json.loads(PACK.read_text())["nodes"]
    for entry in pack:
        spec = NODE_TYPES[entry["type"]]
        assert spec.retried == bool(entry["settings"].get("retryOnFail")), entry["type"]
    ours = {name for name in NODE_TYPES if name.startswith("CUSTOM.")}
    assert ours == {entry["type"] for entry in pack}


def test_the_checker_never_changes_the_document_it_is_given() -> None:
    document = gate_removed()
    before = deepcopy(document)
    add_yes(document, "uc")
    grade(document, ERROR_WORKFLOW, TEAM_ZONE)
    assert document == before


def platform(name: str) -> Doc:
    """One of the platform's own workflows as bootstrap loads it, failures sent to the error
    workflow."""
    document: Doc = json.loads((PLATFORM_WORKFLOWS_DIR / f"{name}.n8n.json").read_text())
    if name == SELF_TEST:
        document["settings"]["errorWorkflow"] = ERROR_WORKFLOW
    return document


def test_the_platform_s_own_workflows_as_committed_are_in_shape() -> None:
    assert set(PLATFORM_SHAPES) == {"run_failure_reporter", "self_test_failure"}
    for name in PLATFORM_SHAPES:
        assert check_platform(platform(name), ERROR_WORKFLOW) == (), name


def test_the_self_test_runs_once_a_day_at_six_singapore_time() -> None:
    self_test = platform(SELF_TEST)
    [trigger] = [n for n in self_test["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"]
    assert trigger["parameters"]["rule"]["interval"] == [
        {"field": "days", "triggerAtHour": 6, "triggerAtMinute": 0}
    ]
    assert self_test["settings"]["timezone"] == "Asia/Singapore"


def http_reporter(document: Doc) -> None:
    node(document, "Report a failure")["type"] = "n8n-nodes-base.httpRequest"


def second_report(document: Doc) -> None:
    second = {**node(document, "Report a failure"), "id": "again", "name": "Report again"}
    document["nodes"].append(second)
    link(document, "Report a failure", "Report again")


def unlinked(document: Doc) -> None:
    document["connections"] = {}


@pytest.mark.parametrize(
    ("name", "change", "says"),
    [
        (ERROR_WORKFLOW_NAME, lambda d: d["settings"].pop("callerPolicy"), "callerPolicy"),
        (ERROR_WORKFLOW_NAME, http_reporter, "is off"),
        (ERROR_WORKFLOW_NAME, second_report, "nothing else"),
        (ERROR_WORKFLOW_NAME, unlinked, "nothing else"),
        (SELF_TEST, lambda d: d["settings"].pop("errorWorkflow"), "error workflow"),
        (SELF_TEST, lambda d: d["settings"].update(timezone="UTC"), "Singapore"),
        (SELF_TEST, lambda d: without(d, "Fail on purpose"), "nothing else"),
        (SELF_TEST, lambda d: d.update(name="something else"), "not one of the platform"),
    ],
    ids=[
        "no-caller-policy",
        "http-node",
        "a-second-block",
        "not-linked",
        "no-error-workflow",
        "another-time-zone",
        "no-read",
        "unknown-name",
    ],
)
def test_a_platform_workflow_out_of_shape_is_named(
    name: str, change: Callable[[Doc], object], says: str
) -> None:
    document = platform(name)
    change(document)
    findings = check_platform(document, ERROR_WORKFLOW)
    assert findings and all(f.grade == "needs_a_fix" for f in findings)
    assert any(says in f.text for f in findings), [f.text for f in findings]
