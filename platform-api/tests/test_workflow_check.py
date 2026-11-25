"""The safety checker's grade for a workflow in n8n, on the sketch's cases (safe, gate removed,
unknown node, no trigger) and on each of its rules (ENGINE-PLAN 2.4)."""

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, get_args

import pytest

from platform_api.orchestration import (
    ASK_EXITS,
    FLAG_RULES,
    NODE_TYPES,
    ApproverMayAccept,
    KnownOptions,
    RuleId,
    add_yes,
    grade,
)
from platform_api.orchestration.workflow_check import ERROR_WORKFLOW as ERROR_WORKFLOW_NAME
from platform_api.orchestration.workflow_check import (
    OURS_FIRST,
    PLATFORM_SHAPES,
    SELF_TEST,
    check_platform,
    platform_document,
    unchecked,
)
from tests.support import FIXTURES, TEAM_ZONE

PAT = "jiraSoftwareServerPatApi"
"""The credential type of a Data Center personal access token."""

GOLDEN = Path(__file__).parent / "golden" / "n8n"
PACK = FIXTURES.parent / "n8n" / "node-types.json"
"""The node pack's types, as the pack's own test keeps contracts/ in step with it."""
ERROR_WORKFLOW = "wfErrorReporter01"
AGAIN = " Save its schedule again, or change its time zone in n8n."
"""What every time zone finding says to do."""

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
    return link(without(release_check(), "Ask for approval"), "Newer?", "Create ticket")


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


def renamed(document: Doc, old: str, new: str) -> Doc:
    """Renames a block everywhere n8n names it: the node, its connections and the edges in."""
    return json.loads(json.dumps(document).replace(json.dumps(old), json.dumps(new)))


@pytest.mark.parametrize("gate", ["Ask for approval", "Ask for a yes"])
def test_the_gate_counts_by_its_type_under_today_s_name_and_the_one_before_25_nov(
    gate: str,
) -> None:
    """A workflow set up before 25 Nov 2026 keeps "Ask for a yes" in n8n. The checker knows the
    block by its type, so either name lets the write through, and either removed refuses it."""
    document = renamed(release_check(), "Ask for approval", gate)
    assert graded(document) == "safe"
    removed = link(without(deepcopy(document), gate), "Newer?", "Create ticket")
    assert graded(removed) == "writes_refused"
    with_yes = add_yes(removed, "uc_01JB8RELEASE")
    asks = [n["name"] for n in with_yes.document["nodes"] if n["type"] == "CUSTOM.wabAskForYes"]
    assert (asks, graded(with_yes.document)) == (["Ask for approval"], "safe")
    assert add_yes(document, "uc_01JB8RELEASE").document == document, "an old name stays"


@pytest.mark.parametrize("exit_name", ["No answer", "No", "Nothing to change"])
def test_a_write_after_any_exit_but_yes_has_no_yes(exit_name: str) -> None:
    document = release_check()
    link(document, "Ask for approval", "Create ticket", ASK_EXITS.index(exit_name))
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
    link(without(document, "Create ticket"), "Ask for approval", "Ask again", 1)
    assert graded(document) == "needs_a_fix"


def turned_off(document: Doc, *names: str) -> Doc:
    """Ticks Deactivate on each block in n8n's editor."""
    for name in names:
        node(document, name)["disabled"] = True
    return document


def test_a_yes_turned_off_in_n8n_is_no_yes() -> None:
    """n8n passes items straight through a turned-off block, so it asks nobody (ADR 0051)."""
    result = grade(turned_off(release_check(), "Ask for approval"), ERROR_WORKFLOW, TEAM_ZONE)
    assert result.grade == "writes_refused"
    assert [f.text for f in result.findings] == ['"Create ticket" can run without approval.']


def test_a_write_turned_off_in_n8n_still_needs_its_yes() -> None:
    """Turning a write off never makes a workflow safer: turning it on again is a publish the
    checker grades again, and until then the checker denies by default."""
    assert graded(turned_off(gate_removed(), "Create ticket")) == "writes_refused"
    assert graded(turned_off(release_check(), "Create ticket")) == "safe"


def test_the_yes_put_back_after_a_turned_off_one_is_the_only_yes_on_its_path() -> None:
    with_yes = add_yes(turned_off(release_check(), "Ask for approval"), "uc_01JB8RELEASE")
    assert with_yes.added_before == ("Create ticket",)
    assert grade(with_yes.document, ERROR_WORKFLOW, TEAM_ZONE).findings == ()


def test_our_step_turned_off_is_no_step_before_n8n_s_blocks() -> None:
    """Our first step links the run and checks its version. Turned off, it does neither."""
    document = turned_off(release_notice(), "Read release")
    assert notice_findings(document) == [], "Compare still calls the platform first"
    turned_off(document, "Compare")
    assert notice_findings(document) == [(FIRST.format("Tell Slack"), True)]
    assert [f.text for f in unchecked(document, KEYS_MADE)] == [FIRST.format("Tell Slack")]
    turned_off(document, "Tell Slack")
    assert notice_findings(document) == [(FIRST.format("Tell Slack"), True)], (
        "n8n's own block turned off still counts, as a write does"
    )


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
def test_a_block_the_platform_has_not_classed_needs_a_fix(block_type: str) -> None:
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


def off_findings(document: Doc) -> list[tuple[str, str, bool]]:
    return [
        (f.rule, f.text, f.runs_anyway) for f in grade(document, ERROR_WORKFLOW, TEAM_ZONE).findings
    ]


@pytest.mark.parametrize(
    "block_type",
    [
        "n8n-nodes-base.sort",
        "n8n-nodes-base.itemLists",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
        "n8n-nodes-base.aiTransform",
        "@n8n/n8n-nodes-langchain.toolCode",
        "n8n-nodes-base.readWriteFile",
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.wait",
        "n8n-nodes-base.respondToWebhook",
        "n8n-nodes-base.httpRequestTool",
    ],
)
def test_a_block_n8n_loads_that_the_platform_has_not_classed_is_a_flag_that_runs_anyway(
    block_type: str,
) -> None:
    """n8n loads every built-in block (ADR 0051, build step 12), so it would run this one as it
    is, and nothing in the platform's project may be live with it."""
    assert off_findings(with_block(release_check(), block_type, "Off")) == [
        ("operation_off", f'"Off" uses {block_type}, which the platform hasn\'t classed.', True)
    ]


@pytest.mark.parametrize(
    ("block_type", "because"),
    [
        ("n8n-nodes-base.executeWorkflow", "It runs another workflow"),
        ("n8n-nodes-base.executeWorkflowTrigger", "It runs another workflow"),
        ("@n8n/n8n-nodes-langchain.toolWorkflow", "It runs another workflow"),
        ("@n8n/n8n-nodes-langchain.retrieverWorkflow", "It runs another workflow"),
        ("n8n-nodes-base.n8n", "It changes n8n itself"),
    ],
)
def test_a_block_n8n_loads_that_can_t_run_here_says_why_and_runs_anyway(
    block_type: str, because: str
) -> None:
    [(rule, text, runs_anyway)] = off_findings(with_block(release_check(), block_type, "Held"))
    assert (rule, runs_anyway) == ("block_held", True)
    assert text.startswith(
        f'"Held" uses {block_type}, which can\'t run on this platform. {because}'
    )


@pytest.mark.parametrize(
    "block_type",
    [
        "n8n-nodes-base.executeCommand",
        "n8n-nodes-base.localFileTrigger",
        "n8n-nodes-base.function",
        "n8n-nodes-base.functionItem",
        "@n8n/n8n-nodes-langchain.code",
        "n8n-nodes-base.git",
        "n8n-nodes-base.gitTool",
        "n8n-nodes-community.anything",
        "wab.read",
    ],
)
def test_a_block_n8n_does_not_load_can_t_run_and_never_runs(block_type: str) -> None:
    assert off_findings(with_block(release_check(), block_type, "Off")) == [
        ("block_off", f'"Off" uses {block_type}, which our n8n doesn\'t load.', False)
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
        [f"It does not run on London time.{AGAIN}"],
    )
    assert findings(london) == [f"It does not run on Singapore time.{AGAIN}"]


@pytest.mark.parametrize(
    ("zone", "named"),
    [
        ("UTC", "UTC"),
        ("Etc/GMT-8", "GMT+8"),
        ("Etc/GMT+5", "GMT-5"),
        ("America/Argentina/Buenos_Aires", "Buenos Aires time"),
        ("EST5EDT", "EST5EDT time"),
    ],
)
def test_the_finding_names_the_team_time_zone_as_the_portal_does(zone: str, named: str) -> None:
    [finding] = grade(release_check(), ERROR_WORKFLOW, zone).findings
    assert finding.text == f"It does not run on {named}.{AGAIN}"


def test_an_unknown_error_workflow_is_never_taken_for_the_platform_s() -> None:
    assert grade(release_check(), None, TEAM_ZONE).grade == "needs_a_fix"


@pytest.mark.parametrize(
    "interval",
    [
        {"field": "days", "daysInterval": 2, "triggerAtHour": 8, "triggerAtMinute": 0},
        {"field": "hours", "hoursInterval": 5, "triggerAtMinute": 0},
        {"field": "days", "triggerAtHour": 8, "triggerAtMinute": None},
        {"field": "weeks", "triggerAtDay": [1], "triggerAtHour": None, "triggerAtMinute": 0},
        {"field": "hours", "hoursInterval": 1, "triggerAtMinute": None},
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
        {"field": "months", "triggerAtDayOfMonth": None, "triggerAtHour": 9, "triggerAtMinute": 0},
        {"field": "seconds", "secondsInterval": 30},
        {"field": "cronExpression", "expression": "at nine on weekdays"},
    ],
)
def test_a_schedule_whose_next_run_n8n_decides_needs_a_fix(interval: dict[str, Any]) -> None:
    """A part saved as null is one n8n picks by itself, so its next run can't be shown."""
    document = release_check()
    node(document, "Daily 8:00")["parameters"] = {"rule": {"interval": [interval]}}
    assert graded(document) == "needs_a_fix"


@pytest.mark.parametrize(
    ("rule", "said"),
    [
        ({}, '"Daily 8:00" leaves its hour or minute for n8n to pick.'),
        ({"interval": [None]}, '"Daily 8:00" leaves its hour or minute for n8n to pick.'),
        ({"interval": []}, '"Daily 8:00" has no time to run.'),
    ],
)
def test_a_rule_with_no_interval_runs_at_a_time_n8n_picks_and_an_empty_one_never(
    rule: dict[str, Any], said: str
) -> None:
    document = release_check()
    node(document, "Daily 8:00")["parameters"] = {"rule": rule}
    assert said in findings(document)


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
        {"field": "days", "triggerAtHour": 8},
        {"field": "weeks", "triggerAtDay": [1], "triggerAtMinute": 0},
        {"field": "hours", "hoursInterval": 1},
        {"field": "months", "triggerAtHour": 9, "triggerAtMinute": 0},
    ],
)
def test_a_schedule_the_portal_can_show_to_the_minute_is_fine(interval: dict[str, Any]) -> None:
    """A part left out is one n8n's editor showed at its default and n8n fills in as it loads the
    workflow, so it runs at that default."""
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


def platform(name: str, zone: str = TEAM_ZONE) -> Doc:
    """One of the platform's own workflows as bootstrap loads it."""
    return platform_document(name, ERROR_WORKFLOW, zone)


@pytest.mark.parametrize("zone", [TEAM_ZONE, "Europe/London"])
def test_the_platform_s_own_workflows_as_committed_are_in_shape(zone: str) -> None:
    assert set(PLATFORM_SHAPES) == {"run_failure_reporter", "self_test_failure"}
    for name in PLATFORM_SHAPES:
        assert check_platform(platform(name, zone), ERROR_WORKFLOW, zone) == (), name


def test_the_self_test_runs_once_a_day_at_six_in_the_team_time_zone() -> None:
    self_test = platform(SELF_TEST, "Europe/London")
    [trigger] = [n for n in self_test["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"]
    assert trigger["parameters"]["rule"]["interval"] == [
        {"field": "days", "triggerAtHour": 6, "triggerAtMinute": 0}
    ]
    assert self_test["settings"]["timezone"] == "Europe/London"
    singapore = check_platform(platform(SELF_TEST), ERROR_WORKFLOW, "Europe/London")
    assert [f.text for f in singapore] == ["Its setting timezone must be 'Europe/London'."]


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
        (ERROR_WORKFLOW_NAME, http_reporter, "hasn't classed"),
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
    findings = check_platform(document, ERROR_WORKFLOW, TEAM_ZONE)
    assert findings and all(f.grade == "needs_a_fix" for f in findings)
    assert any(says in f.text for f in findings), [f.text for f in findings]


SLACK_KEY = "wab-slack-send"
JIRA_KEY = "wab-jira-read"
KEYS_MADE = {SLACK_KEY: "slackApi", JIRA_KEY: PAT}
"""The keys the platform made in n8n, by id, with each one's n8n credential type."""


def release_notice() -> Doc:
    """The release check that tells Slack, from n8n's own Slack block (tests/test_layout.py)."""
    return json.loads((GOLDEN / "release_notice.json").read_text())


def with_keys(keys: dict[str, str] | None = None) -> KnownOptions:
    return KnownOptions(
        frozenset({"crd_version_checker"}),
        {"github_releases": frozenset({"langchain-ai/langgraph"})},
        {},
        {"crd_version_checker": {"GitHub repository": None, "Jira project": None}},
        KEYS_MADE if keys is None else keys,
    )


def notice_findings(document: Doc, keys: dict[str, str] | None = None) -> list[tuple[str, bool]]:
    graded = grade(document, ERROR_WORKFLOW, TEAM_ZONE, with_keys(keys))
    return [(f.text, f.runs_anyway) for f in graded.findings]


def jira_read(document: Doc, parameters: dict[str, Any], key: str = JIRA_KEY) -> Doc:
    with_block(document, "n8n-nodes-base.jira", "Read tickets", "Compare", 1, parameters)
    node(document, "Read tickets")["credentials"] = {PAT: {"id": key, "name": "Jira"}}
    return document


def test_a_slack_notice_with_the_platform_s_key_and_a_fixed_channel_is_safe() -> None:
    assert notice_findings(release_notice()) == []


def test_a_jira_read_with_the_platform_s_key_is_safe() -> None:
    reads = jira_read(release_notice(), {"jiraVersion": "serverPat", "operation": "getAll"})
    assert notice_findings(reads) == []


@pytest.mark.parametrize(
    ("channel", "where"),
    [
        ({"__rl": True, "value": "={{ $json.channel }}", "mode": "id"}, "channelId"),
        ("={{ 'user' }}", "select"),
    ],
    ids=["a-channel", "who-it-posts-to"],
)
def test_a_notice_to_a_place_an_expression_picks_is_off(channel: Any, where: str) -> None:
    """The Tell rule (ADR 0045, section 4): a notice posts only to a place written in the block.
    n8n would post it all the same, so it runs anyway and is never set up or turned on."""
    document = release_notice()
    node(document, "Tell Slack")["parameters"][where] = channel
    assert notice_findings(document) == [
        ('"Tell Slack" posts to a place an expression picks, so it is off.', True)
    ]


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("text", "={{ $json.summary }} {{ $json.newer }}"),
        ("text", "={{ '<!' + 'channel>' }}"),
        ("blocksUi", "={{ JSON.stringify($json.blocks) }}"),
        ("attachments", [{"text": "={{ $json.summary }}"}]),
    ],
    ids=["from-the-run", "built-to-hide-a-mention", "blocks", "an-attachment"],
)
def test_a_notice_written_with_an_expression_is_off(where: str, value: Any) -> None:
    """n8n notice text is written out in this release, so the checker reads every word before
    anything runs. A notice that says what a run read goes through our Tell."""
    document = release_notice()
    node(document, "Tell Slack")["parameters"][where] = value
    assert notice_findings(document) == [
        (
            '"Tell Slack" writes its message with an expression, so it is off. Use our Tell for '
            "that.",
            True,
        )
    ]


def test_a_notice_whose_blocks_the_checker_can_t_read_is_off() -> None:
    document = release_notice()
    node(document, "Tell Slack")["parameters"]["blocksUi"] = '{"blocks": [<!channel>'
    assert notice_findings(document) == [
        ('"Tell Slack" has a message the checker can\'t read, so it is off.', True)
    ]


def test_an_email_s_copy_to_an_address_an_expression_picks_is_off() -> None:
    document = release_notice()
    with_block(
        document,
        "n8n-nodes-base.microsoftOutlook",
        "Email",
        "Newer?",
        2,
        {
            "operation": "send",
            "toRecipients": "team@codesparks.test",
            "additionalFields": {"ccRecipients": "={{ $json.who }}"},
        },
    )
    assert ('"Email" posts to a place an expression picks, so it is off.', True) in (
        notice_findings(document)
    )


@pytest.mark.parametrize(
    ("parameters", "says"),
    [
        ({"operation": "create"}, '"Read tickets" does something that is off: issue create.'),
        ({}, '"Read tickets" does something that is off: issue create.'),
        (
            {"resource": "issueComment", "operation": "add"},
            '"Read tickets" does something that is off: issueComment add.',
        ),
        (
            {"operation": "={{ $json.what }}"},
            '"Read tickets" picks what it does with an expression, so it is off.',
        ),
        (
            {"resource": "={{ 'user' }}", "operation": "get"},
            '"Read tickets" picks what it does with an expression, so it is off.',
        ),
    ],
    ids=[
        "a-write",
        "n8n-s-default-a-write",
        "a-comment",
        "an-operation-expression",
        "a-resource-expression",
    ],
)
def test_a_write_or_an_expression_on_a_block_classed_to_read_is_off(
    parameters: dict[str, Any], says: str
) -> None:
    """n8n's allow list is by type, so it would run the Jira block's write: the finding runs
    anyway, and the platform's own key could not write anyway (ADR 0045)."""
    assert notice_findings(jira_read(release_notice(), parameters)) == [(says, True)]


def test_a_key_the_platform_did_not_make_needs_a_fix_that_runs_anyway() -> None:
    """In the platform's project n8n lets a workflow use every key there is, a member's too, so
    this is the guard (ENGINE-PLAN E15's review)."""
    document = release_notice()
    node(document, "Tell Slack")["credentials"] = {"slackApi": {"id": "aliceSlack", "name": "Mine"}}
    assert notice_findings(document) == [
        ('"Tell Slack" does not use the platform\'s key.', False),
        ('"Tell Slack" uses a key the platform did not make.', True),
    ]
    reads = jira_read(release_notice(), {"operation": "get"}, key="aliceJira")
    assert ('"Read tickets" uses a key the platform did not make.', True) in notice_findings(reads)


def test_a_key_named_by_name_only_is_not_the_platform_s() -> None:
    document = release_notice()
    node(document, "Tell Slack")["credentials"] = {"slackApi": {"name": "The platform's Slack key"}}
    assert ('"Tell Slack" uses a key the platform did not make.', True) in notice_findings(document)


def test_without_the_platform_s_keys_every_key_is_someone_else_s() -> None:
    """Fail closed: a grade that is not told the platform's keys trusts none."""
    graded = grade(release_notice(), ERROR_WORKFLOW, TEAM_ZONE)
    assert [f.text for f in graded.findings] == [
        '"Tell Slack" has no key: the platform has none for it.',
        '"Tell Slack" uses a key the platform did not make.',
    ]
    assert graded.grade == "needs_a_fix"


def test_a_platform_key_in_another_block_s_slot_needs_a_fix() -> None:
    """n8n refuses to run it, so it needs a fix but does not run anyway."""
    document = release_notice()
    node(document, "Tell Slack")["credentials"] = {"slackOAuth2Api": {"id": SLACK_KEY, "name": "x"}}
    assert notice_findings(document) == [
        ('"Tell Slack" uses a platform key made for another block.', False)
    ]


def test_a_key_on_one_of_our_own_blocks_is_not_the_platform_s_either() -> None:
    document = release_notice()
    node(document, "Compare")["credentials"] = {"slackApi": {"id": "aliceSlack", "name": "x"}}
    assert ('"Compare" uses a key the platform did not make.', True) in notice_findings(document)


def test_a_block_n8n_loads_but_the_platform_has_not_classed_needs_a_fix_that_runs_anyway() -> None:
    document = with_block(release_notice(), "n8n-nodes-base.httpRequest", "Post it", "Newer?", 4.2)
    assert notice_findings(document) == [
        ('"Post it" uses n8n-nodes-base.httpRequest, which the platform hasn\'t classed.', True)
    ]


@pytest.mark.parametrize(
    ("block_type", "version"),
    [
        ("n8n-nodes-base.slack", 1),
        ("n8n-nodes-base.microsoftTeams", 1.1),
        ("n8n-nodes-base.gmail", 1),
    ],
)
def test_an_older_version_of_a_system_block_is_off_and_runs_anyway(
    block_type: str, version: float
) -> None:
    document = with_block(release_notice(), block_type, "Old", "Newer?", version)
    assert notice_findings(document) == [
        (f'"Old" uses version {version:g} of {block_type}, which is off.', True)
    ]


def test_a_block_for_a_system_with_no_platform_key_needs_a_fix() -> None:
    """Teams, Outlook and Gmail have no key the platform can hold (ADR 0045, as amended), so their
    blocks cannot run. A refused or missing Slack key leaves Slack's the same."""
    document = with_block(
        release_notice(),
        "n8n-nodes-base.microsoftTeams",
        "Tell Teams",
        "Newer?",
        2,
        {
            "resource": "channelMessage",
            "teamId": {"__rl": True, "value": "T1", "mode": "id"},
            "channelId": {"__rl": True, "value": "C1", "mode": "id"},
        },
    )
    assert notice_findings(document) == [
        ('"Tell Teams" has no key: the platform has none for it.', False)
    ]
    assert notice_findings(release_notice(), {JIRA_KEY: PAT}) == [
        ('"Tell Slack" has no key: the platform has none for it.', False),
        ('"Tell Slack" uses a key the platform did not make.', True),
    ]


def test_a_block_with_its_key_taken_off_does_not_use_the_platform_s_key() -> None:
    document = release_notice()
    del node(document, "Tell Slack")["credentials"]
    assert notice_findings(document) == [('"Tell Slack" does not use the platform\'s key.', False)]


FIRST = '"{}" runs before any of our steps. Add one of our steps first, so each run is recorded.'


def test_one_of_n8n_s_blocks_before_any_of_ours_needs_a_fix_that_runs_anyway() -> None:
    """Our first block links the run, so it is recorded and shown, and checks the version before
    n8n reads or posts anything (ADR 0045, as amended)."""
    document = release_notice()
    link(document, "Start from the Portal", "Tell Slack")
    assert notice_findings(document) == [(FIRST.format("Tell Slack"), True)]
    reads_first = jira_read(release_notice(), {"operation": "getAll"})
    assert notice_findings(reads_first) == [], "after Read release and Compare"
    link(reads_first, "Daily 8:00", "Read tickets")
    assert notice_findings(reads_first) == [(FIRST.format("Read tickets"), True)], (
        "every way from a trigger counts, the schedule's too"
    )


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("text", "New release <!channel>"),
        ("text", "Look <!HERE|here>"),
        ("text", "heads up @everyone"),
        ("text", "heads up \uff20channel"),
        ("blocksUi", '{"blocks": [{"type": "section", "text": {"text": "\\u003c!everyone>"}}]}'),
        ("attachments", [{"text": "@channel look"}]),
        ("text", "Look <!subteam^S0123|@devs>"),
        ("blocksUi", '{"blocks": [{"type": "section", "text": {"text": "<!subteam^S1>"}}]}'),
    ],
    ids=[
        "channel",
        "here-in-capitals",
        "at-everyone",
        "full-width-at",
        "in-blocks",
        "attached",
        "a-user-group",
        "a-user-group-in-blocks",
    ],
)
def test_a_notice_that_calls_out_a_whole_channel_is_off(where: str, value: Any) -> None:
    """The Tell rule: a notice tells the people it is for, never a whole channel at once."""
    document = release_notice()
    node(document, "Tell Slack")["parameters"][where] = value
    assert notice_findings(document) == [
        ('"Tell Slack" calls out a whole channel, so it is off.', True)
    ]


@pytest.mark.parametrize("switch", [True, "={{ true }}"], ids=["on", "an-expression"])
def test_a_notice_that_links_names_is_off(switch: Any) -> None:
    """Slack's link_names turns a written @channel into a call to everyone in it."""
    document = release_notice()
    node(document, "Tell Slack")["parameters"]["otherOptions"] = {"link_names": switch}
    assert notice_findings(document) == [
        ('"Tell Slack" calls out a whole channel, so it is off.', True)
    ]


def test_a_notice_that_names_one_person_or_leaves_link_names_off_is_fine() -> None:
    document = release_notice()
    parameters = node(document, "Tell Slack")["parameters"]
    parameters["text"] = "<@U123> the release is out, see #releases"
    parameters["otherOptions"] = {"link_names": False}
    assert notice_findings(document) == []


def test_unchecked_names_only_what_n8n_would_run_whatever_the_platform_says() -> None:
    """The invariant (ADR 0045, as amended): no version with one of these is live in the
    platform's n8n project, and no draft with one is run."""
    assert unchecked(release_notice(), KEYS_MADE) == ()
    document = release_notice()
    node(document, "Tell Slack")["parameters"]["operation"] = "delete"
    node(document, "Compare")["credentials"] = {"slackApi": {"id": "aliceSlack", "name": "x"}}
    with_block(document, "n8n-nodes-base.httpRequest", "Post it", "Newer?", 4.2)
    with_block(document, "n8n-nodes-base.executeCommand", "Run it", "Newer?")
    assert [f.text for f in unchecked(document, KEYS_MADE)] == [
        '"Tell Slack" does something that is off: message delete.',
        '"Post it" uses n8n-nodes-base.httpRequest, which the platform hasn\'t classed.',
        '"Compare" uses a key the platform did not make.',
    ], "a block n8n does not load never runs, so it is not one"


def test_unchecked_counts_a_block_before_ours_and_a_key_the_platform_no_longer_holds() -> None:
    document = release_notice()
    first = next(n["name"] for n in document["nodes"] if n["type"].endswith("scheduleTrigger"))
    link(document, first, "Tell Slack")
    assert [f.text for f in unchecked(document, {})] == [
        '"Tell Slack" uses a key the platform did not make.',
        f'"Tell Slack" runs before any of our steps. {OURS_FIRST}',
    ]


def test_a_document_the_checker_can_t_read_counts_as_unchecked() -> None:
    [found] = unchecked({"nodes": "not a list"}, KEYS_MADE)
    assert found.runs_anyway


ALLOWED = KnownOptions(
    frozenset({"crd_version_checker"}),
    {"github_releases": frozenset({"langchain-ai/langgraph"})},
    {"jira.create_ticket": frozenset({"MOCK"})},
    {"crd_version_checker": {"GitHub repository": None, "Jira project": frozenset({"MOCK"})}},
    KEYS_MADE,
)
"""Every list the editor shows, so every rule the checker has is checked."""


def setting(name: str, value: object) -> Callable[[], Doc]:
    def changed() -> Doc:
        document = release_check()
        document["settings"][name] = value
        return document

    return changed


def changed(make: Callable[[], Doc], name: str, *path: str, value: object) -> Callable[[], Doc]:
    def change() -> Doc:
        document = make()
        held: Any = node(document, name)
        for part in path[:-1]:
            held = held[part]
        held[path[-1]] = value
        return document

    return change


def second_yes() -> Doc:
    document = with_block(release_check(), "CUSTOM.wabAskForYes", "Ask again", "Ask for approval")
    return link(without(document, "Create ticket"), "Ask for approval", "Ask again", 1)


def notice_channel(value: object) -> Callable[[], Doc]:
    return changed(release_notice, "Tell Slack", "parameters", "channelId", "value", value=value)


BREAKS: dict[str, Callable[[], Doc]] = {
    "unreadable": lambda: {"nodes": "none"},
    "block_off": lambda: with_block(release_check(), "n8n-nodes-base.executeCommand", "Run it"),
    "block_held": lambda: with_block(release_check(), "n8n-nodes-base.executeWorkflow", "Call it"),
    "version_off": lambda: with_block(release_check(), "n8n-nodes-base.if", "Old", version=99),
    "picked_by_expression": lambda: with_block(
        release_check(), "n8n-nodes-base.merge", "Mix", version=3.2, parameters={"mode": "={{ 1 }}"}
    ),
    "operation_off": lambda: jira_read(release_check(), {"operation": "create"}),
    "nothing_starts": lambda: without(release_check(), "Daily 8:00", "Start from the Portal"),
    "no_error_workflow": setting("errorWorkflow", "someone_else"),
    "other_time_zone": setting("timezone", "Europe/London"),
    "test_runs_not_kept": setting("saveManualExecutions", False),
    "progress_not_saved": setting("saveExecutionProgress", False),
    "tell_place": lambda: with_block(
        release_check(), "CUSTOM.wabTell", "Tell you", parameters={"where": "https://x.example"}
    ),
    "notice_place_expression": notice_channel("={{ $json.channel }}"),
    "notice_words_expression": changed(
        release_notice, "Tell Slack", "parameters", "text", value="={{ $json.summary }}"
    ),
    "notice_words_unreadable": changed(
        release_notice, "Tell Slack", "parameters", "blocksUi", value='{"blocks": ['
    ),
    "calls_everyone": changed(
        release_notice, "Tell Slack", "parameters", "text", value="Look <!channel>"
    ),
    "no_platform_key": lambda: with_block(
        release_check(),
        "n8n-nodes-base.microsoftTeams",
        "Tell Teams",
        version=2,
        parameters={
            "resource": "channelMessage",
            "teamId": {"__rl": True, "value": "T1", "mode": "id"},
            "channelId": {"__rl": True, "value": "C1", "mode": "id"},
        },
    ),
    "not_platform_key": changed(release_notice, "Tell Slack", "credentials", value={}),
    "key_not_made": changed(
        release_check, "Read release", "credentials", value={"githubApi": {"id": "alices"}}
    ),
    "key_for_other_block": changed(
        release_check, "Read release", "credentials", value={"slackApi": {"id": JIRA_KEY}}
    ),
    "runs_before_ours": lambda: link(release_notice(), "Start from the Portal", "Tell Slack"),
    "no_run_time": changed(
        release_check, "Daily 8:00", "parameters", "rule", value={"interval": []}
    ),
    "run_time_unshowable": changed(
        release_check,
        "Daily 8:00",
        "parameters",
        "rule",
        value={"interval": [{"field": "hours", "hoursInterval": 5, "triggerAtMinute": 0}]},
    ),
    "unknown_agent": changed(release_check, "Compare", "parameters", "agent", value="crd_x"),
    "unknown_agent_input": changed(
        release_check,
        "Compare",
        "parameters",
        "inputs",
        "input",
        value=[{"name": "Repo", "value": "evil/repo"}],
    ),
    "write_place_not_allowed": changed(
        release_check,
        "Compare",
        "parameters",
        "inputs",
        "input",
        value=[{"name": "Jira project", "value": "PROD"}],
    ),
    "read_place_not_allowed": changed(
        release_check, "Read release", "parameters", "place", value="someone/else"
    ),
    "change_not_allowed": lambda: with_block(
        release_check(),
        "CUSTOM.wabProposeChange",
        "Propose",
        parameters={"action": "jira.create_ticket", "place": "PROD"},
    ),
    "no_yes_before_write": gate_removed,
    "second_yes": second_yes,
}
"""For each rule, the release check broken in that one way."""


def test_every_rule_has_a_row_saying_what_it_is_why_it_matters_and_who_clears_it() -> None:
    assert set(get_args(RuleId.__value__)) == set(FLAG_RULES)
    assert set(BREAKS) == set(FLAG_RULES), "and a test that breaks it"


@pytest.mark.parametrize("rule", list(BREAKS))
def test_each_finding_names_the_one_rule_it_breaks(rule: str) -> None:
    assert grade(release_check(), ERROR_WORKFLOW, TEAM_ZONE, ALLOWED).findings == ()
    found = grade(BREAKS[rule](), ERROR_WORKFLOW, TEAM_ZONE, ALLOWED).findings
    assert {f.rule for f in found} == {rule}


def test_two_approvers_accept_a_flag_when_code_can_t_tell_what_the_block_does() -> None:
    """Code can't tell such a block leaves everyone's access as it was (ADR 0051, section 3)."""
    twos = {
        rule
        for rule, row in FLAG_RULES.items()
        if isinstance(row.clears, ApproverMayAccept) and row.clears.approvers == 2
    }
    assert twos == {"version_off", "picked_by_expression", "operation_off"}
