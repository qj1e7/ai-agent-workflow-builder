"""The catalogue of n8n's blocks (ADR 0051, section 8), and the pin check of what their code
reaches (ADR 0051, section 2).

The catalogue holds every type the pinned n8n image ships: its name, its description and the other
words n8n finds it by, its versions, its resources and operations, and the parameters of each
version with n8n's `displayOptions`, so that a reader can return only what n8n shows for one
resource and operation. Fields that only shape n8n's editor are left out. From our own files it
adds each operation's class, tag and `says` from the class file, which key of the platform's the
type runs with (`KEY_FOR_TYPE`), and the blocks section 2 holds off. The workflow drafter reads it
through `agent_runtime.catalogue`.

    python -m platform_api.n8n_catalogue <served nodes.json> <image> <sources>

prints the catalogue. `<served nodes.json>` is what the image serves at /types/nodes.json without
the allow list, `<image>` is the pin it came from, and `<sources>` holds each package in
`SHIPPED` as the image has it: `<package>/dist/known/nodes.json`, `<package>/dist/nodes` and
`<package>/dist/utils`. scripts/n8n-catalogue.sh runs it.

It also runs the pin check of the blocks' code (`n8n_code_check`), and fails when that finds
anything new.
"""

import json
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from platform_api.n8n_code_check import SHIPPED, Scan, problems, scan
from platform_api.orchestration.node_classes import (
    NODE_CLASSES,
    OURS,
    Classed,
    NodeClasses,
    OffType,
    Operations,
    Resources,
    Use,
    version_key,
)
from platform_api.orchestration.platform_keys import KEY_FOR_TYPE

type Json = dict[str, Any]

FETCHED = ("@n8n/mcp-registry",)
"""Packages whose blocks n8n makes while it runs, from a list it fetches from n8n's own API
(api.n8n.io), not from the image. They change without a new pin, and DevNet can't fetch them, so
the catalogue leaves them out."""
FETCHED_BACKING = frozenset({"@n8n/n8n-nodes-langchain.mcpRegistryClientTool"})
"""The hidden block that runs the fetched ones. n8n serves it once more each time it fetches the
list, so what n8n serves of it changes while n8n runs."""
LEFT_OUT = frozenset({"n8n-nodes-base.executeCommand", "n8n-nodes-base.localFileTrigger"})
"""n8n never loads these (NODES_EXCLUDE): either one opens n8n's own environment."""
NOT_PARAMETERS = frozenset({"notice", "callout"})
"""Property types that only show words in n8n's editor and hold no value."""


@dataclass(frozen=True)
class Hold:
    """Why a block can't run on this platform yet, and what it waits for (ADR 0051, section 2)."""

    because: str
    waits_for: str
    when: Mapping[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])
    """Only while each of these parameters has one of these values. Empty: whatever it does."""

    def as_json(self) -> Json:
        held: Json = {"because": self.because, "waits_for": self.waits_for}
        if self.when:
            held["when"] = {name: list(values) for name, values in self.when.items()}
        return held


P9 = "spike P9"
AMENDMENT = "an amendment that makes a version's approval cover the workflows it calls"
CODE = Hold("It runs code.", P9)
DISK = Hold("It reads or writes a path on n8n's disk.", P9)
CALLS = Hold("It runs another workflow, which its approval doesn't cover.", AMENDMENT)

HELD: Mapping[str, tuple[Hold, ...]] = {
    "n8n-nodes-base.code": (CODE,),
    "@n8n/n8n-nodes-langchain.code": (CODE,),
    "@n8n/n8n-nodes-langchain.toolCode": (CODE,),
    "n8n-nodes-base.function": (CODE,),
    "n8n-nodes-base.functionItem": (CODE,),
    "n8n-nodes-base.aiTransform": (CODE,),
    "n8n-nodes-base.sort": (Hold(CODE.because, P9, {"type": ("code",)}),),
    "n8n-nodes-base.itemLists": (Hold(CODE.because, P9, {"type": ("code",)}),),
    "n8n-nodes-base.merge": (Hold(CODE.because, P9, {"mode": ("combineBySql",)}),),
    "n8n-nodes-base.readWriteFile": (DISK,),
    "n8n-nodes-base.readBinaryFile": (DISK,),
    "n8n-nodes-base.readBinaryFiles": (DISK,),
    "n8n-nodes-base.writeBinaryFile": (DISK,),
    "n8n-nodes-base.git": (DISK,),
    "n8n-nodes-base.executeWorkflow": (
        CALLS,
        Hold(DISK.because, P9, {"source": ("localFile",)}),
    ),
    "n8n-nodes-base.executeWorkflowTrigger": (CALLS,),
    "@n8n/n8n-nodes-langchain.toolWorkflow": (CALLS,),
    "@n8n/n8n-nodes-langchain.retrieverWorkflow": (CALLS,),
}
"""The blocks section 2 holds off. A tool n8n makes from one of them is held the same way."""

_PARAMETER_KEYS = (
    "name",
    "displayName",
    "type",
    "default",
    "required",
    "description",
    "placeholder",
    "displayOptions",
    "noDataExpression",
)
_TYPE_OPTIONS = (
    "loadOptionsMethod",
    "loadOptionsDependsOn",
    "multipleValues",
    "minValue",
    "maxValue",
    "password",
    "editor",
    "editorLanguage",
    "sqlDialect",
)
"""The type options that say what a value may be, rather than how n8n's editor draws it."""
_CHOICE_KEYS = ("name", "value", "description", "action")
_CLASS_KEYS = frozenset({"class", "tag", "says"})
"""What the catalogue adds to an operation from the class file."""
_MODE_KEYS = ("name", "displayName", "type", "placeholder")


def catalogue(
    served: Iterable[Mapping[str, Any]],
    image: str,
    own: Collection[str],
    classes: NodeClasses = NODE_CLASSES,
) -> Json:
    """The catalogue of every type in `served` that the image ships, with our own blocks. `own`
    names the blocks with code of their own; n8n makes the other `...Tool` types from them."""
    descriptions: dict[str, list[Mapping[str, Any]]] = {}
    for description in served:
        name = str(description.get("name"))
        # n8n can serve one description twice, as it does after loading a block again.
        if _kept(name) and description not in descriptions.get(name, []):
            descriptions.setdefault(name, []).append(description)
    names = set(descriptions)
    blocks = {
        name: _block(
            name,
            descriptions[name],
            classes,
            None if name in own else _made_from(name, names),
        )
        for name in sorted(descriptions)
    }
    for block in blocks.values():
        if (base := block.get("tool_of")) is not None:
            _share_parameters(block, blocks[base])
    return {"image": image, "blocks": blocks}


def dump(made: Json) -> str:
    """The catalogue as the committed file holds it: keys sorted, and each block on a line of its
    own, so that a new pin's diff names the blocks it changed."""
    blocks = cast(Mapping[str, Json], made["blocks"])
    lines = [f"{_compact(name)}: {_compact(blocks[name])}" for name in sorted(blocks)]
    rest = _compact({key: value for key, value in made.items() if key != "blocks"})
    return '{"blocks": {\n' + ",\n".join(lines) + "\n}, " + rest[1:] + "\n"


def pin_problems(
    found: Scan, served: Iterable[str], listed: Collection[str] | None = None
) -> list[str]:
    """What the pin check of the blocks' code found (`n8n_code_check`), and each type n8n serves
    whose code it didn't read."""
    said = problems(found, listed)
    names = set(served)
    for name in sorted(names):
        if _kept(name) and not name.startswith(OURS) and name not in found.blocks:
            base = _made_from(name, names)
            if base is None or base not in found.blocks:
                said.append(f"n8n serves {name}, whose code the pin check didn't read.")
    return said


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        print(
            "usage: python -m platform_api.n8n_catalogue <served nodes.json> <image> <sources>",
            file=sys.stderr,
        )
        return 2
    served = cast(list[Mapping[str, Any]], json.loads(Path(args[0]).read_text()))
    found = scan(Path(args[2]))
    try:
        made = catalogue(served, args[1], found.blocks)
    except ValueError as error:
        print(f"catalogue: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(dump(made))
    problems = pin_problems(found, (str(d.get("name")) for d in served))
    for problem in problems:
        print(f"pin check: {problem}", file=sys.stderr)
    return 1 if problems else 0


def _compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _share_parameters(tool: Json, base: Json) -> None:
    """Leaves out of a tool n8n made what it has from its block. Where its parameters are the
    block's own, after the few n8n adds for an AI agent, the tool keeps only those few, as
    `tool_parameters`, and a reader takes the rest, with the resources and operations, from the
    block's version with the same versions. The tool keeps its own class."""
    by_versions = {
        tuple(cast(list[float], group["versions"])): group
        for group in cast(list[Json], base["versions"])
    }
    for group in cast(list[Json], tool["versions"]):
        theirs = by_versions.get(tuple(cast(list[float], group["versions"])))
        if theirs is None:
            continue
        mine = cast(list[Json], group["parameters"])
        added = len(mine) - len(cast(list[Json], theirs["parameters"]))
        same = all(
            _unclassed(group.get(key)) == _unclassed(theirs.get(key))
            for key in ("resources", "operations")
        )
        if same and added >= 0 and mine[added:] == theirs["parameters"]:
            for key in ("parameters", "resources", "operations"):
                group.pop(key, None)
            group["tool_parameters"] = mine[:added]


def _unclassed(listed: object) -> list[Json]:
    return [
        {key: value for key, value in item.items() if key not in _CLASS_KEYS}
        for item in cast(list[Json], listed or [])
    ]


def _package(name: str) -> str:
    return name.rpartition(".")[0]


def _kept(name: str) -> bool:
    """Whether the catalogue holds this type. A type from a package nobody has placed fails."""
    package = _package(name)
    if name.startswith(OURS) or package in SHIPPED:
        return name not in LEFT_OUT and name not in FETCHED_BACKING
    if package in FETCHED:
        return False
    raise ValueError(
        f"n8n serves {name}, from {package}, which platform_api/n8n_catalogue.py doesn't know. "
        "Say whether the image ships it (SHIPPED) or n8n fetches it (FETCHED). Community "
        "nodes stay off."
    )


def _made_from(name: str, names: set[str]) -> str | None:
    """The block n8n made this one from, for an AI agent's tool it makes of every block marked
    usable as one."""
    for suffix in ("HitlTool", "Tool"):
        if name.endswith(suffix) and (base := name.removesuffix(suffix)) in names:
            return base
    return None


def _versions(description: Mapping[str, Any]) -> list[int | float]:
    version = description.get("version")
    listed = cast(list[object], version) if isinstance(version, list) else [version]
    return sorted(v for v in listed if isinstance(v, int | float) and not isinstance(v, bool))


def _block(
    name: str,
    descriptions: Sequence[Mapping[str, Any]],
    classes: NodeClasses,
    made_from: str | None,
) -> Json:
    ordered = sorted(descriptions, key=lambda d: _versions(d)[-1])
    default = ordered[-1].get("defaultVersion", _versions(ordered[-1])[-1])
    current = next((d for d in ordered if default in _versions(d)), ordered[-1])
    block: Json = {
        "name": current.get("displayName") or name,
        "description": current.get("description") or "",
        "default_version": default,
    }
    codex = cast(Mapping[str, Any], current.get("codex") or {})
    if aliases := [a for a in cast(list[object], codex.get("alias") or []) if isinstance(a, str)]:
        block["aliases"] = aliases
    if current.get("hidden"):
        block["hidden"] = True
    if made_from is not None:
        block["tool_of"] = made_from
    if (spec := KEY_FOR_TYPE.get(name)) is not None:
        block["key"] = {"system": spec.system, "for": spec.on}
    holds = HELD.get(name) or HELD.get(made_from or "", ())
    if holds:
        block["held"] = [hold.as_json() for hold in holds]
    block["versions"] = [_version(name, d, classes) for d in ordered]
    return block


def _version(name: str, description: Mapping[str, Any], classes: NodeClasses) -> Json:
    versions = _versions(description)
    properties = cast(Sequence[Mapping[str, Any]], description.get("properties") or [])
    version: Json = {"versions": versions}
    if resources := _resources(properties, versions):
        version["resources"] = resources
    operations = _operations(properties, versions)
    _class(name, versions, version, operations, classes)
    if operations:
        version["operations"] = operations
    version["parameters"] = [
        _parameter(p) for p in properties if p.get("type") not in NOT_PARAMETERS
    ]
    return version


def _resources(
    properties: Sequence[Mapping[str, Any]], versions: Sequence[int | float]
) -> list[Json]:
    """Each resource n8n offers. One that only some of the versions offer names them."""
    seen: dict[str, Json] = {}
    shown: dict[str, set[int | float]] = {}
    for prop in properties:
        if prop.get("name") == "resource" and prop.get("type") == "options":
            these = _shown_in(prop, versions)
            for option in _choices(prop):
                value = str(option.get("value"))
                seen.setdefault(value, _picked(option, ("name", "value")))
                shown.setdefault(value, set()).update(these)
    return [_only_in(seen[value], shown[value], versions) for value in seen if shown[value]]


def _operations(
    properties: Sequence[Mapping[str, Any]], versions: Sequence[int | float]
) -> list[Json]:
    """Each operation n8n offers, with the resource it is offered for. One that only some of the
    versions offer names them, as n8n's `@version` conditions decide."""
    seen: dict[tuple[str | None, str], Json] = {}
    shown: dict[tuple[str | None, str], set[int | float]] = {}
    for prop in properties:
        if prop.get("name") != "operation" or prop.get("type") != "options":
            continue
        these = _shown_in(prop, versions)
        options = cast(Mapping[str, Any], prop.get("displayOptions") or {})
        show = cast(Mapping[str, Any], options.get("show") or {})
        offered = [r for r in cast(list[object], show.get("resource") or []) if isinstance(r, str)]
        for resource in offered or [None]:
            for option in _choices(prop):
                value = str(option.get("value"))
                operation: Json = {"value": value, "name": option.get("name") or value}
                if resource is not None:
                    operation["resource"] = resource
                if said := option.get("action") or option.get("description"):
                    operation["action"] = said
                seen.setdefault((resource, value), operation)
                shown.setdefault((resource, value), set()).update(these)
    return [_only_in(seen[key], shown[key], versions) for key in seen if shown[key]]


def _only_in(item: Json, shown: set[int | float], versions: Sequence[int | float]) -> Json:
    if len(shown) < len(versions):
        item["versions"] = [v for v in versions if v in shown]
    return item


def _shown_in(prop: Mapping[str, Any], versions: Sequence[int | float]) -> set[int | float]:
    """The versions n8n shows this property in, by its `@version` conditions. A condition this
    code can't judge counts as shown."""
    options = cast(Mapping[str, Any], prop.get("displayOptions") or {})
    show = cast(Mapping[str, Any], options.get("show") or {}).get("@version")
    hide = cast(Mapping[str, Any], options.get("hide") or {}).get("@version")
    return {
        v
        for v in versions
        if (show is None or _version_in(cast(list[object], show), v) is not False)
        and (hide is None or _version_in(cast(list[object], hide), v) is not True)
    }


def _version_in(conditions: Sequence[object], version: int | float) -> bool | None:
    """Whether any condition holds for the version, as n8n's `checkConditions` decides, or None
    when this code can't tell."""
    results = [_version_is(condition, version) for condition in conditions]
    if True in results:
        return True
    return None if None in results else False


def _version_is(condition: object, version: int | float) -> bool | None:
    if isinstance(condition, int | float) and not isinstance(condition, bool):
        return condition == version
    test = cast(Mapping[str, Any], condition).get("_cnd") if isinstance(condition, dict) else None
    if not isinstance(test, dict) or len(cast(Json, test)) != 1:
        return None
    ((how, target),) = cast(Json, test).items()
    try:
        match how:
            case "eq":
                return version == target
            case "not":
                return version != target
            case "gte":
                return version >= target
            case "lte":
                return version <= target
            case "gt":
                return version > target
            case "lt":
                return version < target
            case "between":
                return target["from"] <= version <= target["to"]
            case _:
                return None
    except TypeError, KeyError:
        return None


def _class(
    name: str,
    versions: Sequence[int | float],
    version: Json,
    operations: Sequence[Json],
    classes: NodeClasses,
) -> None:
    """Puts on the version, or on each of its operations, what the class file says of them."""
    entry = classes.entry(name)
    if entry is None:
        return
    said: list[tuple[Classed | None, Use | None]] = []
    for served in versions:
        key = version_key(served)
        if isinstance(entry, OffType):
            said.append(("off", None))
        elif key is not None:
            said.append((entry.versions.get(key), entry.uses.get(key)))
    if not said or any(other != said[0] for other in said):
        raise ValueError(
            f"The class file classes the versions of {name} that n8n serves together, "
            f"{', '.join(f'{v:g}' for v in versions)}, differently. Class them alike."
        )
    classed, use = said[0]
    match classed:
        case None:
            return
        case str():
            version["class"] = classed
            _use(version, use)
        case Operations(by="operation", classes=by_operation):
            for operation in operations:
                _operation_class(operation, by_operation.get(operation["value"]), use)
        case Operations(by=by, classes=by_value):
            version["class_by"] = {"parameter": by, "classes": dict(by_value)}
            _use(version, use)
        case Resources(operations=by_resource):
            for operation in operations:
                picked = by_resource.get(str(operation.get("resource")))
                chosen = (
                    picked.classes.get(operation["value"])
                    if isinstance(picked, Operations)
                    else picked
                )
                _operation_class(operation, chosen, use)


def _operation_class(operation: Json, chosen: str | None, use: Use | None) -> None:
    if chosen is None:
        return
    operation["class"] = chosen
    if chosen != "off":
        _use(operation, use)


def _use(target: Json, use: Use | None) -> None:
    if use is not None:
        target["tag"] = use.tag
        target["says"] = use.says


def _choices(prop: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        cast(Mapping[str, Any], o)
        for o in cast(list[object], prop.get("options") or [])
        if isinstance(o, dict)
    ]


def _picked(source: Mapping[str, Any], keys: Sequence[str]) -> Json:
    return {key: source[key] for key in keys if source.get(key) not in (None, "")}


def _parameter(prop: Mapping[str, Any]) -> Json:
    """One of n8n's properties, with what says what its value may be and when n8n shows it."""
    parameter = _picked(prop, _PARAMETER_KEYS)
    if "default" in prop:
        parameter["default"] = prop["default"]
    type_options = _picked(cast(Mapping[str, Any], prop.get("typeOptions") or {}), _TYPE_OPTIONS)
    if type_options:
        parameter["typeOptions"] = type_options
    match prop.get("type"):
        case "options" | "multiOptions":
            parameter["options"] = [_picked(o, _CHOICE_KEYS) for o in _choices(prop)]
        case "collection":
            parameter["options"] = [
                _parameter(o) for o in _choices(prop) if o.get("type") not in NOT_PARAMETERS
            ]
        case "fixedCollection":
            parameter["options"] = [
                {
                    **_picked(o, ("name", "displayName")),
                    "values": [
                        _parameter(cast(Mapping[str, Any], v))
                        for v in cast(list[object], o.get("values") or [])
                        if isinstance(v, dict)
                        and cast(Mapping[str, Any], v).get("type") not in NOT_PARAMETERS
                    ],
                }
                for o in _choices(prop)
            ]
        case "resourceLocator":
            modes = cast(list[object], prop.get("modes") or [])
            parameter["modes"] = [
                _picked(cast(Mapping[str, Any], m), _MODE_KEYS)
                for m in modes
                if isinstance(m, dict)
            ]
        case _:
            pass
    return parameter


if __name__ == "__main__":
    sys.exit(main())
