"""The plan of a drafted workflow, and code's check of its blocks and wires against the catalogue
(ADR 0051, sections 1 and 2). The model chooses and code places: a plan names blocks with their
parameters, the wires between their exits, and the settings that stand in for values. Code checks
every type, version, resource, operation, parameter, value and wire against the catalogue of the
pinned n8n image, and refuses what can't run on this platform. A plan that fails goes back to the
drafter with every problem, in words it can act on. Plain code, with no model.

A wire leaves by one of the block's exits and joins one of the next block's inputs, as n8n's
outputs and inputs in the catalogue say (`connections`).
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, cast

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.catalogue import (
    CUSTOM_API_CALL,
    OURS,
    Catalogue,
    Json,
    NotInCatalogue,
    is_expression,
)
from agent_runtime.connections import MAIN, Inputs, Link
from agent_runtime.contract import (
    BLOCK_NAME_LIMIT,
    PLAN_NAME_LIMIT,
    PlanBlock,
    PlanProblem,
    PlanWire,
    ProblemCode,
    SettingKind,
    SettingPlace,
)

PLACEHOLDER: Final = re.compile(r"<<([a-z][a-z0-9_]{0,39})>>")
"""A setting's placeholder, which stands as a whole value: <<channel>>."""
MOST_BLOCKS: Final = 40
MOST_WIRES: Final = 80
USE_OURS: Final = "Use our Propose a change, Ask for approval and Make the approved changes blocks"
THEMED: Final = re.compile(
    r"\b(Flint|Forge|Striker|Spark\s+Map|Scout|Analyst|Messenger|Clerk|Fixer|Kindling|"
    r"Firebreak|Ember)\b",
    re.IGNORECASE,
)
"""The old themed names, which confused the sponsor."""
LANGCHAIN: Final = "@n8n/n8n-nodes-langchain."
SHIPPED: Final = ("n8n-nodes-base.", LANGCHAIN, OURS)
"""The packages whose blocks our n8n loads: n8n's two, and our node pack."""


# What the drafter submits. Every field is required, as strict tools ask, and their descriptions
# are what the model reads.


class _Shape(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ProposedBlock(_Shape):
    name: str = Field(
        description="Plain words, unique in the plan, at most 60 characters, as Read open bugs."
    )
    type: str = Field(description="The block's type, exactly as find_blocks gave it.")
    version: float = Field(description="A version describe_block gave for the block.")
    parameters: str = Field(
        description="The block's parameters as one JSON object, as n8n holds them: resource and "
        "operation in it when the block has them, then only parameters describe_block showed. A "
        "setting's placeholder <<id>> is a whole value. An expression is text that starts with =."
    )


class ProposedWire(_Shape):
    from_block: str = Field(description="The name of the block the items leave.")
    exit: str = Field(
        description='Which exit of from_block: "main" for a block with one exit, else the exit\'s '
        "name, as describe_block lists them."
    )
    to_block: str = Field(description="The name of the block the items go to.")
    input: int | None = Field(
        default=None,
        description="Which input of to_block, numbered from 0 among its inputs of the wire's "
        "kind, as describe_block numbers them: 1 is Merge's Input 2. null for a block with one "
        "input of that kind, or to take its next free input in the order the plan lists its "
        "wires.",
    )


class ProposedSetting(_Shape):
    id: str = Field(
        description="Lowercase letters, digits and _, starting with a letter, as jira_project. "
        "Its placeholder is <<id>>."
    )
    kind: SettingKind
    label: str = Field(description="What it is, in 2 to 6 plain words, as The Slack channel.")
    value: str | None = Field(
        description="The value from the person's words or the facts, or your guess for a "
        "repository, a Confluence page or text. null when you don't know it."
    )


class ProposedPlan(_Shape):
    """Submit the whole plan of the workflow. The platform checks every block, parameter, value
    and wire against n8n, and sends the plan back with each problem until it passes."""

    name: str = Field(description="The workflow's name: 2 to 6 plain words saying what it does.")
    blocks: list[ProposedBlock]
    wires: list[ProposedWire]
    settings: list[ProposedSetting]


# Blocks that can't be in a plan, whatever the catalogue holds.

NEVER_LOADED: Final[Mapping[str, str]] = {
    "n8n-nodes-base.executeCommand": "Execute Command",
    "n8n-nodes-base.localFileTrigger": "Local File Trigger",
    "n8n-nodes-base.function": "Function",
    "n8n-nodes-base.functionItem": "Function Item",
    "@n8n/n8n-nodes-langchain.code": "LangChain Code",
    "n8n-nodes-base.git": "Git",
    "n8n-nodes-base.gitTool": "Git Tool",
}
"""The blocks n8n never loads on this platform (NODES_EXCLUDE, platform-api's n8n_blocks.LEFT_OUT),
because each reaches n8n's own secrets, disk or host."""
PLATFORM_ADDS: Final[Mapping[str, str]] = {
    "n8n-nodes-base.stickyNote": "the Sticky Note",
    f"{OURS}wabStartFromPortal": "Start from the Portal, beside any schedule",
    f"{OURS}wabReportFailure": "Report failure, in its error workflow",
}
CANT_RUN: Final[Mapping[str, str]] = {
    "n8n-nodes-base.n8n": "It changes n8n itself, and Settings refuses a key to n8n's own API.",
    "n8n-nodes-base.microsoftTeams": "It posts only with a person's own sign-in. Our Tell block "
    "tells the team in Teams.",
}
ATLASSIAN: Final[Mapping[str, str]] = {
    "n8n-nodes-base.jira": "Jira",
    "n8n-nodes-base.confluence": "Confluence",
}
READ_OPERATION: Final = re.compile(r"^(?:get|query|search)")
"""An operation of n8n's Confluence block, which the class file doesn't class, that only reads."""
ATLASSIAN_URL: Final = re.compile(
    r"atlassian\.(?:net|com)|/rest/(?:api|agile)/|/wiki/(?:rest|api)/", re.IGNORECASE
)
"""Jira's and Confluence's APIs, in the cloud, through Atlassian's gateway, or self-hosted."""
READ_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Requester:
    """A block that sends a request to an address its parameters name."""

    method: str | None
    """The parameter that holds the method, or None for GraphQL, whose query decides."""
    address: str


REQUESTERS: Final[Mapping[str, Requester]] = {
    "n8n-nodes-base.httpRequest": Requester("method", "url"),
    "@n8n/n8n-nodes-langchain.toolHttpRequest": Requester("method", "url"),
    "n8n-nodes-base.graphql": Requester(None, "endpoint"),
}
MUTATION: Final = re.compile(r"\bmutation\b", re.IGNORECASE)
PARAMETERS_LIMIT: Final = 20_000
"""The most characters of one block's parameters, as JSON."""


def refused_type(node_type: str) -> PlanProblem | None:
    """Why a type can't be in a plan before the catalogue is read, or None."""
    if node_type in NEVER_LOADED:
        return PlanProblem(
            code="left_out",
            text=f"{NEVER_LOADED[node_type]} never loads on this platform, because it would reach "
            "n8n's own secrets, disk or host. Use another block.",
        )
    if not node_type.startswith(SHIPPED):
        return PlanProblem(
            code="community",
            text=f"{node_type!r} is not one of n8n's own blocks or ours. Community nodes stay off "
            "on this platform.",
        )
    if node_type in PLATFORM_ADDS:
        return PlanProblem(
            code="platform_adds",
            text=f"Leave {node_type} out: the platform adds {PLATFORM_ADDS[node_type]} itself.",
        )
    return None


STARTS: Final = frozenset(
    {
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.cron",
        "n8n-nodes-base.interval",
        "n8n-nodes-base.start",
        "n8n-nodes-base.emailReadImap",
    }
)
"""Blocks that start a workflow, besides every type whose name ends in Trigger."""


def starts_a_run(node_type: str) -> bool:
    """Whether a run starts at the block, so no wire of any kind may join it. A tool wired into
    MCP Server Trigger would let any outside caller use it, with no yes."""
    return node_type in STARTS or node_type.endswith("Trigger")


# Parameters that hold a setting, never a value the drafter writes.

NEVER_GUESSED: Final[Mapping[str, Mapping[str, SettingKind]]] = {
    "n8n-nodes-base.scheduleTrigger": {"rule": "run_time"},
    "n8n-nodes-base.jira": {"project": "jira_project"},
    "n8n-nodes-base.slack": {
        "channelId": "channel",
        "user": "channel",
        "otherOptions.ephemeral.ephemeralValues.user": "channel",
    },
    "n8n-nodes-base.mattermost": {"channelId": "channel"},
    "n8n-nodes-base.discord": {"channelId": "channel", "userId": "channel"},
    "n8n-nodes-base.telegram": {"chatId": "channel"},
    "n8n-nodes-base.emailSend": {
        "toEmail": "address",
        "options.ccEmail": "address",
        "options.bccEmail": "address",
        "options.replyTo": "address",
    },
    "n8n-nodes-base.gmail": {
        "sendTo": "address",
        "options.sendTo": "address",
        "options.ccList": "address",
        "options.bccList": "address",
        "options.replyTo": "address",
    },
    "n8n-nodes-base.microsoftOutlook": {
        "toRecipients": "address",
        "additionalFields.toRecipients": "address",
        "additionalFields.ccRecipients": "address",
        "additionalFields.bccRecipients": "address",
        "additionalFields.replyTo": "address",
    },
}
"""The run time, the Jira project, and each place a notice posts to, by the full path of the
parameter that holds it. ADR 0051, section 5, never lets the drafter guess these, so only a
setting's placeholder may stand there: never a value, and never an expression."""
READ_PLACES: Final[Mapping[str, SettingKind]] = {
    "jira_tickets": "jira_project",
    "github_releases": "repository",
    "confluence_page": "confluence_page",
}
KIND_WORDS: Final[Mapping[SettingKind, str]] = {
    "run_time": "a run time",
    "jira_project": "a Jira project",
    "channel": "a channel a notice posts to",
    "address": "an address a notice posts to",
    "repository": "a repository",
    "confluence_page": "a Confluence page",
    "text": "a value",
}


def setting_places(base: str, values: Mapping[str, object]) -> dict[str, SettingKind]:
    """The kind of setting each parameter path of the block must hold. Only a placeholder may
    stand there. Our Read's and Propose a change's place is always a setting, so code can check
    it against the places the team allows."""
    places: dict[str, SettingKind] = dict(NEVER_GUESSED.get(base, {}))
    if base == f"{OURS}wabRead":
        places["place"] = READ_PLACES.get(str(values.get("source")), "text")
    if base == f"{OURS}wabProposeChange":
        action = str(values.get("action") or "")
        places["place"] = "confluence_page" if action.startswith("confluence.") else "jira_project"
    return places


def placeholder_of(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    found = PLACEHOLDER.fullmatch(value)
    return None if found is None else found.group(1)


def _empty(value: object) -> bool:
    if isinstance(value, dict):
        locator = cast(Json, value)
        return not locator or ("mode" in locator and locator.get("value") in ("", None))
    return value in ("", None) or value == []


# The check of one block's parameters.


@dataclass
class _Walk:
    block: str
    held: Mapping[str, SettingKind] = field(default_factory=dict[str, SettingKind])
    """The parameter paths only a setting's placeholder may fill, with the setting's kind."""
    problems: list[PlanProblem] = field(default_factory=list[PlanProblem])
    placeholders: list[tuple[str, str, SettingKind | None]] = field(
        default_factory=list[tuple[str, str, SettingKind | None]]
    )
    """Each placeholder's setting id, the parameter path it stands in, and the kind of setting
    that path must hold, if it must hold one kind."""

    def bad(self, code: ProblemCode, text: str) -> None:
        self.problems.append(
            PlanProblem(code=code, block=self.block, text=f'"{self.block}": {text}')
        )


def _listed(values: Sequence[object], most: int = 15) -> str:
    shown = ", ".join(json.dumps(v) for v in values[:most])
    return shown + (", ..." if len(values) > most else "")


def _fit(parameter: Json, value: object, path: str, walk: _Walk) -> None:
    """Whether the value fits the parameter, as n8n's editor would hold it."""
    kind = walk.held.get(path)
    if kind is not None:
        _setting_only(parameter, value, path, kind, walk)
        return
    said = placeholder_of(value)
    if said is not None:
        listed = [o.get("value") for o in cast(list[Json], parameter.get("options") or [])]
        if parameter.get("type") in ("options", "multiOptions") and listed:
            # A setting's value isn't checked against the choices, so it can't stand in for one.
            walk.bad(
                "bad_value", f"{path} takes one of {_listed(listed)}, written out, never a setting."
            )
            return
        walk.placeholders.append((said, path, None))
        return
    if is_expression(value):
        if parameter.get("noDataExpression"):
            walk.bad("bad_value", f"{path} takes a value written out, not an expression.")
        return
    options = cast(Json, parameter.get("typeOptions") or {})
    many = options.get("multipleValues") is True
    match parameter.get("type"):
        case "string" | "dateTime" | "color":
            items = cast(list[object], value) if many and isinstance(value, list) else [value]
            if not all(isinstance(item, str) for item in items):
                walk.bad("bad_value", f"{path} takes text.")
        case "number":
            _number(options, value, path, walk)
        case "boolean":
            if not isinstance(value, bool):
                walk.bad("bad_value", f"{path} takes true or false.")
        case "options":
            _choice(parameter, value, path, walk)
        case "multiOptions":
            if not isinstance(value, list):
                walk.bad("bad_value", f"{path} takes a list of choices.")
            else:
                for item in cast(list[object], value):
                    _choice(parameter, item, path, walk)
        case "json":
            if not isinstance(value, str | dict | list):
                walk.bad("bad_value", f"{path} takes JSON.")
        case "collection":
            for entry in _entries(value, many, path, walk):
                _named(cast(list[Json], parameter.get("options") or []), entry, path, walk)
        case "fixedCollection":
            _fixed(parameter, value, path, walk, many)
        case "resourceLocator":
            _locator(parameter, value, path, walk)
        case _:
            pass


def _locator_of(parameter: Json, value: object) -> Json | None:
    """The value as a resource locator, when the parameter is one and the value is an object."""
    if parameter.get("type") != "resourceLocator" or not isinstance(value, dict):
        return None
    return cast(Json, value)


def _setting_only(
    parameter: Json, value: object, path: str, kind: SettingKind, walk: _Walk
) -> None:
    """A path a setting holds takes only its placeholder, as the whole value or as a resource
    locator's value. A value or an expression there is a guess."""
    said = placeholder_of(value)
    if said is not None:
        walk.placeholders.append((said, path, kind))
        return
    locator = _locator_of(parameter, value)
    if locator is not None and (inner := placeholder_of(locator.get("value"))) is not None:
        if _locator_fits(parameter, locator, path, walk):
            walk.placeholders.append((inner, f"{path}.value", kind))
        return
    if _empty(value):
        if parameter.get("required"):
            walk.bad(
                "missing_value",
                f"{path} is {KIND_WORDS[kind]}, which the workflow can't run without. Put a "
                f'placeholder there, as "<<{kind}>>", and add a setting of kind {kind} with no '
                "value, so the person is asked for it.",
            )
    else:
        walk.bad(
            "guessed",
            f"{path} is {KIND_WORDS[kind]}, which a setting holds and the drafter never writes, "
            f'not even as an expression. Put a placeholder there, as "<<{kind}>>", and add a '
            f"setting of kind {kind}.",
        )


def _number(options: Json, value: object, path: str, walk: _Walk) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        walk.bad("bad_value", f"{path} takes a number.")
        return
    low, high = options.get("minValue"), options.get("maxValue")
    if isinstance(low, int | float) and value < low:
        walk.bad("bad_value", f"{path} is at least {low}.")
    if isinstance(high, int | float) and value > high:
        walk.bad("bad_value", f"{path} is at most {high}.")


def _choice(parameter: Json, value: object, path: str, walk: _Walk) -> None:
    options = cast(Json, parameter.get("typeOptions") or {})
    allowed = [o.get("value") for o in cast(list[Json], parameter.get("options") or [])]
    if "loadOptionsMethod" in options and not allowed:
        # n8n lists these choices while it runs, so any written value may be one of them. The
        # catalogue lists the ones our API gives every team, such as Propose a change's changes.
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            walk.bad("bad_value", f"{path} takes one choice, written out.")
        return
    if not any(value == a and type(value) is type(a) for a in allowed):
        walk.bad("bad_value", f"{path} must be one of {_listed(allowed)}.")


def _entries(value: object, many: bool, path: str, walk: _Walk) -> list[Json]:
    items = cast(list[object], value) if many and isinstance(value, list) else [value]
    if not all(isinstance(item, dict) for item in items):
        walk.bad("bad_value", f"{path} takes " + ("a list of objects." if many else "an object."))
        return []
    return cast(list[Json], items)


def _named(parameters: list[Json], entry: Json, path: str, walk: _Walk) -> None:
    by_name = {str(p.get("name")): p for p in parameters}
    for key, inner in entry.items():
        parameter = by_name.get(key)
        if parameter is None:
            walk.bad("no_parameter", f"{path} has no {key!r}. It has {_listed(sorted(by_name))}.")
        else:
            _fit(parameter, inner, f"{path}.{key}", walk)


def _fixed(parameter: Json, value: object, path: str, walk: _Walk, many: bool) -> None:
    if not isinstance(value, dict):
        walk.bad("bad_value", f"{path} takes an object of its groups.")
        return
    groups = {str(g.get("name")): g for g in cast(list[Json], parameter.get("options") or [])}
    for name, inside in cast(Json, value).items():
        group = groups.get(name)
        if group is None:
            walk.bad(
                "no_parameter", f"{path} has no group {name!r}. It has {_listed(sorted(groups))}."
            )
            continue
        for entry in _entries(inside, many, f"{path}.{name}", walk):
            _named(cast(list[Json], group.get("values") or []), entry, f"{path}.{name}", walk)


LOCATOR_KEYS: Final = frozenset({"__rl", "mode", "value", "cachedResultName", "cachedResultUrl"})


def _locator(parameter: Json, value: object, path: str, walk: _Walk) -> None:
    if isinstance(value, str):
        return
    if not isinstance(value, dict):
        walk.bad("bad_value", f'{path} takes {{"__rl": true, "mode": ..., "value": ...}}.')
        return
    locator = cast(Json, value)
    if not _locator_fits(parameter, locator, path, walk):
        return
    inner = locator.get("value")
    if (said := placeholder_of(inner)) is not None:
        walk.placeholders.append((said, f"{path}.value", None))
    elif isinstance(inner, bool) or not isinstance(inner, str | int | float):
        walk.bad("bad_value", f"{path}.value takes text.")


def _locator_fits(parameter: Json, locator: Json, path: str, walk: _Walk) -> bool:
    modes = [str(m.get("name")) for m in cast(list[Json], parameter.get("modes") or [])]
    if set(locator) - LOCATOR_KEYS or locator.get("mode") not in modes:
        walk.bad(
            "bad_value",
            f'{path} takes {{"__rl": true, "mode": ..., "value": ...}} with a mode of '
            f"{_listed(modes)}.",
        )
        return False
    return True


# One block.


@dataclass(frozen=True)
class CheckedBlock:
    block: PlanBlock
    exits: tuple[Link, ...]
    inputs: Inputs
    starts: bool
    """Whether a run starts at the block, so no wire joins it."""
    placeholders: list[tuple[str, str, SettingKind | None]]
    """Each placeholder's setting id, the parameter path, and the kind of setting the parameter
    must hold, if it must hold one kind."""


def check_block(proposed: ProposedBlock, catalogue: Catalogue) -> CheckedBlock | list[PlanProblem]:
    walk = _Walk(proposed.name)
    refused = refused_type(proposed.type)
    if refused is not None:
        return [refused.model_copy(update={"block": proposed.name})]
    if len(proposed.parameters) > PARAMETERS_LIMIT:
        walk.bad(
            "too_big",
            f"its parameters are longer than {PARAMETERS_LIMIT} characters. Keep only what the "
            "task needs.",
        )
        return walk.problems
    try:
        block = catalogue.block(proposed.type)
    except NotInCatalogue as missing:
        walk.bad("no_block", str(missing))
        return walk.problems
    base = str(block.get("tool_of") or proposed.type)
    if base in CANT_RUN:
        walk.bad("cant_run", f"{block['name']} can't run on this platform. {CANT_RUN[base]}")
        return walk.problems
    if block.get("hidden") and not block.get("held"):
        # A held block is refused below, with the reason it waits.
        walk.bad(
            "hidden",
            f"n8n hides {block['name']} from its editor, as old or replaced, so the drafter "
            "doesn't use it. Find another block with find_blocks.",
        )
        return walk.problems
    try:
        loaded = json.loads(proposed.parameters)
    except ValueError:
        loaded = None
    if not isinstance(loaded, dict):
        walk.bad("unreadable", "parameters must be one JSON object.")
        return walk.problems
    values = cast(Json, loaded)
    described = _described(proposed, catalogue, values, walk)
    if described is None:
        return walk.problems
    known = {k: v for k, v in values.items() if placeholder_of(v) is None}
    settled = catalogue.settled(proposed.type, proposed.version, known)
    _held(block, settled, values, walk)
    _native_write(block, base, described, settled, values, walk)
    if walk.problems:
        # The block must go, so its parameters don't matter.
        return walk.problems
    shown = catalogue.shown(proposed.type, proposed.version, known)
    walk.held = setting_places(base, values)
    _parameters(shown, values, walk)
    if walk.problems:
        return walk.problems
    return CheckedBlock(
        PlanBlock(
            name=proposed.name, type=proposed.type, version=proposed.version, parameters=values
        ),
        catalogue.exits(proposed.type, proposed.version, known),
        catalogue.inputs(proposed.type, proposed.version, known),
        starts_a_run(proposed.type),
        walk.placeholders,
    )


def _described(
    proposed: ProposedBlock, catalogue: Catalogue, values: Json, walk: _Walk
) -> Json | None:
    """The block described for its resource and operation, or None with the problem."""
    try:
        top = catalogue.describe_block(proposed.type, proposed.version)
    except NotInCatalogue as missing:
        walk.bad("no_version", str(missing))
        return None
    resource, operation = values.get("resource"), values.get("operation")
    for name, said in (("resource", resource), ("operation", operation)):
        if said is not None and not isinstance(said, str):
            walk.bad("bad_value", f"{name} is written out as text.")
            return None
        if is_expression(said) or placeholder_of(said) is not None:
            walk.bad("bad_value", f"{name} is written out, never an expression or a setting.")
            return None
    resources = [str(r.get("value")) for r in cast(list[Json], top.get("resources") or [])]
    try:
        described = catalogue.describe_block(
            proposed.type, proposed.version, cast(str | None, resource), cast(str | None, operation)
        )
    except NotInCatalogue as missing:
        code: ProblemCode = (
            "no_resource" if resource is not None and resource not in resources else "no_operation"
        )
        walk.bad(code, str(missing))
        return None
    if "choose" in described:
        offered = [
            f"{o['resource']}/{o['value']}" if "resource" in o else str(o["value"])
            for o in cast(list[Json], described.get("operations") or [])
        ]
        needs = "a resource and an operation" if resources and resource is None else "an operation"
        walk.bad(
            "missing_value",
            f"{described['name']} needs {needs} in its parameters. It offers {_listed(offered)}.",
        )
        return None
    return described


def _held(block: Json, settled: Mapping[str, object], values: Json, walk: _Walk) -> None:
    for hold in cast(list[Json], block.get("held") or []):
        when = cast(Mapping[str, list[object]], hold.get("when") or {})
        # A value code can't read could be the one held, so it counts as held.
        if all(
            is_expression(values.get(name))
            or placeholder_of(values.get(name)) is not None
            or settled.get(name) in allowed
            for name, allowed in when.items()
        ):
            only = "".join(f" with {name} {_listed(allowed)}" for name, allowed in when.items())
            walk.bad(
                "held",
                f"{block['name']}{only} can't run on this platform yet. {hold['because']} It "
                f"waits for {hold['waits_for']}.",
            )


def _native_write(
    block: Json,
    base: str,
    described: Json,
    settled: Mapping[str, object],
    values: Json,
    walk: _Walk,
) -> None:
    """A write to Jira or Confluence by one of n8n's own blocks goes back: our blocks give that
    write a yes on each run. It is the drafter's rule, not a limit on people. A block that sends
    a request (`REQUESTERS`) and writes must name its address written out, so the check can read
    it."""
    system = ATLASSIAN.get(base)
    operation = str(described.get("operation") or "")
    if system is not None:
        classed = described.get("class")
        reads = classed == "read" or (
            classed is None and operation != CUSTOM_API_CALL and READ_OPERATION.match(operation)
        )
        if not reads:
            walk.bad(
                "native_write",
                f"{block['name']} writes to {system} with n8n's own block. "
                f"{USE_OURS}, which ask for approval of that write on each run.",
            )
    requester = REQUESTERS.get(base)
    if requester is None or not _writes(requester, settled, values):
        return
    address = values.get(requester.address)
    if is_expression(address) or placeholder_of(address) is not None:
        walk.bad(
            "address_unread",
            f"{block['name']} sends a change to an address an expression or a setting picks. "
            "Write the address out, so the check can read it.",
        )
    elif isinstance(address, str) and ATLASSIAN_URL.search(address):
        walk.bad(
            "native_write",
            f"{block['name']} writes to Jira or Confluence. {USE_OURS}, which ask for "
            "approval of that write on each run.",
        )


def _writes(requester: Requester, settled: Mapping[str, object], values: Json) -> bool:
    """Whether the request may change something. A method or a query that code can't read counts
    as a change."""
    if requester.method is None:
        query = values.get("query")
        return not isinstance(query, str) or is_expression(query) or bool(MUTATION.search(query))
    if is_expression(values.get(requester.method)):
        return True
    return str(settled.get(requester.method) or "GET").upper() not in READ_METHODS


def _parameters(shown: list[Json], values: Json, walk: _Walk) -> None:
    """Checks each value against the parameter n8n shows for it, and each parameter n8n needs
    against the values."""
    by_name: dict[str, Json] = {}
    for parameter in shown:
        name = str(parameter.get("name"))
        # Of two parameters with one name, the one n8n surely shows wins.
        if name not in by_name or (
            "displayOptions" in by_name[name] and "displayOptions" not in parameter
        ):
            by_name[name] = parameter
    for name, value in cast(Mapping[str, object], values).items():
        parameter = by_name.get(name)
        if parameter is None:
            walk.bad(
                "no_parameter",
                f"there is no parameter {name!r} for these values. It has "
                f"{_listed(sorted(by_name))}. Describe the block again to see them.",
            )
            continue
        _fit(parameter, value, name, walk)
    for name, parameter in by_name.items():
        if (
            parameter.get("required")
            and "displayOptions" not in parameter
            and name not in values
            and _empty(parameter.get("default"))
        ):
            label = parameter.get("displayName") or name
            walk.bad("missing_value", f"{label} ({name}) needs a value.")


# The whole plan's blocks and wires.


@dataclass(frozen=True)
class Placed:
    """A plan whose blocks and wires passed, with where each setting's placeholder stands."""

    name: str
    blocks: list[PlanBlock]
    wires: list[PlanWire]
    places: list[tuple[str, SettingPlace, SettingKind | None]]


def check_blocks(proposed: ProposedPlan, catalogue: Catalogue) -> Placed | list[PlanProblem]:
    problems = _names(proposed)
    checked: dict[str, CheckedBlock] = {}
    for block in proposed.blocks[:MOST_BLOCKS]:
        done = check_block(block, catalogue)
        if isinstance(done, list):
            problems += done
        else:
            checked[block.name] = done
    wires = _wires(proposed, checked, problems)
    if problems:
        return problems
    places: list[tuple[str, SettingPlace, SettingKind | None]] = [
        (said, SettingPlace(block=name, parameter=path), kind)
        for name, block in checked.items()
        for said, path, kind in block.placeholders
    ]
    return Placed(proposed.name.strip(), [b.block for b in checked.values()], wires, places)


def _plain(name: str, limit: int) -> str | None:
    """Why a name isn't plain, or None."""
    if not name.strip():
        return "is empty"
    if len(name) > limit:
        return f"is longer than {limit} characters"
    if any(not c.isprintable() for c in name) or "<<" in name:
        return "holds characters that are not plain words"
    if THEMED.search(name):
        return "uses an old themed name. Name it plainly by what it does"
    return None


def _names(proposed: ProposedPlan) -> list[PlanProblem]:
    problems: list[PlanProblem] = []
    if (why := _plain(proposed.name, PLAN_NAME_LIMIT)) is not None:
        problems.append(PlanProblem(code="name", text=f"The workflow's name {why}."))
    if not proposed.blocks:
        problems.append(PlanProblem(code="name", text="A plan needs at least one block."))
    if len(proposed.blocks) > MOST_BLOCKS:
        problems.append(PlanProblem(code="name", text=f"A plan has at most {MOST_BLOCKS} blocks."))
    seen: set[str] = set()
    for block in proposed.blocks:
        if (why := _plain(block.name, BLOCK_NAME_LIMIT)) is not None:
            problems.append(
                PlanProblem(
                    code="name", block=block.name, text=f"The block name {block.name!r} {why}."
                )
            )
        if block.name.casefold() in seen:
            problems.append(
                PlanProblem(
                    code="name", block=block.name, text=f"Two blocks are named {block.name!r}."
                )
            )
        seen.add(block.name.casefold())
    return problems


def _wires(
    proposed: ProposedPlan, checked: Mapping[str, CheckedBlock], problems: list[PlanProblem]
) -> list[PlanWire]:
    names = {b.name for b in proposed.blocks}
    if len(proposed.wires) > MOST_WIRES:
        problems.append(PlanProblem(code="wire", text=f"A plan has at most {MOST_WIRES} wires."))
    wires: list[PlanWire] = []
    # The inputs wires joined so far, and the ones the plan's wires name, by block and kind.
    joined: dict[tuple[str, str], set[int]] = {}
    named = _named_inputs(proposed, checked)
    seen: set[tuple[str, int, str]] = set()
    for wire in proposed.wires[:MOST_WIRES]:
        said = f"The wire from {wire.from_block!r} to {wire.to_block!r}"
        missing = [n for n in (wire.from_block, wire.to_block) if n not in names]
        if missing:
            problems.append(
                PlanProblem(
                    code="wire",
                    text=f"{said} names {', '.join(map(repr, missing))}, which "
                    "no block in the plan is called.",
                )
            )
            continue
        source, target = checked.get(wire.from_block), checked.get(wire.to_block)
        if source is None or target is None:
            continue  # The block's own problems are already listed.
        left = _exit_of(source.exits, wire.exit)
        if wire.from_block == wire.to_block:
            problems.append(PlanProblem(code="wire", text=f"{said} joins a block to itself."))
            continue
        if left is None:
            exits = _listed(_exit_names(source.exits)) if source.exits else "none"
            problems.append(
                PlanProblem(
                    code="wire",
                    text=f"{said} leaves by {wire.exit!r}, but "
                    f"{wire.from_block!r} has the exits {exits}.",
                )
            )
            continue
        exit_index, exit_name = left
        if (wire.from_block, exit_index, wire.to_block) in seen:
            problems.append(PlanProblem(code="wire", text=f"{said} is in the plan twice."))
            continue
        seen.add((wire.from_block, exit_index, wire.to_block))
        input_index = _input_of(wire, source.exits[exit_index].kind, target, joined, named)
        if isinstance(input_index, str):
            problems.append(PlanProblem(code="wire", text=f"{said} {input_index}"))
            continue
        wires.append(
            PlanWire(
                from_block=wire.from_block,
                exit=exit_name,
                to_block=wire.to_block,
                exit_index=exit_index,
                input_index=input_index,
            )
        )
    return wires


def _named_inputs(
    proposed: ProposedPlan, checked: Mapping[str, CheckedBlock]
) -> dict[tuple[str, str], set[int]]:
    """The inputs the plan's wires name, by block and kind, so that a wire that names none takes
    another."""
    named: dict[tuple[str, str], set[int]] = {}
    for wire in proposed.wires[:MOST_WIRES]:
        source = checked.get(wire.from_block)
        if source is None or wire.input is None:
            continue
        left = _exit_of(source.exits, wire.exit)
        if left is not None:
            named.setdefault((wire.to_block, source.exits[left[0]].kind), set()).add(wire.input)
    return named


def _exit_of(exits: Sequence[Link], said: str) -> tuple[int, str] | None:
    """The exit a wire names, with the name it goes by: n8n's name for one exit, or the kind of
    the block's only exit of that kind, as "main". A name two exits share names neither."""
    folded = said.casefold()
    named = [
        (at, link.name)
        for at, link in enumerate(exits)
        if link.name is not None and link.name.casefold() == folded
    ]
    if named:
        return named[0] if len(named) == 1 else None
    of_kind = [at for at, link in enumerate(exits) if link.kind.casefold() == folded]
    return (of_kind[0], exits[of_kind[0]].kind) if len(of_kind) == 1 else None


def _exit_names(exits: Sequence[Link]) -> list[str]:
    if len(exits) == 1:
        return [exits[0].kind]
    return [link.name or link.kind for link in exits]


def _input_of(
    wire: ProposedWire,
    kind: str,
    target: CheckedBlock,
    joined: dict[tuple[str, str], set[int]],
    named: Mapping[tuple[str, str], set[int]],
) -> int | str:
    """The input of the target block the wire joins, counted among its inputs of the wire's kind,
    or why it can't join one."""
    to = wire.to_block
    if target.starts:
        return f"goes into {to!r}, which starts the workflow and takes no wire in."
    count = sum(link.kind == kind for link in target.inputs.links)
    if count == 0 and kind != MAIN and target.inputs.any_ai:
        if wire.input not in (None, 0):
            return (
                f"joins input {wire.input} of {to!r}, whose inputs code keeps by hand, so a "
                f"{kind} wire joins its first: write 0 or null."
            )
        return 0
    if count == 0:
        return f"goes into {to!r}, which takes no {kind} wire in."
    taken = joined.setdefault((to, kind), set())
    if wire.input is not None:
        if not 0 <= wire.input < count:
            wires_in = "wire" if count == 1 else "wires"
            return (
                f"joins input {wire.input} of {to!r}, which takes {count} {kind} {wires_in} in, "
                "numbered from 0."
            )
        if kind == MAIN and count > 1 and wire.input in taken:
            return (
                f"joins input {wire.input} of {to!r}, which another wire already joins. Give each "
                "wire its own input."
            )
        taken.add(wire.input)
        return wire.input
    if count == 1:
        return 0
    free = [at for at in range(count) if at not in taken and at not in named.get((to, kind), ())]
    if not free:
        return (
            f"goes into {to!r}, which takes {count} wires in, one to each input, in the order "
            "the plan lists them."
        )
    taken.add(free[0])
    return free[0]
