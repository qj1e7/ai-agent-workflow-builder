"""Repairs a card the model drafted, before check_card, so a draft never stops at a problem the
person's words can't fix.

Pure. Code tidies only what is a label or an example, puts in place the one input each tool
needs, and sets aside a step it has no tool for as a part left out. It never cuts a step's
words, fills in a value or picks between two projects the words name. What it can't repair,
check_card still flags, and the Planner says how to go on.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from platform_api.builder.cards import (
    EXAMPLE_LIMIT,
    GOOD_FOR_COUNT,
    GOOD_FOR_LIMIT,
    NAME_LIMIT,
    NEEDED_INPUTS,
    OLD_NAMES,
    PURPOSE_LIMIT,
    WHAT_LIMIT,
    needed_kinds,
    with_needed_inputs,
)
from platform_api.builder.models import CardBlock, CardDefinition, CardInput, CardProblem
from platform_api.orchestration import INPUT_KINDS, RULES

NEW_AGENT_NAME: Final = "New agent"
NAMELESS: Final = {
    "github_repo": "GitHub repository",
    "jira_project": "Jira project",
    "text": "Detail",
}
PROJECT_IN: Final = re.compile(r"\b(?:project|in)\s+([A-Z][A-Z0-9_]{1,9})\b")
"""A Jira project key as a task names it, "project MOCK" or "in MOCK", as the Portal reads it."""


def _squashed(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.casefold())


TOOL_OF: Final = {_squashed(tool): tool for tool in RULES}
"""Each tool by its id less case and punctuation, so "Jira.Search" or "jira_search" is it."""


@dataclass(frozen=True)
class Repaired:
    """The card as code repaired it, and each step set aside because no tool does it yet, in
    the step's own words."""

    card: CardDefinition
    left_out: list[str]


@dataclass(frozen=True)
class TwoProjects:
    """A draft with an input for each of two or more projects the task names. An agent reads
    and writes in one, so which is the person's choice."""

    keys: list[str]


def one_project_only(keys: Sequence[str]) -> str:
    named = ", ".join(keys[:-1]) + f" and {keys[-1]}"
    return (
        f"An agent reads and writes in one Jira project, and your words name {named}. Say "
        "which one it should use."
    )


def repaired(card: CardDefinition, task: str) -> Repaired | TwoProjects:
    """The draft repaired where code can: its labels tidied, each tool id as the platform writes
    it, the one input each tool needs, and one input for each name. Two inputs for the Jira
    project become one when the task names one project or none, since the Portal fills them
    alike. When it names two, which one is the person's choice."""
    blocks, left_out = _steps(card.blocks)
    tidied = card.model_copy(update={"blocks": blocks, "inputs": [_tidied(i) for i in card.inputs]})
    inputs = with_needed_inputs(tidied).inputs
    needed = needed_kinds(blocks)
    for kind in needed:
        of_kind = [n for n, item in enumerate(inputs) if item.kind == kind]
        if len(of_kind) < 2:
            continue
        keys = list(dict.fromkeys(PROJECT_IN.findall(task)))
        if len(keys) > 1:
            return TwoProjects(keys)
        inputs = [
            NEEDED_INPUTS[kind] if n == of_kind[0] else item
            for n, item in enumerate(inputs)
            if n not in of_kind[1:]
        ]
    name = _name(card.name)
    return Repaired(
        card=tidied.model_copy(
            update={
                "name": name,
                "purpose": _cut(card.purpose, PURPOSE_LIMIT) or name,
                "good_for": _examples(card.good_for),
                "inputs": _named_once(inputs, needed),
            }
        ),
        left_out=left_out,
    )


def theirs_to_change(problem: CardProblem, task: str) -> bool:
    """Whether the problem is a word the person wrote, such as an old themed name in their task,
    which changing their words does fix."""
    found = OLD_NAMES.match(problem.message)
    return (
        found is not None
        and re.search(rf"\b{re.escape(found.group(0))}\b", task, re.IGNORECASE) is not None
    )


def _cut(text: str, limit: int) -> str:
    """The text on one line, cut at a word to the limit, with "…" where it was cut."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    head = flat[:limit]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head[: limit - 1]).rstrip(" ,.;:") + "…"


def _name(name: str) -> str:
    """The model's name, without an old themed name and cut to the limit, or "New agent"."""
    plain = _cut(" ".join(OLD_NAMES.sub(" ", name).split()), NAME_LIMIT)
    return plain[:1].upper() + plain[1:] if len(plain) >= 2 else NEW_AGENT_NAME


def _examples(good_for: Sequence[str]) -> list[str]:
    """The model's example requests, less those too long or with an old themed name."""
    lines = (" ".join(text.split()) for text in good_for)
    kept = [t for t in lines if t and len(t) <= GOOD_FOR_LIMIT and OLD_NAMES.search(t) is None]
    return kept[:GOOD_FOR_COUNT]


def _steps(blocks: Sequence[CardBlock]) -> tuple[list[CardBlock], list[str]]:
    """The steps with each tool id as the platform writes it, and the words of each step whose
    tool the platform doesn't have. A step with no words says its tool's name, or goes when it
    has no tool either."""
    kept: list[CardBlock] = []
    left_out: list[str] = []
    for block in blocks:
        say = " ".join(block.say.split())
        given = (block.tool or "").strip()
        tool = TOOL_OF.get(_squashed(given)) if given else None
        if given and tool is None:
            left_out.append(say.rstrip(" .") or given)
        elif tool is not None:
            kept.append(CardBlock(say=say or f"{RULES[tool].name}.", tool=tool))
        elif say:
            kept.append(CardBlock(say=say, tool=None))
    return kept, left_out


def _kind(given: str) -> str:
    """A kind the platform has: the model's own, or the one its words name, else text."""
    if given.strip() in INPUT_KINDS:
        return given.strip()
    squashed = _squashed(given)
    if "jira" in squashed or squashed in ("project", "projectkey"):
        return "jira_project"
    return "github_repo" if "github" in squashed or "repo" in squashed else "text"


def _tidied(item: CardInput) -> CardInput:
    kind = _kind(item.kind)
    example = " ".join(item.example.split())
    return CardInput(
        name=_cut(item.name, NAME_LIMIT) or NAMELESS[kind],
        kind=kind,
        what=_cut(item.what, WHAT_LIMIT),
        example=example if len(example) <= EXAMPLE_LIMIT else "",
    )


def _named_once(inputs: Sequence[CardInput], needed: Sequence[str]) -> list[CardInput]:
    """One input for each name, where it first stands: the one of a kind a tool needs, else the
    first."""
    kept: dict[str, CardInput] = {}
    for item in inputs:
        key = item.name.casefold()
        first = kept.get(key)
        if first is None or (item.kind in needed and first.kind not in needed):
            kept[key] = item
    return list(kept.values())
