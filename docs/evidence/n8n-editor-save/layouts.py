"""Prints every layout the platform writes to n8n, as JSON, for editor_save.js."""

import json

from platform_api.builder.layout import (
    LayoutPlan,
    PlannedAgent,
    agent_cards,
    release_check,
    release_notice,
    slack_notice,
    watchlist,
)
from platform_api.orchestration import Day, Schedule
from platform_api.orchestration.workflow_check import add_yes

ZONE = "Asia/Singapore"


def plan(day: Day | None, at: str = "08:00", agents: tuple[PlannedAgent, ...] = ()) -> LayoutPlan:
    schedule = None if day is None else Schedule(day, at, ZONE)
    return LayoutPlan("uc1", "Example", "https://portal.example", schedule, agents, "errors", ZONE)


writer = PlannedAgent("card-1", "Ticket maker", [("Project", "MOCK")], True)
notice = slack_notice("Tell Slack", "C0123", "A new release is out.")
layouts = {
    "release check, every day at 8:00": release_check(plan("every_day"), "a/b", "MOCK"),
    "release check, every day at 0:00": release_check(plan("every_day", "00:00"), "a/b", "MOCK"),
    "release check, Sundays at 7:00": release_check(plan("sunday", "07:00"), "a/b", "MOCK"),
    "release check, weekdays at 9:15": release_check(plan("weekdays", "09:15"), "a/b", "MOCK"),
    "release check, Run now only": release_check(plan(None), "a/b", "MOCK"),
    "release notice to Slack": release_notice(plan("every_day"), "a/b", "MOCK", notice),
    "agent cards": agent_cards(plan("every_day", agents=(writer,))),
    "watchlist": watchlist(plan("every_day")),
}
with_yes = add_yes(layouts["agent cards"], "uc1").document
layouts["agent cards, with the yes the checker adds"] = with_yes
print(json.dumps(layouts))
