"""A use case's draft in n8n: the safety checker's yes and grade on the Planner's layout, and the
lines of the build log the set-up card replays (ENGINE-PLAN 2.5, section 1 row 1). The words
are the sketch's.

Pure. The service stamps each line with the moment it happened and saves the draft.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from platform_api.builder.models import BlockView, N8nBlockKind, N8nBlockView, N8nExitView
from platform_api.orchestration import (
    ASK_EXITS,
    BlockKind,
    Document,
    Edge,
    Face,
    Finding,
    Graded,
    KnownOptions,
    Unreadable,
    add_yes,
    face,
    grade,
    read_flow,
    writes,
)

ADDING = "Adding blocks in n8n…"
FIT = "The blocks fit together."
CHECKING = "Safety checker is checking the write…"
EVERY_WRITE = "Every write waits for approval."
SAVED = "Saved as a draft in n8n."
WHAT_IS_WRITTEN: Mapping[str, str] = {
    "Create ticket": "each ticket",
    "Create tickets": "each ticket",
    "Update page": "each page update",
}
"""What each write makes, in the words of the approval step's line. A write not here is "each
change", never a quoted block name."""

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
class N8nNotReady:
    """n8n could not do what was asked, so nothing changed here."""

    detail: str


@dataclass(frozen=True)
class NotSafe:
    """The version on record did not grade safe, so it never goes live."""


@dataclass(frozen=True)
class DraftRefused:
    """The checker would not let this layout be saved."""

    findings: tuple[Finding, ...]


def test_run_skips(name: str) -> str:
    return f'A test run skips "{name}", so it posts nothing.'


def notices_in(document: Mapping[str, Any]) -> list[str]:
    try:
        flow = read_flow(document)
    except Unreadable:
        return []
    return [b.name for b in flow.blocks.values() if face(b.type, b.version, b.parameters).notice]


def added_line(write: str) -> str:
    return (
        "I added an approval step. "
        f"Before {WHAT_IS_WRITTEN.get(write, 'each change')} is made, "
        "an Approver must approve it in Teams."
    )


def check_draft(
    laid: Mapping[str, Any],
    key: str,
    error_workflow: str,
    time_zone: str,
    known: KnownOptions | None = None,
) -> Checked | DraftRefused:
    """The checker puts a yes before each write, then grades the result. Only a draft that grades
    Safe is saved: a layout that needs a fix, or a write the checker could not put behind one
    yes, is refused."""
    try:
        changes = bool(writes(laid))
        with_yes = add_yes(laid, key)
    except Unreadable as unreadable:
        return DraftRefused((Finding("unreadable", "needs_a_fix", None, str(unreadable)),))
    graded = grade(with_yes.document, error_workflow, time_zone, known)
    if graded.grade != "safe":
        return DraftRefused(graded.findings)
    lines: list[tuple[LineKind, str]] = [("check", FIT)]
    if changes:
        lines.append(("status", CHECKING))
    lines.extend(("note", added_line(write)) for write in with_yes.added_before)
    if changes:
        lines.append(("check", EVERY_WRITE))
    lines.extend(("note", test_run_skips(name)) for name in notices_in(with_yes.document))
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
        block = flow.blocks[name]
        seen = face(block.type, block.version, block.parameters)
        if seen.kind == "note":
            continue
        kind = view_kind(seen)
        exits = ASK_EXITS if kind == "ask" else BRANCH_EXITS if kind == "branch" else ()
        views.append(
            N8nBlockView(
                name=name,
                kind=kind,
                badge="ours" if seen.ours else "n8n",
                tag=seen.tag,
                next=[
                    N8nExitView(
                        exit=exits[edge.exit] if edge.exit < len(exits) else None, to=edge.target
                    )
                    for edge in flow.after(name)
                ],
            )
        )
    return views


READ_STEP = "Read"


def read_only_steps(document: Mapping[str, Any] | None) -> list[BlockView]:
    """The run line's steps for a workflow that only reads, with no agent to name a step after,
    as one made in n8n may be: one step for each of our Read blocks, in the order a run meets
    them, named by what the block is."""
    blocks = [] if document is None else blocks_of(document)
    if any(block.kind == "agent" for block in blocks):
        return []
    reads = [block for block in blocks if block.kind == "read"]
    return [
        BlockView(
            key=f"read_{number}",
            name=READ_STEP,
            description="Reads from GitHub, Jira or Confluence. It can't change anything.",
            kind="agent",
        )
        for number, _ in enumerate(reads, start=1)
    ]


def view_kind(seen: Face) -> N8nBlockKind:
    """A sticky note, a data block and a system block are all other to the run line, which tells
    them apart by their tag."""
    match seen.kind:
        case None:
            return "off"
        case "note" | "shape" | "system":
            return "other"
        case known:
            return known


def _exit(edge: Edge) -> int:
    return edge.exit
