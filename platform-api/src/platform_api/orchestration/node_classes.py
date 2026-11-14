"""Which n8n node types, versions and operations may run, as the class file `node_classes.json`
classes them (ADR 0045): `read`, `notice`, `write` or `off`. Anything the file does not class is
off.

One file decides it everywhere. n8n's allow list, `NODES_INCLUDE`, is generated from it by
`scripts/nodes-include.sh` as every type that is not off. The safety checker grades each block by
it, bootstrap checks that n8n loaded exactly its types, and the pin check (`platform_api.pin_check`)
keeps it complete against the node types the pinned n8n image serves.

The file maps each type to `{"off": why}`, or to its block kind and its rows. A row classes some
versions of the type, either whole (`class`) or by the parameter that picks what the node does
(`by`), with n8n's default for it and a class for each choice.
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
]
"""What a block is to the safety checker and the Planner's layout. `shape` is one of n8n's data
nodes, which only reshape items (P7 Q10). Every other kind is one type."""

CLASS_FILE = Path(__file__).with_name("node_classes.json")
OURS = "CUSTOM."
"""How n8n names the types of our node pack (P7 Q11)."""
CHOICES = ("resource", "operation")
"""The parameters by which n8n's nodes pick what they do. A row's `by` names any other."""


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    versions: tuple[float, ...] = Field(min_length=1)
    whole: Class | None = Field(default=None, alias="class")
    by: str | None = None
    default: str | None = None
    operations: dict[str, Class] | None = None

    @model_validator(mode="after")
    def _one_way(self) -> _Row:
        picked = (self.by, self.default, self.operations)
        whole = self.whole is not None
        if (whole and picked != (None, None, None)) or (not whole and None in picked):
            raise ValueError("a row has a class, or by, default and operations, never both")
        if self.operations is not None and self.default not in self.operations:
            raise ValueError(f"the default {self.default} has no class")
        return self


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


type Classed = Class | Operations


@dataclass(frozen=True)
class OnType:
    block: BlockKind
    versions: Mapping[str, Classed]
    """By version, written as `version_key` writes it."""


@dataclass(frozen=True)
class OffType:
    why: str


@dataclass(frozen=True)
class Runs:
    on: On


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

    def included(self) -> tuple[str, ...]:
        """n8n's allow list: every type the file does not turn off, in the file's order."""
        return tuple(name for name, entry in self._types.items() if isinstance(entry, OnType))

    def blocks(self) -> Mapping[str, BlockKind]:
        return {
            name: entry.block for name, entry in self._types.items() if isinstance(entry, OnType)
        }

    def verdict(
        self, node_type: str, version: object, parameters: Mapping[str, object]
    ) -> Runs | Off:
        """Whether one block may run. What it does is the value of its `by` parameter, or n8n's
        default when it is left out. An expression there could pick anything when it runs."""
        entry = self._types.get(node_type)
        if not isinstance(entry, OnType):
            return Off("type", node_type)
        key = version_key(version)
        classed = None if key is None else entry.versions.get(key)
        if classed is None or classed == "off":
            return Off("version", str(version))
        if not isinstance(classed, Operations):
            return Runs(classed)
        picked = parameters.get(classed.by, classed.default)
        if isinstance(picked, str) and picked.startswith("="):
            return Off("expression", picked)
        chosen = classed.classes.get(picked) if isinstance(picked, str) else None
        if chosen is None or chosen == "off":
            return Off("operation", str(picked))
        return Runs(chosen)

    def unclassed(self, served: Iterable[Mapping[str, Any]]) -> list[str]:
        """Every way the node types n8n serves, as its `/types/nodes.json` lists them, and the
        file disagree: a type, a version or a choice n8n has that the file does not class, n8n's
        default for a choice changed, or a type or version the file classes that n8n does not
        load. None when they agree."""
        problems: list[str] = []
        seen: dict[str, set[str]] = {}
        for description in served:
            name = str(description.get("name"))
            entry = self._types.get(name)
            if not isinstance(entry, OnType):
                problems.append(f"n8n loads {name}, which the class file does not turn on.")
                continue
            properties = cast(Sequence[Mapping[str, Any]], description.get("properties") or [])
            for version in _served_versions(description.get("version")):
                seen.setdefault(name, set()).add(version)
                classed = entry.versions.get(version)
                if classed is None:
                    problems.append(f"{name} version {version} is not classed.")
                elif classed != "off":
                    problems += _choices(f"{name} version {version}", classed, properties)
        for name, entry in self._types.items():
            if isinstance(entry, OnType):
                for version in sorted(entry.versions.keys() - seen.get(name, set())):
                    problems.append(
                        f"The class file classes {name} version {version}, which n8n does not load."
                    )
        return problems


def _domain(entry: _On | _Off) -> OnType | OffType:
    if isinstance(entry, _Off):
        return OffType(entry.off)
    versions: dict[str, Classed] = {}
    for row in entry.rows:
        classed: Classed = (
            row.whole
            if row.whole is not None
            else Operations(str(row.by), str(row.default), dict(row.operations or {}))
        )
        for version in row.versions:
            key = version_key(version)
            if key is None or key in versions:
                raise ValueError(f"version {version} is classed twice")
            versions[key] = classed
    return OnType(entry.block, versions)


def _classes(classed: Classed) -> set[Class]:
    return {classed} if isinstance(classed, str) else set(classed.classes.values())


def _check(types: Mapping[str, OnType | OffType]) -> None:
    """What the file may say, so a row that breaks a safety rule fails every test and start."""
    holders: dict[BlockKind, list[str]] = {}
    for name, entry in types.items():
        if not isinstance(entry, OnType):
            continue
        holders.setdefault(entry.block, []).append(name)
        classes = set[Class]().union(*(_classes(c) for c in entry.versions.values()))
        if classes <= {"off"}:
            raise ValueError(f"{name} is on, but nothing it does is: turn it off instead")
        if ("write" in classes) != (entry.block == "write"):
            raise ValueError(f"{name}: only Make the approved changes writes")
        if not name.startswith(OURS) and not classes <= {"read", "off"}:
            raise ValueError(
                f"{name}: n8n's own nodes only read until the Tell rule's checks for its notices "
                "(ENGINE-PLAN E16) and the write proxy (ADR 0045, E18) exist"
            )
    for block, names in holders.items():
        if block != "shape" and len(names) > 1:
            raise ValueError(f"{', '.join(names)} are all the {block} block")


def _served_versions(version: object) -> list[str]:
    listed = cast(list[object], version) if isinstance(version, list) else [version]
    return [key for key in (version_key(v) for v in listed) if key is not None]


def _choices(what: str, classed: Classed, properties: Sequence[Mapping[str, Any]]) -> list[str]:
    by = classed.by if isinstance(classed, Operations) else None
    names = {*CHOICES, *(() if by is None else (by,))}
    picks: dict[str, list[Mapping[str, Any]]] = {}
    for prop in properties:
        if (name := prop.get("name")) in names:
            picks.setdefault(str(name), []).append(prop)
    problems = [
        f"{what} picks what it does by {name}, which the class file does not class."
        for name in picks
        if name != by
    ]
    if not isinstance(classed, Operations):
        return problems
    offered = picks.get(classed.by)
    if offered is None:
        return [*problems, f"{what} no longer picks what it does by {classed.by}."]
    if any(prop.get("type") != "options" for prop in offered):
        return [*problems, f"{what} picks what it does by {classed.by} from no fixed list."]
    values = {
        str(cast(Mapping[str, Any], option).get("value"))
        for prop in offered
        for option in cast(list[object], prop.get("options") or [])
        if isinstance(option, dict)
    }
    defaults = {str(prop.get("default")) for prop in offered}
    problems += [
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
