"""Code's scope check of a fix (ADR 0055, sections 3 and 4): the fixed version changes only the
blocks the coordinator named, and nothing there widens the change.

It denies by default, and reads with allow-lists. The fixed plan may differ from the stopped one
only in the blocks in `change_only`, and there only at the parameter paths their type lists in
`MAY_CHANGE`. It keeps every Ask for a yes as it was and where it was, every other block, every
wire, every setting and the workflow's name. A change may not touch what a block does (its type,
version, resource, operation, method or action), where it reaches (another system, or an address
on another host), a key, or what lets it go past its own failure. Code, a query and a command are
never changed. An expression a fix writes must be one code can read (`READABLE`): the item's own
fields and plain words, joined with +. An expression already in the stopped version may stay as
it is. Code can't tell anything else is safe, so it counts as widening. The first finding, in the
order `scope_of` and `_widening` look, is the one given.

`change_only` is what the coordinator asked the Fix drafter to change, so the check holds the
draft to the same blocks the fix_drafter event names. Pure."""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast
from urllib.parse import parse_qsl, urlsplit

from agent_runtime.contract import PlanBlock, PlanSetting, WorkflowPlan
from agent_runtime.fixing.events import FixWidening
from agent_runtime.fixing.ports import Inside, Scope, Widened
from agent_runtime.monitoring.masking import KEPT_KEY, MASKED_SHAPES, names_a_secret
from agent_runtime.workflow_plan import PLACEHOLDER

ASK_FOR_A_YES: Final = "CUSTOM.wabAskForYes"
GOES_PAST_A_FAILURE: Final = frozenset(
    {"onError", "continueOnFail", "alwaysOutputData", "executeOnce", "disabled"}
)
"""What lets a block go on past its own failure, or skips it (ADR 0051, section 3)."""
STOPS_ON_FAILURE: Final = frozenset({"stopWorkflow"})
WHAT_IT_DOES: Final = frozenset(
    {"resource", "operation", "method", "requestMethod", "action", "mode"}
)
"""Top-level parameters that choose what a block does. A change to one can make a read a write."""
WHERE_IT_GOES: Final = frozenset({"source", "where", "agent"})
"""Our blocks' parameters that choose the system: Read's source, Tell's where, Agent's card."""
ADDRESS_ENDS: Final = ("url", "uri", "endpoint", "host", "hostname", "domain", "server", "site")
"""How the name of a parameter that holds an address ends, once its case is gone."""
KEY_PARAMETERS: Final = frozenset(
    {
        "authentication",
        "nodeCredentialType",
        "genericAuthType",
        "predefinedCredentialType",
        "credentials",
    }
)
"""Parameters that pick a key for the block."""
CODE: Final = frozenset(
    {"jsCode", "pythonCode", "functionCode", "code", "query", "sqlQuery", "command"}
)
"""Parameters that hold code, a query or a command, which a fix never changes."""
_CONDITION: Final = frozenset(
    {"conditions.conditions[].leftValue", "conditions.conditions[].rightValue"}
)
MAY_CHANGE: Final[Mapping[str, frozenset[str]]] = {
    "CUSTOM.wabRead": frozenset({"place"}),
    "CUSTOM.wabProposeChange": frozenset({"place", "title", "body", "subject"}),
    "CUSTOM.wabTell": frozenset({"what"}),
    "CUSTOM.wabAgent": frozenset({"inputs"}),
    "n8n-nodes-base.httpRequest": frozenset({"url", "queryParameters.parameters[].value"}),
    "n8n-nodes-base.github": frozenset({"owner", "repository"}),
    "n8n-nodes-base.if": _CONDITION,
    "n8n-nodes-base.filter": _CONDITION,
    "n8n-nodes-base.set": frozenset({"assignments.assignments[].value"}),
    "n8n-nodes-base.slack": frozenset({"text"}),
}
"""The parameter paths a fix may change, by block type: where a place, a field the run reads, or
words people see stand. [] stands for any item of a list, and a path allows what is under it. Any
other path, and every path of a type not listed, is one code can't check."""
KEY_READS: Final = re.compile(
    r"\$(?:env|credentials|secrets?|vars|node|parameter|evaluateExpression)\b|\$\("
)
"""What an expression reads that can hold a key: n8n's environment, keys and variables, and
another block, whose parameters it can read."""
_WORDS: Final = r"[A-Za-z0-9 .,!?#()_\-]*"
_FIELD: Final = (
    r"\$json(?:\.[A-Za-z_][A-Za-z0-9_]*|\[(?:'[A-Za-z0-9 _\-]+'|\"[A-Za-z0-9 _\-]+\")\])+"
)
_TERM: Final = rf"(?:{_FIELD}|'{_WORDS}'|\"{_WORDS}\")"
READABLE: Final = re.compile(
    rf"={_WORDS}(?:\{{\{{\s*{_TERM}(?:\s*\+\s*{_TERM})*\s*\}}\}}{_WORDS})*"
)
"""An expression code can read: plain words, and between braces the item's own fields and plain
words joined with +. It calls nothing, reads nothing else, and can't spell an address."""
NAME_VALUE: Final = re.compile(r"[\"']?([A-Za-z0-9_.\-]+)[\"']?\s*[:=]\s*(?!<<)[\"']?[^\s\"',}&/]")
"""A name, then : or =, then a value that isn't a setting's placeholder, as in token=abc or
"Authorization": "Basic abc"."""
URL: Final = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s\"'<>]+", re.IGNORECASE)
_INDEX: Final = re.compile(r"\[\d+\]")

type Leaves = dict[str, Any]


@dataclass(frozen=True)
class Leaf:
    path: str
    name: str
    """The name the value goes by: its key, or for n8n's name and value pairs, as a header's or
    a query parameter's, the pair's name."""
    value: Any
    secret: bool
    """Whether its name, or the name of anything it sits under, is a key's."""


class PlanScope:
    """The scope check the coordinator runs on each draft (`ScopeCheck`)."""

    def check(
        self, stopped: WorkflowPlan, fixed: WorkflowPlan, change_only: Sequence[str]
    ) -> Scope:
        return scope_of(stopped, fixed, change_only)


def scope_of(stopped: WorkflowPlan, fixed: WorkflowPlan, change_only: Sequence[str]) -> Scope:
    before = {block.name: block for block in stopped.blocks}
    after = {block.name: block for block in fixed.blocks}
    yeses = {name for name, block in before.items() if block.type == ASK_FOR_A_YES}
    if any(name not in after or after[name].type != ASK_FOR_A_YES for name in yeses):
        return Widened("removes_a_yes")
    rewired = _wires(stopped) ^ _wires(fixed)
    if any(f in yeses or t in yeses for f, t, *_ in rewired) or any(
        before[name] != after[name] for name in yeses
    ):
        return Widened("moves_a_yes")
    if after.keys() - before.keys():
        return Widened("adds_a_block")
    if _settings(stopped) != _settings(fixed) or _placeholders(stopped) != _placeholders(fixed):
        return Widened("changes_a_persons_setting")
    changed = [name for name in before if name in after and before[name] != after[name]]
    if (
        before.keys() - after.keys()
        or rewired
        or stopped.name != fixed.name
        or any(name not in change_only for name in changed)
    ):
        return Widened("outside_failed_part")
    for name in changed:
        if (widening := _widening(before[name], after[name])) is not None:
            return Widened(widening)
    return Inside(tuple(changed))


def _widening(before: PlanBlock, after: PlanBlock) -> FixWidening | None:
    """How a change to one block the fix may change widens it, or None."""
    was, now = before.parameters, after.parameters
    if any(_past_a_failure(now.get(k)) and now.get(k) != was.get(k) for k in GOES_PAST_A_FAILURE):
        return "goes_past_a_failure"
    if (
        before.type != after.type
        or before.version != after.version
        or any(was.get(k) != now.get(k) for k in WHAT_IT_DOES)
    ):
        return "adds_a_write"
    old, new = _leaves(was), _leaves(now)
    touched = [leaf for path, leaf in new.items() if path not in old or old[path] != leaf]
    gone = [leaf for path, leaf in old.items() if path not in new or new[path] != leaf]
    if any(was.get(k) != now.get(k) for k in KEY_PARAMETERS) or any(
        _holds_a_key(leaf) for leaf in [*touched, *gone]
    ):
        return "adds_a_key"
    if any(_expression(leaf.value) and not READABLE.fullmatch(leaf.value) for leaf in touched):
        return "cant_check"
    if any(was.get(k) != now.get(k) for k in WHERE_IT_GOES) or _hosts(new) - _hosts(old):
        return "adds_a_system"
    if any(_names_an_address(leaf.name) and _unread(leaf.value) for leaf in touched):
        return "adds_a_system"
    if not all(_may_change(after.type, leaf.path) for leaf in [*touched, *gone]):
        return "cant_check"
    return None


def _past_a_failure(value: object) -> bool:
    return value not in (None, False, "") and value not in STOPS_ON_FAILURE


def _expression(value: object) -> bool:
    """Whether n8n may read the value as an expression. Braces without the mark count too."""
    return isinstance(value, str) and (value.startswith("=") or "{{" in value)


def _may_change(node_type: str, path: str) -> bool:
    """Whether a fix may change the value at `path` of a block of this type."""
    if path.split(".", 1)[0].split("[", 1)[0] in CODE:
        return False
    general = _INDEX.sub("[]", path)
    return any(
        general == allowed or general.startswith((f"{allowed}.", f"{allowed}["))
        for allowed in MAY_CHANGE.get(node_type, frozenset())
    )


def _holds_a_key(leaf: Leaf) -> bool:
    """A value under a key's name, the platform's stand-in for a key, anything shaped like a key,
    an expression that reads where keys are, a key's name with a value after it, or an address
    with a name and password or a key in it."""
    if leaf.secret and leaf.value not in (None, ""):
        return True
    text = leaf.value if isinstance(leaf.value, str) else ""
    if KEPT_KEY in text or MASKED_SHAPES.search(text):
        return True
    if _expression(text) and KEY_READS.search(text):
        return True
    if any(names_a_secret(found.group(1)) for found in NAME_VALUE.finditer(text)):
        return True
    for found in URL.finditer(text):
        parts = urlsplit(found.group())
        if parts.username or parts.password:
            return True
        if any(names_a_secret(name) for name, _ in parse_qsl(parts.query)):
            return True
    return False


def _hosts(leaves: Leaves) -> set[str]:
    """Every host an address in the parameters names, as scheme and host."""
    hosts: set[str] = set()
    for leaf in leaves.values():
        if isinstance(leaf.value, str):
            for found in URL.finditer(leaf.value):
                parts = urlsplit(found.group())
                hosts.add(f"{parts.scheme.lower()}://{(parts.hostname or '').lower()}")
    return hosts


def _names_an_address(name: str) -> bool:
    return name.lower().endswith(ADDRESS_ENDS)


def _unread(value: object) -> bool:
    """An address code can't read: an expression, or text with no address in it."""
    if not isinstance(value, str) or not value:
        return False
    return value.startswith("=") or URL.search(value) is None


def _leaves(parameters: Mapping[str, Any]) -> Leaves:
    return {leaf.path: leaf for leaf in _walk(parameters, "", "", False)}


def _walk(value: Any, path: str, name: str, secret: bool) -> Iterator[Leaf]:
    match value:
        case dict():
            fields = cast(dict[str, Any], value)
            paired = fields.get("name") if "value" in fields else None
            for key, inner in fields.items():
                said = str(paired) if key == "value" and isinstance(paired, str) else key
                inside = f"{path}.{key}" if path else key
                yield from _walk(inner, inside, said, secret or names_a_secret(said))
        case list():
            for index, inner in enumerate(cast(list[Any], value)):
                yield from _walk(inner, f"{path}[{index}]", name, secret)
        case _:
            yield Leaf(path, name, value, secret)


def _wires(plan: WorkflowPlan) -> set[tuple[str, str, int, int]]:
    """Each wire as n8n joins it: from, to, the exit's place and the input's."""
    return {(w.from_block, w.to_block, w.exit_index, w.input_index) for w in plan.wires}


def _settings(plan: WorkflowPlan) -> dict[str, tuple[object, ...]]:
    return {setting.id: _setting(setting) for setting in plan.settings}


def _setting(setting: PlanSetting) -> tuple[object, ...]:
    fills = frozenset((f.block, f.parameter) for f in setting.fills)
    return (setting.kind, setting.label, setting.value, setting.mark, fills)


def _placeholders(plan: WorkflowPlan) -> set[tuple[str, str, str]]:
    """Each setting's placeholder where it stands: the block, the path and the setting."""
    return {
        (block.name, leaf.path, found)
        for block in plan.blocks
        for leaf in _walk(block.parameters, "", "", False)
        if isinstance(leaf.value, str)
        for found in PLACEHOLDER.findall(leaf.value)
    }
