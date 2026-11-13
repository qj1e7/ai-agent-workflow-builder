"""A use case's draft in n8n: the safety checker's yes and grade on the Planner's layout, and the
lines of the build log the set-up card replays (ENGINE-PLAN 2.5, section 1 row 1). The words
are the sketch's.

Pure. The service stamps each line with the moment it happened and saves the draft.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from platform_api.builder.models import N8nBlockKind, N8nBlockView, N8nExitView
from platform_api.orchestration import (
    ASK_EXITS,
    BlockKind,
    Document,
    Edge,
    Finding,
    Graded,
    KnownOptions,
    Unreadable,
    add_yes,
    grade,
    read_flow,
    writes,
)

ADDING = "Adding blocks in n8n…"
FIT = "The blocks fit together."
CHECKING = "Safety checker is checking the write…"
EVERY_WRITE = "Every write waits for a yes."
SAVED = "Saved as a draft in n8n."
WHAT_IS_WRITTEN: Mapping[str, str] = {
    "Create ticket": "the ticket",
    "Create tickets": "the tickets",
}

type LineKind = Literal["status", "check", "note"]
"""status: what the builder is doing now. check: a check that passed. note: what the safety
checker changed."""


@dataclass(frozen=True)
class Checked:
    document: Document
    graded: Graded
    lines: tuple[tuple[LineKind, str], ...]
    """What happened between "Adding blocks in n8n…" and the save."""


@dataclass(frozen=True)
class DraftRefused:
    """The checker would not let this layout be saved."""

    findings: tuple[Finding, ...]


def added_line(write: str) -> str:
    return f"Added a yes before {WHAT_IS_WRITTEN.get(write, f'"{write}"')}."


def check_draft(
    laid: Mapping[str, Any], key: str, error_workflow: str, known: KnownOptions | None = None
) -> Checked | DraftRefused:
    """The checker puts a yes before each write, then grades the result. Only a draft that grades
    Safe is saved: a layout that needs a fix, or a write the checker could not put behind one
    yes, is refused."""
    try:
        changes = bool(writes(laid))
        with_yes = add_yes(laid, key)
    except Unreadable as unreadable:
        return DraftRefused((Finding("needs_a_fix", None, str(unreadable)),))
    graded = grade(with_yes.document, error_workflow, known)
    if graded.grade != "safe":
        return DraftRefused(graded.findings)
    lines: list[tuple[LineKind, str]] = [("check", FIT)]
    if changes:
        lines.append(("status", CHECKING))
    lines.extend(("note", added_line(write)) for write in with_yes.added_before)
    if changes:
        lines.append(("check", EVERY_WRITE))
    return Checked(with_yes.document, graded, tuple(lines))


STARTS_FIRST: tuple[BlockKind, ...] = ("schedule", "start", "manual", "error")
BRANCH_EXITS = ("true", "false")


def blocks_of(document: Mapping[str, Any]) -> list[N8nBlockView]:
    """The blocks in the order a run meets them: the blocks that start a run, the schedule
    first, then each path in exit order, so the way to the write comes before the quiet end. A
    block no run reaches comes last. Sticky notes are not blocks a run meets."""
    try:
        flow = read_flow(document)
    except Unreadable:
        return []
    starts = [b.name for kind in STARTS_FIRST for b in flow.of_kind(kind)]
    order: dict[str, None] = dict.fromkeys(starts)
    stack = [edge.target for name in reversed(starts) for edge in reversed(flow.after(name))]
    while stack:
        name = stack.pop()
        if name in order:
            continue
        order[name] = None
        stack.extend(edge.target for edge in reversed(sorted(flow.after(name), key=_exit)))
    order.update(dict.fromkeys(flow.blocks))
    views: list[N8nBlockView] = []
    for name in order:
        spec = flow.blocks[name].spec
        kind: N8nBlockKind
        if spec is None:
            kind = "other"
        elif (known := spec.kind) == "note":
            continue
        else:
            kind = known
        exits = ASK_EXITS if kind == "ask" else BRANCH_EXITS if kind == "branch" else ()
        views.append(
            N8nBlockView(
                name=name,
                kind=kind,
                next=[
                    N8nExitView(
                        exit=exits[edge.exit] if edge.exit < len(exits) else None, to=edge.target
                    )
                    for edge in flow.after(name)
                ],
            )
        )
    return views


def _exit(edge: Edge) -> int:
    return edge.exit
