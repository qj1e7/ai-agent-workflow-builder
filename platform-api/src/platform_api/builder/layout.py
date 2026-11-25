"""The Planner lays out each use case as an n8n workflow of its own, from our node pack
(ENGINE-PLAN 2.5).

The layout is code, not a model call: the model chooses the cards and their values (ADR 0023),
and this places the blocks. Block names are the sketch's words, so the run line, the build
canvas and n8n read the same. A layout leaves out the yes. The safety checker puts it in front
of the write, which is what the build panel shows ("I added an approval step. Before each
ticket is made, an Approver must approve it in Teams.").

A layout may also place one of n8n's own blocks that the class file classes to read or post a
notice, with the key the platform made for it (ADR 0045). The Planner proposes none yet.

Pure. Ids come from the use case's id, so the same use case always gets the same document.
"""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from platform_api.orchestration import (
    GITHUB_RELEASES,
    KEY_FOR_TYPE,
    KEYS,
    NODE_CLASSES,
    NODE_TYPES,
    NOTHING_TO_CHANGE_BLOCK,
    REPO_INPUT,
    TYPE_OF,
    VERSION_CHECKER_ID,
    WATCHLIST_CHECKER,
    WATCHLIST_PLACE,
    BlockKind,
    Day,
    Document,
    KeySpec,
    PlanBlock,
    Runs,
    Schedule,
    Unreadable,
    WorkflowPlan,
    block_id,
    face,
    free_name,
    read_flow,
    skipped_in_tests,
    zone_words,
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
PROJECT_INPUT = "Jira project"

STEP = 220
ROW = 200
TYPE_VERSIONS: Mapping[BlockKind, float] = {"schedule": 1.2, "branch": 2}
RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}
SETTINGS = {
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
class N8nBlock:
    """One of n8n's own blocks, as a layout places it, with the platform's key it runs with."""

    name: str
    node_type: str
    version: float
    parameters: Mapping[str, Any]
    key: KeySpec
    slot: str
    """The n8n credential type the block asks for its key by, as its parameters pick it."""


def slack_notice(name: str, channel: str, text: str) -> N8nBlock:
    """n8n's Slack block posting to one channel, written in the block (the Tell rule)."""
    parameters = {
        "select": "channel",
        "channelId": {"__rl": True, "value": channel, "mode": "id"},
        "text": text,
        "otherOptions": {},
    }
    return N8nBlock(name, KEYS["slack"].node_type, 2.7, parameters, KEYS["slack"], "slackApi")


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
    time_zone: str
    """The team time zone, which the workflow and its Schedule Trigger run on."""


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
        self.pins: dict[str, list[dict[str, Any]]] = {}
        """Each notice block's output in a test run, which n8n uses in place of running it, so a
        test run posts nothing. n8n ignores it in every other run."""

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

    def n8n_block(self, block: N8nBlock, column: int, row: int) -> str:
        """Only a block the class file lets read or post, so a layout never names one that is
        off, and never one without the platform's key."""
        seen = face(block.node_type, block.version, dict(block.parameters))
        if seen.kind != "system" or seen.tag is None:
            raise ValueError(f"{block.node_type} does not read or post as its parameters say")
        self.nodes.append(
            {
                "id": block_id(self.key, block.name),
                "name": block.name,
                "type": block.node_type,
                "typeVersion": block.version,
                "position": [column * STEP, row * ROW],
                "parameters": dict(block.parameters),
                "credentials": {block.slot: {"id": block.key.id, "name": block.key.name}},
            }
        )
        if seen.notice:
            self.pins[block.name] = [{"json": {"skipped": skipped_in_tests(block.key.said)}}]
        return block.name

    def drafted(
        self, block: PlanBlock, column: int, row: int, parameters: Mapping[str, Any]
    ) -> str:
        """One block of a drafted plan, as the drafter chose it. Our blocks get the retries every
        layout gives them, and each of n8n's own blocks that could change or send something gets
        pinned output, so a test run changes and sends nothing (ADR 0051, section 4)."""
        version = int(block.version) if block.version.is_integer() else block.version
        node: dict[str, Any] = {
            "id": block_id(self.key, block.name),
            "name": block.name,
            "type": block.type,
            "typeVersion": version,
            "position": [column * STEP, row * ROW],
            "parameters": dict(parameters),
        }
        spec = NODE_TYPES.get(block.type)
        if spec is not None and spec.retried:
            node.update(RETRY)
        self.nodes.append(node)
        if _could_change_or_send(block.type, version, parameters):
            self.pins[block.name] = [{"json": {"skipped": _skipped(block)}}]
        return block.name

    def link(self, source: str, target: str, exit_index: int = 0, input_index: int = 0) -> None:
        outputs = self.connections.setdefault(source, {"main": []})["main"]
        while len(outputs) <= exit_index:
            outputs.append([])
        outputs[exit_index].append({"node": target, "type": "main", "index": input_index})

    def document(self, plan: LayoutPlan | DraftedLayout) -> Document:
        return {
            "name": plan.name,
            "nodes": self.nodes,
            "connections": self.connections,
            "settings": {
                "timezone": plan.time_zone,
                **SETTINGS,
                "errorWorkflow": plan.error_workflow,
            },
            **({"pinData": self.pins} if self.pins else {}),
        }


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
    _note(canvas, plan.name, plan.portal_link, what)


def _note(canvas: _Canvas, name: str, portal_link: str, what: str) -> None:
    content = (
        f"## {name}\n{what}\n\nSet up in the Portal: {portal_link}\n\n"
        "Safe to change here: when it runs, and the words in a block. Every change to Jira "
        "waits for approval in Teams before it is made."
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


def release_notice(plan: LayoutPlan, repo: str, project: str, notice: N8nBlock) -> Document:
    """The release check that tells, in place of raising a ticket: a newer release goes on to
    one of n8n's own notice blocks, such as a post in a Slack channel. It changes no data, so it
    needs no yes (the Tell rule)."""
    canvas = _Canvas(plan.use_case_id)
    _about(canvas, plan, f"Checks {repo} for a new release and tells the team.")
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
    told = canvas.n8n_block(notice, 4, 0)
    quiet = canvas.node(NOTHING_TO_CHANGE_BLOCK, "end", 4, 1)
    canvas.link(read, compare)
    canvas.link(compare, newer)
    canvas.link(newer, told, 0)
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


def watchlist(plan: LayoutPlan) -> Document:
    """The Software watchlist (D11): read the watchlist, check every watched software at once,
    and raise one upgrade ticket for each that is behind. The tickets go to the watchlist's own
    Jira project, so the block does not name it again."""
    canvas = _Canvas(plan.use_case_id)
    _about(
        canvas,
        plan,
        "Checks every watched software and raises a ticket for each one behind.",
    )
    starts = _starts(canvas, plan)
    read = canvas.node(
        READ_WATCHLIST, "read", 1, 0, {"source": GITHUB_RELEASES, "place": WATCHLIST_PLACE.id}
    )
    for start in starts:
        canvas.link(start, read)
    check = canvas.node(CHECK_WATCHLIST, "agent", 2, 0, _agent_parameters(WATCHLIST_CHECKER.id, []))
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


@dataclass(frozen=True)
class DraftedLayout:
    """A drafted workflow's checked plan, and what the platform puts in every layout of it."""

    use_case_id: str
    """The id the workflow will have once it is set up, which its blocks' ids come from."""
    portal_link: str
    plan: WorkflowPlan
    error_workflow: str
    time_zone: str

    @property
    def name(self) -> str:
        return self.plan.name


def lay_out_drafted(drafted: DraftedLayout, values: Mapping[str, str]) -> Document:
    """The workflow drafter's plan as an n8n workflow (ADR 0051, flow step 3). Each setting's
    value goes where its placeholder stands, and a setting with no value keeps its placeholder, so
    the check reads it as still needed. Then it adds what every layout adds and the model never
    writes: the Sticky Note, Start from the Portal joined to what each trigger starts, the team
    time zone, the error workflow, saved progress, retries on our blocks, and pinned output on
    n8n's own blocks that could change or send something. Record the run after each trigger comes
    with build step 10, here, before the wires. The yes and the keys go on after this, as for
    every layout (`add_yes`, `attach_keys`)."""
    plan = drafted.plan
    canvas = _Canvas(drafted.use_case_id)
    _note(canvas, plan.name, drafted.portal_link, "Drafted by the Workflow drafter.")
    placed = _placed(plan, values, drafted.time_zone)
    columns = _columns(plan)
    rows: dict[int, int] = {}
    for block in plan.blocks:
        column = columns[block.name]
        rows[column] = rows.get(column, -1) + 1
        canvas.drafted(block, column, rows[column], placed[block.name])
    for wire in plan.wires:
        canvas.link(wire.from_block, wire.to_block, wire.exit_index, wire.input_index)
    _start_beside_triggers(canvas, plan, rows.get(0, -1) + 1)
    return canvas.document(drafted)


def _placed(
    plan: WorkflowPlan, values: Mapping[str, str], time_zone: str
) -> dict[str, dict[str, Any]]:
    """Each block's parameters with every value that has one in place of its placeholder."""
    placed = {block.name: deepcopy(block.parameters) for block in plan.blocks}
    for setting in plan.settings:
        value = values.get(setting.id)
        if value is None:
            continue
        put: Any = value
        if setting.kind == "run_time":
            schedule = _schedule_of(value, time_zone)
            if schedule is None:
                continue
            put = schedule_rule(schedule)["rule"]
        for place in setting.fills:
            _put(placed[place.block], place.parameter, f"<<{setting.id}>>", put)
    return placed


def _schedule_of(value: str, time_zone: str) -> Schedule | None:
    """Code's reading of a run time, as "monday 09:00". The person's own words for one code
    can't read stay a placeholder, so the run time is still needed."""
    day, _, at = value.partition(" ")
    if day not in DAY_LABELS or len(at) != 5 or at[2] != ":":
        return None
    hour, minute = at.split(":")
    if not (hour.isdigit() and minute.isdigit() and int(hour) < 24 and int(minute) < 60):
        return None
    return Schedule(cast(Day, day), at, time_zone)


def _put(parameters: dict[str, Any], path: str, placeholder: str, value: Any) -> None:
    """The value at the path, only where the placeholder stands, so nothing else changes."""
    *parents, last = path.split(".")
    held: dict[str, Any] | None = parameters
    for part in parents:
        inner: object = None if held is None else held.get(part)
        held = cast(dict[str, Any], inner) if isinstance(inner, dict) else None
    if held is not None and held.get(last) == placeholder:
        held[last] = value


def _columns(plan: WorkflowPlan) -> dict[str, int]:
    """Each block's column: how many wires a run crosses to reach it from the nearest trigger."""
    targets = {wire.to_block for wire in plan.wires}
    column = {b.name: 0 for b in plan.blocks if b.name not in targets}
    queue = list(column)
    while queue:
        name = queue.pop(0)
        for wire in plan.wires:
            if wire.from_block == name and wire.to_block not in column:
                column[wire.to_block] = column[name] + 1
                queue.append(wire.to_block)
    return {b.name: column.get(b.name, 0) for b in plan.blocks}


def _start_beside_triggers(canvas: _Canvas, plan: WorkflowPlan, row: int) -> None:
    """Start from the Portal, joined to every block a trigger starts, so Run now and a test run
    can start it."""
    starts = {b.name for b in plan.blocks if _is_trigger(b.type)}
    joined = dict.fromkeys(
        (wire.to_block, wire.input_index) for wire in plan.wires if wire.from_block in starts
    )
    name = free_name(START, {b.name for b in plan.blocks} | {ABOUT})
    canvas.node(name, "start", 0, row, webhookId=block_id(canvas.key, "webhook/start"))
    for target, input_index in joined:
        canvas.link(name, target, 0, input_index)


def _is_trigger(node_type: str) -> bool:
    spec = NODE_TYPES.get(node_type)
    if spec is not None:
        return spec.starts
    return node_type.endswith("Trigger")


def _could_change_or_send(node_type: str, version: Any, parameters: Mapping[str, Any]) -> bool:
    """One of n8n's own blocks that isn't classed to read, or that the class file doesn't know."""
    if node_type.startswith("CUSTOM."):
        return False
    spec = NODE_TYPES.get(node_type)
    if spec is not None and spec.kind != "system":
        return False
    verdict = NODE_CLASSES.verdict(node_type, version, parameters)
    return not (isinstance(verdict, Runs) and verdict.on == "read")


def _skipped(block: PlanBlock) -> str:
    key = KEY_FOR_TYPE.get(block.type)
    return (
        skipped_in_tests(key.said) if key is not None else f"{block.name} skipped in the test run."
    )


FIXED_SETTINGS: Mapping[str, str] = {
    "errorWorkflow": "sends its failures to the platform's error workflow",
    "timezone": "runs it on {zone}",
    "saveManualExecutions": "keeps its test runs",
    "saveExecutionProgress": "saves its progress",
}
ADDS_START = "adds Start from the Portal for Run now"


@dataclass(frozen=True)
class FixedForYou:
    """A workflow made in n8n as Set up leaves it, with the platform's own plumbing put right,
    which is never its maker's job (ADR 0051, Fixed for you)."""

    document: Document
    fixed: tuple[str, ...]
    """What Set up changed, each in words that follow "Set up also"."""
    no_start: bool = False
    """It has a schedule, but no Start from the Portal, since no schedule that is on starts a
    block."""


def fixed_for_you(
    document: Mapping[str, Any], workflow_id: str, error_workflow: str | None, time_zone: str
) -> FixedForYou:
    """The settings every layout has, and Start from the Portal beside the schedule, joined to
    what the schedule starts, so Run now and a test run can start it."""
    try:
        read_flow(document)
    except Unreadable:
        return FixedForYou(dict(document), ())
    result: Document = deepcopy(dict(document))
    settings = dict(cast(dict[str, Any], result.get("settings") or {}))
    wanted = {
        "errorWorkflow": error_workflow,
        "timezone": time_zone,
        "saveManualExecutions": True,
        "saveExecutionProgress": True,
    }
    fixed: list[str] = []
    for setting, value in wanted.items():
        held = settings.get(setting)
        if value is not None and (type(held) is not type(value) or held != value):
            settings[setting] = value
            fixed.append(FIXED_SETTINGS[setting].format(zone=zone_words(time_zone)))
    result["settings"] = settings
    if _start_added(result, workflow_id):
        fixed.append(ADDS_START)
    nodes = cast(list[dict[str, Any]], result["nodes"])
    starts = any(n.get("type") == TYPE_OF["start"] and not n.get("disabled") for n in nodes)
    scheduled = any(n.get("type") == TYPE_OF["schedule"] for n in nodes)
    return FixedForYou(result, tuple(fixed), scheduled and not starts)


def _start_added(document: Document, workflow_id: str) -> bool:
    nodes = cast(list[dict[str, Any]], document["nodes"])
    on = [node for node in nodes if not node.get("disabled")]
    if any(node.get("type") == TYPE_OF["start"] for node in on):
        return False
    connections = cast(dict[str, dict[str, list[list[dict[str, Any]]]]], document["connections"])
    schedules = [node for node in on if node.get("type") == TYPE_OF["schedule"]]
    targets: dict[tuple[str, int], dict[str, Any]] = {}
    for schedule in schedules:
        for target in (connections.get(str(schedule["name"]), {}).get("main") or [[]])[0] or []:
            targets.setdefault((str(target["node"]), int(target.get("index", 0))), target)
    if not targets:
        return False
    name = free_name(START, {str(node["name"]) for node in nodes})
    x, y = cast(list[float], schedules[0].get("position") or [0, 0])
    nodes.append(
        {
            "id": block_id(workflow_id, START),
            "name": name,
            "type": TYPE_OF["start"],
            "typeVersion": 1,
            "position": [x, y + ROW],
            "parameters": {},
            "webhookId": block_id(workflow_id, "webhook/start"),
        }
    )
    connections[name] = {"main": [[dict(target) for target in targets.values()]]}
    return True
