"""A use case's draft in n8n: the safety checker's yes and grade on the Planner's layout, and the
lines of the build log the set-up card replays (ENGINE-PLAN 2.5, section 1 row 1). The words
are the sketch's.

Pure. The service stamps each line with the moment it happened and saves the draft.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from platform_api.orchestration import (
    Document,
    Finding,
    Graded,
    Unreadable,
    add_yes,
    grade,
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


def check_draft(laid: Mapping[str, Any], key: str, error_workflow: str) -> Checked | DraftRefused:
    """The checker puts a yes before each write, then grades the result. Only a draft that grades
    Safe is saved: a layout that needs a fix, or a write the checker could not put behind one
    yes, is refused."""
    try:
        first = grade(laid, error_workflow)
        fixes = tuple(f for f in first.findings if f.grade == "needs_a_fix")
        if fixes:
            return DraftRefused(fixes)
        lines: list[tuple[LineKind, str]] = [("check", FIT)]
        changes = bool(writes(laid))
        if changes:
            lines.append(("status", CHECKING))
        with_yes = add_yes(laid, key)
    except Unreadable as unreadable:
        return DraftRefused((Finding("needs_a_fix", None, str(unreadable)),))
    lines.extend(("note", added_line(write)) for write in with_yes.added_before)
    graded = grade(with_yes.document, error_workflow)
    if graded.grade != "safe":
        return DraftRefused(graded.findings)
    if changes:
        lines.append(("check", EVERY_WRITE))
    return Checked(with_yes.document, graded, tuple(lines))
