"""When n8n's Schedule Trigger fires, against n8n's own answers in the P7 golden table, made with
n8n 2.42.6's code and its `cron` library (ENGINE-PLAN 2.4, P7 Q12)."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.layout import LayoutPlan, PlannedAgent, lay_out
from platform_api.orchestration import Schedule
from platform_api.orchestration.n8n_schedule import (
    cron_expression,
    interval_problem,
    next_fire,
    next_run,
)

TABLE = json.loads(
    (
        Path(__file__).parents[2]
        / "docs"
        / "evidence"
        / "prototypes"
        / "p7-n8n-engine-facts"
        / "cron_table.json"
    ).read_text()
)
ROWS: list[dict[str, Any]] = TABLE["rows"]
SINGAPORE = ZoneInfo("Asia/Singapore")
FRIDAY_0830 = datetime(2026, 11, 13, 8, 30, tzinfo=SINGAPORE)
DAILY_8 = {"field": "days", "triggerAtHour": 8, "triggerAtMinute": 0}
MONDAY_9 = {"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 9, "triggerAtMinute": 0}
EVERY_2_DAYS = {"field": "days", "daysInterval": 2, "triggerAtHour": 8, "triggerAtMinute": 0}


def labelled(rows: list[dict[str, Any]]) -> Any:
    return pytest.mark.parametrize("row", rows, ids=[row["label"] for row in rows])


def trigger(node_id: str, *intervals: dict[str, Any], disabled: bool = False) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": f"Schedule {node_id}",
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "disabled": disabled,
        "parameters": {"rule": {"interval": list(intervals)}},
    }


def workflow(*nodes: dict[str, Any], timezone: str | None = "Asia/Singapore") -> dict[str, Any]:
    settings = {} if timezone is None else {"timezone": timezone}
    return {"name": "Check", "nodes": list(nodes), "connections": {}, "settings": settings}


@labelled(ROWS)
def test_each_rule_gives_n8n_s_own_cron_expression(row: dict[str, Any]) -> None:
    assert cron_expression(row["interval"], TABLE["node_key"]) == row["expression"]


@labelled(ROWS)
def test_each_expression_fires_when_n8n_s_cron_library_fires_it(row: dict[str, Any]) -> None:
    after = datetime.fromisoformat(TABLE["from"])
    fires: list[datetime] = []
    for _ in row["next_utc"]:
        after = next_fire(row["expression"], after, ZoneInfo(TABLE["tz"]))
        fires.append(after)
    assert fires == [datetime.fromisoformat(fire) for fire in row["next_utc"]]


@labelled([row for row in ROWS if row["recurrence_filter"]])
def test_a_rule_n8n_filters_by_state_it_keeps_cannot_be_shown(row: dict[str, Any]) -> None:
    assert interval_problem(row["interval"]) is not None


@pytest.mark.parametrize(
    "interval",
    [
        DAILY_8,
        MONDAY_9,
        {"field": "hours", "hoursInterval": 6, "triggerAtMinute": 15},
        {"field": "minutes", "minutesInterval": 15},
        {"field": "minutes"},
        {
            "field": "months",
            "monthsInterval": 3,
            "triggerAtDayOfMonth": 1,
            "triggerAtHour": 9,
            "triggerAtMinute": 0,
        },
        {"field": "cronExpression", "expression": "0 30 7 * * 1-5"},
        {"field": "cronExpression", "expression": "30 7 * * 1-5"},
    ],
)
def test_a_rule_the_cron_alone_spaces_can_be_shown(interval: dict[str, Any]) -> None:
    assert interval_problem(interval) is None


@pytest.mark.parametrize(
    ("expression", "fires"),
    [
        ("0 0 9-17/4 * * *", [(13, 9), (13, 13), (13, 17), (14, 9)]),
        ("0 0 9 1 * 1", [(16, 9), (23, 9), (30, 9), (1, 9)]),
        ("0 0 9 1 * *", [(1, 9), (1, 9)]),
        ("0 0 9 * * 7", [(15, 9), (22, 9)]),
        ("0 9 * * 1", [(16, 9), (23, 9)]),
    ],
    ids=["a range with a step", "either day field", "day of month", "7 is Sunday", "five fields"],
)
def test_a_cron_expression_fires_on_the_days_and_hours_it_names(
    expression: str, fires: list[tuple[int, int]]
) -> None:
    after = FRIDAY_0830
    found: list[tuple[int, int]] = []
    for _ in fires:
        after = next_fire(expression, after, SINGAPORE)
        found.append((after.day, after.hour))
    assert found == fires


@pytest.mark.parametrize("expression", ["every weekday", "0 0 9 * * * *", "0 0 24 * * *"])
def test_an_expression_that_cannot_be_read_raises(expression: str) -> None:
    with pytest.raises(ValueError):
        next_fire(expression, FRIDAY_0830, SINGAPORE)
    assert interval_problem({"field": "cronExpression", "expression": expression}) is not None


def test_an_expression_that_never_fires_raises_and_cannot_be_shown() -> None:
    with pytest.raises(ValueError):
        next_fire("0 0 9 30 2 *", FRIDAY_0830, SINGAPORE)
    assert interval_problem({"field": "cronExpression", "expression": "0 0 9 30 2 *"}) is not None


def test_the_next_run_is_the_earliest_of_its_schedules() -> None:
    document = workflow(trigger("monday", MONDAY_9), trigger("daily", DAILY_8))
    run = next_run(document, "wfCheck01", FRIDAY_0830)
    assert run is not None
    assert run.replace(second=0) == datetime(2026, 11, 14, 8, 0, tzinfo=SINGAPORE)


def test_a_disabled_schedule_does_not_count() -> None:
    document = workflow(trigger("monday", MONDAY_9), trigger("daily", DAILY_8, disabled=True))
    run = next_run(document, "wfCheck01", FRIDAY_0830)
    assert run is not None
    assert run.replace(second=0) == datetime(2026, 11, 16, 9, 0, tzinfo=SINGAPORE)


def test_a_workflow_with_no_schedule_has_no_next_run() -> None:
    start = {"id": "s", "name": "Start", "type": "CUSTOM.wabStartFromPortal", "parameters": {}}
    assert next_run(workflow(start), "wfCheck01", FRIDAY_0830) is None
    assert next_run(workflow(trigger("off", DAILY_8, disabled=True)), "wf", FRIDAY_0830) is None


def test_one_rule_the_portal_cannot_show_hides_the_next_run() -> None:
    document = workflow(trigger("monday", MONDAY_9), trigger("daily", DAILY_8, EVERY_2_DAYS))
    assert next_run(document, "wfCheck01", FRIDAY_0830) is None


def test_the_next_run_is_on_the_workflow_s_clock_and_singapore_s_when_it_has_none() -> None:
    utc = next_run(workflow(trigger("daily", DAILY_8), timezone="UTC"), "wf", FRIDAY_0830)
    unset = next_run(workflow(trigger("daily", DAILY_8), timezone=None), "wf", FRIDAY_0830)
    assert utc is not None and unset is not None
    assert utc.replace(second=0) == datetime.fromisoformat("2026-11-13T08:00:00+00:00")
    assert unset.replace(second=0) == datetime(2026, 11, 14, 8, 0, tzinfo=SINGAPORE)


def test_a_laid_out_release_check_runs_next_monday_at_9_on_its_hidden_second() -> None:
    checker = PlannedAgent(
        VERSION_CHECKER_ID,
        "Version checker",
        (("GitHub repository", "langchain-ai/langgraph"), ("Jira project", "MOCK")),
        writes=True,
    )
    plan = LayoutPlan(
        "uc_01JB8RELEASE",
        "LangGraph release check",
        "https://portal.example/workflows/uc_01JB8RELEASE",
        Schedule("monday", "09:00"),
        (checker,),
        "wfErrorReporter01",
    )
    document = lay_out(plan)
    schedule = next(n for n in document["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger")
    interval = schedule["parameters"]["rule"]["interval"][0]
    second = int(cron_expression(interval, f"wfRelease01:{schedule['id']}").split()[0])
    run = next_run(document, "wfRelease01", FRIDAY_0830)
    assert run == datetime(2026, 11, 16, 9, 0, second, tzinfo=SINGAPORE)
