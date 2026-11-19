"""The catalogue of n8n's blocks (ADR 0051, section 8), read for the workflow drafter's tools.
`find_blocks` searches it, and `describe_block` returns only the parameters n8n shows for one
resource and operation of a block, so that a large block such as Jira is never sent whole. Plain
code, with no model.

scripts/n8n-catalogue.sh writes the catalogue, contracts/n8n/catalogue.json, from the pinned n8n
image. Each version of a block holds n8n's own parameters, each with the `displayOptions` that say
when n8n's editor shows it, and what our class file says of each operation.

The agent-runtime image carries the file at `IN_THE_IMAGE`.

    python -m agent_runtime.catalogue [path]

prints the image the catalogue was made from, or why it can't be used.
"""

import json
import re
import sys
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

type Json = dict[str, Any]

IN_THE_IMAGE: Final = Path("/app/contracts/n8n/catalogue.json")
PINNED: Final = re.compile(r"[^\s@:]+(?:/[^\s@:]+)*:[^\s@:]+@sha256:[0-9a-f]{64}")
"""An image named by its tag and its digest, as the catalogue's stamp must be."""
OURS: Final = "CUSTOM."
"""How n8n names the types of our node pack."""
CUSTOM_API_CALL: Final = "__CUSTOM_API_CALL__"
"""The resource and operation n8n adds to a block with a key, which sends any request with it."""
_CLASS_KEYS: Final = ("class", "tag", "says")
_MARKS: Final = ("key", "held", "hidden", "tool_of")
_STOP_WORDS: Final = frozenset(
    {
        *("a", "an", "and", "any", "are", "as", "at", "be", "by", "do", "does", "each"),
        *("every", "for", "from", "get", "i", "if", "in", "into", "is", "it", "its", "me"),
        *("my", "new", "of", "on", "or", "our", "please", "some", "that", "the", "then"),
        *("them", "this", "to", "up", "us", "we", "when", "with"),
    }
)
"""Words too common in a request to tell one block from another."""
_WEIGHTS: Final = {"name": 3, "type": 3, "aliases": 2, "operations": 2, "description": 1}
_UNKNOWN: Final = object()


class NotInCatalogue(ValueError):
    """The catalogue has no such block, version, resource or operation. The words say what it has
    instead, so that the drafter can choose again."""


class CatalogueUnusable(Exception):
    """The catalogue file is missing, can't be read, or doesn't name the n8n image it was made
    from by its digest. Drafting stops until it is fixed."""


def load(path: Path) -> Catalogue:
    """The catalogue at `path`, or `CatalogueUnusable` with words an operator can act on."""
    try:
        read: object = json.loads(path.read_bytes())
    except FileNotFoundError:
        raise CatalogueUnusable(
            f"The n8n block catalogue is missing at {path}. The agent-runtime image must carry "
            "contracts/n8n/catalogue.json."
        ) from None
    except (OSError, ValueError) as error:
        raise CatalogueUnusable(
            f"The n8n block catalogue at {path} can't be read ({type(error).__name__})."
        ) from None
    raw = cast(Json, read) if isinstance(read, dict) else {}
    image = raw.get("image")
    if not isinstance(image, str) or PINNED.fullmatch(image) is None:
        raise CatalogueUnusable(
            f"The n8n block catalogue at {path} doesn't name the n8n image it was made from by "
            "its digest, so nobody can tell which n8n it describes. Run scripts/n8n-catalogue.sh."
        )
    if not isinstance(raw.get("blocks"), dict):
        raise CatalogueUnusable(f"The n8n block catalogue at {path} holds no blocks.")
    return Catalogue(cast(Mapping[str, Any], raw))


def is_expression(value: object) -> bool:
    """Whether n8n reads the value as an expression, as it reads any text that starts with =."""
    return isinstance(value, str) and value.startswith("=")


@dataclass(frozen=True)
class _Indexed:
    type: str
    rank: tuple[int, bool]
    """Our own blocks first, then the blocks the class file lets run, then the rest, then the
    tools n8n makes of blocks for an AI agent. Within each, the blocks n8n hides come last."""
    words: Mapping[str, int]
    """Each word's stem, with the weight of the most telling place it appears."""


class Catalogue:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.image = str(raw["image"])
        """The n8n image the catalogue was made from, with its digest."""
        self._blocks = cast(Mapping[str, Json], raw["blocks"])
        self._index = [self._indexed(name) for name in sorted(self._blocks)]

    @classmethod
    def read(cls, path: Path) -> Catalogue:
        return cls(cast(Mapping[str, Any], json.loads(path.read_bytes())))

    def find_blocks(self, words: str, limit: int = 8) -> list[Json]:
        """The blocks whose name, description or operations match the words at least half as well
        as the best match does: our own blocks and the ones the class file lets run first, then
        the best matches. Our own blocks have no operations in n8n's sense, so the choices they
        list count as theirs: the sources Read reads and the changes Propose a change proposes.
        Each block comes with its operations or choices that match, so the drafter can describe
        one next."""
        asked = _stems(words)
        scored = [(sum(e.words.get(stem, 0) for stem in asked), e) for e in self._index]
        best = max((score for score, _ in scored), default=0)
        found = sorted(
            (entry.rank, -score, entry.type)
            for score, entry in scored
            if score and score * 2 >= best
        )
        return [self._summary(name, asked) for *_, name in found[:limit]]

    def describe_block(
        self,
        node_type: str,
        version: float | None = None,
        resource: str | None = None,
        operation: str | None = None,
    ) -> Json:
        """One version of a block, with only the parameters n8n shows for this resource and
        operation, by n8n's `displayOptions`. A condition on any other parameter stays on the
        parameter, so the drafter sees when it applies. Without a resource or operation that the
        block needs, it returns the choices instead, with no parameters. With no version, it is
        the version n8n gives a new block."""
        block = self._block(node_type)
        chosen = block["default_version"] if version is None else version
        group = self._version(node_type, chosen)
        described: Json = {"type": node_type, "version": chosen, "name": block["name"]}
        described |= {mark: block[mark] for mark in _MARKS if mark in block}
        operations = cast(list[Json], group.get("operations") or [])
        resources = [str(r["value"]) for r in cast(list[Json], group.get("resources") or [])]
        offered = [o for o in operations if o.get("resource") == resource]
        if (resources and resource is None) or (offered and operation is None):
            return described | {
                "resources": group.get("resources") or [],
                "operations": offered if resource is not None else operations,
                "choose": "Describe it again with a resource and an operation from these.",
            }
        if resource is not None and resource not in resources:
            raise NotInCatalogue(
                f"{block['name']} version {chosen:g} has no resource {resource!r}. "
                + (f"It has {', '.join(resources)}." if resources else "It picks no resource.")
            )
        picked = next((o for o in offered if o["value"] == operation), None)
        if operation is not None and picked is None:
            values = [str(o["value"]) for o in offered]
            raise NotInCatalogue(
                f"{block['name']} version {chosen:g} has no operation {operation!r}"
                + (f" for {resource}" if resource else "")
                + (f". It has {', '.join(values)}." if values else ". It picks no operation.")
            )
        # n8n shows some of a block's parameters only in the AI agent's tool it makes of it.
        known: dict[str, object] = {"@version": chosen, "@tool": "tool_of" in block}
        if resource is not None:
            known["resource"] = resource
        if operation is not None:
            known["operation"] = operation
        for key in ("class", "tag", "says", "class_by"):
            if key in group:
                described[key] = group[key]
        if picked is not None:
            described["operation"] = operation
            described |= {key: picked[key] for key in ("action", *_CLASS_KEYS) if key in picked}
        if resource is not None:
            described["resource"] = resource
        parameters = cast(list[Json], group["parameters"])
        return described | {"parameters": _shown(parameters, known, top=True, skip=known)}

    def block(self, node_type: str) -> Json:
        """The block as the catalogue holds it: its name, its default version, and what the
        platform marks on it (`key`, `held`, `hidden`, `tool_of`)."""
        return self._block(node_type)

    def settled(
        self, node_type: str, version: float, values: Mapping[str, object]
    ) -> dict[str, object]:
        """The block's top-level parameter values as n8n settles them: the given ones, and each
        other one n8n shows at its default, in n8n's order. An expression's value is unknown, so
        it is left out, and so is `@version` and `@tool`, which the conditions read."""
        block = self._block(node_type)
        group = self._version(node_type, version)
        known: dict[str, object] = {"@version": version, "@tool": "tool_of" in block}
        known |= {name: value for name, value in values.items() if not is_expression(value)}
        for parameter in cast(list[Json], group["parameters"]):
            name = str(parameter.get("name"))
            if name in known or name in values or "default" not in parameter:
                continue
            # Only a parameter n8n surely shows has its default. One it may show stays unknown.
            if (
                _left(cast(Mapping[str, Any], parameter.get("displayOptions") or {}), known, True)
                == {}
            ):
                known[name] = parameter["default"]
        return known

    def shown(self, node_type: str, version: float, values: Mapping[str, object]) -> list[Json]:
        """Every parameter of the version that n8n shows when the block's parameters have these
        values, the rest at their defaults, each with what is left of the conditions an
        expression's value keeps open. Unlike `describe_block`, the resource and operation stay
        in, so that their values can be checked."""
        known = self.settled(node_type, version, values)
        parameters = cast(list[Json], self._version(node_type, version)["parameters"])
        return _shown(parameters, known, top=True, skip=())

    def _block(self, node_type: str) -> Json:
        block = self._blocks.get(node_type)
        if block is None:
            raise NotInCatalogue(f"n8n has no block {node_type!r}. Find one with find_blocks.")
        return block

    def _version(self, node_type: str, version: float) -> Json:
        """The block's version that holds this one, with only the resources and operations this
        version offers, and with what a tool n8n made has from its block."""
        block = self._block(node_type)
        groups = cast(list[Json], block["versions"])
        group = next((g for g in groups if version in g["versions"]), None)
        if group is None:
            listed = ", ".join(f"{v:g}" for g in groups for v in g["versions"])
            raise NotInCatalogue(f"{block['name']} has no version {version:g}. It has {listed}.")
        if "tool_parameters" not in group:
            return group | {
                "resources": _offered_in(group.get("resources"), version),
                "operations": _offered_in(group.get("operations"), version),
            }
        base = self._version(str(block["tool_of"]), version)
        return {
            **{key: value for key, value in group.items() if key != "tool_parameters"},
            "resources": base["resources"],
            "operations": [
                {key: value for key, value in o.items() if key not in _CLASS_KEYS}
                for o in cast(list[Json], base["operations"])
            ],
            "parameters": [*group["tool_parameters"], *base["parameters"]],
        }

    def _indexed(self, name: str) -> _Indexed:
        block = self._blocks[name]
        group = self._version(name, block["default_version"])
        operations = cast(list[Json], group.get("operations") or [])
        resources = cast(list[Json], group.get("resources") or [])
        places = {
            "name": str(block["name"]),
            "type": _spaced(name.rpartition(".")[2]),
            "aliases": " ".join(cast(list[str], block.get("aliases") or [])),
            "operations": " ".join(
                str(item.get(key) or "")
                for item in (*_specific(operations), *_specific(resources), *_choices(name, group))
                for key in ("name", "action")
            ),
            "description": str(block.get("description") or ""),
        }
        words: dict[str, int] = {}
        for place, text in places.items():
            for stem in _stems(text):
                words[stem] = max(words.get(stem, 0), _WEIGHTS[place])
        if name.startswith(OURS):
            tier = 0
        elif "tool_of" in block:
            tier = 3
        else:
            classes = [group.get("class"), *(o.get("class") for o in operations)]
            tier = 1 if any(c not in (None, "off") for c in classes) else 2
        return _Indexed(name, (tier, bool(block.get("hidden"))), words)

    def _summary(self, name: str, asked: Sequence[str]) -> Json:
        block = self._blocks[name]
        group = self._version(name, block["default_version"])
        summary: Json = {
            "type": name,
            "name": block["name"],
            "description": block["description"],
            "default_version": block["default_version"],
        }
        summary |= {mark: block[mark] for mark in _MARKS if mark in block}
        if "class" in group:
            summary["class"] = group["class"]
        ranked: list[tuple[int, bool, int, Json]] = []
        for at, operation in enumerate(_specific(cast(list[Json], group.get("operations") or []))):
            said = f"{operation.get('resource', '')} {operation['name']} {operation.get('action')}"
            if matched := len(set(_stems(said)) & set(asked)):
                off = operation.get("class") == "off"
                ranked.append((-matched, off, at, operation))
        if ranked:
            summary["operations"] = [
                {key: o[key] for key in ("resource", "value", "name", "class") if key in o}
                for *_, o in sorted(ranked, key=lambda r: r[:3])[:6]
            ]
        if chosen := [c for c in _choices(name, group) if set(_stems(c["name"])) & set(asked)]:
            summary["choices"] = chosen[:6]
        return summary


def _offered_in(items: object, version: float) -> list[Json]:
    """The resources or operations a version offers. The catalogue names the versions of one that
    only some of a block's versions offer."""
    return [
        {key: value for key, value in item.items() if key != "versions"}
        for item in cast(list[Json], items or [])
        if version in item.get("versions", [version])
    ]


def _choices(name: str, group: Json) -> list[Json]:
    """The choices one of our own blocks lists for its top-level parameters, each with the
    parameter it is for. n8n's blocks are found by their operations instead."""
    if not name.startswith(OURS):
        return []
    return [
        {"parameter": parameter["name"], "value": choice["value"], "name": str(choice["name"])}
        for parameter in cast(list[Json], group.get("parameters") or [])
        if parameter.get("type") in ("options", "multiOptions")
        for choice in cast(list[Json], parameter.get("options") or [])
    ]


def _specific(items: Sequence[Json]) -> list[Json]:
    """Leaves out the Custom API Call n8n adds to every block with a key, which would match any
    request that names an API."""
    return [item for item in items if item.get("value") != CUSTOM_API_CALL]


def _stems(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [_stem(word) for word in words if word not in _STOP_WORDS]


def _stem(word: str) -> str:
    """Enough of English plurals that "issues" finds Issue and "posts" finds Post."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _spaced(text: str) -> str:
    """A type's camelCase name split into words, as in googleSheets."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)


def _shown(
    parameters: Sequence[Json], known: Mapping[str, object], top: bool, skip: Collection[str]
) -> list[Json]:
    """The parameters n8n shows when the known parameters have these values, each with what is
    left of its conditions, without the top-level ones named in `skip`."""
    shown: list[Json] = []
    for parameter in parameters:
        if top and parameter.get("name") in skip:
            continue
        options = cast(Mapping[str, Any] | None, parameter.get("displayOptions"))
        left = _left(options or {}, known, top)
        if left is None:
            continue
        kept = {key: value for key, value in parameter.items() if key != "displayOptions"}
        if left:
            kept["displayOptions"] = left
        match parameter.get("type"):
            case "collection":
                kept["options"] = _shown(
                    cast(list[Json], parameter.get("options") or []), known, False, ()
                )
            case "fixedCollection":
                kept["options"] = [
                    {
                        **group,
                        "values": _shown(
                            cast(list[Json], group.get("values") or []), known, False, ()
                        ),
                    }
                    for group in cast(list[Json], parameter.get("options") or [])
                ]
            case _:
                pass
        shown.append(kept)
    return shown


def _left(options: Mapping[str, Any], known: Mapping[str, object], top: bool) -> Json | None:
    """What is left of n8n's `displayOptions` once the known values are in, or None when n8n
    hides the parameter. As n8n does, every `show` rule must match, and any `hide` rule hides."""
    left: Json = {}
    for kind in ("show", "hide"):
        rules = cast(Mapping[str, list[object]], options.get(kind) or {})
        unsettled: Json = {}
        for key, conditions in rules.items():
            value = _value(key, known, top)
            matched = None if value is _UNKNOWN else _any(conditions, value)
            if matched is None:
                unsettled[key] = conditions
            elif matched != (kind == "show"):
                return None
        if unsettled:
            left[kind] = unsettled
    return left


def _value(key: str, known: Mapping[str, object], top: bool) -> object:
    """The known value a condition names: one of the block's own parameters by its name, or by
    `/name` from inside a collection, or `@version`."""
    if key.startswith("/"):
        key = key[1:]
    elif not top and not key.startswith("@"):
        return _UNKNOWN
    return known.get(key, _UNKNOWN)


def _any(conditions: Sequence[object], value: object) -> bool | None:
    """Whether any condition holds for the value, as n8n's `checkConditions` decides, or None when
    one this code can't judge might."""
    results = [_holds(condition, value) for condition in conditions]
    if True in results:
        return True
    return None if None in results else False


def _holds(condition: object, value: object) -> bool | None:
    if not isinstance(condition, dict):
        if isinstance(condition, bool) or isinstance(value, bool):
            return condition is value
        return condition == value
    test = cast(Mapping[str, Any], condition).get("_cnd")
    if not isinstance(test, dict) or len(cast(Json, test)) != 1:
        return None
    ((how, target),) = cast(Json, test).items()
    try:
        match how:
            case "eq":
                return value == target
            case "not":
                return value != target
            case "gte":
                return cast(Any, value) >= target
            case "lte":
                return cast(Any, value) <= target
            case "gt":
                return cast(Any, value) > target
            case "lt":
                return cast(Any, value) < target
            case "between":
                return target["from"] <= cast(Any, value) <= target["to"]
            case "includes" if isinstance(value, str):
                return str(target) in value
            case "startsWith" if isinstance(value, str):
                return value.startswith(str(target))
            case "endsWith" if isinstance(value, str):
                return value.endswith(str(target))
            case "regex" if isinstance(value, str):
                return re.search(str(target), value) is not None
            case "exists":
                return value not in (None, "")
            case _:
                return None
    except TypeError, KeyError, re.error:
        return None


def main(argv: Sequence[str]) -> int:
    try:
        catalogue = load(Path(argv[0]) if argv else IN_THE_IMAGE)
    except CatalogueUnusable as unusable:
        print(unusable, file=sys.stderr)
        return 1
    print(catalogue.image)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
