"""The safety checker's grade for an n8n workflow, and the yes it puts before a write
(ENGINE-PLAN 2.4 and 2.5, ADR 0027).

The grade is not the barrier. The write gateway checks our records at the moment of each write,
and n8n's allow list leaves no block that can reach anything else. The grade tells a person,
before anything runs, whether a workflow will be refused: `writes_refused` when a write can run
without a yes, `needs_a_fix` when it cannot run as the platform expects at all, as when a block,
its version or what it was asked to do is off in the class file (ADR 0045).

Pure. A document is the n8n workflow JSON as the public API takes it.
"""

import hashlib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from platform_api.orchestration import n8n_schedule, node_classes
from platform_api.orchestration.agents import CardInput
from platform_api.orchestration.n8n_calls import WRITE_TARGETS, Grade, WriteEntry
from platform_api.orchestration.n8n_schedule import interval_problem, schedule_intervals
from platform_api.orchestration.node_classes import CLASS_FILE, NODE_CLASSES, BlockKind, Off
from platform_api.orchestration.schedule import TIME_ZONE

type Document = dict[str, Any]


@dataclass(frozen=True)
class NodeType:
    kind: BlockKind
    retried: bool = False
    """The Planner sets retryOnFail, 3 tries 2 s apart (ENGINE-PLAN 2.2). Never on Ask for a
    yes, because a retried ask would send a second request."""
    starts: bool = False
    """It can start an execution."""


STARTS: frozenset[BlockKind] = frozenset({"schedule", "start", "manual", "error"})
RETRIED: frozenset[BlockKind] = frozenset({"read", "agent", "propose", "write", "tell"})

NODE_TYPES: Mapping[str, NodeType] = {
    name: NodeType(kind, retried=kind in RETRIED, starts=kind in STARTS)
    for name, kind in NODE_CLASSES.blocks().items()
}
"""Every type the class file turns on: our node pack, as n8n names a custom extension's nodes
(`CUSTOM.<name>`, P7 Q11), n8n's three triggers, IF, Merge, No Op, Sticky Note and its data
nodes. Whether one block may run also depends on its version and what it does."""

GRADING_RULES = hashlib.sha256(
    b"".join(
        Path(f).read_bytes()
        for f in (__file__, node_classes.__file__, CLASS_FILE, n8n_schedule.__file__)
    )
).hexdigest()[:16]
"""The rules a grade is made under: this checker, the class file and the schedule rules, as this
release holds them. The versions sweep grades again a version graded under others."""

TYPE_OF: Mapping[BlockKind, str] = {
    spec.kind: name for name, spec in NODE_TYPES.items() if spec.kind != "shape"
}

ASK_EXITS = ("No answer", "Yes", "No", "Nothing to change")
"""Ask for a yes's exits in n8n's order. Output 0 is No answer, so an error path that n8n sends
out of output 0 never writes (P7 Q14)."""
YES = ASK_EXITS.index("Yes")
NOTHING_TO_CHANGE = ASK_EXITS.index("Nothing to change")
NOTHING_TO_CHANGE_BLOCK = "Nothing to change"
"""The No Op a layout ends a quiet branch with. A yes the checker adds sends its own Nothing to
change exit there too."""

TELL_WHERE = frozenset({"channel", "email", "both"})
ASK_TYPE_VERSION = 1
ADDED_SPACING = 220


@dataclass(frozen=True)
class Finding:
    grade: Grade
    block: str | None
    text: str


@dataclass(frozen=True)
class Graded:
    grade: Grade
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class KnownOptions:
    """What the editor's lists hold now, so a block that names anything else needs a fix."""

    agents: frozenset[str]
    places: Mapping[str, frozenset[str]]
    """Read places by source."""
    writes: Mapping[str, frozenset[str]]
    """Propose a change places by change."""
    inputs: Mapping[str, Mapping[str, frozenset[str] | None]]
    """Each agent's inputs, and for an input that names where a write lands, the places allowed.
    None allows any value."""


def known_options(
    agents: Mapping[str, Sequence[CardInput]],
    places: Mapping[str, Iterable[str]],
    writes: Sequence[WriteEntry],
) -> KnownOptions:
    """The editor's lists as one snapshot, with the same write targets the node calls check."""
    by_connector: dict[str, set[str]] = {}
    for entry in writes:
        by_connector.setdefault(entry.connector, set()).update(o.id for o in entry.places)
    inputs = {
        agent: {
            item.name: (
                None
                if (connector := WRITE_TARGETS.get(item.kind)) is None
                else frozenset(by_connector.get(connector, set()))
            )
            for item in items
        }
        for agent, items in agents.items()
    }
    return KnownOptions(
        frozenset(agents),
        {source: frozenset(listed) for source, listed in places.items()},
        {entry.id: frozenset(o.id for o in entry.places) for entry in writes},
        inputs,
    )


class _Target(BaseModel):
    model_config = ConfigDict(extra="allow")
    node: str
    type: str = "main"
    index: int = 0


class _Outputs(BaseModel):
    model_config = ConfigDict(extra="allow")
    main: list[list[_Target] | None] = Field(default_factory=list[list[_Target] | None])


class _Node(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    type: str = ""
    typeVersion: JsonValue = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0])


class N8nDocument(BaseModel):
    """An n8n workflow as the public API takes it. Fields this module does not read are kept."""

    model_config = ConfigDict(extra="allow")
    nodes: list[_Node]
    connections: dict[str, _Outputs]
    settings: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


@dataclass(frozen=True)
class Block:
    name: str
    type: str
    parameters: Mapping[str, JsonValue]
    version: JsonValue = None

    @property
    def spec(self) -> NodeType | None:
        return NODE_TYPES.get(self.type)


@dataclass(frozen=True)
class Edge:
    source: str
    exit: int
    target: str


@dataclass(frozen=True)
class Flow:
    """A document read as blocks and the edges between their exits."""

    blocks: Mapping[str, Block]
    edges: tuple[Edge, ...]
    settings: Mapping[str, JsonValue]

    def after(self, name: str) -> list[Edge]:
        return [edge for edge in self.edges if edge.source == name]

    def of_kind(self, *kinds: BlockKind) -> list[Block]:
        return [b for b in self.blocks.values() if b.spec is not None and b.spec.kind in kinds]


class Unreadable(ValueError):
    pass


def parse(document: Mapping[str, Any]) -> N8nDocument:
    """Raises Unreadable when the document is not an n8n workflow's shape."""
    try:
        parsed = N8nDocument.model_validate(document)
    except ValidationError:
        raise Unreadable("It is not an n8n workflow the platform can read.") from None
    names = {node.name for node in parsed.nodes}
    if len(names) != len(parsed.nodes):
        raise Unreadable("Two blocks have the same name.")
    for source, outputs in parsed.connections.items():
        for targets in outputs.main:
            if any(target.node not in names for target in targets or []):
                raise Unreadable(f'"{source}" connects to a block that is not there.')
    return parsed


def read_flow(document: Mapping[str, Any]) -> Flow:
    """Raises Unreadable when the document is not an n8n workflow's shape."""
    parsed = parse(document)
    blocks = {
        node.name: Block(node.name, node.type, node.parameters, node.typeVersion)
        for node in parsed.nodes
    }
    edges = tuple(
        Edge(source, exit_index, target.node)
        for source, outputs in parsed.connections.items()
        for exit_index, targets in enumerate(outputs.main)
        for target in targets or []
    )
    return Flow(blocks, edges, parsed.settings)


def writes(document: Mapping[str, Any]) -> list[str]:
    """The names of the blocks that make changes."""
    return [block.name for block in read_flow(document).of_kind("write")]


def grade(
    document: Mapping[str, Any], error_workflow: str | None, known: KnownOptions | None = None
) -> Graded:
    """The worst of the findings: `needs_a_fix` over `writes_refused` over `safe`."""
    try:
        flow = read_flow(document)
    except Unreadable as unreadable:
        return _graded([Finding("needs_a_fix", None, str(unreadable))])
    findings: list[Finding] = [
        *_off_blocks(flow),
        *_triggers(flow),
        *_settings(flow, error_workflow),
        *_parameters(flow),
        *_schedules(flow),
        *(() if known is None else _options(flow, known)),
        *_yes_before_writes(flow),
    ]
    return _graded(findings)


ERROR_WORKFLOW = "run_failure_reporter"
SELF_TEST = "self_test_failure"
PLATFORM_WORKFLOWS_DIR = Path(__file__).parent / "workflows"
"""Where bootstrap reads the platform's own n8n workflows, one `<name>.n8n.json` each."""


@dataclass(frozen=True)
class PlatformShape:
    """The one shape one of the platform's own n8n workflows may have."""

    chain: tuple[BlockKind, ...]
    """Its blocks, from the trigger on, each leading to the next by its first exit."""
    said: str
    kept: Mapping[str, JsonValue]
    """Settings it must keep as they are."""
    reports_failures: bool
    """Its failures go to the error workflow."""


PLATFORM_SHAPES: Mapping[str, PlatformShape] = {
    ERROR_WORKFLOW: PlatformShape(
        ("error", "report"),
        "an Error Trigger, then Report a failure",
        # Without it n8n refuses to report for a workflow held in a member's project (P7 Q13).
        {"callerPolicy": "any"},
        reports_failures=False,
    ),
    SELF_TEST: PlatformShape(
        ("schedule", "read"),
        "a Schedule Trigger, then a Read",
        {"timezone": TIME_ZONE},
        reports_failures=True,
    ),
}
"""The platform's own n8n workflows, which bootstrap loads and checks (ENGINE-PLAN 2.8): the
error workflow, and the daily self-test that fails on purpose to prove it reports."""


def check_platform(document: Mapping[str, Any], error_workflow: str | None) -> tuple[Finding, ...]:
    """Every way the document differs from its platform shape, none for a document in shape."""
    name = str(document.get("name"))
    shape = PLATFORM_SHAPES.get(name)
    if shape is None:
        return (_fix(None, f'"{name}" is not one of the platform\'s own workflows.'),)
    try:
        flow = read_flow(document)
    except Unreadable as unreadable:
        return (_fix(None, str(unreadable)),)
    findings = [*_chain(flow, shape), *_kept(flow, shape.kept), *_off_blocks(flow)]
    findings += _schedules(flow)
    reported = error_workflow is not None and flow.settings.get("errorWorkflow") == error_workflow
    if shape.reports_failures and not reported:
        findings.append(_fix(None, "Its failures do not go to the platform's error workflow."))
    return tuple(findings)


def _chain(flow: Flow, shape: PlatformShape) -> Iterable[Finding]:
    names = [block.name for kind in shape.chain for block in flow.of_kind(kind)]
    edges = {Edge(source, 0, target) for source, target in pairwise(names)}
    if len(names) != len(shape.chain) or len(flow.blocks) != len(names) or set(flow.edges) != edges:
        yield _fix(None, f"It must be {shape.said}, and nothing else.")


def _kept(flow: Flow, kept: Mapping[str, JsonValue]) -> Iterable[Finding]:
    for key, value in kept.items():
        if flow.settings.get(key) != value:
            yield _fix(None, f"Its setting {key} must be {value!r}.")


def _graded(findings: Sequence[Finding]) -> Graded:
    grades = {finding.grade for finding in findings}
    worst: Grade = (
        "needs_a_fix"
        if "needs_a_fix" in grades
        else "writes_refused"
        if "writes_refused" in grades
        else "safe"
    )
    return Graded(worst, tuple(findings))


def _fix(block: str | None, text: str) -> Finding:
    return Finding("needs_a_fix", block, text)


def _off_blocks(flow: Flow) -> Iterable[Finding]:
    """Every block the class file does not let run: its type, its version, or what it was asked
    to do. Unknown means off (ADR 0045)."""
    for block in flow.blocks.values():
        verdict = NODE_CLASSES.verdict(block.type, block.version, block.parameters)
        if isinstance(verdict, Off):
            yield _fix(block.name, _off_words(block, verdict))


def _off_words(block: Block, off: Off) -> str:
    match off.because:
        case "type":
            return f'"{block.name}" uses a block that is off: {block.type}.'
        case "version":
            return f'"{block.name}" uses version {off.value} of {block.type}, which is off.'
        case "expression":
            return f'"{block.name}" picks what it does with an expression, so it is off.'
        case "operation":
            return f'"{block.name}" does something that is off: {off.value}.'


def _triggers(flow: Flow) -> Iterable[Finding]:
    if not flow.of_kind("schedule", "start"):
        yield _fix(None, "Nothing starts it: it has no Schedule and no Start from the Portal.")


def _settings(flow: Flow, error_workflow: str | None) -> Iterable[Finding]:
    settings = flow.settings
    if error_workflow is None or settings.get("errorWorkflow") != error_workflow:
        yield _fix(None, "Its failures do not go to the platform's error workflow.")
    if settings.get("timezone") != TIME_ZONE:
        yield _fix(None, "It does not run on Singapore time.")
    if settings.get("saveManualExecutions") is not True:
        yield _fix(None, "n8n does not keep its test runs.")
    if settings.get("saveExecutionProgress") is not True:
        yield _fix(None, "n8n does not save its progress, so a run cannot be linked.")


def _parameters(flow: Flow) -> Iterable[Finding]:
    for block in flow.of_kind("tell"):
        if block.parameters.get("where", "channel") not in TELL_WHERE:
            yield _fix(block.name, f'"{block.name}" tells somewhere other than the fixed places.')


def _schedules(flow: Flow) -> Iterable[Finding]:
    """n8n picks a missing hour or minute itself, and runs "every 2 days" or "every 5 hours" by
    state it keeps, so the next run could not be shown to the minute (P7 Q12)."""
    for block in flow.of_kind("schedule"):
        intervals = schedule_intervals(block.parameters)
        if not intervals:
            yield _fix(block.name, f'"{block.name}" has no time to run.')
        for interval in intervals:
            problem = interval_problem(interval)
            if problem is not None:
                yield _fix(block.name, f'"{block.name}" {problem}')


def _options(flow: Flow, known: KnownOptions) -> Iterable[Finding]:
    for block in flow.of_kind("agent"):
        agent = block.parameters.get("agent")
        if not isinstance(agent, str) or agent not in known.agents:
            yield _fix(block.name, f'"{block.name}" names an agent the platform does not know.')
            continue
        allowed = known.inputs.get(agent, {})
        for name, value in _input_rows(block):
            if name not in allowed:
                yield _fix(block.name, f'"{block.name}" gives its agent an input it does not have.')
            elif (places := allowed[name]) is not None and value not in places:
                yield _fix(
                    block.name, f'"{block.name}" writes to a place the platform does not allow.'
                )
    for block in flow.of_kind("read"):
        source = str(block.parameters.get("source", "github_releases"))
        if block.parameters.get("place") not in known.places.get(source, frozenset()):
            yield _fix(block.name, f'"{block.name}" reads a place the platform does not allow.')
    for block in flow.of_kind("propose"):
        places = known.writes.get(str(block.parameters.get("action")))
        if places is None or block.parameters.get("place") not in places:
            yield _fix(block.name, f'"{block.name}" proposes a change the platform does not allow.')


def _input_rows(block: Block) -> list[tuple[str, JsonValue]]:
    """An Agent block's inputs, as its fixed collection holds them."""
    inputs = block.parameters.get("inputs")
    rows = inputs.get("input") if isinstance(inputs, dict) else None
    if not isinstance(rows, list):
        return []
    return [(str(row.get("name")), row.get("value")) for row in rows if isinstance(row, dict)]


def _yes_before_writes(flow: Flow) -> Iterable[Finding]:
    """Walks every path from every block that starts an execution. A path has a yes only once it
    leaves an Ask for a yes by its Yes exit."""
    unapproved: dict[str, None] = {}
    doubled: dict[str, None] = {}
    starts = [b.name for b in flow.blocks.values() if b.spec is not None and b.spec.starts]
    seen: set[tuple[str, bool, bool]] = set()
    stack = [(name, False, False) for name in starts]
    while stack:
        state = stack.pop()
        if state in seen:
            continue
        seen.add(state)
        name, approved, asked = state
        kind = _kind(flow, name)
        if kind == "write" and not approved:
            unapproved[name] = None
        if kind == "ask" and asked:
            doubled[name] = None
        for edge in flow.after(name):
            if kind == "ask":
                stack.append((edge.target, edge.exit == YES, True))
            else:
                stack.append((edge.target, approved, asked))
    for name in unapproved:
        yield Finding("writes_refused", name, f'"{name}" can run without a yes.')
    for name in doubled:
        yield _fix(name, f'"{name}" asks for a second yes on the same path.')


def _kind(flow: Flow, name: str) -> BlockKind | None:
    spec = flow.blocks[name].spec
    return None if spec is None else spec.kind


@dataclass(frozen=True)
class WithYes:
    document: Document
    added_before: tuple[str, ...]
    """The writes that a yes was put in front of, in the document's order."""


def add_yes(document: Mapping[str, Any], key: str) -> WithYes:
    """Puts an Ask for a yes in front of each write that a path reaches without one. The ask takes
    every edge that led to the write, its Yes exit leads on to the write, and its Nothing to
    change exit ends at the layout's "Nothing to change" when there is one. `key` makes the new
    blocks' ids the same for the same workflow, so a layout is reproducible. Everything else in
    the document stays exactly as it was.

    Raises Unreadable for a document that is not an n8n workflow's shape."""
    flow = read_flow(document)
    needing = {f.block for f in _yes_before_writes(flow) if f.grade == "writes_refused"}
    result: Document = deepcopy(dict(document))
    nodes = cast(list[dict[str, Any]], result["nodes"])
    connections = cast(
        dict[str, dict[str, list[list[dict[str, Any]] | None]]], result["connections"]
    )
    ordered = tuple(str(node["name"]) for node in nodes if node["name"] in needing)
    quiet = flow.blocks.get(NOTHING_TO_CHANGE_BLOCK)
    ends_quietly = quiet is not None and quiet.spec is not None and quiet.spec.kind == "end"
    taken = set(flow.blocks)
    for write in ordered:
        ask = free_name("Ask for a yes", taken)
        taken.add(ask)
        node = next(n for n in nodes if n["name"] == write)
        x, y = cast(list[float], node.get("position") or [0, 0])
        node["position"] = [x + ADDED_SPACING, y]
        nodes.insert(
            nodes.index(node),
            {
                "id": block_id(key, ask),
                "name": ask,
                "type": TYPE_OF["ask"],
                "typeVersion": ASK_TYPE_VERSION,
                "position": [x, y],
                "parameters": {},
            },
        )
        for outputs in connections.values():
            for targets in outputs.get("main", []):
                for target in targets or []:
                    if target.get("node") == write:
                        target["node"] = ask
        exits: list[list[dict[str, Any]] | None] = [[] for _ in ASK_EXITS]
        exits[YES] = [_edge_to(write)]
        if ends_quietly:
            exits[NOTHING_TO_CHANGE] = [_edge_to(NOTHING_TO_CHANGE_BLOCK)]
        connections[ask] = {"main": exits}
    return WithYes(result, ordered)


def _edge_to(name: str) -> dict[str, Any]:
    return {"node": name, "type": "main", "index": 0}


def block_id(key: str, name: str) -> str:
    """A block's id, the same every time for the same workflow and name."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wab:{key}/{name}"))


def free_name(wanted: str, taken: set[str]) -> str:
    if wanted not in taken:
        return wanted
    number = 2
    while f"{wanted} {number}" in taken:
        number += 1
    return f"{wanted} {number}"
