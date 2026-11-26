"""Scenarios (ADR 0054, section 5): the situations a workflow version is tried in, as data in a
schema code owns. Code reads the version's plan, picks the kinds that apply, builds one scenario
from a template for each, checks any scenario it is given against the plan, and stages it for the
simulation. No model is used here. The scenario writer (PR 6) writes the same schema, and code
checks what it writes as it checks the templates.

A scenario names, for each block that reads a source, how it is served:

- recorded: a recorded sample as it is (recorded_samples.py);
- varied: a recorded sample that code varies, for odd data;
- empty: nothing, for nothing new;
- not_found: a source that is not found;
- too_slow: a source that drops the connection, which plays a timeout (spike S5).

and for each Agent block a recorded reply, or one that is too slow. The Approver's answer follows
from the kind: no for "Approver says no", yes for every other. A read or Agent block a scenario
leaves out is served as its kind's template serves it.

A scenario can't add a block, a system or a key: code refuses one that names a block the version
doesn't have, a sample there is none of, or a play that doesn't fit its kind.

Staging puts each play where it can be played. The gateway answers our blocks. Mock GitHub serves
n8n's own GitHub block, or drops the connection, or answers not found. A block with no mock is
pinned with the sample, so it can't fail: a scenario that needs it to fail lists it as not tried,
never as passed.
"""

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Final, Literal, Self, cast

from pydantic import Field, JsonValue, model_validator

from platform_api.orchestration.mock_setup import BlockMode, Mode
from platform_api.orchestration.n8n import START_NAME, START_TYPE
from platform_api.orchestration.n8n_calls import NODE_WRITES
from platform_api.orchestration.node_classes import NODE_CLASSES, Mock, OnType, Runs
from platform_api.orchestration.recorded_samples import (
    ALLOW_LISTS,
    AnswerKind,
    RecordedSamples,
    Variation,
    answer_of,
    vary,
)
from platform_api.orchestration.simulated_calls import (
    RECORDED_LIMIT,
    BlockAnswer,
    Change,
    GitHubPlay,
    Scenario,
)
from platform_api.orchestration.write_actions import Json
from platform_api.wire import WireIn

type ScenarioKind = Literal[
    "happy_path", "nothing_new", "source_not_found", "timeout", "approver_says_no", "odd_data"
]
type Serve = Literal["recorded", "varied", "empty", "not_found", "too_slow"]
type Role = Literal[
    "start", "read", "agent", "propose", "ask", "write", "tell", "notice", "idle", "other"
]
"""What a block is to a simulation. `idle` never runs in a run by hand from Start from the Portal:
another trigger, a note, or Report a failure."""

KINDS: Final[tuple[ScenarioKind, ...]] = (
    "happy_path",
    "nothing_new",
    "source_not_found",
    "timeout",
    "approver_says_no",
    "odd_data",
)
KIND_SAID: Final[Mapping[ScenarioKind, str]] = {
    "happy_path": "Happy path",
    "nothing_new": "Nothing new",
    "source_not_found": "Source not found",
    "timeout": "Timeout",
    "approver_says_no": "Approver says no",
    "odd_data": "Odd data",
}
SERVES: Final[tuple[Serve, ...]] = ("recorded", "varied", "empty", "not_found", "too_slow")
HOW: Final[Mapping[Serve, str]] = {
    "recorded": "recorded",
    "varied": "varied",
    "empty": "empty",
    "not_found": "not found",
    "too_slow": "too slow",
}
POINT: Final[Mapping[ScenarioKind, Serve]] = {
    "nothing_new": "empty",
    "source_not_found": "not_found",
    "timeout": "too_slow",
    "odd_data": "varied",
}
"""The play a kind is about. A scenario where no block can play it is not tried."""
NEEDS_A_READ: Final = frozenset({"nothing_new", "source_not_found", "timeout", "odd_data"})
STEERED: Final[frozenset[Mock]] = frozenset({"github"})
"""The mocks a simulation steers for each scenario. Any other mock answers one way."""
FAILURES: Final[frozenset[Serve]] = frozenset({"not_found", "too_slow"})

NO_START: Final = "A simulation starts a version from Start from the Portal, and this one has none."
PINNED_PLAY: Final = "Its output is pinned, so a simulation can't play it as {how}."
ONE_WAY_MOCK: Final = "Its mock answers only one way, so a simulation can't play it as {how}."
NO_ALLOW_LIST: Final = "No allow list covers what it reads, so a simulation can't play it as {how}."

SAMPLE_REPLY: Final[dict[str, JsonValue]] = {"summary": "An answer made up for a simulation."}
SAMPLE_CHANGE: Final = Change(
    action=NODE_WRITES[0].id,
    place="SIM",
    title="A change made up for a simulation",
    body="Made up for a simulation.",
)
"""What an Agent's recorded reply proposes in a version where no block proposes a change, so the
happy path can reach the yes."""

BlockName = Annotated[str, Field(min_length=1, max_length=200)]
MOST_GONE: Final = 10
GONE_SERVES: Final[frozenset[Serve]] = frozenset({"recorded", "varied"})
SampleId = Annotated[
    str, Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
]


class Play(WireIn):
    """How one read block is served."""

    serve: Serve
    sample: SampleId | None = Field(
        default=None,
        description="The recorded sample to serve or vary. None serves the block's own newest, "
        "else the newest of its kind, else the made-up one.",
    )
    vary: list[Variation] = Field(
        default_factory=list[Variation], max_length=3, description="For varied only."
    )
    gone: list[BlockName] = Field(
        default_factory=list[str],
        max_length=MOST_GONE,
        description="Places that answer not found, as a renamed repository does. Any other place "
        "is served as the play says. For recorded or varied only, on a read that can be not "
        "found. A fix's replay of its stop names the place the stopped run read (ADR 0055, PR 5).",
    )


class Reply(WireIn):
    """What one Agent block answers."""

    serve: Literal["recorded", "too_slow"] = "recorded"
    items: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]], max_length=RECORDED_LIMIT
    )
    proposes: list[Change] = Field(default_factory=list[Change], max_length=20)


class ScenarioSpec(WireIn):
    """One scenario, as the templates and the scenario writer give it."""

    kind: ScenarioKind
    name: str = Field(default="", max_length=80, description="Its kind, unless it names itself.")
    reads: dict[BlockName, Play] = Field(default_factory=dict[str, Play], max_length=100)
    agents: dict[BlockName, Reply] = Field(default_factory=dict[str, Reply], max_length=100)

    @model_validator(mode="after")
    def _named(self) -> Self:
        if not self.name:
            self.name = self.kind
        return self


# The plan


@dataclass(frozen=True)
class PlanBlock:
    name: str
    node_type: str
    role: Role
    mode: Mode
    why: str | None
    """For a pinned block, why no mock stands in for it."""
    answer: AnswerKind | None
    """For a read block, what it gives, when an allow list covers it."""
    mock: Mock | None
    parameters: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True)
class SimulationPlan:
    """A version as a simulation sees it: each block's role and mode, in the version's order."""

    blocks: tuple[PlanBlock, ...]
    after_write: frozenset[str]
    """Blocks after Make the approved changes. The gateway refuses every write, and the refusal
    ends the run, so they never run in a simulation (ADR 0054, PR 3). A write set to go on after a
    failure is the exception (`_after_writes`)."""

    def having(self, role: Role) -> tuple[PlanBlock, ...]:
        return tuple(block for block in self.blocks if block.role == role)

    def block(self, name: str) -> PlanBlock | None:
        return next((block for block in self.blocks if block.name == name), None)

    @property
    def reads(self) -> tuple[PlanBlock, ...]:
        return self.having("read")

    @property
    def agents(self) -> tuple[PlanBlock, ...]:
        return self.having("agent")


IDLE: Final = frozenset({"schedule", "manual", "error", "note", "report"})
OWN_ROLES: Final[frozenset[Role]] = frozenset(
    {"start", "read", "agent", "propose", "ask", "write", "tell"}
)


def _role(node: Mapping[str, Any]) -> Role:
    node_type = str(node.get("type"))
    entry = NODE_CLASSES.entry(node_type)
    if not isinstance(entry, OnType):
        return "other"
    if entry.block == "system":
        parameters = cast(Mapping[str, object], node.get("parameters") or {})
        verdict = NODE_CLASSES.verdict(node_type, node.get("typeVersion"), parameters)
        return "read" if isinstance(verdict, Runs) and verdict.on == "read" else "notice"
    if entry.block in IDLE:
        return "idle"
    return cast(Role, entry.block) if entry.block in OWN_ROLES else "other"


def plan_of(version: Mapping[str, Any], modes: Sequence[BlockMode]) -> SimulationPlan | str:
    """The plan of a version the mock setup took, with the modes it gave. Words when a simulation
    can't start it."""
    nodes = {str(n.get("name")): n for n in cast(list[Mapping[str, Any]], version["nodes"])}
    blocks: list[PlanBlock] = []
    for mode in modes:
        node = nodes[mode.block]
        role = _role(node)
        parameters = cast(Mapping[str, Any], node.get("parameters") or {})
        answer = answer_of(node) if role == "read" else None
        blocks.append(
            PlanBlock(
                mode.block, mode.node_type, role, mode.mode, mode.why, answer, mode.mock, parameters
            )
        )
    if not any(b.node_type == START_TYPE and b.name == START_NAME for b in blocks):
        return NO_START
    writes = [nodes[b.name] for b in blocks if b.role == "write"]
    connections = cast(Mapping[str, Any], version.get("connections") or {})
    return SimulationPlan(tuple(blocks), _after_writes(writes, connections))


def _after_writes(
    writes: Sequence[Mapping[str, Any]], connections: Mapping[str, Any]
) -> frozenset[str]:
    """The blocks a refused write keeps from running, as n8n 2.42.6 reads a block's settings. A
    write set to continue (onError continueRegularOutput, or the older continueOnFail) passes the
    refusal on, so it keeps none from running. One that sends a failure to its error exit
    (continueErrorOutput) runs that exit, the one after Make the approved changes' only exit. Any
    other stops the run."""
    names = {str(write.get("name")) for write in writes}
    first: list[str] = []
    for write in writes:
        on_error = write.get("onError")
        if on_error == "continueRegularOutput" or (
            on_error is None and write.get("continueOnFail") is True
        ):
            continue
        exits = _exits(str(write.get("name")), connections)
        dead = exits[:1] if on_error == "continueErrorOutput" else exits
        first += [name for targets in dead for name in targets]
    return frozenset(_reached(first, connections) - names)


def _exits(name: str, connections: Mapping[str, Any]) -> list[list[str]]:
    """The blocks each of a block's exits leads to, in exit order."""
    outputs: object = cast(Mapping[str, Any], connections.get(name) or {}).get("main")
    return [
        [str(cast(Mapping[str, Any], link).get("node")) for link in cast(list[Any], links or [])]
        for links in cast(list[Any], outputs or [])
    ]


def _reached(starts: Sequence[str], connections: Mapping[str, Any]) -> set[str]:
    """These blocks, and every block reached from them."""
    seen = set(starts)
    queue = deque(starts)
    while queue:
        for targets in _exits(queue.popleft(), connections):
            for target in targets:
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
    return seen


def kinds_that_apply(plan: SimulationPlan) -> tuple[ScenarioKind, ...]:
    """A version with no Ask for a yes gets no "Approver says no". A version that reads no source
    gets none of the kinds about what a source answers, and one whose reads no allow list covers
    gets no "Odd data", since code has no sample to vary."""
    return tuple(kind for kind in KINDS if _applies(kind, plan) is None)


def _applies(kind: ScenarioKind, plan: SimulationPlan) -> str | None:
    """None when the kind applies, else words for why not."""
    said = f'"{KIND_SAID[kind]}"'
    if kind == "approver_says_no" and not plan.having("ask"):
        return f"{said} needs an Ask for approval block, and this version has none."
    if kind in NEEDS_A_READ and not plan.reads:
        return f"{said} needs a block that reads a source, and this version has none."
    if kind == "odd_data" and all(b.answer is None for b in plan.reads):
        return f"{said} needs a read a recorded sample covers, and this version has none."
    return None


# The templates


def _template_play(
    kind: ScenarioKind, block: PlanBlock, plan: SimulationPlan, samples: RecordedSamples
) -> Play:
    """The kind's own play where the block can play it, else as recorded. Nothing new empties
    every read. When no read can play the kind, each one that may is asked to, so staging lists
    each as not tried."""
    sample = None if block.answer is None else samples.for_block(block.name, block.answer).id
    point = POINT.get(kind)
    if point is None:
        return Play(serve="recorded", sample=sample)
    nobody = all(_cannot(b, point) is not None for b in plan.reads)
    may = not (point == "varied" and block.answer is None)
    if point != "empty" and not (_cannot(block, point) is None or (nobody and may)):
        return Play(serve="recorded", sample=sample)
    if point == "varied" and block.answer is not None:
        return Play(serve="varied", sample=sample, vary=list(ALLOW_LISTS[block.answer].varies))
    return Play(serve=point)


def _template_reply(kind: ScenarioKind, plan: SimulationPlan, block: PlanBlock) -> Reply:
    if kind == "nothing_new":
        return Reply(items=[])
    first = plan.agents[0].name == block.name
    proposes = plan.having("ask") and not plan.having("propose") and first
    return Reply(items=[SAMPLE_REPLY], proposes=[SAMPLE_CHANGE] if proposes else [])


def _template(kind: ScenarioKind, plan: SimulationPlan, samples: RecordedSamples) -> ScenarioSpec:
    return ScenarioSpec(
        kind=kind,
        name=kind,
        reads={b.name: _template_play(kind, b, plan, samples) for b in plan.reads},
        agents={b.name: _template_reply(kind, plan, b) for b in plan.agents},
    )


def templates(plan: SimulationPlan, samples: RecordedSamples) -> tuple[ScenarioSpec, ...]:
    """Code's own scenarios, one for each kind that applies, which run without a model."""
    return tuple(_template(kind, plan, samples) for kind in kinds_that_apply(plan))


def _filled(spec: ScenarioSpec, plan: SimulationPlan, samples: RecordedSamples) -> ScenarioSpec:
    """The scenario, with each read and Agent block it leaves out served as its template does."""
    template = _template(spec.kind, plan, samples)
    return spec.model_copy(
        update={
            "reads": {**template.reads, **spec.reads},
            "agents": {**template.agents, **spec.agents},
        }
    )


# The check


def _sample_of(play: Play, block: PlanBlock, samples: RecordedSamples) -> Any:
    if play.sample is not None:
        return samples.get(play.sample)
    return None if block.answer is None else samples.for_block(block.name, block.answer)


def _play_problems(name: str, block: PlanBlock, play: Play, samples: RecordedSamples) -> list[str]:
    if play.serve != "varied" and play.vary:
        return [f'"{name}" is not varied, so it names no way to vary it.']
    if play.serve == "varied" and not play.vary:
        return [f'"{name}" is varied, so it names how to vary it.']
    twice = sorted({v for v in play.vary if play.vary.count(v) > 1})
    if twice:
        return [f'"{name}" names "{twice[0]}" twice.']
    if play.gone and play.serve not in GONE_SERVES:
        return [f'"{name}" names places that are gone, so it is served as recorded or varied.']
    if play.gone and (why := _cannot(block, "not_found")) is not None:
        return [f'"{name}" names places that are gone, but {why[0].lower()}{why[1:]}']
    if play.sample is not None:
        sample = samples.get(play.sample)
        if sample is None:
            return [f'There is no recorded sample "{play.sample}".']
        if sample.answer != block.answer:
            return [f'The sample "{play.sample}" is not what "{name}" reads.']
    if play.serve == "varied":
        if block.answer is None:
            return [f'"{name}" reads what no allow list covers, so it can\'t be varied.']
        sample = _sample_of(play, block, samples)
        varied = vary(sample.items, block.answer, play.vary)
        if isinstance(varied, str):
            return [varied]
    return []


def _kind_problem(kind: ScenarioKind, serves: Sequence[Serve]) -> str | None:
    said = f'"{KIND_SAID[kind]}"'
    match kind:
        case "nothing_new" if any(s != "empty" for s in serves):
            return f"{said} serves every read empty."
        case "source_not_found" | "timeout":
            point = POINT[kind]
            if point not in serves or any(s not in (point, "recorded") for s in serves):
                return (
                    f"{said} plays at least one read as {HOW[point]}, and serves every other as "
                    "recorded."
                )
        case "happy_path" | "approver_says_no" if any(s != "recorded" for s in serves):
            return f"{said} serves every read as recorded."
        case "odd_data":
            if "varied" not in serves or any(s not in ("varied", "recorded") for s in serves):
                return f"{said} varies at least one read, and serves every other as recorded."
        case _:
            pass
    return None


def check(spec: ScenarioSpec, plan: SimulationPlan, samples: RecordedSamples) -> tuple[str, ...]:
    """Words for each way the scenario doesn't fit the version. None when it fits."""
    applies = _applies(spec.kind, plan)
    if applies is not None:
        return (applies,)
    problems: list[str] = []
    reads = {b.name: b for b in plan.reads}
    for name, play in spec.reads.items():
        block = reads.get(name)
        if block is None:
            problems.append(f'The version has no block "{name}" that reads a source.')
        else:
            problems += _play_problems(name, block, play, samples)
    agents = {b.name for b in plan.agents}
    problems += [f'The version has no Agent block "{n}".' for n in spec.agents if n not in agents]
    if spec.kind != "timeout" and any(r.serve == "too_slow" for r in spec.agents.values()):
        problems.append('Only "Timeout" plays an agent as too slow.')
    filled = _filled(spec, plan, samples)
    serves: list[Serve] = [filled.reads[b.name].serve for b in plan.reads]
    problem = _kind_problem(spec.kind, serves)
    if problem is not None:
        problems.append(problem)
    github = {
        filled.reads[b.name].model_dump_json()
        for b in plan.reads
        if b.mode == "mock" and b.mock == "github"
    }
    if len(github) > 1:
        problems.append("Blocks that read mock GitHub get one answer in a scenario.")
    return tuple(problems)


def check_all(
    specs: Sequence[ScenarioSpec], plan: SimulationPlan, samples: RecordedSamples
) -> tuple[str, ...]:
    """Every problem of every scenario, each after its scenario's name."""
    problems: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        problems += [f"{spec.name}: {problem}" for problem in check(spec, plan, samples)]
        if spec.name in seen:
            problems.append(f'Two scenarios are named "{spec.name}".')
        seen.add(spec.name)
    return tuple(problems)


# Staging


@dataclass(frozen=True)
class NotTried:
    block: str
    why: str


@dataclass(frozen=True)
class Played:
    """How a scenario played one block, when not as recorded: a read served another way, or an
    Agent block that is too slow. The explainer reads these (PR 6)."""

    block: str
    serve: Serve
    vary: tuple[Variation, ...] = ()


@dataclass(frozen=True)
class Staged:
    """One scenario, ready to run."""

    kind: ScenarioKind
    name: str
    gateway: Scenario
    """What the gateway answers our blocks."""
    pins: Mapping[str, list[dict[str, Any]]]
    """The output pinned for each block with no mock that the scenario serves."""
    github: GitHubPlay | None
    """What mock GitHub does, when a block reads it."""
    not_tried: tuple[NotTried, ...]
    """Blocks the scenario can't play as it asks."""
    runs: bool
    """Whether any block plays what the kind is about. When none can, it is not run."""
    plays: tuple[Played, ...] = ()
    """How it played each block other than as recorded, in the version's order."""


def _items(
    play: Play, block: PlanBlock, samples: RecordedSamples
) -> tuple[Mapping[str, Json], ...]:
    """What the play serves, when it serves items. A failure serves the recorded sample, for a
    block that can't fail."""
    if play.serve == "empty":
        return ()
    sample = _sample_of(play, block, samples)
    if sample is None or block.answer is None:
        return ()
    if play.serve == "varied":
        varied = vary(sample.items, block.answer, play.vary)
        return () if isinstance(varied, str) else varied
    return cast(tuple[Mapping[str, Json], ...], sample.items)


def _cannot(block: PlanBlock, serve: Serve) -> str | None:
    """Words for why the block can't be played this way, or None when it can."""
    how = HOW[serve]
    if serve == "recorded":
        return None
    if serve == "varied" and block.answer is None:
        return NO_ALLOW_LIST.format(how=how)
    if block.mode == "ours":
        return None
    if block.mode == "pinned":
        return PINNED_PLAY.format(how=how) if serve in FAILURES else None
    if block.mock not in STEERED:
        return ONE_WAY_MOCK.format(how=how)
    if serve == "empty" and block.answer is None:
        return NO_ALLOW_LIST.format(how=how)
    return None


def stage(spec: ScenarioSpec, plan: SimulationPlan, samples: RecordedSamples) -> Staged:
    """A scenario the check took, as the gateway, mock GitHub and the copy's pins play it. A
    block that can't play what the scenario is about is listed as not tried."""
    filled = _filled(spec, plan, samples)
    point = POINT.get(spec.kind)
    answers: dict[str, BlockAnswer] = {}
    pins: dict[str, list[dict[str, Any]]] = {}
    github: GitHubPlay | None = None
    not_tried: list[NotTried] = []
    played = point is None
    for block in plan.reads:
        play = filled.reads[block.name]
        why = _cannot(block, play.serve)
        if why is None and point is not None and play.serve != point:
            why = _cannot(block, point)
        if why is not None:
            not_tried.append(NotTried(block.name, why))
        played = played or (why is None and play.serve == point)
        items = [dict(item) for item in _items(play, block, samples)]
        if block.mode == "ours":
            serve = {"not_found": "not_found", "too_slow": "timeout"}.get(play.serve, "recorded")
            items = [] if play.serve in FAILURES else items
            answers[block.name] = BlockAnswer.model_validate(
                {"serve": serve, "items": items, "gone": play.gone}
            )
        elif block.mode == "pinned":
            if block.answer is not None or play.serve == "empty":
                pins[block.name] = items
        elif block.mock in STEERED:
            github = _github_play(play, block, items)
    for block in plan.agents:
        reply = filled.agents[block.name]
        answers[block.name] = BlockAnswer(
            serve="recorded" if reply.serve == "recorded" else "timeout",
            items=reply.items,
            proposes=reply.proposes,
        )
    approver = "no" if spec.kind == "approver_says_no" else "yes"
    gateway = Scenario(name=spec.name, blocks=answers, approver=approver)
    plays = _plays(filled, plan)
    return Staged(spec.kind, spec.name, gateway, pins, github, tuple(not_tried), played, plays)


def _plays(filled: ScenarioSpec, plan: SimulationPlan) -> tuple[Played, ...]:
    reads = [(b.name, filled.reads[b.name]) for b in plan.reads]
    slow = [b.name for b in plan.agents if filled.agents[b.name].serve == "too_slow"]
    return (
        *(Played(n, p.serve, tuple(p.vary)) for n, p in reads if p.serve != "recorded"),
        *(Played(n, "too_slow") for n in slow),
    )


def plays_of(block: PlanBlock) -> tuple[Serve, ...]:
    """How a simulation can play the block: each way a read can be served, or recorded and too
    slow for an Agent block. None for any other block. The scenario writer is offered these."""
    if block.role == "agent":
        return ("recorded", "too_slow")
    if block.role != "read":
        return ()
    return tuple(serve for serve in SERVES if _cannot(block, serve) is None)


def _github_play(play: Play, block: PlanBlock, items: list[dict[str, Any]]) -> GitHubPlay:
    gone = tuple(play.gone)
    match play.serve:
        case "not_found":
            return GitHubPlay("not_found", None)
        case "too_slow":
            return GitHubPlay("drop", None)
        case _ if block.answer is None:
            return GitHubPlay("ok", None, gone)
        case _:
            return GitHubPlay("ok", tuple(items), gone)
