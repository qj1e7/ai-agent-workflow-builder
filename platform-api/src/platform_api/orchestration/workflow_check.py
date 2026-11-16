"""The safety checker's grade for an n8n workflow, and the yes it puts before a write
(ENGINE-PLAN 2.4 and 2.5, ADR 0027).

For our own blocks the grade is not the barrier. The write gateway checks our records at the
moment of each write, and n8n's allow list leaves no block that can reach anything else. The
grade tells a person, before anything runs, whether a workflow will be refused: `writes_refused`
when a write can run without a yes, `needs_a_fix` when it cannot run as the platform expects at
all, as when a block, its version or what it was asked to do is off in the class file (ADR 0045).

n8n's own blocks never call our API, so n8n runs them whatever the grade says. A finding about
one of them `runs_anyway`: a version with such a finding must not run at all. For those blocks
the grade is the guard, with the platform's keys, which can only read or post, and the
credential sweep (ADR 0045, section 2): a notice posts only to a place written in the block, and
every key a block names must be one the platform made.

In the platform's own n8n project n8n lets a workflow use every key there is. So no version with
a finding that `runs_anyway` is ever live there, and no draft with one is ever run (`unchecked`).

Pure. A document is the n8n workflow JSON as the public API takes it.
"""

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from platform_api.orchestration import n8n_schedule, node_classes
from platform_api.orchestration.agents import CardInput
from platform_api.orchestration.n8n_calls import WRITE_TARGETS, Grade, WriteEntry
from platform_api.orchestration.n8n_schedule import interval_problem, schedule_intervals
from platform_api.orchestration.node_classes import (
    CLASS_FILE,
    NODE_CLASSES,
    OURS,
    BlockKind,
    Off,
    OffBecause,
    Runs,
    Use,
)
from platform_api.orchestration.platform_keys import KEY_FOR_TYPE

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


type RuleId = Literal[
    "unreadable",
    "block_off",
    "version_off",
    "picked_by_expression",
    "operation_off",
    "nothing_starts",
    "no_error_workflow",
    "other_time_zone",
    "test_runs_not_kept",
    "progress_not_saved",
    "tell_place",
    "notice_place_expression",
    "notice_words_expression",
    "notice_words_unreadable",
    "calls_everyone",
    "no_platform_key",
    "not_platform_key",
    "key_not_made",
    "key_for_other_block",
    "runs_before_ours",
    "no_run_time",
    "run_time_unshowable",
    "unknown_agent",
    "unknown_agent_input",
    "write_place_not_allowed",
    "read_place_not_allowed",
    "change_not_allowed",
    "no_yes_before_write",
    "second_yes",
]
"""Each rule the checker grades a workflow by (ADR 0051). FLAG_RULES has a row for each."""
type PlatformRule = Literal["platform_shape", "platform_setting", "not_platform_workflow"]
"""The rules only the platform's own n8n workflows are held to, which no report shows."""


@dataclass(frozen=True)
class Finding:
    rule: RuleId | PlatformRule
    grade: Grade
    block: str | None
    text: str
    runs_anyway: bool = False
    """n8n would run the block as it is, since it never calls the platform: one of n8n's own
    blocks that is off for what it does, posts to a place an expression picks, or uses a key
    the platform did not make. A version with such a finding is not set up or turned on."""


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
    keys: Mapping[str, str] = field(default_factory=dict[str, str])
    """The keys the platform made in n8n, by their id, with each one's n8n credential type."""


def known_options(
    agents: Mapping[str, Sequence[CardInput]],
    places: Mapping[str, Iterable[str]],
    writes: Sequence[WriteEntry],
    keys: Mapping[str, str] | None = None,
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
        dict(keys or {}),
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
    credentials: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    disabled: bool = False


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
    credentials: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    """The keys it names, by the n8n credential type each is for."""
    disabled: bool = False
    """Turned off in n8n's editor. n8n passes items straight through it (ADR 0051)."""

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
        node.name: Block(
            node.name, node.type, node.parameters, node.typeVersion, node.credentials, node.disabled
        )
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
    document: Mapping[str, Any],
    error_workflow: str | None,
    time_zone: str,
    known: KnownOptions | None = None,
) -> Graded:
    """The worst of the findings: `needs_a_fix` over `writes_refused` over `safe`. `time_zone`
    is the team time zone, which every workflow runs on."""
    try:
        flow = read_flow(document)
    except Unreadable as unreadable:
        return _graded([_fix("unreadable", None, str(unreadable))])
    findings: list[Finding] = [
        *_off_blocks(flow),
        *_triggers(flow),
        *_settings(flow, error_workflow, time_zone),
        *_parameters(flow),
        *_places(flow),
        *_words(flow),
        *_keys(flow, {} if known is None else known.keys),
        *_ours_first(flow),
        *_schedules(flow),
        *(() if known is None else _options(flow, known)),
        *_yes_before_writes(flow),
    ]
    return _graded(findings)


def unchecked(document: Mapping[str, Any], keys: Mapping[str, str]) -> tuple[Finding, ...]:
    """What n8n would run in the document whatever the platform says: one of its own blocks that
    is off, posts where an expression picks or calls out a whole channel, names a key the platform
    did not make, or runs before any of ours. `keys` is each key the platform made, by id, with
    its n8n credential type. A document the checker can't read counts as one, since n8n may still
    run it."""
    try:
        flow = read_flow(document)
    except Unreadable as unreadable:
        return (_fix("unreadable", None, str(unreadable), runs_anyway=True),)
    found = (
        *_off_blocks(flow),
        *_places(flow),
        *_words(flow),
        *_keys(flow, keys),
        *_ours_first(flow),
    )
    return tuple(finding for finding in found if finding.runs_anyway)


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
    scheduled: bool = False
    """Its Schedule Trigger runs on the team time zone, as every workflow's does."""


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
        {},
        reports_failures=True,
        scheduled=True,
    ),
}
"""The platform's own n8n workflows, which bootstrap loads and checks (ENGINE-PLAN 2.8): the
error workflow, and the daily self-test that fails on purpose to prove it reports."""


def platform_document(name: str, error_workflow: str | None, time_zone: str) -> Document:
    """One of the platform's own n8n workflows as bootstrap loads it: its failures go to the error
    workflow, and a scheduled one runs on the team time zone."""
    document: Document = json.loads((PLATFORM_WORKFLOWS_DIR / f"{name}.n8n.json").read_text())
    shape = PLATFORM_SHAPES[name]
    settings = document.setdefault("settings", {})
    if shape.reports_failures and error_workflow is not None:
        settings["errorWorkflow"] = error_workflow
    if shape.scheduled:
        settings["timezone"] = time_zone
    return document


def check_platform(
    document: Mapping[str, Any], error_workflow: str | None, time_zone: str
) -> tuple[Finding, ...]:
    """Every way the document differs from its platform shape, none for a document in shape."""
    name = str(document.get("name"))
    shape = PLATFORM_SHAPES.get(name)
    if shape is None:
        return (
            _fix(
                "not_platform_workflow",
                None,
                f'"{name}" is not one of the platform\'s own workflows.',
            ),
        )
    try:
        flow = read_flow(document)
    except Unreadable as unreadable:
        return (_fix("unreadable", None, str(unreadable)),)
    kept = {**shape.kept, **({"timezone": time_zone} if shape.scheduled else {})}
    findings = [*_chain(flow, shape), *_kept(flow, kept), *_off_blocks(flow)]
    findings += _schedules(flow)
    reported = error_workflow is not None and flow.settings.get("errorWorkflow") == error_workflow
    if shape.reports_failures and not reported:
        findings.append(_fix("no_error_workflow", None, NOT_REPORTED))
    return tuple(findings)


def _chain(flow: Flow, shape: PlatformShape) -> Iterable[Finding]:
    names = [block.name for kind in shape.chain for block in flow.of_kind(kind)]
    edges = {Edge(source, 0, target) for source, target in pairwise(names)}
    if len(names) != len(shape.chain) or len(flow.blocks) != len(names) or set(flow.edges) != edges:
        yield _fix("platform_shape", None, f"It must be {shape.said}, and nothing else.")


def _kept(flow: Flow, kept: Mapping[str, JsonValue]) -> Iterable[Finding]:
    for key, value in kept.items():
        if flow.settings.get(key) != value:
            yield _fix("platform_setting", None, f"Its setting {key} must be {value!r}.")


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


def _fix(
    rule: RuleId | PlatformRule, block: str | None, text: str, runs_anyway: bool = False
) -> Finding:
    return Finding(rule, "needs_a_fix", block, text, runs_anyway)


_UTC_NAMES = frozenset(
    {"UTC", "Etc/UTC", "GMT", "Etc/GMT", "GMT0", "Etc/GMT0", "GMT+0", "GMT-0", "Etc/UCT", "UCT"}
    | {"Universal", "Etc/Universal", "Zulu", "Etc/Zulu", "Greenwich", "Etc/Greenwich"}
)
_FIXED = re.compile(r"Etc/GMT([+-])(\d+)")
_CITY = re.compile(r"(?!Etc/)[A-Z][A-Za-z]+/(?:[A-Za-z_-]+/)?([A-Z][A-Za-z_-]+)")


def zone_words(time_zone: str) -> str:
    """A zone named as the Portal names it: "London time", "UTC", or "GMT+8" for Etc/GMT-8, whose
    sign is the other way round. A zone with no city shows its id: "EST5EDT time"."""
    if time_zone in _UTC_NAMES:
        return "UTC"
    if fixed := _FIXED.fullmatch(time_zone):
        hours = int(fixed[2])
        return "UTC" if hours == 0 else f"GMT{'-' if fixed[1] == '+' else '+'}{hours}"
    city = _CITY.fullmatch(time_zone)
    place = time_zone if city is None else re.sub(r"[_-]", " ", city[1])
    return f"{place} time"


OFF_RULES: Mapping[OffBecause, RuleId] = {
    "type": "block_off",
    "version": "version_off",
    "expression": "picked_by_expression",
    "operation": "operation_off",
}


def _off_blocks(flow: Flow) -> Iterable[Finding]:
    """Every block the class file does not let run: its type, its version, or what it was asked
    to do. Unknown means off (ADR 0045)."""
    for block in flow.blocks.values():
        verdict = NODE_CLASSES.verdict(block.type, block.version, block.parameters)
        if isinstance(verdict, Off):
            yield _fix(
                OFF_RULES[verdict.because],
                block.name,
                _off_words(block, verdict),
                _runs_anyway(block),
            )


SHAPES = "Shapes the data"
"""The tag of one of n8n's data blocks (ADR 0045, section 3)."""


@dataclass(frozen=True)
class Face:
    """What a block is to a person: what it does, whether it is one of ours or n8n's own, and the
    tag its class gives it, such as Reads Jira or Posts in Slack."""

    kind: BlockKind | None
    """None for a block that is off: its type, its version or what it was asked to do."""
    ours: bool
    tag: str | None
    notice: bool = False
    """One of n8n's own blocks that posts a notice, which a test run must skip."""


def face(node_type: str, version: JsonValue, parameters: Mapping[str, JsonValue]) -> Face:
    ours = node_type.startswith(OURS)
    spec = NODE_TYPES.get(node_type)
    if spec is None:
        return Face(None, ours, None)
    if spec.kind not in ("shape", "system"):
        return Face(spec.kind, ours, None)
    verdict = NODE_CLASSES.verdict(node_type, version, parameters)
    if isinstance(verdict, Off):
        return Face(None, ours, None)
    tag = SHAPES if spec.kind == "shape" else None if verdict.use is None else verdict.use.tag
    return Face(spec.kind, ours, tag, verdict.on == "notice")


def skipped_in_tests(said: str) -> str:
    """What a notice block's pinned output says, in place of a post, in a test run."""
    return f"{said} notice skipped in the test run."


def unpinned_notices(document: Mapping[str, Any]) -> list[str]:
    """Each of n8n's own notice blocks whose output is not pinned, which a test run, a manual run
    by hand, would post from. n8n ignores pinned output in every run that is not by hand."""
    pinned = cast(Mapping[str, Any], document.get("pinData") or {})
    return [
        str(node.get("name"))
        for node in cast(list[dict[str, Any]], document.get("nodes") or [])
        if not node.get("disabled")
        and face(
            str(node.get("type")), node.get("typeVersion"), node.get("parameters") or {}
        ).notice
        and not pinned.get(str(node.get("name")))
    ]


def _runs_anyway(block: Block) -> bool:
    """n8n loads the type, so it runs the block, and it is not one of ours, so it never asks."""
    return NODE_CLASSES.loads(block.type) and not block.type.startswith(OURS)


CALLS: frozenset[BlockKind] = frozenset({"read", "agent", "propose", "ask", "write", "tell"})
"""Our blocks that call the platform, so a run that meets one is linked and its version checked
before anything after it runs."""
OURS_FIRST = "Add one of our steps first, so each run is recorded."


def _ours_first(flow: Flow) -> Iterable[Finding]:
    """On every way from a trigger, one of our blocks that calls the platform comes before the
    first of n8n's own blocks for a system. That call links the run, so it is recorded and shown,
    and checks the version first, so a version that does not pass the check stops there before
    n8n reads or posts anything. One of ours turned off calls nothing, so it counts as absent,
    but one of n8n's turned off still counts (ADR 0051)."""
    starts = [b.name for b in flow.blocks.values() if b.spec is not None and b.spec.starts]
    early: dict[str, None] = {}
    seen: set[tuple[str, bool]] = set()
    stack = [(name, False) for name in starts]
    while stack:
        name, called = stack.pop()
        if (name, called) in seen:
            continue
        seen.add((name, called))
        kind = _kind(flow, name)
        if kind == "system" and not called:
            early[name] = None
        called = called or (kind in CALLS and not flow.blocks[name].disabled)
        stack.extend((edge.target, called) for edge in flow.after(name))
    for name in early:
        yield _fix(
            "runs_before_ours",
            name,
            f'"{name}" runs before any of our steps. {OURS_FIRST}',
            runs_anyway=True,
        )


def _places(flow: Flow) -> Iterable[Finding]:
    """The Tell rule for n8n's own notice blocks (ADR 0045, section 4): a notice posts only to a
    place written in the block, never to one an expression picks from what a run read."""
    for block in flow.blocks.values():
        verdict = NODE_CLASSES.verdict(block.type, block.version, block.parameters)
        if not isinstance(verdict, Runs) or verdict.on != "notice" or verdict.use is None:
            continue
        if not all(_literal(_at_path(block.parameters, path)) for path in verdict.use.target):
            yield _fix(
                "notice_place_expression",
                block.name,
                f'"{block.name}" posts to a place an expression picks, so it is off.',
                runs_anyway=True,
            )


MASS_MENTION = re.compile(r"<!(?:channel|here|everyone)\b|<!subteam\^|@(?:channel|here|everyone)\b")
"""Slack's words that call out everyone in a channel, a workspace or a user group, matched on text
in NFKC and case-folded."""
SAYS_WHAT_A_RUN_READ = "writes its message with an expression, so it is off. Use our Tell for that"
UNREADABLE_WORDS = "has a message the checker can't read, so it is off"
CALLS_EVERYONE = "calls out a whole channel, so it is off"
type NoticeWordsRule = Literal[
    "notice_words_expression", "notice_words_unreadable", "calls_everyone"
]
SAID: Mapping[NoticeWordsRule, str] = {
    "notice_words_expression": SAYS_WHAT_A_RUN_READ,
    "notice_words_unreadable": UNREADABLE_WORDS,
    "calls_everyone": CALLS_EVERYONE,
}


def _words(flow: Flow) -> Iterable[Finding]:
    """The Tell rule for what a notice says (ADR 0045, as amended): in this release n8n's own
    notice text is written out in the block, never an expression, so the checker reads all of it
    before anything runs, and a notice that says what a run read goes through our Tell. It never
    calls out a whole channel, in its words or by a switch such as Slack's link_names."""
    for block in flow.blocks.values():
        verdict = NODE_CLASSES.verdict(block.type, block.version, block.parameters)
        if not isinstance(verdict, Runs) or verdict.on != "notice" or verdict.use is None:
            continue
        rule = _said(block.parameters, verdict.use)
        if rule is not None:
            yield _fix(rule, block.name, f'"{block.name}" {SAID[rule]}.', runs_anyway=True)


def _said(parameters: Mapping[str, JsonValue], use: Use) -> NoticeWordsRule | None:
    said: list[str] = []
    for path in use.text:
        value = _at_path(parameters, path)
        texts = list(_texts(value))
        if any(text.startswith("=") for text in texts):
            return "notice_words_expression"
        if path in use.encoded and isinstance(value, str):
            try:
                texts = list(_texts(json.loads(value)))
            except ValueError:
                return "notice_words_unreadable"
        said += texts
    if any(MASS_MENTION.search(unicodedata.normalize("NFKC", text).casefold()) for text in said):
        return "calls_everyone"
    if any(_at_path(parameters, path) not in (None, False) for path in use.quiet):
        return "calls_everyone"
    return None


def _texts(value: JsonValue) -> Iterable[str]:
    match value:
        case str():
            yield value
        case dict():
            for inner in value.values():
                yield from _texts(inner)
        case list():
            for inner in value:
                yield from _texts(inner)
        case _:
            return


def _at_path(parameters: Mapping[str, JsonValue], path: str) -> JsonValue:
    value: JsonValue = dict(parameters)
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _literal(value: JsonValue) -> bool:
    """n8n reads a string that starts with = as an expression. A resource locator holds the
    place in its value."""
    match value:
        case str():
            return not value.startswith("=")
        case {"__rl": True, **rest}:
            return _literal(rest.get("value"))
        case dict():
            return all(_literal(v) for v in value.values())
        case list():
            return all(_literal(v) for v in value)
        case _:
            return True


def _keys(flow: Flow, keys: Mapping[str, str]) -> Iterable[Finding]:
    """Only the platform makes keys in n8n (ADR 0045). A block that names any other key would
    run with it, and in the platform's own n8n project n8n lets a workflow use every key there
    is, a member's too. A block for a system names the platform's key for it, or it cannot run:
    Teams, Outlook and Gmail have none."""
    for block in flow.blocks.values():
        spec = KEY_FOR_TYPE.get(block.type)
        runs = NODE_CLASSES.verdict(block.type, block.version, block.parameters)
        if block.spec is not None and block.spec.kind == "system" and isinstance(runs, Runs):
            if spec is None or spec.id not in keys:
                yield _fix(
                    "no_platform_key",
                    block.name,
                    f'"{block.name}" has no key: the platform has none for it.',
                )
            elif not any(
                isinstance(named, dict) and named.get("id") == spec.id
                for named in block.credentials.values()
            ):
                yield _fix(
                    "not_platform_key",
                    block.name,
                    f'"{block.name}" does not use the platform\'s key.',
                )
        for kind, named in block.credentials.items():
            key = named.get("id") if isinstance(named, dict) else None
            if not isinstance(key, str) or key not in keys:
                yield _fix(
                    "key_not_made",
                    block.name,
                    f'"{block.name}" uses a key the platform did not make.',
                    runs_anyway=True,
                )
            elif keys[key] != kind:
                yield _fix(
                    "key_for_other_block",
                    block.name,
                    f'"{block.name}" uses a platform key made for another block.',
                )


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
        yield _fix(
            "nothing_starts",
            None,
            "Nothing starts it: it has no Schedule and no Start from the Portal.",
        )


NOT_REPORTED = "Its failures do not go to the platform's error workflow."


def _settings(flow: Flow, error_workflow: str | None, time_zone: str) -> Iterable[Finding]:
    settings = flow.settings
    if error_workflow is None or settings.get("errorWorkflow") != error_workflow:
        yield _fix("no_error_workflow", None, NOT_REPORTED)
    if settings.get("timezone") != time_zone:
        yield _fix(
            "other_time_zone",
            None,
            f"It does not run on {zone_words(time_zone)}. "
            "Save its schedule again, or change its time zone in n8n.",
        )
    if settings.get("saveManualExecutions") is not True:
        yield _fix("test_runs_not_kept", None, "n8n does not keep its test runs.")
    if settings.get("saveExecutionProgress") is not True:
        yield _fix(
            "progress_not_saved", None, "n8n does not save its progress, so a run cannot be linked."
        )


def _parameters(flow: Flow) -> Iterable[Finding]:
    for block in flow.of_kind("tell"):
        if block.parameters.get("where", "channel") not in TELL_WHERE:
            yield _fix(
                "tell_place",
                block.name,
                f'"{block.name}" tells somewhere other than the fixed places.',
            )


def _schedules(flow: Flow) -> Iterable[Finding]:
    """n8n picks a missing hour or minute itself, and runs "every 2 days" or "every 5 hours" by
    state it keeps, so the next run could not be shown to the minute (P7 Q12)."""
    for block in flow.of_kind("schedule"):
        intervals = schedule_intervals(block.parameters)
        if not intervals:
            yield _fix("no_run_time", block.name, f'"{block.name}" has no time to run.')
        for interval in intervals:
            problem = interval_problem(interval)
            if problem is not None:
                yield _fix("run_time_unshowable", block.name, f'"{block.name}" {problem}')


def _options(flow: Flow, known: KnownOptions) -> Iterable[Finding]:
    for block in flow.of_kind("agent"):
        agent = block.parameters.get("agent")
        if not isinstance(agent, str) or agent not in known.agents:
            yield _fix(
                "unknown_agent",
                block.name,
                f'"{block.name}" names an agent the platform does not know.',
            )
            continue
        allowed = known.inputs.get(agent, {})
        for name, value in _input_rows(block):
            if name not in allowed:
                yield _fix(
                    "unknown_agent_input",
                    block.name,
                    f'"{block.name}" gives its agent an input it does not have.',
                )
            elif (places := allowed[name]) is not None and value not in places:
                yield _fix(
                    "write_place_not_allowed",
                    block.name,
                    f'"{block.name}" writes to a place the platform does not allow.',
                )
    for block in flow.of_kind("read"):
        source = str(block.parameters.get("source", "github_releases"))
        if block.parameters.get("place") not in known.places.get(source, frozenset()):
            yield _fix(
                "read_place_not_allowed",
                block.name,
                f'"{block.name}" reads a place the platform does not allow.',
            )
    for block in flow.of_kind("propose"):
        places = known.writes.get(str(block.parameters.get("action")))
        if places is None or block.parameters.get("place") not in places:
            yield _fix(
                "change_not_allowed",
                block.name,
                f'"{block.name}" proposes a change the platform does not allow.',
            )


def _input_rows(block: Block) -> list[tuple[str, JsonValue]]:
    """An Agent block's inputs, as its fixed collection holds them."""
    inputs = block.parameters.get("inputs")
    rows = inputs.get("input") if isinstance(inputs, dict) else None
    if not isinstance(rows, list):
        return []
    return [(str(row.get("name")), row.get("value")) for row in rows if isinstance(row, dict)]


def _yes_before_writes(flow: Flow) -> Iterable[Finding]:
    """Walks every path from every block that starts an execution. A path has a yes only once it
    leaves an Ask for a yes by its Yes exit. An Ask for a yes turned off asks nobody, so it counts
    as absent, but a write turned off still counts as a write (ADR 0051)."""
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
        asks = kind == "ask" and not flow.blocks[name].disabled
        if kind == "write" and not approved:
            unapproved[name] = None
        if asks and asked:
            doubled[name] = None
        for edge in flow.after(name):
            if asks:
                stack.append((edge.target, edge.exit == YES, True))
            else:
                stack.append((edge.target, approved, asked))
    for name in unapproved:
        yield Finding(
            "no_yes_before_write", "writes_refused", name, f'"{name}" can run without a yes.'
        )
    for name in doubled:
        yield _fix("second_yes", name, f'"{name}" asks for a second yes on the same path.')


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


@dataclass(frozen=True)
class FixedForYou:
    """Code puts it right whenever it lays a workflow out."""

    added: str
    """What code made sure of, as the report's "Fixed for you" lists it."""


@dataclass(frozen=True)
class NeedsAnAnswer:
    """The person setting the workflow up answers it, in the chat or in n8n."""


@dataclass(frozen=True)
class NeedsASetting:
    """An Operator changes it in Settings or the agent library. Our API refuses it at run time
    whatever an approval says."""


@dataclass(frozen=True)
class CantRun:
    """Nobody can clear it in the app. It needs a new ADR, or spike P9."""


@dataclass(frozen=True)
class ApproverMayAccept:
    """An Approver may accept it at set-up (ADR 0051, section 3)."""

    agrees: str
    """What the Approver agrees to by accepting it."""
    approvers: int = 1
    """How many Approvers accept it, one after the other. Two when code can't tell what a block
    does, so can't tell that it leaves everyone's access as it was (ADR 0051, section 3)."""


type Clears = FixedForYou | NeedsAnAnswer | NeedsASetting | CantRun | ApproverMayAccept


@dataclass(frozen=True)
class FlagRow:
    what: str
    why: str
    """Why it matters."""
    passed: str
    """What the report says when no block breaks the rule."""
    clears: Clears


FLAG_RULES: Mapping[RuleId, FlagRow] = {
    "unreadable": FlagRow(
        "The checker can't read it",
        "Nothing in it can be checked, so nobody can say what it does.",
        "The checker read the whole workflow.",
        NeedsAnAnswer(),
    ),
    "block_off": FlagRow(
        "Uses a block our n8n doesn't load",
        "n8n can't run a block it doesn't load, so the workflow can't run as it is.",
        "Every block loads in our n8n.",
        CantRun(),
    ),
    "version_off": FlagRow(
        "Uses a version of a block the platform hasn't classed",
        "Nobody has checked what this version of the block does, and n8n runs it as it is.",
        "Every block is a version the platform has classed.",
        ApproverMayAccept(
            "The block runs as n8n made it, in a version nobody here has checked.", approvers=2
        ),
    ),
    "picked_by_expression": FlagRow(
        "Picks what it does from the run's data",
        "What the block does is known only when it runs, so nobody can check it first.",
        "Every block does one thing, written in the block.",
        ApproverMayAccept("The block does whatever the run's data picks.", approvers=2),
    ),
    "operation_off": FlagRow(
        "Does something the platform hasn't classed",
        "It could change data, and n8n's own blocks don't ask for a yes on each run.",
        "Each of n8n's blocks only reads, posts or shapes the data.",
        ApproverMayAccept("It does this on every run, with no yes on each run.", approvers=2),
    ),
    "nothing_starts": FlagRow(
        "Nothing starts it",
        "It has no schedule and no Start from the Portal, so it never runs.",
        "A schedule or Start from the Portal starts it.",
        NeedsAnAnswer(),
    ),
    "no_error_workflow": FlagRow(
        "A stopped run isn't reported",
        "Its failures don't go to the platform's error workflow, so a stopped run wouldn't show.",
        "A stopped run is reported in the Portal.",
        FixedForYou("Added our error workflow, so a stopped run shows in the Portal."),
    ),
    "other_time_zone": FlagRow(
        "Runs on another time zone",
        "Its run times wouldn't match the times the Portal shows.",
        "Runs on the team's time zone.",
        FixedForYou("Set the team's time zone."),
    ),
    "test_runs_not_kept": FlagRow(
        "Test runs aren't kept",
        "n8n wouldn't keep its test runs, so nobody could look at one afterwards.",
        "n8n keeps its test runs.",
        FixedForYou("Turned on keeping test runs."),
    ),
    "progress_not_saved": FlagRow(
        "Progress isn't saved",
        "n8n wouldn't save each step, so a run couldn't be linked to its record.",
        "n8n saves each step of a run.",
        FixedForYou("Turned on saved progress."),
    ),
    "tell_place": FlagRow(
        "Tells a place that isn't one of the fixed ones",
        "Our Tell posts only to the team's Teams channel, its email list, or both.",
        "Every Tell goes to one of the fixed places.",
        NeedsAnAnswer(),
    ),
    "notice_place_expression": FlagRow(
        "Posts to a place the run's data picks",
        "Where it posts is known only when it runs, so a run could post anywhere the key reaches.",
        "Every post goes to a place written in the block.",
        ApproverMayAccept("It posts wherever the run's data says."),
    ),
    "notice_words_expression": FlagRow(
        "Posts words from what the run read",
        "The words are known only when it runs, and what a run reads could say anything.",
        "Every post's words are written in the block.",
        ApproverMayAccept("What the run read is posted as it is."),
    ),
    "notice_words_unreadable": FlagRow(
        "Has words the checker can't read",
        "Nobody can check what it would post.",
        "The checker read every post's words.",
        NeedsAnAnswer(),
    ),
    "calls_everyone": FlagRow(
        "Calls out a whole channel",
        "Everyone in the channel is told, not only the people it is for.",
        "No post calls out a whole channel.",
        ApproverMayAccept("Everyone in the channel is told each time it posts."),
    ),
    "no_platform_key": FlagRow(
        "Uses a system the platform has no key for",
        "The block runs only with a key the platform made, and there is none for this system.",
        "The platform has a key for every system a block uses.",
        CantRun(),
    ),
    "not_platform_key": FlagRow(
        "Doesn't use the platform's key",
        "Each of n8n's blocks for a system runs with the key the platform made for that system.",
        "Every block uses the platform's key for its system.",
        FixedForYou("Put the platform's key on each of n8n's blocks."),
    ),
    "key_not_made": FlagRow(
        "Uses a key the platform didn't make",
        "In the platform's n8n project a workflow could use any key kept there, a member's too.",
        "No block uses a key the platform didn't make.",
        FixedForYou("Put no other key on any block."),
    ),
    "key_for_other_block": FlagRow(
        "Uses a platform key made for another block",
        "A key goes only on the kind of block it was made for.",
        "Each key is on the kind of block it was made for.",
        FixedForYou("Put each key only on the kind of block it was made for."),
    ),
    "runs_before_ours": FlagRow(
        "Runs before any of our steps",
        "Our first step records the run and checks its version. Before it, nothing is checked.",
        "One of our steps comes first, so every run is recorded.",
        FixedForYou("Put one of our steps first, so every run is recorded."),
    ),
    "no_run_time": FlagRow(
        "Has no time to run",
        "Its schedule names no time, so it never runs on its own.",
        "Its schedule names a time.",
        NeedsAnAnswer(),
    ),
    "run_time_unshowable": FlagRow(
        "Runs at times the Portal can't show",
        "n8n would pick part of the time itself, so nobody can see the next run to the minute.",
        "The Portal can show each next run.",
        ApproverMayAccept("It runs at times n8n picks, which the Portal can't show."),
    ),
    "unknown_agent": FlagRow(
        "Names an agent card nobody saved",
        "Our platform refuses to run an agent it doesn't know, whatever an approval says.",
        "Every agent is a saved card.",
        NeedsASetting(),
    ),
    "unknown_agent_input": FlagRow(
        "Gives its agent an input the card doesn't have",
        "Our platform refuses an input the card doesn't have, whatever an approval says.",
        "Every agent gets only its own inputs.",
        NeedsASetting(),
    ),
    "write_place_not_allowed": FlagRow(
        "Writes to a place the team hasn't allowed",
        "Our platform refuses a write to a place that isn't on the team's list.",
        "Writes only to places the team allows.",
        NeedsASetting(),
    ),
    "read_place_not_allowed": FlagRow(
        "Reads a place the team hasn't allowed",
        "Our platform refuses to read a place that isn't on the team's list.",
        "Reads only places the team allows.",
        NeedsASetting(),
    ),
    "change_not_allowed": FlagRow(
        "Proposes a change the team hasn't allowed",
        "Our platform refuses a change, or a place for it, that isn't on the team's list.",
        "Proposes only changes the team allows.",
        NeedsASetting(),
    ),
    "no_yes_before_write": FlagRow(
        "Writes with no yes before it",
        "Our platform refuses the write, so the run stops before it.",
        "Every write waits for a yes.",
        FixedForYou("Added a yes before each write."),
    ),
    "second_yes": FlagRow(
        "Asks for a yes twice on one path",
        "A path needs one yes before its write, and this one asks twice.",
        "No path asks for a yes twice.",
        ApproverMayAccept("It asks for a yes twice on one path."),
    ),
}
"""What each rule is, why it matters and who can clear it, in plain words (ADR 0051, section 2).
The workflow report reads it."""
