"""Which n8n node types, versions and operations may run, as the class file `node_classes.json`
classes them (ADR 0045): `read`, `notice`, `write` or `off`. Anything the file does not class is
off.

n8n loads every built-in block but seven (ADR 0051, `n8n_blocks`), so the file no longer decides
what n8n loads. It classes the blocks it knows, for their tags, their `says` and their keys. The
safety checker grades each block by it and flags every type it doesn't class, and the pin check
(`platform_api.pin_check`) keeps each of its rows true to the node types the pinned image serves.

The file maps each type to `{"off": why}`, or to its block kind and its rows. A row classes some
versions of the type, either whole (`class`) or by the parameter that picks what the node does
(`by`), with n8n's default for it and a class for each choice. A node that picks a resource and
then an operation on it is classed by both together (`by` is `["resource", "operation"]`), with
each resource's own default operation.

A row of one of n8n's own nodes for an outside system (block `system`) also says what the block
is to a person and to the checker (`Use`): its tag and what it does, the parameters that name
where it reads or posts, and how many Approvers a change by it needs. Such a node may read, or
post a notice when its row names where it posts, so the checker can hold it to the Tell rule. It
never writes until the write proxy exists (ADR 0045, E18).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

type On = Literal["read", "notice", "write"]
type Class = On | Literal["off"]
type BlockKind = Literal[
    "schedule",
    "start",
    "manual",
    "error",
    "read",
    "agent",
    "propose",
    "ask",
    "write",
    "tell",
    "report",
    "branch",
    "merge",
    "end",
    "note",
    "shape",
    "system",
]
"""What a block is to the safety checker and the Planner's layout. `shape` is one of n8n's data
nodes, which only reshape items (P7 Q10). `system` is one of n8n's own nodes for an outside
system, such as Jira or Slack, which reads or posts with a key the platform made (ADR 0045).
Every other kind is one type."""

MANY: frozenset[BlockKind] = frozenset({"shape", "system"})
"""The kinds several types share."""

CLASS_FILE = Path(__file__).with_name("node_classes.json")
OURS = "CUSTOM."
"""How n8n names the types of our node pack (P7 Q11)."""
CHOICES = ("resource", "operation")
"""The parameters by which n8n's nodes pick what they do. A row's `by` names any other."""
PAIR = ("resource", "operation")


class _Resource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    default: str
    operations: dict[str, Class] = Field(min_length=1)

    @model_validator(mode="after")
    def _known_default(self) -> _Resource:
        if self.default not in self.operations:
            raise ValueError(f"the default {self.default} has no class")
        return self


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    versions: tuple[float, ...] = Field(min_length=1)
    whole: Class | None = Field(default=None, alias="class")
    by: str | tuple[str, str] | None = None
    default: str | None = None
    operations: dict[str, Class] | None = None
    resources: dict[str, _Resource | Literal["off"]] | None = None
    tag: str | None = Field(default=None, min_length=1)
    says: str | None = Field(default=None, min_length=1)
    target: tuple[str, ...] = ()
    text: tuple[str, ...] = ()
    encoded: tuple[str, ...] = ()
    quiet: tuple[str, ...] = ()
    approvers_min: int | None = Field(default=None, ge=1, le=2)

    @model_validator(mode="after")
    def _one_way(self) -> _Row:
        whole = self.whole is not None
        if isinstance(self.by, tuple):
            if self.by != PAIR:
                raise ValueError(f"a row picks by one parameter, or by {' and '.join(PAIR)}")
            picked = (self.default, self.resources)
            if whole or self.operations is not None or None in picked:
                raise ValueError("a row by resource and operation has default and resources only")
            assert self.resources is not None
            if not isinstance(self.resources.get(str(self.default)), _Resource):
                raise ValueError(f"the default {self.default} has no resource that is on")
            return self
        if self.resources is not None:
            raise ValueError(f"only a row by {' and '.join(PAIR)} has resources")
        picked = (self.by, self.default, self.operations)
        if (whole and picked != (None, None, None)) or (not whole and None in picked):
            raise ValueError("a row has a class, or by, default and operations, never both")
        if self.operations is not None and self.default not in self.operations:
            raise ValueError(f"the default {self.default} has no class")
        return self

    @property
    def use(self) -> Use | None:
        described = (self.tag, self.says, self.approvers_min)
        if described == (None, None, None) and not self.target:
            return None
        if None in described:
            raise ValueError("a row that says what it does has a tag, says and approvers_min")
        assert self.tag is not None and self.says is not None and self.approvers_min is not None
        return Use(
            self.tag,
            self.says,
            self.target,
            self.approvers_min,
            self.text,
            self.encoded,
            self.quiet,
        )


class _On(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    block: BlockKind
    rows: tuple[_Row, ...] = Field(min_length=1)


class _Off(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    off: str = Field(min_length=1)


_FILE = TypeAdapter(dict[str, _On | _Off])


@dataclass(frozen=True)
class Operations:
    """A version that does one of several things, picked by one parameter."""

    by: str
    default: str
    """What the node does when the parameter is left out, as n8n leaves out a default."""
    classes: Mapping[str, Class]


@dataclass(frozen=True)
class Resources:
    """A version that picks a resource, then an operation on it. Each resource has its own
    operations and its own default one, as n8n shows one operation list a resource."""

    default: str
    """The resource when `resource` is left out."""
    operations: Mapping[str, Operations | Literal["off"]]
    """Each resource's operations, or off for a resource that is off whatever it does, such as
    the Custom API Call n8n adds to a node with a key, which sends any request with it."""


type Classed = Class | Operations | Resources


@dataclass(frozen=True)
class Use:
    """What one of n8n's own nodes for an outside system is (ADR 0045, section 1)."""

    tag: str
    """The block's tag on the run line and the canvas: Reads Jira, Posts in Slack."""
    says: str
    """What it does, as the inspector line and an approval card say it."""
    target: tuple[str, ...]
    """The parameters that name where it reads or posts, as dotted paths into its parameters.
    A notice's must be literals (the Tell rule)."""
    approvers_min: int
    text: tuple[str, ...] = ()
    """The parameters that hold what a notice says. In this release each is written out in the
    block, never an expression, and none calls out a whole channel."""
    encoded: tuple[str, ...] = ()
    """Those of the text parameters that hold JSON in a string, such as Slack's blocks, which
    the checker reads decoded."""
    quiet: tuple[str, ...] = ()
    """Switches a notice leaves off, such as Slack's link_names, which turns a written @channel
    into a call to everyone in it."""


@dataclass(frozen=True)
class OnType:
    block: BlockKind
    versions: Mapping[str, Classed]
    """By version, written as `version_key` writes it."""
    uses: Mapping[str, Use]
    """By version, for one of n8n's own nodes for an outside system."""


@dataclass(frozen=True)
class OffType:
    why: str


@dataclass(frozen=True)
class Runs:
    on: On
    use: Use | None = None


type OffBecause = Literal["type", "version", "expression", "operation"]


@dataclass(frozen=True)
class Off:
    because: OffBecause
    value: str
    """The type, the version or what the node was asked to do."""


def version_key(version: object) -> str | None:
    """n8n writes a type's version as a number, 1 or 2.1. Anything else is no version."""
    if isinstance(version, bool) or not isinstance(version, int | float):
        return None
    return f"{float(version):g}"


class NodeClasses:
    def __init__(self, types: Mapping[str, OnType | OffType]) -> None:
        self._types = dict(types)
        _check(self._types)

    @classmethod
    def read(cls, path: Path = CLASS_FILE) -> NodeClasses:
        parsed = _FILE.validate_json(path.read_bytes())
        return cls({name: _domain(entry) for name, entry in parsed.items()})

    def names(self) -> tuple[str, ...]:
        """Every type the file names, on or off, in the file's order."""
        return tuple(self._types)

    def blocks(self) -> Mapping[str, BlockKind]:
        """Every type the file turns on, with what it is to the checker, in the file's order."""
        return {
            name: entry.block for name, entry in self._types.items() if isinstance(entry, OnType)
        }

    def entry(self, node_type: str) -> OnType | OffType | None:
        """What the file says of one type, or None when it does not name it."""
        return self._types.get(node_type)

    def verdict(
        self, node_type: str, version: object, parameters: Mapping[str, object]
    ) -> Runs | Off:
        """Whether one block may run. What it does is the value of its `by` parameter, or n8n's
        default when it is left out, and for a node that picks a resource first, the operation
        that resource offers. An expression in either could pick anything when it runs."""
        entry = self._types.get(node_type)
        if not isinstance(entry, OnType):
            return Off("type", node_type)
        key = version_key(version)
        classed = None if key is None else entry.versions.get(key)
        if classed is None or classed == "off":
            return Off("version", str(version))
        picked = _what(classed, parameters)
        if isinstance(picked, Off):
            return picked
        what, chosen = picked
        if chosen == "off":
            return Off("operation", what)
        return Runs(chosen, entry.uses.get(str(key)))

    def unclassed(self, served: Iterable[Mapping[str, Any]]) -> list[str]:
        """Every way the node types n8n serves, as its `/types/nodes.json` lists them, and the
        file's rows disagree: a version or a choice of a type the file turns on that the file does
        not class, n8n's default for a choice changed, a type or version the file names that n8n
        does not load, or one of our blocks the file does not class. A type the file doesn't name
        is no problem: the checker flags it (ADR 0051). None when they agree."""
        problems: list[str] = []
        seen: dict[str, set[str]] = {}
        for description in served:
            name = str(description.get("name"))
            entry = self._types.get(name)
            seen.setdefault(name, set())
            if entry is None and name.startswith(OURS):
                problems.append(
                    f"n8n loads {name}, one of our blocks, which the class file does not class."
                )
            if not isinstance(entry, OnType):
                continue
            properties = cast(Sequence[Mapping[str, Any]], description.get("properties") or [])
            for version in _served_versions(description.get("version")):
                seen.setdefault(name, set()).add(version)
                classed = entry.versions.get(version)
                if classed is None:
                    problems.append(f"{name} version {version} is not classed.")
                elif classed != "off":
                    problems += _choices(f"{name} version {version}", classed, properties)
        problems += [
            f"The class file names {name}, which n8n does not load."
            for name, entry in self._types.items()
            if isinstance(entry, OffType) and name not in seen
        ]
        for name, entry in self._types.items():
            if isinstance(entry, OnType):
                for version in sorted(entry.versions.keys() - seen.get(name, set())):
                    problems.append(
                        f"The class file classes {name} version {version}, which n8n does not load."
                    )
        return problems


def _picked(parameters: Mapping[str, object], by: str, default: str) -> str | Off:
    picked = parameters.get(by, default)
    if isinstance(picked, str) and picked.startswith("="):
        return Off("expression", picked)
    if not isinstance(picked, str):
        return Off("operation", str(picked))
    return picked


def _what(classed: Classed, parameters: Mapping[str, object]) -> tuple[str, Class] | Off:
    """What the block was asked to do, in words, and its class."""
    match classed:
        case "read" | "notice" | "write" | "off":
            return "", classed
        case Operations():
            picked = _picked(parameters, classed.by, classed.default)
            if isinstance(picked, Off):
                return picked
            chosen = classed.classes.get(picked)
            return Off("operation", picked) if chosen is None else (picked, chosen)
        case Resources():
            resource = _picked(parameters, "resource", classed.default)
            if isinstance(resource, Off):
                return resource
            operations = classed.operations.get(resource)
            if operations is None or operations == "off":
                return Off("operation", resource)
            chosen = _what(operations, parameters)
            return chosen if isinstance(chosen, Off) else (f"{resource} {chosen[0]}", chosen[1])


def _classed(row: _Row) -> Classed:
    if row.whole is not None:
        return row.whole
    if row.resources is not None:
        return Resources(
            str(row.default),
            {
                name: "off"
                if resource == "off"
                else Operations("operation", resource.default, dict(resource.operations))
                for name, resource in row.resources.items()
            },
        )
    return Operations(str(row.by), str(row.default), dict(row.operations or {}))


def _domain(entry: _On | _Off) -> OnType | OffType:
    if isinstance(entry, _Off):
        return OffType(entry.off)
    versions: dict[str, Classed] = {}
    uses: dict[str, Use] = {}
    for row in entry.rows:
        classed = _classed(row)
        use = row.use
        for version in row.versions:
            key = version_key(version)
            if key is None or key in versions:
                raise ValueError(f"version {version} is classed twice")
            versions[key] = classed
            if use is not None:
                uses[key] = use
    return OnType(entry.block, versions, uses)


def _classes(classed: Classed) -> set[Class]:
    if isinstance(classed, str):
        return {classed}
    if isinstance(classed, Resources):
        return set[Class]().union(*(_classes(o) for o in classed.operations.values()))
    return set(classed.classes.values())


def _check(types: Mapping[str, OnType | OffType]) -> None:
    """What the file may say, so a row that breaks a safety rule fails every test and start."""
    holders: dict[BlockKind, list[str]] = {}
    for name, entry in types.items():
        if isinstance(entry, OffType):
            continue
        holders.setdefault(entry.block, []).append(name)
        classes = set[Class]().union(*(_classes(c) for c in entry.versions.values()))
        if classes <= {"off"}:
            raise ValueError(f"{name} is on, but nothing it does is: turn it off instead")
        if ("write" in classes) != (entry.block == "write"):
            raise ValueError(f"{name}: only Make the approved changes writes")
        if not name.startswith(OURS):
            _check_n8ns_own(name, entry)
    for block, names in holders.items():
        if block not in MANY and len(names) > 1:
            raise ValueError(f"{', '.join(names)} are all the {block} block")


def _check_n8ns_own(name: str, entry: OnType) -> None:
    """n8n's own nodes read, and a node for an outside system may post a notice when its row
    names where it posts, which the checker then holds to literals (the Tell rule). None writes
    until the write proxy exists (ADR 0045, E18)."""
    system = entry.block == "system"
    if not system and entry.uses:
        raise ValueError(f"{name}: only a block for an outside system says what it does")
    for key, classed in entry.versions.items():
        on = _classes(classed) - {"off"}
        if not on:
            continue
        use = entry.uses.get(key)
        if system and (use is None or len(on) != 1):
            raise ValueError(f"{name} version {key}: say what it does, and give it one class")
        if on <= {"read"}:
            continue
        if on != {"notice"} or use is None or not use.target or not use.text:
            raise ValueError(
                f"{name} version {key}: n8n's own nodes only read, or post where their row says "
                "and what their row names as its text, until the write proxy (ADR 0045, E18) "
                "exists"
            )


def _served_versions(version: object) -> list[str]:
    listed = cast(list[object], version) if isinstance(version, list) else [version]
    return [key for key in (version_key(v) for v in listed) if key is not None]


def _choices(what: str, classed: Classed, properties: Sequence[Mapping[str, Any]]) -> list[str]:
    match classed:
        case Operations(by=by):
            bys: tuple[str, ...] = (by,)
        case Resources():
            bys = PAIR
        case _:
            bys = ()
    names = {*CHOICES, *bys}
    picks: dict[str, list[Mapping[str, Any]]] = {}
    for prop in properties:
        if (name := prop.get("name")) in names:
            picks.setdefault(str(name), []).append(prop)
    problems = [
        f"{what} picks what it does by {name}, which the class file does not class."
        for name in picks
        if name not in bys
    ]
    match classed:
        case Operations():
            return [*problems, *_offered(what, classed, picks.get(classed.by))]
        case Resources():
            resource = Operations(
                "resource", classed.default, dict.fromkeys(classed.operations, "read")
            )
            problems += _offered(what, resource, picks.get("resource"))
            for name, operations in sorted(classed.operations.items()):
                if operations == "off":
                    continue
                shown = [p for p in picks.get("operation", []) if name in _shown_for(p)]
                problems += _offered(f"{what} {name}", operations, shown or None)
            return problems
        case _:
            return problems


def _shown_for(prop: Mapping[str, Any]) -> list[str]:
    """The resources an operation list is shown for."""
    options = cast(Mapping[str, Any], prop.get("displayOptions") or {})
    show = cast(Mapping[str, Any], options.get("show") or {})
    return [str(r) for r in cast(list[object], show.get("resource") or [])]


def _offered(what: str, classed: Operations, offered: list[Mapping[str, Any]] | None) -> list[str]:
    if offered is None:
        return [f"{what} no longer picks what it does by {classed.by}."]
    if any(prop.get("type") != "options" for prop in offered):
        return [f"{what} picks what it does by {classed.by} from no fixed list."]
    values = {
        str(cast(Mapping[str, Any], option).get("value"))
        for prop in offered
        for option in cast(list[object], prop.get("options") or [])
        if isinstance(option, dict)
    }
    defaults = {str(prop.get("default")) for prop in offered}
    problems = [
        f"{what} can {value}, which the class file does not class."
        for value in sorted(values - classed.classes.keys())
    ]
    problems += [
        f"The class file classes {what} {value}, which n8n does not have."
        for value in sorted(classed.classes.keys() - values)
    ]
    if defaults != {classed.default}:
        problems.append(
            f"n8n's default for {what} is {', '.join(sorted(defaults))}, not {classed.default}."
        )
    return problems


NODE_CLASSES = NodeClasses.read()
