"""The workflow report: the plain-words account that code builds of one version of any workflow
(ADR 0051, section 6). The draft card, the approval page and Explain all show it.

Code writes every word of it, never a model. Each string from the plan or the document, such as
a block's name, a place or a notice's words, is a Quoted value kept apart from code's own words,
so a block named "Security approved" can't read as code's verdict. A value shaped like a key
shows as hidden, and a key's secret never reaches the report.

Pure. It needs no running n8n, and it grades the version itself under today's rules.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from pydantic import JsonValue

from platform_api.builder.cards import card_spec
from platform_api.builder.models import CardView
from platform_api.builder.n8n_draft import blocks_of
from platform_api.builder.versions import schedule_of, schedule_words
from platform_api.orchestration import (
    FLAG_RULES,
    KEY_FOR_TYPE,
    NODE_CLASSES,
    RULES,
    ApproverMayAccept,
    Block,
    BlockKind,
    CantRun,
    Clears,
    Finding,
    FixedForYou,
    Flow,
    Grade,
    InputKind,
    KnownOptions,
    NeedsAnAnswer,
    NeedsASetting,
    RuleId,
    Runs,
    ToolId,
    ToolRule,
    Unreadable,
    Use,
    approvers_needed,
    face,
    grade,
    read_flow,
    write_tools_used,
)


@dataclass(frozen=True)
class Quoted:
    """A string from the plan or the document, shown in quotes."""

    text: str


type Words = tuple[str | Quoted, ...]


@dataclass(frozen=True)
class Team:
    """What today's rules grade a version against."""

    error_workflow: str | None
    time_zone: str
    known: KnownOptions
    override_built: bool = False
    """Whether an Approver can approve a flagged version at set-up (ADR 0051, build step 10).
    Until then the report says nothing can run on that approval."""


@dataclass(frozen=True)
class SetUp:
    """A version of a workflow that is set up: one the Planner laid out (E4), or one made in n8n
    and set up from there (E15)."""

    laid_by: Literal["planner", "n8n"]
    document: Mapping[str, Any]
    cards: Mapping[str, CardView]
    """The saved card each Agent block names, by its id (ADR 0023)."""


@dataclass(frozen=True)
class Older:
    """An older published version, as ADR 0027 keeps every one, with the grade it had then."""

    version: SetUp
    number: int
    graded_then: Grade


@dataclass(frozen=True)
class Filled:
    value: str | Words
    """A string from the plan, shown in quotes, or code's own words, as for a run time."""


@dataclass(frozen=True)
class Guessed:
    value: str | Words


@dataclass(frozen=True)
class Needed:
    pass


@dataclass(frozen=True)
class DraftSetting:
    label: str | Words
    """The plan's label, shown in quotes, or code's own words for a setting the builder adds."""
    given: Filled | Guessed | Needed
    said: str | None = None
    """Where the value came from, in words to show. Its mark when None."""


@dataclass(frozen=True)
class Drafted:
    """A revision of a drafted workflow. Its set-up approval comes with the drafter (ADR 0051,
    build steps 6 and 7)."""

    document: Mapping[str, Any]
    cards: Mapping[str, CardView]
    settings: tuple[DraftSetting, ...]


type Source = SetUp | Older | Drafted


@dataclass(frozen=True)
class Step:
    name: Quoted
    ours: bool
    block_type: Quoted
    """n8n's type, shown only to people with n8n access."""
    tag: str


type Action = Literal["reads", "writes", "posts"]


@dataclass(frozen=True)
class Touch:
    """One thing it reads, writes or posts, by system and place."""

    action: Action
    system: str | None
    """None when code can't tell which system."""
    place: Quoted | None
    block: Quoted
    phrase: Words
    """What it does, as In short says it after "it"."""
    key: str | None = None
    """The display name of the platform's key that one of n8n's blocks uses, never the key's
    secret."""


@dataclass(frozen=True)
class Flag:
    rule: RuleId
    block: Quoted | None
    what: str
    why: str
    clears: Clears
    takes: str
    """Who can clear it."""


@dataclass(frozen=True)
class Cleared:
    """A rule no block breaks, with what the report says of it."""

    rule: RuleId
    words: str


@dataclass(frozen=True)
class EachRun:
    approvers: int
    """How many Approvers say yes on each run, one after the other."""


@dataclass(frozen=True)
class AtSetUp:
    """It runs on the set-up approval, with no yes on each run."""


@dataclass(frozen=True)
class Refused:
    """No yes comes before it, so our platform refuses the write."""


@dataclass(frozen=True)
class CantRunYet:
    """No approval lets it run on this platform yet."""


@dataclass(frozen=True)
class WriteApproval:
    block: Quoted
    decides: EachRun | AtSetUp | Refused | CantRunYet
    words: str


type Mark = Literal["filled", "guessed", "needed", "set"]


@dataclass(frozen=True)
class Setting:
    label: Words
    value: Words | None
    mark: Mark
    said: str


@dataclass(frozen=True)
class Then:
    number: int
    grade: Grade


@dataclass(frozen=True)
class WorkflowReport:
    name: Quoted
    grade: Grade
    """Under today's rules."""
    then: Then | None
    in_short: Words
    steps: tuple[Step, ...]
    touches: tuple[Touch, ...]
    flags: tuple[Flag, ...]
    fixed: tuple[Cleared, ...]
    passed: tuple[Cleared, ...]
    approves: tuple[WriteApproval, ...]
    settings: tuple[Setting, ...]
    approval: str
    needs_an_answer: int
    """The questions left: a drafted workflow's settings still needed, or a set-up workflow's
    flags that need an answer."""


RUNTIME_KEY_SHAPES = (
    r"sk-ant-[A-Za-z0-9_\-]{8,}",
    r"(?:(?<=\\[bfnrt])|(?<=\\u[0-9A-Fa-f]{4})|(?<=[%=][0-9A-Fa-f]{2})|(?<![A-Za-z]))"
    r"sk-[A-Za-z0-9_\-]{16,}",
    r"gh[pousr]_[A-Za-z0-9]{16,}",
    r"github_pat_[A-Za-z0-9_]{16,}",
    r"glpat-[A-Za-z0-9_\-]{16,}",
    r"(?:AKIA|ASIA)[0-9A-Z]{16}",
    r"xox[abeprs]-[A-Za-z0-9\-]{10,}",
    r"xapp-[0-9]-[A-Za-z0-9\-]{10,}",
    r"hooks\.slack\.com/(?:services|triggers|workflows)/[A-Za-z0-9_/\-]+",
    r"webhook\.office\.com/[A-Za-z0-9@_/\-]+",
    r"ATATT[A-Za-z0-9_=\-]{16,}",
    r"AIza[A-Za-z0-9_\-]{35}",
    r"(?i:accountkey|sharedaccesskey)=[A-Za-z0-9+/=]{32,}",
    r"sig=[A-Za-z0-9%+/=_\-]{40,}",
    r"(?:(?<=\\)(?![bfnrt]|u[0-9A-Fa-f]{4})|(?<=\\[bfnrt])|(?<=\\u[0-9A-Fa-f]{4})"
    r"|(?<![A-Za-z0-9_\-\\]))"
    r"(?=[A-Za-z0-9_\-]*?eyJ)[A-Za-z0-9_\-]++\.eyJ[A-Za-z0-9_\-]++\.[A-Za-z0-9_\-]+",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
    r"(?i:bearer)\s+(?=[A-Za-z._~\-]*[0-9+/=])[A-Za-z0-9._~+/=\-]{8,}",
    r"(?i:basic)\s+(?=[A-Za-z]*[0-9+/=])[A-Za-z0-9+/=]{8,}",
)
"""The agent runtime's masker's shapes, each as it writes it in
contracts/fixtures/agent/key-shapes.json. A test holds the two lists together."""
KEY_SHAPE_SOURCES = (
    *RUNTIME_KEY_SHAPES,
    r"\b(?i:token|key|secret|sig|password|api[_-]?key)=[^&\s\"']{8,}",
)
"""Every shape of a key or token platform-api knows: the runtime's, and a key or password in a
query. A git commit's 40 hex letters are not a key, so a person may paste one."""
KEY_SHAPE = re.compile("|".join(KEY_SHAPE_SOURCES))
"""Refused in a person's words, an answer and a read-back from n8n, and hidden in a report."""
HIDDEN = "(hidden, looks like a key)"
CHOOSERS = frozenset({"select"})
"""Target parameters that only pick which other one applies, as Slack's select picks a channel
or a user."""

READ_SOURCES: Mapping[str, str] = {
    "github_releases": "GitHub",
    "jira_tickets": "Jira",
    "confluence_page": "Confluence",
}
TOOL_PLACES: Mapping[ToolId, tuple[str, InputKind | None]] = {
    "github.read_releases": ("GitHub", "github_repo"),
    "jira.search": ("Jira", "jira_project"),
    "jira.read_ticket": ("Jira", "jira_project"),
    "confluence.read_page": ("Confluence", None),
    "jira.create_ticket": ("Jira", "jira_project"),
}
"""For each tool, the system it reaches and the kind of the card's input that names the place."""
TELL_PLACES: Mapping[str, tuple[str, str]] = {
    "channel": ("Teams", "tells the team in its Teams channel"),
    "email": ("email", "tells the team by email"),
    "both": ("Teams and email", "tells the team in its Teams channel and by email"),
}
STARTS = "Starts it"
SHAPES = "Shapes the data"
OUR_TAGS: Mapping[BlockKind, str] = {
    "schedule": STARTS,
    "start": STARTS,
    "manual": STARTS,
    "error": STARTS,
    "agent": "Runs an agent",
    "propose": "Shapes the change",
    "ask": "Waits for a yes",
    "write": "Writes after a yes",
    "tell": "Tells the team",
    "report": "Reports a failure",
    "branch": SHAPES,
    "merge": SHAPES,
    "end": "Ends the run",
}
UNCLASSED = "Does something the platform hasn't classed"
UNREAD = "The checker can't read this workflow, so nothing more can be said of it."
UNSHOWN_SCHEDULE = "On a schedule the Portal can't show"
RUN_TIME_NEEDED = "At a run time still needed"
SOMEONE_STARTS = "When someone starts it"
NOTHING_STARTS = "Nothing starts it. When it runs"
CHANGES_NOTHING_ELSE = " It changes nothing else."
CHANGES_NOTHING = " It changes nothing."
ON_SET_UP = "Writes on the set-up approval"
NOT_YET = "Can't run on this platform yet"
NOT_YET_TAKES = "This can't run on this platform yet."
WAITS = {
    1: "Waits for a yes in Teams on each run. Nobody who started the run or made the workflow "
    "can give it.",
    2: "Waits for two yeses in Teams on each run, from two Approvers, one after the other. "
    "Nobody who started the run or made the workflow can give one.",
}
REFUSED = "Can't write. No yes comes before it, so our platform refuses the write."
WRITES_ON_SET_UP = "Runs on the set-up approval, with no yes on each run."
POSTS_ON_SET_UP = "Posts on the set-up approval, with no yes on each run."
NO_YES_EACH_RUN = ", with no yes on each run"
HELD = ", but it can't run on this platform yet"
TELL_RULE: frozenset[RuleId] = frozenset(
    {
        "notice_place_expression",
        "notice_words_expression",
        "notice_words_unreadable",
        "calls_everyone",
    }
)
APPROVAL = {
    "planner": "None needed. The Planner laid it out, and each write through our blocks waits "
    "for a yes.",
    "n8n": "None needed. An Operator with n8n access set it up.",
    "drafter": "It is set up only after an Approver approves it.",
}
SAID = {"planner": "Set in the Portal", "n8n": "Set in n8n"}
DRAFT_SAID = {"filled": "Filled", "guessed": "Guessed, and can be changed", "needed": "Needed"}
PLACEHOLDER = re.compile(r"<<[a-z][a-z0-9_]{0,39}>>")
"""Where a drafted workflow's setting goes, while nobody has given it (ADR 0051, section 5)."""
AWAITS: frozenset[RuleId] = frozenset(
    {
        "no_run_time",
        "run_time_unshowable",
        "read_place_not_allowed",
        "write_place_not_allowed",
        "change_not_allowed",
        "tell_place",
        "unknown_agent_input",
    }
)
"""What a block finds while a setting it holds is still needed. Until it is answered, that is
the question the card asks, not a flag besides."""
_NAMED = re.compile(r"""\$\(\s*(['"])(.+?)\1\s*\)|\$node\[\s*(['"])(.+?)\3\s*\]""")
_THIS_ITEM = re.compile(r"\$(?:json|input|binary)\b")


def workflow_report(source: Source, team: Team) -> WorkflowReport:
    match source:
        case Older(version, number, graded_then):
            return replace(workflow_report(version, team), then=Then(number, graded_then))
        case SetUp(laid_by, document, cards):
            return _report(document, cards, laid_by, None, team)
        case Drafted(document, cards, settings):
            return _report(document, cards, "drafter", settings, team)


def _report(
    document: Mapping[str, Any],
    cards: Mapping[str, CardView],
    laid_by: Literal["planner", "n8n", "drafter"],
    drafted: tuple[DraftSetting, ...] | None,
    team: Team,
) -> WorkflowReport:
    graded = grade(document, team.error_workflow, team.time_zone, team.known)
    name = _quote(str(document.get("name") or ""))
    awaiting = set[str]() if drafted is None else _awaiting(document)
    flags = _flags(
        [f for f in graded.findings if not (f.block in awaiting and f.rule in AWAITS)],
        team.override_built,
    )
    asked = sum(isinstance(f.clears, NeedsAnAnswer) for f in flags)
    try:
        flow = read_flow(document)
    except Unreadable:
        return WorkflowReport(
            name,
            graded.grade,
            None,
            (UNREAD,),
            (),
            (),
            flags,
            (),
            (),
            (),
            (),
            APPROVAL[laid_by],
            asked,
        )
    fixed, passed = _cleared(graded.findings, flow, laid_by != "n8n")
    order = [view.name for view in blocks_of(document)]
    held = {f.block for f in flags if not isinstance(f.clears, ApproverMayAccept | FixedForYou)}
    version = _Version(
        flow,
        order,
        cards,
        frozenset(f.block for f in graded.findings if f.block and f.rule == "no_yes_before_write"),
        frozenset(f.block for f in graded.findings if f.block and f.rule in TELL_RULE),
        frozenset(f.block for f in graded.findings if f.block and f.rule == "operation_off"),
        frozenset(n for n in order if team.override_built and _quote(n) not in held),
    )
    used = [cards[a] for a in _agents(flow) if a in cards]
    approvers = approvers_needed(
        [card_spec(c) for c in used],
        max((a.approvers for c in used for a in c.approvals), default=1),
    )
    touches = tuple(touch for n in order for touch in _touches(version, n))
    settings = (
        _set_settings(flow, order, document, team.time_zone, approvers, SAID[laid_by])
        if drafted is None
        else tuple(_draft_setting(s) for s in drafted)
    )
    return WorkflowReport(
        name,
        graded.grade,
        None,
        _in_short(_when(flow, document, team.time_zone, awaiting), touches),
        tuple(_step(version, n) for n in order),
        touches,
        flags,
        fixed,
        passed,
        tuple(_approves(version, approvers)),
        settings,
        APPROVAL[laid_by],
        asked if drafted is None else sum(s.mark == "needed" for s in settings),
    )


@dataclass(frozen=True)
class _Version:
    """One graded version, as the report's sections read it."""

    flow: Flow
    order: Sequence[str]
    cards: Mapping[str, CardView]
    refused: frozenset[str]
    """Writes with no yes before them."""
    told: frozenset[str]
    """n8n's notices that break the Tell rule."""
    changes: frozenset[str]
    """n8n's blocks set to do something off, such as a write."""
    on_approval: frozenset[str]
    """The blocks that would run on a set-up approval."""


def quoted(text: str) -> Quoted:
    """A string from the plan or the document, with anything shaped like a key hidden."""
    return Quoted(KEY_SHAPE.sub(HIDDEN, text))


_quote = quoted


def _flags(findings: Sequence[Finding], override_built: bool) -> tuple[Flag, ...]:
    """Each finding in FLAG_RULES order. Until an Approver can accept a flag at set-up, it can't
    run on this platform."""
    flags: list[Flag] = []
    for rule, row in FLAG_RULES.items():
        clears = row.clears
        takes = _takes(clears)
        if isinstance(clears, ApproverMayAccept) and not override_built:
            clears, takes = CantRun(), NOT_YET_TAKES
        flags += [
            Flag(
                rule,
                None if f.block is None else _quote(f.block),
                row.what,
                row.why,
                clears,
                takes,
            )
            for f in findings
            if f.rule == rule
        ]
    return tuple(flags)


def _takes(clears: Clears) -> str:
    match clears:
        case FixedForYou():
            return "Fix it in n8n. Code makes sure of it in every workflow it lays out."
        case NeedsAnAnswer():
            return "The person setting it up answers it, in the chat or in n8n."
        case NeedsASetting():
            return "An Operator fixes it in Settings or the agent library. No approval clears it."
        case CantRun():
            return "Nobody can clear it in the app. The platform itself would have to change."
        case ApproverMayAccept():
            return "An Approver may accept it at set-up."


def _cleared(
    findings: Sequence[Finding], flow: Flow, laid_by_code: bool
) -> tuple[tuple[Cleared, ...], tuple[Cleared, ...]]:
    """Each rule no block breaks: under Fixed for you when code laid the workflow out and made
    sure of it here, else under Passed."""
    broken = {f.rule for f in findings}
    fixed: list[Cleared] = []
    passed: list[Cleared] = []
    for rule, row in FLAG_RULES.items():
        if rule in broken:
            continue
        match row.clears:
            case FixedForYou(added) if laid_by_code and _applies(rule, flow):
                fixed.append(Cleared(rule, added))
            case _:
                passed.append(Cleared(rule, row.passed))
    return tuple(fixed), tuple(passed)


def _applies(rule: RuleId, flow: Flow) -> bool:
    """Whether the workflow has anything for code to have made sure of."""
    match rule:
        case "no_yes_before_write":
            return bool(flow.of_kind("write"))
        case "not_platform_key" | "key_not_made" | "key_for_other_block" | "runs_before_ours":
            return bool(flow.of_kind("system"))
        case _:
            return True


def _kind(flow: Flow, name: str) -> BlockKind | None:
    block = flow.blocks[name]
    return face(block.type, block.version, block.parameters).kind


def _step(version: _Version, name: str) -> Step:
    block = version.flow.blocks[name]
    seen = face(block.type, block.version, block.parameters)
    match seen.kind:
        case None:
            tag = UNCLASSED if seen.ours else ON_SET_UP if name in version.on_approval else NOT_YET
        case "read":
            tag = f"Reads {_read_system(block.parameters)}"
        case "shape" | "system":
            tag = seen.tag or UNCLASSED
        case kind:
            tag = OUR_TAGS.get(kind, UNCLASSED)
    return Step(_quote(name), seen.ours, _quote(block.type), tag)


def _read_system(parameters: Mapping[str, JsonValue]) -> str:
    return READ_SOURCES.get(str(parameters.get("source", "github_releases")), "a source")


def _agents(flow: Flow) -> list[str]:
    return [str(b.parameters.get("agent")) for b in flow.of_kind("agent")]


def _inputs(parameters: Mapping[str, JsonValue]) -> list[tuple[str, str]]:
    """An Agent block's inputs, as its fixed collection holds them."""
    match parameters.get("inputs"):
        case {"input": list(rows)}:
            return [(str(r.get("name")), str(r.get("value"))) for r in rows if isinstance(r, dict)]
        case _:
            return []


def _card_place(
    card: CardView, values: Sequence[tuple[str, str]], kind: InputKind | None
) -> Quoted | None:
    names = [i.name for i in card.inputs if i.kind == kind]
    given = dict(values)
    return _quote(given[names[0]]) if len(names) == 1 and names[0] in given else None


def _touches(version: _Version, name: str) -> list[Touch]:
    flow = version.flow
    block = flow.blocks[name]
    seen = face(block.type, block.version, block.parameters)
    quoted = _quote(name)
    match seen.kind:
        case "read":
            system = _read_system(block.parameters)
            place = block.parameters.get("place")
            at = _quote(place) if isinstance(place, str) else None
            return [Touch("reads", system, at, quoted, _reads(system, at))]
        case "agent":
            card = version.cards.get(str(block.parameters.get("agent")))
            if card is None:
                return []
            values = _inputs(block.parameters)
            touches: list[Touch] = []
            for tool in card.tools:
                rule = RULES[tool]
                if rule.kind != "read":
                    continue
                system, kind = TOOL_PLACES[tool]
                at = _card_place(card, values, kind)
                touches.append(Touch("reads", system, at, quoted, _reads(system, at)))
            return touches
        case "write":
            return _writes(version, name)
        case "tell":
            where = str(block.parameters.get("where", "channel"))
            system, tells = TELL_PLACES.get(where, ("Teams", "tells a place that isn't fixed"))
            return [Touch("posts", system, None, quoted, (tells,))]
        case "system":
            told = name in version.told
            return _n8n_touches(flow, name, told, told and name not in version.on_approval)
        case None if not seen.ours:
            spec = KEY_FOR_TYPE.get(block.type)
            system = None if spec is None else spec.said
            does = (
                f"could change data in {system} through "
                if system is not None and name in version.changes
                else "could change or send data through "
            )
            then = NO_YES_EACH_RUN if name in version.on_approval else HELD
            return [Touch("writes", system, None, quoted, (does, quoted, then))]
        case _:
            return []


def _reads(system: str, at: Quoted | None) -> Words:
    return (f"reads {system}",) if at is None else (f"reads {system} ", at)


def _writes(version: _Version, name: str) -> list[Touch]:
    """What a Make the approved changes block writes: each change proposed before it, by an
    agent's write tool or a Propose a change block."""
    flow, cards, refused = version.flow, version.cards, name in version.refused
    before = _before(flow, name)
    proposed: dict[tuple[str, Quoted | None, str], None] = {}
    for earlier in (n for n in version.order if n in before):
        block = flow.blocks[earlier]
        match _kind(flow, earlier):
            case "agent":
                card = cards.get(str(block.parameters.get("agent")))
                if card is None:
                    continue
                values = _inputs(block.parameters)
                for rule in write_tools_used(card.tools):
                    system, kind = TOOL_PLACES[rule.id]
                    proposed[system, _card_place(card, values, kind), _verb(rule)] = None
            case "propose":
                rule = RULES.get(str(block.parameters.get("action")))
                if rule is None:
                    continue
                place = block.parameters.get("place")
                at = _quote(place) if isinstance(place, str) else None
                proposed[TOOL_PLACES[rule.id][0], at, _verb(rule)] = None
            case _:
                continue
    quoted = _quote(name)
    if not proposed:
        phrase = _write_phrase("make the changes approved in the run", None, refused)
        return [Touch("writes", None, None, quoted, phrase)]
    return [
        Touch("writes", system, at, quoted, _write_phrase(verb, at, refused))
        for system, at, verb in proposed
    ]


def _write_phrase(verb: str, at: Quoted | None, refused: bool) -> Words:
    where: Words = () if at is None else (" in ", at)
    if refused:
        return (f"would {verb}", *where, ", but our platform refuses it with no yes before it")
    return (f"can {verb}", *where, ", each after a yes")


def _verb(rule: ToolRule) -> str:
    said = rule.action_name or rule.name
    return said[:1].lower() + said[1:]


def _before(flow: Flow, name: str) -> set[str]:
    """Every block a run passes before this one."""
    seen: set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        for edge in flow.edges:
            if edge.target == current and edge.source not in seen:
                seen.add(edge.source)
                stack.append(edge.source)
    return seen


def _n8n_touches(flow: Flow, name: str, told: bool, held: bool) -> list[Touch]:
    """What one of n8n's blocks for a system reads or posts, as its class row says. A notice that
    breaks the Tell rule posts with no yes on each run, or can't run at all while it is held."""
    block = flow.blocks[name]
    row = _n8n_row(block)
    if row is None:
        return []
    on, use = row
    quoted = _quote(name)
    spec = KEY_FOR_TYPE.get(block.type)
    system = spec.said if spec is not None else use.tag.split()[-1]
    key = None if spec is None else spec.name
    at = _n8n_place(block, use)
    if on == "read":
        return [Touch("reads", system, at, quoted, _reads(system, at), key)]
    where: Words = (
        (f" in {system}, in a place the run's data picks",)
        if at is None
        else (f" in {system} ", at)
    )
    said = _said(flow, name, [_at(block.parameters, path) for path in use.text])
    then = HELD if held else NO_YES_EACH_RUN if told else ""
    does = "would post " if held else "posts "
    return [Touch("posts", system, at, quoted, (does, *said, *where, then), key)]


def _n8n_row(block: Block) -> tuple[str, Use] | None:
    match NODE_CLASSES.verdict(block.type, block.version, block.parameters):
        case Runs(on, Use() as use):
            return on, use
        case _:
            return None


def _n8n_place(block: Block, use: Use) -> Quoted | None:
    """Where it reads or posts, or None when an expression picks it or nothing names it."""
    shown = [
        t
        for path in use.target
        if path not in CHOOSERS
        for t in _shown(_at(block.parameters, path))
    ]
    picked = any(t.startswith("=") for t in shown)
    return None if picked or not shown else _quote(", ".join(shown))


def _at(parameters: Mapping[str, JsonValue], path: str) -> JsonValue:
    value: JsonValue = dict(parameters)
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _shown(value: JsonValue) -> list[str]:
    """A place as it is written: a resource locator, or any collection, by its value."""
    match value:
        case None:
            return []
        case {"value": inner}:
            return _shown(inner)
        case dict() | list():
            return list(_texts(value))
        case _:
            return [str(value)]


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


def _said(flow: Flow, name: str, values: Sequence[JsonValue]) -> Words:
    """A post's words in full when they are written out, or which blocks' output they read."""
    texts = [t for value in values for t in _texts(value) if t]
    expressions = [t for t in texts if t.startswith("=")]
    if not expressions:
        return (_quote(" ".join(texts)),)
    named = [m[2] or m[4] for t in expressions for m in _NAMED.finditer(t)]
    if any(_THIS_ITEM.search(t) for t in expressions):
        named += [e.source for e in flow.edges if e.target == name]
    read = [n for n in dict.fromkeys(named) if n in flow.blocks]
    if not read:
        return ("words the run's data picks",)
    return ("what ", *_joined([(_quote(n),) for n in read]), " returned")


def _joined(items: Sequence[Words]) -> Words:
    out: list[str | Quoted] = []
    for index, item in enumerate(items):
        if index:
            out.append(" and " if index == len(items) - 1 else ", ")
        out.extend(item)
    return tuple(out)


def _approves(version: _Version, approvers: int) -> Iterable[WriteApproval]:
    for name in version.order:
        block = version.flow.blocks[name]
        seen = face(block.type, block.version, block.parameters)
        quoted = _quote(name)
        on_approval = name in version.on_approval
        if seen.kind == "write":
            if name in version.refused:
                yield WriteApproval(quoted, Refused(), REFUSED)
            else:
                yield WriteApproval(quoted, EachRun(approvers), WAITS[approvers])
        elif (seen.kind is None and not seen.ours) or name in version.told:
            if not on_approval:
                yield WriteApproval(quoted, CantRunYet(), f"{NOT_YET}.")
            elif name in version.told:
                yield WriteApproval(quoted, AtSetUp(), POSTS_ON_SET_UP)
            else:
                yield WriteApproval(quoted, AtSetUp(), WRITES_ON_SET_UP)


def _when(
    flow: Flow, document: Mapping[str, Any], team_zone: str, awaiting: set[str] | None = None
) -> Words:
    schedule = schedule_of(document, team_zone)
    if schedule is not None:
        said = schedule_words(schedule.day, schedule.at)
        return (said[:1].upper() + said[1:],)
    if any(b.name in (awaiting or set()) for b in flow.of_kind("schedule")):
        return (RUN_TIME_NEEDED,)
    if flow.of_kind("schedule"):
        return (UNSHOWN_SCHEDULE,)
    if flow.of_kind("start", "manual"):
        return (SOMEONE_STARTS,)
    return (NOTHING_STARTS,)


def _in_short(when: Words, touches: Sequence[Touch]) -> Words:
    reads = list(dict.fromkeys((t.system, t.place) for t in touches if t.action == "reads"))
    said: list[str | Quoted] = [*when, ", it "]
    if reads:
        listed = [((f"{s}",) if p is None else (f"{s} ", p)) for s, p in reads]
        said += ["reads ", *_joined(listed), "."]
    else:
        said.append("runs.")
    for phrase in dict.fromkeys(t.phrase for t in touches if t.action != "reads"):
        said += [" It ", *phrase, "."]
    writes = any(t.action == "writes" for t in touches)
    said.append(CHANGES_NOTHING_ELSE if writes else CHANGES_NOTHING)
    return tuple(said)


def _set_settings(
    flow: Flow,
    order: Sequence[str],
    document: Mapping[str, Any],
    team_zone: str,
    approvers: int,
    said: str,
) -> tuple[Setting, ...]:
    """Each value a workflow that is set up runs with, from its document."""
    settings: list[Setting] = []
    if flow.of_kind("schedule"):
        schedule = schedule_of(document, team_zone)
        when = (
            "a time the Portal can't show"
            if schedule is None
            else schedule_words(schedule.day, schedule.at)
        )
        settings.append(Setting(("Run time",), (when,), "set", said))
    for name in order:
        block = flow.blocks[name]
        quoted = _quote(name)
        match _kind(flow, name):
            case "read":
                place = block.parameters.get("place")
                if isinstance(place, str):
                    settings.append(
                        Setting(("Where ", quoted, " reads"), (_quote(place),), "set", said)
                    )
            case "agent":
                for input_name, value in _inputs(block.parameters):
                    label: Words = (_quote(input_name), " for ", quoted)
                    settings.append(Setting(label, (_quote(value),), "set", said))
            case "system":
                settings += _n8n_settings(flow, name, said)
            case _:
                pass
    if flow.of_kind("write"):
        who = "Any Approver" if approvers == 1 else "Two Approvers, one after the other"
        settings.append(Setting(("Who says yes on each run",), (who,), "set", said))
    return tuple(settings)


def _n8n_settings(flow: Flow, name: str, said: str) -> list[Setting]:
    block = flow.blocks[name]
    row = _n8n_row(block)
    if row is None:
        return []
    on, use = row
    at = _n8n_place(block, use)
    verb = " reads" if on == "read" else " posts"
    value: Words = ("a place the run's data picks",) if at is None else (at,)
    return [Setting(("Where ", _quote(name), verb), value, "set", said)]


def _draft_setting(setting: DraftSetting) -> Setting:
    label = _given_words(setting.label)
    match setting.given:
        case Filled(value):
            words, mark = _given_words(value), "filled"
        case Guessed(value):
            words, mark = _given_words(value), "guessed"
        case Needed():
            words, mark = None, "needed"
    return Setting(label, words, mark, setting.said or DRAFT_SAID[mark])


def _given_words(value: str | Words) -> Words:
    return (_quote(value),) if isinstance(value, str) else value


def _awaiting(document: Mapping[str, Any]) -> set[str]:
    """The blocks where a setting still needed stands as its placeholder."""
    try:
        flow = read_flow(document)
    except Unreadable:
        return set()
    return {
        name
        for name, block in flow.blocks.items()
        if any(PLACEHOLDER.fullmatch(t) for t in _texts(dict(block.parameters)))
    }
