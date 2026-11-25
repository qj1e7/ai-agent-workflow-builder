"""The Planner's layouts, as the drafts the platform saves in n8n (ENGINE-PLAN 2.5).

Each draft must match its golden document in tests/golden/n8n/. After a deliberate change, run
`UPDATE_GOLDEN=1 uv run pytest tests/test_layout.py` and read the diff before committing it."""

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.layout import (
    ADDS_START,
    CREATE_TICKET,
    NEWER,
    START,
    LayoutPlan,
    N8nBlock,
    PlannedAgent,
    agent_cards,
    fixed_for_you,
    lay_out,
    release_notice,
    slack_notice,
    watchlist,
)
from platform_api.builder.n8n_draft import (
    CHECKING,
    EVERY_WRITE,
    FIT,
    Checked,
    DraftRefused,
    check_draft,
    read_only_steps,
)
from platform_api.orchestration import (
    ASK_EXITS,
    KEYS,
    TYPE_OF,
    KnownOptions,
    Schedule,
    grade,
    unpinned_notices,
)
from tests.support import TEAM_ZONE

GOLDEN = Path(__file__).parent / "golden" / "n8n"
ERROR_WORKFLOW = "wfErrorReporter01"
LINK = "https://portal.example/workflows/uc_01JB8RELEASE"
CHECKER = PlannedAgent(
    VERSION_CHECKER_ID,
    "Version checker",
    (("GitHub repository", "langchain-ai/langgraph"), ("Jira project", "MOCK")),
    writes=True,
)
DIGEST = PlannedAgent(
    "crd_sprint_digest", "Sprint digest", (("Jira project", "MOCK"),), writes=False
)
RELEASE_CHECK = LayoutPlan(
    "uc_01JB8RELEASE",
    "LangGraph release check",
    LINK,
    Schedule("every_day", "08:00", TEAM_ZONE),
    (CHECKER,),
    ERROR_WORKFLOW,
    TEAM_ZONE,
)
AGENT_CARDS = LayoutPlan(
    "uc_01JB9CARDS",
    "Weekly release and sprint check",
    LINK,
    Schedule("monday", "09:00", TEAM_ZONE),
    (DIGEST, CHECKER),
    ERROR_WORKFLOW,
    TEAM_ZONE,
)
WATCHLIST = LayoutPlan(
    "uc_01JC2WATCH",
    "Software watchlist",
    LINK,
    Schedule("monday", "09:00", TEAM_ZONE),
    (),
    ERROR_WORKFLOW,
    TEAM_ZONE,
)


def drafted(laid: dict[str, Any], plan: LayoutPlan) -> Checked:
    checked = check_draft(laid, plan.use_case_id, ERROR_WORKFLOW, plan.time_zone)
    assert isinstance(checked, Checked), checked
    return checked


def matches_golden(name: str, document: dict[str, Any]) -> None:
    path = GOLDEN / f"{name}.json"
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(text)
    assert json.loads(path.read_text()) == document, f"{path.name} differs from the layout"


def edges(document: dict[str, Any]) -> set[tuple[str, int, str]]:
    return {
        (source, index, target["node"])
        for source, outputs in document["connections"].items()
        for index, targets in enumerate(outputs["main"])
        for target in targets
    }


def test_the_release_check_is_the_sketch_s_blocks_with_the_yes_the_checker_added() -> None:
    checked = drafted(lay_out(RELEASE_CHECK), RELEASE_CHECK)
    matches_golden("release_check", checked.document)
    names = [node["name"] for node in checked.document["nodes"]]
    assert names == [
        "About this workflow",
        "Daily 8:00",
        "Start from the Portal",
        "Read release",
        "Compare",
        "Newer?",
        "Ask for a yes",
        "Create ticket",
        "Nothing to change",
    ]
    yes = ASK_EXITS.index("Yes")
    quiet = ASK_EXITS.index("Nothing to change")
    assert {
        (NEWER, 0, "Ask for a yes"),
        (NEWER, 1, "Nothing to change"),
        ("Ask for a yes", yes, CREATE_TICKET),
        ("Ask for a yes", quiet, "Nothing to change"),
    } <= edges(checked.document)
    assert checked.graded.grade == "safe"


def test_the_build_log_reads_as_the_sketch_s_set_up_card() -> None:
    checked = drafted(lay_out(RELEASE_CHECK), RELEASE_CHECK)
    assert checked.lines == (
        ("check", FIT),
        ("status", CHECKING),
        ("note", "I added an approval step. Before each ticket is made, an Approver must say yes in Teams."),
        ("check", EVERY_WRITE),
    )


def test_agent_cards_run_in_order_and_end_with_the_yes_and_the_write() -> None:
    laid = agent_cards(AGENT_CARDS)
    checked = drafted(laid, AGENT_CARDS)
    matches_golden("agent_cards", checked.document)
    assert ("Sprint digest", 0, "Version checker") in edges(checked.document)
    assert ("Version checker", 0, "Ask for a yes") in edges(checked.document)


def test_agent_cards_that_only_read_have_no_yes_and_no_write() -> None:
    plan = LayoutPlan("uc_reads", "Sprint digest", LINK, None, (DIGEST,), ERROR_WORKFLOW, TEAM_ZONE)
    checked = drafted(lay_out(plan), plan)
    kinds = {node["type"] for node in checked.document["nodes"]}
    assert "CUSTOM.wabAskForYes" not in kinds
    assert "CUSTOM.wabMakeApprovedChanges" not in kinds
    assert "n8n-nodes-base.scheduleTrigger" not in kinds, "it runs only by hand"
    assert checked.lines == (("check", FIT),)


def test_the_watchlist_reads_every_watched_software_then_checks_them_at_once() -> None:
    checked = drafted(watchlist(WATCHLIST), WATCHLIST)
    matches_golden("watchlist", checked.document)
    assert checked.graded.grade == "safe"


@pytest.mark.parametrize("zone", [TEAM_ZONE, "Europe/London"])
def test_the_schedule_always_names_its_hour_and_minute_in_the_team_time_zone(zone: str) -> None:
    plan = replace(RELEASE_CHECK, schedule=Schedule("every_day", "08:00", zone), time_zone=zone)
    document = lay_out(plan)
    [when] = [n for n in document["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"]
    assert when["parameters"] == {
        "rule": {"interval": [{"field": "days", "triggerAtHour": 8, "triggerAtMinute": 0}]}
    }
    assert document["settings"]["timezone"] == zone
    assert drafted(document, plan).graded.grade == "safe"


def test_the_same_use_case_always_gets_the_same_document() -> None:
    assert lay_out(RELEASE_CHECK) == lay_out(RELEASE_CHECK)
    other = LayoutPlan("uc_other", *list(RELEASE_CHECK.__dict__.values())[1:])
    assert lay_out(other)["nodes"][0]["id"] != lay_out(RELEASE_CHECK)["nodes"][0]["id"]


@pytest.mark.parametrize("plan", [RELEASE_CHECK, AGENT_CARDS])
def test_a_layout_on_its_own_would_be_refused_its_writes(plan: LayoutPlan) -> None:
    """The yes is the checker's: without it the layout grades writes_refused."""
    assert grade(lay_out(plan), ERROR_WORKFLOW, TEAM_ZONE).grade == "writes_refused"


def test_a_layout_with_a_block_that_is_not_on_is_never_saved() -> None:
    laid = lay_out(RELEASE_CHECK)
    laid["nodes"].append({"id": "h", "name": "Post it", "type": "n8n-nodes-base.httpRequest"})
    refused = check_draft(laid, RELEASE_CHECK.use_case_id, ERROR_WORKFLOW, TEAM_ZONE)
    assert isinstance(refused, DraftRefused)
    assert [f.block for f in refused.findings] == ["Post it"]


def test_a_write_the_checker_cannot_put_behind_one_yes_is_never_saved() -> None:
    """A write after an Ask for a yes's No exit gets a second yes in front of it, and two yeses on
    one path need a fix."""
    laid = drafted(lay_out(RELEASE_CHECK), RELEASE_CHECK).document
    no = ASK_EXITS.index("No")
    laid["connections"]["Ask for a yes"]["main"][no] = [
        {"node": CREATE_TICKET, "type": "main", "index": 0}
    ]
    refused = check_draft(laid, RELEASE_CHECK.use_case_id, ERROR_WORKFLOW, TEAM_ZONE)
    assert isinstance(refused, DraftRefused)
    assert {f.grade for f in refused.findings} == {"needs_a_fix"}


SLACK = slack_notice("Tell Slack", "C0123ABCD", "A newer LangGraph release is out.")
PLATFORM_KEYS = KnownOptions(
    frozenset({VERSION_CHECKER_ID}),
    {"github_releases": frozenset({"langchain-ai/langgraph"})},
    {},
    {VERSION_CHECKER_ID: {"GitHub repository": None, "Jira project": None}},
    {KEYS["slack"].id: "slackApi"},
)
"""What the editor lists, and the key the platform made for Slack."""


def test_the_release_check_may_tell_slack_with_the_platform_s_key_and_needs_no_yes() -> None:
    """n8n's own Slack block posts to the channel written in it, with the key the platform made,
    and changes no data, so the checker adds no yes and grades it safe (ADR 0045)."""
    laid = release_notice(RELEASE_CHECK, "langchain-ai/langgraph", "MOCK", SLACK)
    checked = check_draft(laid, RELEASE_CHECK.use_case_id, ERROR_WORKFLOW, TEAM_ZONE, PLATFORM_KEYS)
    assert isinstance(checked, Checked), checked
    matches_golden("release_notice", checked.document)
    [slack] = [n for n in checked.document["nodes"] if n["name"] == "Tell Slack"]
    assert slack["type"] == "n8n-nodes-base.slack"
    assert slack["credentials"] == {
        "slackApi": {"id": "wab-slack-send", "name": KEYS["slack"].name}
    }
    assert "retryOnFail" not in slack, "a retried post would post twice"
    assert (NEWER, 0, "Tell Slack") in edges(checked.document)
    kinds = {node["type"] for node in checked.document["nodes"]}
    assert "CUSTOM.wabAskForYes" not in kinds
    assert checked.lines == (
        ("check", FIT),
        ("note", 'A test run skips "Tell Slack", so it posts nothing.'),
    )
    assert checked.document["pinData"] == {
        "Tell Slack": [{"json": {"skipped": "Slack notice skipped in the test run."}}]
    }, "n8n uses the pinned output in a run by hand, a test run, and ignores it in every other run"
    assert unpinned_notices(checked.document) == []
    del checked.document["pinData"]
    assert unpinned_notices(checked.document) == ["Tell Slack"]


def test_without_the_platform_s_key_the_slack_notice_is_never_saved() -> None:
    laid = release_notice(RELEASE_CHECK, "langchain-ai/langgraph", "MOCK", SLACK)
    refused = check_draft(laid, RELEASE_CHECK.use_case_id, ERROR_WORKFLOW, TEAM_ZONE)
    assert isinstance(refused, DraftRefused)
    assert [f.text for f in refused.findings] == [
        '"Tell Slack" has no key: the platform has none for it.',
        '"Tell Slack" uses a key the platform did not make.',
    ]


@pytest.mark.parametrize(
    "parameters",
    [
        {"operation": "delete"},
        {
            "select": "channel",
            "channelId": {"__rl": True, "value": "={{ $json.to }}", "mode": "id"},
        },
    ],
    ids=["a-delete", "a-channel-an-expression-picks"],
)
def test_a_layout_never_places_an_n8n_block_that_is_off_or_breaks_the_tell_rule(
    parameters: dict[str, Any],
) -> None:
    off = N8nBlock("Off", "n8n-nodes-base.slack", 2.7, parameters, KEYS["slack"], "slackApi")
    if "operation" in parameters:
        with pytest.raises(ValueError):
            release_notice(RELEASE_CHECK, "langchain-ai/langgraph", "MOCK", off)
        return
    laid = release_notice(RELEASE_CHECK, "langchain-ai/langgraph", "MOCK", off)
    refused = check_draft(laid, RELEASE_CHECK.use_case_id, ERROR_WORKFLOW, TEAM_ZONE, PLATFORM_KEYS)
    assert isinstance(refused, DraftRefused)


SCHEDULE_TRIGGER = "Schedule Trigger"


def made_in_the_editor(*extra: dict[str, Any], **settings: Any) -> dict[str, Any]:
    """A Schedule Trigger at 3am, then our Read, as n8n's editor saves them."""
    nodes: list[dict[str, Any]] = [
        {
            "id": "s1",
            "name": SCHEDULE_TRIGGER,
            "type": TYPE_OF["schedule"],
            "typeVersion": 1.3,
            "position": [40, 60],
            "parameters": {"rule": {"interval": [{"triggerAtHour": 3}]}},
        },
        {
            "id": "r1",
            "name": "Read",
            "type": TYPE_OF["read"],
            "typeVersion": 1,
            "position": [260, 60],
            "parameters": {"place": "langchain-ai/langgraph"},
        },
        *extra,
    ]
    return {
        "name": "React read",
        "nodes": nodes,
        "connections": {
            SCHEDULE_TRIGGER: {"main": [[{"node": "Read", "type": "main", "index": 0}]]}
        },
        "settings": {"executionOrder": "v1", **settings},
    }


def test_set_up_puts_right_each_setting_and_adds_the_start_beside_the_schedule() -> None:
    made = made_in_the_editor()
    fixed = fixed_for_you(made, "wf9", ERROR_WORKFLOW, TEAM_ZONE)
    assert fixed.fixed == (
        "sends its failures to the platform's error workflow",
        "runs it on Singapore time",
        "keeps its test runs",
        "saves its progress",
        ADDS_START,
    )
    assert fixed.document["settings"] == {
        "executionOrder": "v1",
        "errorWorkflow": ERROR_WORKFLOW,
        "timezone": TEAM_ZONE,
        "saveManualExecutions": True,
        "saveExecutionProgress": True,
    }
    start = fixed.document["nodes"][-1]
    assert (start["name"], start["type"], start["position"]) == (START, TYPE_OF["start"], [40, 260])
    assert (
        start["webhookId"]
        != fixed_for_you(made, "wf10", ERROR_WORKFLOW, TEAM_ZONE).document["nodes"][-1]["webhookId"]
    ), "each workflow has its own start address"
    assert fixed == fixed_for_you(made, "wf9", ERROR_WORKFLOW, TEAM_ZONE), "the same every time"
    assert edges(fixed.document) == {(SCHEDULE_TRIGGER, 0, "Read"), (START, 0, "Read")}
    assert grade(fixed.document, ERROR_WORKFLOW, TEAM_ZONE).findings == ()
    assert made == made_in_the_editor(), "the document it was given is left as it was"


def test_a_layout_needs_nothing_put_right() -> None:
    laid = lay_out(RELEASE_CHECK)
    assert fixed_for_you(laid, "wf9", ERROR_WORKFLOW, TEAM_ZONE).fixed == ()
    assert fixed_for_you(laid, "wf9", ERROR_WORKFLOW, TEAM_ZONE).document == laid


@pytest.mark.parametrize(
    ("setting", "held"),
    [("saveManualExecutions", 1), ("saveExecutionProgress", "true"), ("timezone", "UTC")],
)
def test_a_setting_that_is_not_exactly_the_platform_s_is_put_right(setting: str, held: Any) -> None:
    made = made_in_the_editor(
        errorWorkflow=ERROR_WORKFLOW,
        timezone=TEAM_ZONE,
        saveManualExecutions=True,
        saveExecutionProgress=True,
    )
    made["settings"][setting] = held
    fixed = fixed_for_you(made, "wf9", ERROR_WORKFLOW, TEAM_ZONE)
    assert len(fixed.fixed) == 2 and fixed.fixed[-1] == ADDS_START
    wanted = {"saveManualExecutions": True, "saveExecutionProgress": True, "timezone": TEAM_ZONE}
    got = fixed.document["settings"][setting]
    assert (type(got), got) == (type(wanted[setting]), wanted[setting])


def test_with_no_error_workflow_loaded_its_failures_are_left_to_the_check() -> None:
    fixed = fixed_for_you(made_in_the_editor(), "wf9", None, TEAM_ZONE)
    assert "errorWorkflow" not in fixed.document["settings"]
    assert "sends its failures to the platform's error workflow" not in fixed.fixed
    own = fixed_for_you(made_in_the_editor(errorWorkflow="wfTheirs"), "wf9", None, TEAM_ZONE)
    assert own.document["settings"]["errorWorkflow"] == "wfTheirs", "never named as nothing"


def test_start_from_the_portal_starts_every_block_each_schedule_starts_once() -> None:
    second = {
        "id": "s2",
        "name": "Weekly",
        "type": TYPE_OF["schedule"],
        "parameters": {"rule": {"interval": [{"field": "weeks"}]}},
    }
    tell = {"id": "t1", "name": "Tell", "type": TYPE_OF["tell"], "parameters": {}}
    made = made_in_the_editor(second, tell)
    made["connections"]["Weekly"] = {
        "main": [
            [
                {"node": "Read", "type": "main", "index": 0},
                {"node": "Tell", "type": "main", "index": 0},
            ]
        ]
    }
    fixed = fixed_for_you(made, "wf9", ERROR_WORKFLOW, TEAM_ZONE)
    assert fixed.document["connections"][START]["main"] == [
        [{"node": "Read", "type": "main", "index": 0}, {"node": "Tell", "type": "main", "index": 0}]
    ]


@pytest.mark.parametrize(
    "change",
    ["it has a start", "its schedule starts nothing", "its schedule is off"],
)
def test_no_start_is_added_where_one_is_there_or_nothing_would_start(change: str) -> None:
    made = made_in_the_editor()
    match change:
        case "it has a start":
            made["nodes"].append(
                {"id": "p1", "name": "Run it", "type": TYPE_OF["start"], "parameters": {}}
            )
        case "its schedule starts nothing":
            made["connections"] = {}
        case _:
            made["nodes"][0]["disabled"] = True
    fixed = fixed_for_you(made, "wf9", ERROR_WORKFLOW, TEAM_ZONE)
    assert ADDS_START not in fixed.fixed
    assert [n["name"] for n in fixed.document["nodes"]] == [n["name"] for n in made["nodes"]]


def test_a_disabled_start_is_no_start_and_a_taken_name_gets_a_number() -> None:
    off = {"id": "p1", "name": START, "type": TYPE_OF["start"], "disabled": True, "parameters": {}}
    fixed = fixed_for_you(made_in_the_editor(off), "wf9", ERROR_WORKFLOW, TEAM_ZONE)
    assert fixed.document["nodes"][-1]["name"] == f"{START} 2"
    assert (f"{START} 2", 0, "Read") in edges(fixed.document)


def test_a_document_the_checker_cannot_read_is_left_as_it_is() -> None:
    broken = {"name": "Broken", "nodes": "not a list", "connections": {}}
    assert fixed_for_you(broken, "wf9", ERROR_WORKFLOW, TEAM_ZONE).fixed == ()


def test_a_workflow_that_only_reads_has_a_read_step_for_each_read_block() -> None:
    second = {"id": "r2", "name": "Read again", "type": TYPE_OF["read"], "parameters": {}}
    made = made_in_the_editor(second)
    made["connections"]["Read"] = {"main": [[{"node": "Read again", "type": "main", "index": 0}]]}
    steps = read_only_steps(made)
    assert [(step.key, step.name, step.kind) for step in steps] == [
        ("read_1", "Read", "agent"),
        ("read_2", "Read", "agent"),
    ]
    assert read_only_steps(None) == []


def test_a_workflow_with_an_agent_names_its_steps_after_its_agents() -> None:
    assert read_only_steps(lay_out(RELEASE_CHECK)) == [], "the Version checker names the step"
