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


def test_the_files_ship_three_workflows():
    assert {d.name for d in load_all()} == {
        "run",
        "run_failure_reporter",
        "schedule_tick",
    }
    assert by_name(load_all(), "schedule_tick").is_tick_workflow
    assert by_name(load_all(), "run_failure_reporter").is_error_workflow


def test_the_run_workflow_has_two_legs_with_the_steps_in_the_referees_order():
    run = by_name(load_all(), "run")
    two_seconds = timedelta(seconds=2)
    assert run.steps(Leg.WORK) == (
        StepNode(StepName.RUN_AGENTS, "Run agents", 3, two_seconds, timedelta(seconds=120)),
        StepNode(StepName.ASK_APPROVAL, "Ask for approval", 3, two_seconds, timedelta(seconds=30)),
    )
    assert run.steps(Leg.ACT) == (
        StepNode(StepName.WRITE_ACTION, "Do write action", 3, two_seconds, timedelta(seconds=60)),
    )
    assert run.webhook_path(Leg.WORK) == "run/work"
    assert run.webhook_path(Leg.ACT) == "run/act"


def test_the_committed_files_pass_the_lint():
    assert lint(load_all()) == []


def test_render_fills_every_placeholder_and_keeps_only_the_api_body():
    for definition in load_all():
        assert placeholders(definition) <= VALUES.keys()
        rendered = render(definition, VALUES)
        assert set(rendered) == {"name", "nodes", "connections", "settings"}
        assert "${" not in json.dumps(rendered)
    run = by_name(load_all(), "run")
    assert placeholders(run) == {
        "PLATFORM_INTERNAL_URL",
        "ERROR_WORKFLOW_ID",
        "STEP_KEY_CREDENTIAL_ID",
    }
    rendered = render(run, VALUES)
    assert rendered["settings"]["errorWorkflow"] == "ERR1"
    assert node(rendered, "Run agents")["credentials"]["httpHeaderAuth"]["id"] == "CRED1"
    assert node(rendered, "Run agents")["parameters"]["url"].startswith(
        "=http://platform-api:8000/internal/v1/runs/"
    )


def test_render_refuses_a_missing_placeholder():
    with pytest.raises(ValueError, match="ERROR_WORKFLOW_ID"):
        render(by_name(load_all(), "run"), {"PLATFORM_INTERNAL_URL": "x"})


def test_render_escapes_the_value_for_json():
    definition = by_name(load_all(), "run")
    rendered = render(definition, {**VALUES, "ERROR_WORKFLOW_ID": 'quote" and \\ slash'})
    assert rendered["settings"]["errorWorkflow"] == 'quote" and \\ slash'


def test_render_drops_id_and_active_from_a_read_back_document():
    document = {**documents()["run_failure_reporter"], "id": "W1", "active": True}
    rendered = render(parse(document), VALUES)
    assert "id" not in rendered and "active" not in rendered


def wrong_webhook_path(docs: dict[str, Document]) -> None:
    node(docs["run"], "Start act")["parameters"]["path"] = "run/write"


def reporter_calls_the_internet(docs: dict[str, Document]) -> None:
    node(docs["run_failure_reporter"], "Report failure")["parameters"]["url"] = (
        "https://hooks.example.com/alerts"
    )


def run_id_read_from_json(docs: dict[str, Document]) -> None:
    node(docs["run"], "Run agents")["parameters"]["url"] = (
        f"={PLATFORM_INTERNAL_URL}/internal/v1/runs/{{{{ $json.run_id }}}}/steps/run_agents"
    )


def approval_step_missing(docs: dict[str, Document]) -> None:
    docs["run"]["nodes"] = [n for n in docs["run"]["nodes"] if n["name"] != "Ask for approval"]
    docs["run"]["connections"]["Continue?"] = {"main": [[], []]}


def run_id_read_from_the_other_leg(docs: dict[str, Document]) -> None:
    node(docs["run"], "Run agents")["parameters"]["url"] = (
        f"={PLATFORM_INTERNAL_URL}/internal/v1/runs/"
        "{{ $('Start act').first().json.body.run_id }}/steps/run_agents"
    )


def short_retry_wait(docs: dict[str, Document]) -> None:
    node(docs["run"], "Run agents")["waitBetweenTries"] = 500


def no_retry(docs: dict[str, Document]) -> None:
    node(docs["run"], "Do write action")["retryOnFail"] = False


def run_agents_outlasts_working(docs: dict[str, Document]) -> None:
    node(docs["run"], "Run agents")["parameters"]["options"]["timeout"] = 200_000


def write_action_outlasts_acting(docs: dict[str, Document]) -> None:
    node(docs["run"], "Do write action")["parameters"]["options"]["timeout"] = 200_000


def write_action_shorter_than_the_connector(docs: dict[str, Document]) -> None:
    node(docs["run"], "Do write action")["parameters"]["options"]["timeout"] = 20_000


def no_timeout(docs: dict[str, Document]) -> None:
    del node(docs["run"], "Ask for approval")["parameters"]["options"]["timeout"]


def no_error_workflow_setting(docs: dict[str, Document]) -> None:
    del docs["run"]["settings"]["errorWorkflow"]


def error_workflow_file_missing(docs: dict[str, Document]) -> None:
    del docs["run_failure_reporter"]


def a_set_node(docs: dict[str, Document]) -> None:
    docs["run"]["nodes"].append(
        {
            "id": "set",
            "name": "Set fields",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [0, 600],
            "parameters": {},
        }
    )


def tick_calls_another_internal_route(docs: dict[str, Document]) -> None:
    node(docs["schedule_tick"], "Ask what is due")["parameters"]["url"] = (
        f"{PLATFORM_INTERNAL_URL}/internal/v1/workflow-failures"
    )


def tick_calls_a_run_step(docs: dict[str, Document]) -> None:
    node(docs["schedule_tick"], "Ask what is due")["parameters"]["url"] = (
        f"={PLATFORM_INTERNAL_URL}/internal/v1/runs/run_1/steps/run_agents"
    )


def tick_fires_every_minute(docs: dict[str, Document]) -> None:
    node(docs["schedule_tick"], "Every 5 minutes")["parameters"]["rule"]["interval"] = [
        {"field": "minutes", "minutesInterval": 1}
    ]


def tick_keeps_successful_executions(docs: dict[str, Document]) -> None:
    del docs["schedule_tick"]["settings"]["saveDataSuccessExecution"]


def tick_makes_a_second_call(docs: dict[str, Document]) -> None:
    second = copy.deepcopy(node(docs["schedule_tick"], "Ask what is due"))
    second["id"], second["name"] = "second", "Ask again"
    docs["schedule_tick"]["nodes"].append(second)


def tick_has_two_triggers(docs: dict[str, Document]) -> None:
    second = copy.deepcopy(node(docs["schedule_tick"], "Every 5 minutes"))
    second["id"], second["name"] = "second", "Every 5 minutes again"
    docs["schedule_tick"]["nodes"].append(second)


def tick_has_no_trigger_link(docs: dict[str, Document]) -> None:
    docs["schedule_tick"]["connections"] = {}


def tick_is_not_a_post(docs: dict[str, Document]) -> None:
    node(docs["schedule_tick"], "Ask what is due")["parameters"]["method"] = "GET"


def tick_without_error_workflow(docs: dict[str, Document]) -> None:
    del docs["schedule_tick"]["settings"]["errorWorkflow"]


def tick_does_not_retry(docs: dict[str, Document]) -> None:
    node(docs["schedule_tick"], "Ask what is due")["retryOnFail"] = False


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
    (Rule.TICK_SHAPE, tick_calls_another_internal_route),
    (Rule.TICK_SHAPE, tick_calls_a_run_step),
    (Rule.TICK_SHAPE, tick_fires_every_minute),
    (Rule.TICK_SHAPE, tick_keeps_successful_executions),
    (Rule.TICK_SHAPE, tick_makes_a_second_call),
    (Rule.TICK_SHAPE, tick_has_two_triggers),
    (Rule.TICK_SHAPE, tick_has_no_trigger_link),
    (Rule.TICK_SHAPE, tick_is_not_a_post),
    (Rule.ERROR_WORKFLOW, tick_without_error_workflow),
    (Rule.RETRY_WAIT, tick_does_not_retry),
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


def test_a_tick_workflow_that_calls_the_internet_fails_the_url_and_shape_rules():
    docs = copy.deepcopy(documents())
    node(docs["schedule_tick"], "Ask what is due")["parameters"]["url"] = (
        "https://hooks.example.com/alerts"
    )
    findings = lint(parse(d) for d in docs.values())
    assert {f.rule for f in findings} == {Rule.INTERNAL_URLS, Rule.TICK_SHAPE}


def test_a_run_workflow_with_a_schedule_trigger_is_held_to_the_tick_rules():
    docs = copy.deepcopy(documents())
    docs["run"]["nodes"].append(
        {
            "id": "timer",
            "name": "Timer",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [0, 400],
            "parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}},
        }
    )
    findings = lint(parse(d) for d in docs.values())
    assert Rule.TICK_SHAPE in {f.rule for f in findings}


def test_the_tick_workflow_has_no_run_steps_and_ships_the_step_key_credential():
    tick = by_name(load_all(), "schedule_tick")
    assert tick.webhooks == () and tick.is_tick_workflow and not tick.is_error_workflow
    assert tick.document["settings"]["saveDataSuccessExecution"] == "none"
    assert placeholders(tick) == {
        "PLATFORM_INTERNAL_URL",
        "ERROR_WORKFLOW_ID",
        "STEP_KEY_CREDENTIAL_ID",
    }
    rendered = render(tick, VALUES)
    assert node(rendered, "Ask what is due")["parameters"]["url"] == (
        "http://platform-api:8000/internal/v1/schedules/tick"
    )


def test_the_live_lint_passes_when_the_error_workflow_is_wired_and_active():
    live = LiveState(
        VALUES["PLATFORM_INTERNAL_URL"],
        {
            "run_failure_reporter": LiveWorkflow("ERR1", True),
            "run": LiveWorkflow("W1", True),
            "schedule_tick": LiveWorkflow("W2", True),
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
        {"run_failure_reporter": reporter, "run": LiveWorkflow("W1", True)},
    )
    findings = lint(rendered_definitions(error_workflow_id), live=live)
    assert {f.rule for f in findings} == {Rule.ERROR_WORKFLOW}


def test_the_file_lint_uses_the_placeholders_as_written():
    assert STEP_KEY_CREDENTIAL_ID in json.dumps(documents()["run"])
    assert documents()["run"]["settings"]["errorWorkflow"] == ERROR_WORKFLOW_ID
