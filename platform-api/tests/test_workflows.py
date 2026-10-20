import copy
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from platform_api.orchestration.runs import Leg, StepName
from platform_api.orchestration.workflows import (
    ERROR_WORKFLOW_ID,
    PLATFORM_INTERNAL_URL,
    STEP_KEY_CREDENTIAL_ID,
    WORKFLOWS_DIR,
    LiveState,
    LiveWorkflow,
    Rule,
    StepNode,
    WorkflowDefinition,
    lint,
    load_all,
    parse,
    placeholders,
    render,
)

Document = dict[str, Any]
VALUES = {
    "PLATFORM_INTERNAL_URL": "http://platform-api:8000",
    "ERROR_WORKFLOW_ID": "ERR1",
    "STEP_KEY_CREDENTIAL_ID": "CRED1",
}


def documents() -> dict[str, Document]:
    return {
        path.name.removesuffix(".n8n.json"): json.loads(path.read_text())
        for path in WORKFLOWS_DIR.glob("*.n8n.json")
    }


def node(document: Document, name: str) -> Document:
    return next(n for n in document["nodes"] if n["name"] == name)


def by_name(definitions: tuple[WorkflowDefinition, ...], name: str) -> WorkflowDefinition:
    return next(d for d in definitions if d.name == name)


def test_the_files_ship_two_workflows():
    assert {d.name for d in load_all()} == {"release_check", "run_failure_reporter"}
    assert by_name(load_all(), "run_failure_reporter").is_error_workflow


def test_the_release_check_has_two_legs_with_the_steps_in_the_referees_order():
    release_check = by_name(load_all(), "release_check")
    two_seconds = timedelta(seconds=2)
    assert release_check.steps(Leg.WORK) == (
        StepNode(StepName.RUN_AGENTS, "Run agents", 3, two_seconds, timedelta(seconds=120)),
        StepNode(StepName.ASK_APPROVAL, "Ask for approval", 3, two_seconds, timedelta(seconds=30)),
    )
    assert release_check.steps(Leg.ACT) == (
        StepNode(StepName.WRITE_ACTION, "Do write action", 3, two_seconds, timedelta(seconds=60)),
    )
    assert release_check.webhook_path(Leg.WORK) == "release-check/work"
    assert release_check.webhook_path(Leg.ACT) == "release-check/act"


def test_the_committed_files_pass_the_lint():
    assert lint(load_all()) == []


def test_render_fills_every_placeholder_and_keeps_only_the_api_body():
    for definition in load_all():
        assert placeholders(definition) <= VALUES.keys()
        rendered = render(definition, VALUES)
        assert set(rendered) == {"name", "nodes", "connections", "settings"}
        assert "${" not in json.dumps(rendered)
    release_check = by_name(load_all(), "release_check")
    assert placeholders(release_check) == {
        "PLATFORM_INTERNAL_URL",
        "ERROR_WORKFLOW_ID",
        "STEP_KEY_CREDENTIAL_ID",
    }
    rendered = render(release_check, VALUES)
    assert rendered["settings"]["errorWorkflow"] == "ERR1"
    assert node(rendered, "Run agents")["credentials"]["httpHeaderAuth"]["id"] == "CRED1"
    assert node(rendered, "Run agents")["parameters"]["url"].startswith(
        "=http://platform-api:8000/internal/v1/runs/"
    )


def test_render_refuses_a_missing_placeholder():
    with pytest.raises(ValueError, match="ERROR_WORKFLOW_ID"):
        render(by_name(load_all(), "release_check"), {"PLATFORM_INTERNAL_URL": "x"})


def test_render_escapes_the_value_for_json():
    definition = by_name(load_all(), "release_check")
    rendered = render(definition, {**VALUES, "ERROR_WORKFLOW_ID": 'quote" and \\ slash'})
    assert rendered["settings"]["errorWorkflow"] == 'quote" and \\ slash'


def test_render_drops_id_and_active_from_a_read_back_document():
    document = {**documents()["run_failure_reporter"], "id": "W1", "active": True}
    rendered = render(parse(document), VALUES)
    assert "id" not in rendered and "active" not in rendered


def wrong_webhook_path(docs: dict[str, Document]) -> None:
    node(docs["release_check"], "Start act")["parameters"]["path"] = "release-check/write"


def reporter_calls_the_internet(docs: dict[str, Document]) -> None:
    node(docs["run_failure_reporter"], "Report failure")["parameters"]["url"] = (
        "https://hooks.example.com/alerts"
    )


def run_id_read_from_json(docs: dict[str, Document]) -> None:
    node(docs["release_check"], "Run agents")["parameters"]["url"] = (
        f"={PLATFORM_INTERNAL_URL}/internal/v1/runs/{{{{ $json.run_id }}}}/steps/run_agents"
    )


def approval_step_missing(docs: dict[str, Document]) -> None:
    docs["release_check"]["nodes"] = [
        n for n in docs["release_check"]["nodes"] if n["name"] != "Ask for approval"
    ]
    docs["release_check"]["connections"]["Continue?"] = {"main": [[], []]}


def run_id_read_from_the_other_leg(docs: dict[str, Document]) -> None:
    node(docs["release_check"], "Run agents")["parameters"]["url"] = (
        f"={PLATFORM_INTERNAL_URL}/internal/v1/runs/"
        "{{ $('Start act').first().json.body.run_id }}/steps/run_agents"
    )


def short_retry_wait(docs: dict[str, Document]) -> None:
    node(docs["release_check"], "Run agents")["waitBetweenTries"] = 500


def no_retry(docs: dict[str, Document]) -> None:
    node(docs["release_check"], "Do write action")["retryOnFail"] = False


def run_agents_outlasts_working(docs: dict[str, Document]) -> None:
    node(docs["release_check"], "Run agents")["parameters"]["options"]["timeout"] = 200_000


def write_action_outlasts_acting(docs: dict[str, Document]) -> None:
    node(docs["release_check"], "Do write action")["parameters"]["options"]["timeout"] = 200_000


def write_action_shorter_than_the_connector(docs: dict[str, Document]) -> None:
    node(docs["release_check"], "Do write action")["parameters"]["options"]["timeout"] = 20_000


def no_timeout(docs: dict[str, Document]) -> None:
    del node(docs["release_check"], "Ask for approval")["parameters"]["options"]["timeout"]


def no_error_workflow_setting(docs: dict[str, Document]) -> None:
    del docs["release_check"]["settings"]["errorWorkflow"]


def error_workflow_file_missing(docs: dict[str, Document]) -> None:
    del docs["run_failure_reporter"]


def a_set_node(docs: dict[str, Document]) -> None:
    docs["release_check"]["nodes"].append(
        {
            "id": "set",
            "name": "Set fields",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [0, 600],
            "parameters": {},
        }
    )


MUTATIONS: list[tuple[Rule, Callable[[dict[str, Document]], None]]] = [
    (Rule.WEBHOOK_PATHS, wrong_webhook_path),
    (Rule.INTERNAL_URLS, reporter_calls_the_internet),
    (Rule.STEP_ORDER, run_id_read_from_json),
    (Rule.STEP_ORDER, approval_step_missing),
    (Rule.STEP_ORDER, run_id_read_from_the_other_leg),
    (Rule.RETRY_WAIT, short_retry_wait),
    (Rule.RETRY_WAIT, no_retry),
    (Rule.DEADLINES, run_agents_outlasts_working),
    (Rule.DEADLINES, write_action_outlasts_acting),
    (Rule.DEADLINES, write_action_shorter_than_the_connector),
    (Rule.DEADLINES, no_timeout),
    (Rule.ERROR_WORKFLOW, no_error_workflow_setting),
    (Rule.ERROR_WORKFLOW, error_workflow_file_missing),
    (Rule.NODE_TYPES, a_set_node),
]


@pytest.mark.parametrize(("rule", "mutate"), MUTATIONS, ids=lambda m: getattr(m, "__name__", m))
def test_each_rule_catches_its_own_mutation(
    rule: Rule, mutate: Callable[[dict[str, Document]], None]
):
    docs = copy.deepcopy(documents())
    mutate(docs)
    findings = lint(parse(d) for d in docs.values())
    assert findings, "the mutation went unnoticed"
    assert {f.rule for f in findings} == {rule}, [str(f) for f in findings]


def rendered_definitions(error_workflow_id: str) -> tuple[WorkflowDefinition, ...]:
    values = {**VALUES, "ERROR_WORKFLOW_ID": error_workflow_id}
    return tuple(parse(render(d, values)) for d in load_all())


def test_the_live_lint_passes_when_the_error_workflow_is_wired_and_active():
    live = LiveState(
        VALUES["PLATFORM_INTERNAL_URL"],
        {
            "run_failure_reporter": LiveWorkflow("ERR1", True),
            "release_check": LiveWorkflow("W1", True),
        },
    )
    assert lint(rendered_definitions("ERR1"), live=live) == []


@pytest.mark.parametrize(
    ("error_workflow_id", "reporter"),
    [
        ("ERR1", LiveWorkflow("ERR1", False)),
        ("ERR0", LiveWorkflow("ERR1", True)),
    ],
    ids=["inactive", "points elsewhere"],
)
def test_the_live_lint_fails_rule_6_on_a_bad_error_workflow(
    error_workflow_id: str, reporter: LiveWorkflow
):
    live = LiveState(
        VALUES["PLATFORM_INTERNAL_URL"],
        {"run_failure_reporter": reporter, "release_check": LiveWorkflow("W1", True)},
    )
    findings = lint(rendered_definitions(error_workflow_id), live=live)
    assert {f.rule for f in findings} == {Rule.ERROR_WORKFLOW}


def test_the_file_lint_uses_the_placeholders_as_written():
    assert STEP_KEY_CREDENTIAL_ID in json.dumps(documents()["release_check"])
    assert documents()["release_check"]["settings"]["errorWorkflow"] == ERROR_WORKFLOW_ID
