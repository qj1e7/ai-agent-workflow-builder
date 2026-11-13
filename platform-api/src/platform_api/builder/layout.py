"""The Planner lays out each use case as an n8n workflow of its own, from our node pack
(ENGINE-PLAN 2.5).

The layout is code, not a model call: the model chooses the cards and their values (ADR 0023),
and this places the blocks. Block names are the sketch's words, so the run line, the build
canvas and n8n read the same. A layout leaves out the yes. The safety checker puts it in front
of the write, which is what the build panel shows ("Added a yes before the ticket.").

Pure. Ids come from the use case's id, so the same use case always gets the same document.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.orchestration import (
    NODE_TYPES,
    NOTHING_TO_CHANGE_BLOCK,
    TIME_ZONE,
    TYPE_OF,
    BlockKind,
    Day,
    Document,
    Schedule,
    free_name,
)

READ_RELEASE = "Read release"
COMPARE = "Compare"
NEWER = "Newer?"
CREATE_TICKET = "Create ticket"
MAKE_CHANGES = "Make the approved changes"
START = "Start from the Portal"
ABOUT = "About this workflow"
READ_WATCHLIST = "Read the watchlist"
CHECK_WATCHLIST = "Check the watchlist"
WATCHLIST_PLACE = "watchlist"
"""The Read place that stands for every watched software (ENGINE-PLAN 2.5)."""
WATCHLIST_AGENT = "watchlist_checker"
"""The platform's fixed agent that checks every watched software (D11). E9 runs it."""
REPO_INPUT = "GitHub repository"
PROJECT_INPUT = "Jira project"

STEP = 220
ROW = 200
TYPE_VERSIONS: Mapping[BlockKind, float] = {"schedule": 1.2, "branch": 2}
RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}
SETTINGS = {
    "timezone": TIME_ZONE,
    "saveManualExecutions": True,
    "saveExecutionProgress": True,
    "executionOrder": "v1",
}

DAY_LABELS: Mapping[Day, str] = {
    "every_day": "Daily",
    "weekdays": "Weekdays",
    "monday": "Mon",
    "tuesday": "Tue",
    "wednesday": "Wed",
    "thursday": "Thu",
    "friday": "Fri",
    "saturday": "Sat",
    "sunday": "Sun",
}
CRON_DAYS: Mapping[Day, list[int]] = {
    "weekdays": [1, 2, 3, 4, 5],
    "monday": [1],
    "tuesday": [2],
    "wednesday": [3],
    "thursday": [4],
    "friday": [5],
    "saturday": [6],
    "sunday": [0],
}
"""n8n counts the days of the week as cron does, from Sunday, 0."""


@dataclass(frozen=True)
class PlannedAgent:
    card_id: str
    name: str
    values: Sequence[tuple[str, str]]
    """The card's inputs and their values, in the card's order."""
    writes: bool
    """The card has a write tool, so the workflow makes changes after a yes."""


@dataclass(frozen=True)
class LayoutPlan:
    """What the set-up answer carries: the rows Watch, When and Then, as the cards and their
    values, and the schedule."""

    use_case_id: str
    name: str
    portal_link: str
    schedule: Schedule | None
    agents: Sequence[PlannedAgent]
    error_workflow: str


def lay_out(plan: LayoutPlan) -> Document:
    """The release check when the only agent is the Version checker, else one Agent block per
    card."""
    match plan.agents:
        case [PlannedAgent(card_id=card_id, values=values)] if card_id == VERSION_CHECKER_ID:
            given = dict(values)
            return release_check(plan, given[REPO_INPUT], given[PROJECT_INPUT])
        case _:
            return agent_cards(plan)


class _Canvas:
    def __init__(self, key: str) -> None:
        self.key = key
        self.nodes: list[dict[str, Any]] = []
        self.connections: dict[str, dict[str, list[list[dict[str, Any]]]]] = {}

    def node(
        self,
        name: str,
        kind: BlockKind,
        column: int,
        row: int,
        parameters: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> str:
        node: dict[str, Any] = {
            "id": block_id(self.key, name),
            "name": name,
            "type": TYPE_OF[kind],
            "typeVersion": TYPE_VERSIONS.get(kind, 1),
            "position": [column * STEP, row * ROW],
            "parameters": dict(parameters or {}),
        }
        if NODE_TYPES[TYPE_OF[kind]].retried:
            node.update(RETRY)
        node.update(extra)
        self.nodes.append(node)
        return name

    def link(self, source: str, target: str, exit_index: int = 0) -> None:
        outputs = self.connections.setdefault(source, {"main": []})["main"]
        while len(outputs) <= exit_index:
            outputs.append([])
        outputs[exit_index].append({"node": target, "type": "main", "index": 0})

    def document(self, plan: LayoutPlan) -> Document:
        return {
            "name": plan.name,
            "nodes": self.nodes,
            "connections": self.connections,
            "settings": {**SETTINGS, "errorWorkflow": plan.error_workflow},
        }


def block_id(key: str, name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wab:{key}/{name}"))


def _starts(canvas: _Canvas, plan: LayoutPlan) -> list[str]:
    """The schedule, when it has one, and Start from the Portal, which Run now and a test run
    use."""
    starts: list[str] = []
    if plan.schedule is not None:
        starts.append(
            canvas.node(when_label(plan.schedule), "schedule", 0, 0, schedule_rule(plan.schedule))
        )
    starts.append(
        canvas.node(START, "start", 0, 1, webhookId=block_id(plan.use_case_id, "webhook/start"))
    )
    return starts


def _about(canvas: _Canvas, plan: LayoutPlan, what: str) -> None:
    content = (
        f"## {plan.name}\n{what}\n\nSet up in the Portal: {plan.portal_link}\n\n"
        "Safe to change here: when it runs, and the words in a block. Every change to Jira "
        "waits for a yes in Teams before it is made."
    )
    canvas.node(ABOUT, "note", 0, -2, {"content": content, "height": 260, "width": 460})


def release_check(plan: LayoutPlan, repo: str, project: str) -> Document:
    """The sketch's release check: read the newest release, the Version checker compares it with
    the tickets, and only a newer one goes on to a ticket. A quiet run ends at Nothing to
    change."""
    canvas = _Canvas(plan.use_case_id)
    _about(canvas, plan, f"Checks {repo} for a new release and raises a ticket in {project}.")
    starts = _starts(canvas, plan)
    read = canvas.node(READ_RELEASE, "read", 1, 0, {"source": "github_releases", "place": repo})
    for start in starts:
        canvas.link(start, read)
    compare = canvas.node(
        COMPARE,
        "agent",
        2,
        0,
        _agent_parameters(VERSION_CHECKER_ID, [(REPO_INPUT, repo), (PROJECT_INPUT, project)]),
    )
    newer = canvas.node(NEWER, "branch", 3, 0, _is_true(plan.use_case_id, "newer"))
    write = canvas.node(CREATE_TICKET, "write", 4, 0)
    quiet = canvas.node(NOTHING_TO_CHANGE_BLOCK, "end", 4, 1)
    canvas.link(read, compare)
    canvas.link(compare, newer)
    canvas.link(newer, write, 0)
    canvas.link(newer, quiet, 1)
    return canvas.document(plan)


def agent_cards(plan: LayoutPlan) -> Document:
    """One Agent block per card, in order. When a card writes, the changes are made at the end,
    and a run with nothing to change ends at Nothing to change."""
    canvas = _Canvas(plan.use_case_id)
    names = ", ".join(agent.name for agent in plan.agents)
    _about(canvas, plan, f"Runs {names}.")
    previous = _starts(canvas, plan)
    taken: set[str] = {START, ABOUT, *previous}
    for column, agent in enumerate(plan.agents, start=1):
        name = free_name(agent.name, taken)
        taken.add(name)
        canvas.node(name, "agent", column, 0, _agent_parameters(agent.card_id, agent.values))
        for source in previous:
            canvas.link(source, name)
        previous = [name]
    if any(agent.writes for agent in plan.agents):
        column = len(plan.agents) + 1
        write = canvas.node(free_name(CREATE_TICKET, taken), "write", column, 0)
        canvas.node(NOTHING_TO_CHANGE_BLOCK, "end", column, 1)
        canvas.link(previous[0], write)
    return canvas.document(plan)


def watchlist(plan: LayoutPlan, project: str) -> Document:
    """The Software watchlist (D11): read the watchlist, check every watched software at once,
    and raise one upgrade ticket for each that is behind."""
    canvas = _Canvas(plan.use_case_id)
    _about(canvas, plan, f"Checks every watched software and raises upgrade tickets in {project}.")
    starts = _starts(canvas, plan)
    read = canvas.node(
        READ_WATCHLIST, "read", 1, 0, {"source": "github_releases", "place": WATCHLIST_PLACE}
    )
    for start in starts:
        canvas.link(start, read)
    check = canvas.node(
        CHECK_WATCHLIST,
        "agent",
        2,
        0,
        _agent_parameters(WATCHLIST_AGENT, [(PROJECT_INPUT, project)]),
    )
    write = canvas.node("Create tickets", "write", 3, 0)
    canvas.node(NOTHING_TO_CHANGE_BLOCK, "end", 3, 1)
    canvas.link(read, check)
    canvas.link(check, write)
    return canvas.document(plan)


def _agent_parameters(agent: str, values: Sequence[tuple[str, str]]) -> dict[str, Any]:
    rows = [{"name": name, "value": value} for name, value in values]
    return {"agent": agent, "inputs": {"input": rows}}


def _is_true(key: str, field: str) -> dict[str, Any]:
    """IF on one true or false field of the item before it. Its exit 0 is true, 1 is false."""
    return {
        "conditions": {
            "options": {"caseSensitive": True, "typeValidation": "loose", "version": 2},
            "conditions": [
                {
                    "id": block_id(key, f"condition/{field}"),
                    "leftValue": f"={{{{ $json.{field} }}}}",
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }
            ],
            "combinator": "and",
        },
        "options": {},
    }


def schedule_rule(schedule: Schedule) -> dict[str, Any]:
    """The Schedule Trigger's rule, always with its hour and minute, so n8n picks neither
    (P7 Q12)."""
    hour, minute = (int(part) for part in schedule.at.split(":"))
    at = {"triggerAtHour": hour, "triggerAtMinute": minute}
    if schedule.day == "every_day":
        return {"rule": {"interval": [{"field": "days", **at}]}}
    return {
        "rule": {"interval": [{"field": "weeks", "triggerAtDay": CRON_DAYS[schedule.day], **at}]}
    }


def when_label(schedule: Schedule) -> str:
    """The sketch's short words for when it runs, such as "Daily 8:00" or "Mon 9:00"."""
    hour, minute = schedule.at.split(":")
    return f"{DAY_LABELS[schedule.day]} {int(hour)}:{minute}"
