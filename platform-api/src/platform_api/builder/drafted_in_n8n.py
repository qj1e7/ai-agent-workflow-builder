"""Edit in n8n's read-back (ADR 0051, flow step 6). A person changed a drafted workflow in their
own n8n space, and code reads what n8n holds back into a plan, so it is laid out and checked
again, and the drafter can still change it.

What the platform adds to every layout is left out, since the layout adds it again: the Sticky
Note, Start from the Portal, the keys, the pinned test output, the retries on our blocks and the
workflow's own settings. Each setting's place is read: a placeholder left there is still needed,
a value as the platform laid it out keeps its mark, and a value typed in n8n counts as filled by
the person only once it passes the same check as in the chat. A place where one of n8n's notices
posts, or a schedule, that no setting holds becomes a setting the same way.

A setting follows its block when the block is renamed in n8n, by the id n8n keeps, and follows
its placeholder wherever the person moved it. A placeholder that no setting holds is refused with
words, so nothing is ever sent with one standing as a value. A value typed in n8n that doesn't
count comes back as words for the card, never dropped silently.

What a plan can't hold, such as a block set to go on past a failure or a link other than n8n's
main one, comes back as words, so nothing done in n8n is dropped.

Pure."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final, cast

from platform_api.builder.drafted_settings import (
    PLACEHOLDER,
    UNREAD,
    Source,
    free_id,
    never_guessed_places,
    passes,
    place_at,
    placeholders,
    put_at,
)
from platform_api.builder.n8n_draft import BRANCH_EXITS
from platform_api.builder.versions import SCHEDULE_TYPE, schedule_of
from platform_api.orchestration import (
    ASK_EXITS,
    TYPE_OF,
    DrafterFacts,
    PlanBlock,
    PlanSetting,
    PlanWire,
    SettingKind,
    SettingPlace,
    WorkflowPlan,
)
from platform_api.shared import UserId

LAID_OUT: Final = frozenset({"n8n-nodes-base.stickyNote", TYPE_OF["start"]})
"""Blocks the layout adds again: the Sticky Note and Start from the Portal."""
NODE_FIELDS: Final = frozenset(
    {"id", "name", "type", "typeVersion", "position", "parameters", "credentials", "webhookId"}
)
RETRIES: Final = frozenset({"retryOnFail", "maxTries", "waitBetweenTries"})
"""What the layout gives our blocks. On one of n8n's own, a plan can't hold them."""
AGAIN: Final = "Undo it in n8n, then press Done in n8n again."
NOT_A_WORKFLOW: Final = "n8n gave back something that isn't a workflow, so nothing changed."
NO_BLOCKS: Final = f"It has no blocks left. {AGAIN}"


@dataclass(frozen=True)
class ReadBack:
    plan: WorkflowPlan
    sources: dict[str, Source]
    """The settings the person filled by typing in n8n."""
    notes: tuple[str, ...] = ()
    """What came back from n8n that didn't count, in words for the card."""


@dataclass(frozen=True)
class NotReadBack:
    words: str


def read_back(
    document: Mapping[str, Any],
    before: WorkflowPlan,
    laid: Mapping[str, Any],
    facts: DrafterFacts,
    by: UserId,
    time_zone: str,
) -> ReadBack | NotReadBack:
    """The plan of what n8n holds now. `before` is the plan of the revision that was opened in
    n8n and `laid` the document it was laid out as, so code can tell what the person typed."""
    nodes = document.get("nodes")
    connections = document.get("connections")
    if not isinstance(nodes, list) or not isinstance(connections, dict):
        return NotReadBack(NOT_A_WORKFLOW)
    kept = [
        cast(dict[str, Any], n)
        for n in cast(list[object], nodes)
        if isinstance(n, dict) and cast(dict[str, Any], n).get("type") not in LAID_OUT
    ]
    if (problem := _unheld(kept, cast(dict[str, Any], connections))) is not None:
        return NotReadBack(problem)
    if not kept:
        return NotReadBack(NO_BLOCKS)
    blocks = {
        str(n["name"]): PlanBlock(
            name=str(n["name"]),
            type=str(n["type"]),
            version=float(n.get("typeVersion") or 1),
            parameters=deepcopy(cast(dict[str, Any], n.get("parameters") or {})),
        )
        for n in kept
    }
    wires = _wires(cast(dict[str, Any], connections), blocks)
    laid_nodes = cast(list[dict[str, Any]], laid.get("nodes") or [])
    was = {str(n.get("name")): cast(dict[str, Any], n.get("parameters") or {}) for n in laid_nodes}
    now_named = _renamed(kept, laid_nodes)
    held = placeholders(blocks.values())
    ids = {setting.id for setting in before.settings}
    for block, _path, setting_id in held:
        if setting_id not in ids:
            return NotReadBack(f"“{block}” holds <<{setting_id}>>, which nothing fills. {AGAIN}")
    schedule = schedule_of(document, time_zone)
    run_time = None if schedule is None else f"{schedule.day} {schedule.at}"
    settings: list[PlanSetting] = []
    sources: dict[str, Source] = {}
    notes = [_key_picked(str(n["name"])) for n in kept if n.get("credentials")]
    for setting in before.settings:
        placeholder = f"<<{setting.id}>>"
        places = [(now_named.get(f.block, f.block), f.parameter, f.block) for f in setting.fills]
        places += [(b, path, b) for b, path, i in held if i == setting.id]
        fills: list[SettingPlace] = []
        then: list[Any] = []
        for block, path, old in places:
            if block not in blocks or not _holds(blocks[block].parameters, path):
                continue
            if any(f.block == block and f.parameter == path for f in fills):
                continue
            fills.append(SettingPlace(block=block, parameter=path))
            then.append(place_at(was.get(old, {}), path))
        if not fills:
            continue
        now = [place_at(blocks[f.block].parameters, f.parameter) for f in fills]
        for fill in fills:
            put_at(blocks[fill.block].parameters, fill.parameter, placeholder)
        typed = [n for n, t in zip(now, then, strict=True) if n != t and n != placeholder]
        value, mark = setting.value, setting.mark
        if typed:
            value, said = _typed(setting, typed, run_time, facts)
            notes += said
            if value is not None and value != setting.value:
                sources[setting.id] = Source(value, "n8n", by)
            mark = "needed" if value is None else "filled"
            if value is not None and value == setting.value:
                mark = setting.mark
        elif any(n == placeholder for n in now):
            value, mark = None, "needed"
        settings.append(setting.model_copy(update={"fills": fills, "value": value, "mark": mark}))
    name = str(document.get("name") or before.name)
    if len(name) > NAME_LIMIT:
        notes.append(NAME_CUT)
    plan = WorkflowPlan(
        name=name[:NAME_LIMIT],
        blocks=list(blocks.values()),
        wires=wires,
        settings=settings,
    )
    return _with_places_typed(plan, sources, facts, by, run_time, notes)


NAME_LIMIT: Final = 80
NAME_CUT: Final = (
    f"The name given in n8n is longer than {NAME_LIMIT} characters, so it's cut to fit."
)
SHOWN: Final = 60
"""The most of a typed value the card shows."""


def _renamed(
    kept: Sequence[Mapping[str, Any]], laid: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    """Each block renamed in n8n, by its old name, found by the id n8n keeps through a rename."""
    old = {str(n.get("id")): str(n.get("name")) for n in laid if n.get("id")}
    return {
        old[str(n["id"])]: str(n["name"])
        for n in kept
        if n.get("id") and str(n.get("id")) in old and old[str(n["id"])] != n["name"]
    }


def _typed(
    setting: PlanSetting, typed: Sequence[Any], run_time: str | None, facts: DrafterFacts
) -> tuple[str | None, list[str]]:
    """The value the person typed in n8n for one setting, when it passes the check, and words
    for what didn't count."""
    label = setting.label
    if setting.kind == "run_time":
        if run_time is None:
            return None, [
                f"The schedule set in n8n for “{label}” is one the Portal can't show. "
                "So it's asked again."
            ]
        return passes("run_time", run_time, facts), []
    if any(isinstance(t, str) and t.startswith("=") for t in typed):
        return None, [
            f"You put an expression in n8n where “{label}” goes. A setting takes a value "
            "written out, so it's asked again."
        ]
    texts = list(dict.fromkeys(t for t in typed if isinstance(t, str) and t))
    if not texts:
        return None, [
            f"You changed “{label}” in n8n to something a setting can't hold. So it's asked again."
        ]
    notes: list[str] = []
    if len(texts) > 1:
        both = " and ".join(f"“{_short(t)}”" for t in texts)
        notes.append(
            f"You typed {both} in n8n for “{label}”. It holds one value, so "
            f"“{_short(texts[0])}” is kept."
        )
    value = passes(setting.kind, texts[0], facts)
    if value is None:
        notes.append(_not_counted(texts[0], label, setting.kind))
    return value, notes


def _not_counted(typed: str, label: str, kind: SettingKind) -> str:
    why = UNREAD[kind].rstrip(".")
    return (
        f"You typed “{_short(typed)}” in n8n for “{label}”, but {why[:1].lower()}{why[1:]}. "
        "So it's asked again."
    )


def _short(text: str) -> str:
    return text if len(text) <= SHOWN else f"{text[:SHOWN]}…"


def _key_picked(block: str) -> str:
    return (
        f"The key picked on “{block}” in n8n isn't kept. The platform puts on only the keys "
        "it may use."
    )


def _unheld(nodes: Sequence[dict[str, Any]], connections: Mapping[str, Any]) -> str | None:
    """What n8n holds that a plan can't, in words that say where."""
    for node in nodes:
        if not isinstance(node.get("name"), str) or not node["name"]:
            return f"A block in n8n has no name, which the platform can't read back. {AGAIN}"
        name = str(node.get("name"))
        fields = set(node) - NODE_FIELDS
        if str(node.get("type", "")).startswith("CUSTOM."):
            fields -= RETRIES
        if fields:
            return (
                f"“{name}” has {', '.join(sorted(fields))} set in n8n, which the platform can't "
                f"read back yet. {AGAIN}"
            )
    for source, outputs in connections.items():
        if not isinstance(outputs, dict):
            return NOT_A_WORKFLOW
        others = sorted(
            kind
            for kind, links in cast(dict[str, Any], outputs).items()
            if kind != "main" and links and any(cast(list[Any], links))
        )
        if others:
            return (
                f"“{source}” is linked by {', '.join(others)}, which the platform can't read "
                f"back yet. {AGAIN}"
            )
    return None


def _wires(connections: Mapping[str, Any], blocks: Mapping[str, PlanBlock]) -> list[PlanWire]:
    wires: list[PlanWire] = []
    for source, outputs in connections.items():
        if source not in blocks:
            continue
        exits = _exits(blocks[source].type)
        main = cast(list[Any], cast(dict[str, Any], outputs).get("main") or [])
        for index, targets in enumerate(main):
            for target in cast(list[dict[str, Any]], targets or []):
                to = str(target.get("node"))
                if to not in blocks:
                    continue
                wires.append(
                    PlanWire(
                        from_block=source,
                        exit=exits[index] if index < len(exits) else _exit(index),
                        to_block=to,
                        exit_index=index,
                        input_index=int(target.get("index") or 0),
                    )
                )
    return wires


def _exits(node_type: str) -> Sequence[str]:
    if node_type == "n8n-nodes-base.if":
        return BRANCH_EXITS
    if node_type == TYPE_OF["ask"]:
        return ASK_EXITS
    return ()


def _exit(index: int) -> str:
    return "main" if index == 0 else f"output {index}"


def _holds(parameters: Mapping[str, Any], path: str) -> bool:
    return place_at(parameters, path) is not None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value and not value.startswith("=") else None


def _with_places_typed(
    plan: WorkflowPlan,
    sources: dict[str, Source],
    facts: DrafterFacts,
    by: UserId,
    run_time: str | None,
    notes: list[str],
) -> ReadBack:
    """Each place where one of n8n's notices posts, and each schedule, that no setting holds,
    held by a new setting: filled by the person when what they typed passes the check, else
    still needed."""
    taken = {s.id for s in plan.settings}
    held = {(f.block, f.parameter) for s in plan.settings for f in s.fills}
    added: list[PlanSetting] = []
    for block in plan.blocks:
        places = list(never_guessed_places(block.type, block.version, block.parameters))
        if block.type == SCHEDULE_TYPE:
            places.append(("rule", "run_time"))
        for path, kind in places:
            if (block.name, path) in held:
                continue
            written = place_at(block.parameters, path)
            if written is None or (isinstance(written, str) and PLACEHOLDER.fullmatch(written)):
                continue
            if isinstance(written, str) and written.startswith("="):
                continue
            typed = run_time if kind == "run_time" else _text(written)
            value = None if typed is None else passes(kind, typed, facts)
            setting_id = free_id(kind, taken)
            taken.add(setting_id)
            put_at(block.parameters, path, f"<<{setting_id}>>")
            added.append(_new(setting_id, kind, block.name, path, value))
            if value is not None:
                sources[setting_id] = Source(value, "n8n", by)
            elif typed is not None and kind != "run_time":
                notes.append(_not_counted(typed, LABELS.get(kind, "Setting"), kind))
    return ReadBack(
        plan.model_copy(update={"settings": [*plan.settings, *added]}),
        sources,
        tuple(dict.fromkeys(notes)),
    )


LABELS: Final[Mapping[SettingKind, str]] = {
    "run_time": "Run time",
    "channel": "Slack channel",
    "address": "Address",
}


def _new(
    setting_id: str, kind: SettingKind, block: str, path: str, value: str | None
) -> PlanSetting:
    return PlanSetting(
        id=setting_id,
        kind=kind,
        label=LABELS.get(kind, "Setting"),
        fills=[SettingPlace(block=block, parameter=path)],
        value=value,
        mark="needed" if value is None else "filled",
    )
