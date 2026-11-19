"""A drafted workflow laid out as an n8n workflow, with what every layout adds, then checked as
every layout is (ADR 0051, flow step 3)."""

from typing import Any

from platform_api.builder.layout import (
    ABOUT,
    RETRY,
    START,
    DraftedLayout,
    lay_out_drafted,
)
from platform_api.orchestration import (
    KnownOptions,
    WorkflowPlan,
    add_yes,
    attach_keys,
    grade,
    read_flow,
)
from platform_api.shared import TEAM_TIME_ZONE

ZONE = TEAM_TIME_ZONE.key
ERROR_WORKFLOW = "wfErrorReporter01"
SLACK_KEY = "wab-slack-send"
KNOWN = KnownOptions(
    frozenset(),
    {"github_releases": frozenset({"langchain-ai/langgraph"})},
    {"jira.create_ticket": frozenset({"MOCK"})},
    {},
    {SLACK_KEY: "slackApi"},
)
PROPOSE = {
    "action": "jira.create_ticket",
    "place": "<<jira_project>>",
    "title": "={{ 'New release ' + $json.tag }}",
    "subject": "={{ $json.tag }}",
}


def block(name: str, node_type: str, version: float, **parameters: Any) -> dict[str, Any]:
    return {"name": name, "type": node_type, "version": version, "parameters": parameters}


def wire(source: str, target: str, exit_name: str = "main", exit_index: int = 0) -> dict[str, Any]:
    return {
        "from_block": source,
        "exit": exit_name,
        "to_block": target,
        "exit_index": exit_index,
        "input_index": 0,
    }


def setting(id_: str, kind: str, value: str | None, block_name: str, path: str) -> dict[str, Any]:
    mark = "needed" if value is None else "filled"
    return {
        "id": id_,
        "kind": kind,
        "label": id_.replace("_", " "),
        "fills": [{"block": block_name, "parameter": path}],
        "value": value,
        "mark": mark,
    }


def release_check(run_time: str | None = "monday 09:00") -> WorkflowPlan:
    """The plan the mock drafter submits, as the runtime checked and marked it."""
    return WorkflowPlan.model_validate(
        {
            "name": "Release check",
            "blocks": [
                block("Every Monday", "n8n-nodes-base.scheduleTrigger", 1.4, rule="<<run_time>>"),
                block(
                    "Read new releases",
                    "CUSTOM.wabRead",
                    1,
                    source="github_releases",
                    place="<<repository>>",
                ),
                block("Propose a ticket", "CUSTOM.wabProposeChange", 1, **PROPOSE),
                block("Ask for a yes", "CUSTOM.wabAskForYes", 1),
                block("Make the ticket", "CUSTOM.wabMakeApprovedChanges", 1),
            ],
            "wires": [
                wire("Every Monday", "Read new releases"),
                wire("Read new releases", "Propose a ticket"),
                wire("Propose a ticket", "Ask for a yes"),
                wire("Ask for a yes", "Make the ticket", "Yes", 1),
            ],
            "settings": [
                setting("run_time", "run_time", run_time, "Every Monday", "rule"),
                setting(
                    "repository",
                    "repository",
                    "langchain-ai/langgraph",
                    "Read new releases",
                    "place",
                ),
                setting("jira_project", "jira_project", "MOCK", "Propose a ticket", "place"),
            ],
        }
    )


def laid(plan: WorkflowPlan) -> dict[str, Any]:
    drafted = DraftedLayout(
        "uc_01JDRAFTED",
        "https://portal.example/workflows/uc_01JDRAFTED",
        plan,
        ERROR_WORKFLOW,
        ZONE,
    )
    values = {s.id: s.value for s in plan.settings if s.value is not None}
    return lay_out_drafted(drafted, values)


def checked(plan: WorkflowPlan) -> dict[str, Any]:
    return attach_keys(add_yes(laid(plan), "uc_01JDRAFTED").document, KNOWN.keys)


def nodes(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["name"]: node for node in document["nodes"]}


def test_the_drafted_release_check_passes_the_check_with_no_finding():
    document = checked(release_check())

    graded = grade(document, ERROR_WORKFLOW, ZONE, KNOWN)

    assert (graded.grade, graded.findings) == ("safe", ())


def test_each_value_stands_where_its_placeholder_was():
    by_name = nodes(laid(release_check()))

    assert by_name["Read new releases"]["parameters"]["place"] == "langchain-ai/langgraph"
    assert by_name["Propose a ticket"]["parameters"]["place"] == "MOCK"
    assert by_name["Every Monday"]["parameters"]["rule"] == {
        "interval": [
            {"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 9, "triggerAtMinute": 0}
        ]
    }


def test_it_adds_what_every_layout_adds():
    document = laid(release_check())
    by_name = nodes(document)
    flow = read_flow(document)

    assert document["settings"] == {
        "timezone": ZONE,
        "saveManualExecutions": True,
        "saveExecutionProgress": True,
        "executionOrder": "v1",
        "errorWorkflow": ERROR_WORKFLOW,
    }
    assert ABOUT in by_name
    assert "https://portal.example/workflows/uc_01JDRAFTED" in str(by_name[ABOUT]["parameters"])
    assert [e.target for e in flow.after(START)] == ["Read new releases"]
    assert by_name[START]["webhookId"]
    for ours in ("Read new releases", "Propose a ticket", "Make the ticket"):
        assert {k: by_name[ours][k] for k in RETRY} == RETRY
    assert "retryOnFail" not in by_name["Ask for a yes"]


def test_a_setting_still_needed_keeps_its_placeholder_and_the_check_says_so():
    document = checked(release_check(run_time=None))

    assert nodes(document)["Every Monday"]["parameters"]["rule"] == "<<run_time>>"
    assert grade(document, ERROR_WORKFLOW, ZONE, KNOWN).findings


def test_a_run_time_in_words_code_can_t_read_keeps_its_placeholder():
    document = laid(release_check(run_time="the first Monday of each month"))

    assert nodes(document)["Every Monday"]["parameters"]["rule"] == "<<run_time>>"


def test_a_write_with_no_yes_before_it_gets_one():
    plan = release_check().model_dump()
    plan["blocks"] = [b for b in plan["blocks"] if b["name"] != "Ask for a yes"]
    plan["wires"] = [*plan["wires"][:2], wire("Propose a ticket", "Make the ticket")]

    document = checked(WorkflowPlan.model_validate(plan))

    assert grade(document, ERROR_WORKFLOW, ZONE, KNOWN).findings == ()
    assert any(n["type"] == "CUSTOM.wabAskForYes" for n in document["nodes"])


def test_n8n_s_own_block_that_posts_gets_pinned_output_so_a_test_run_sends_nothing():
    plan = release_check().model_dump()
    plan["blocks"].append(
        block(
            "Post in Slack",
            "n8n-nodes-base.slack",
            2.7,
            select="channel",
            channelId={"__rl": True, "value": "C0123", "mode": "id"},
            text="A new release is out.",
            otherOptions={},
        )
    )
    plan["wires"].append(wire("Read new releases", "Post in Slack"))

    document = laid(WorkflowPlan.model_validate(plan))

    assert list(document["pinData"]) == ["Post in Slack"]
    assert "retryOnFail" not in nodes(document)["Post in Slack"]
