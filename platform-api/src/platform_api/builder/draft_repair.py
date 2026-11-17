"""Repairs a card the model drafted, before check_card, so a draft never stops at a problem the
person's words can't fix.

Pure. Code tidies only what is a label or an example, puts in place the one input each tool
needs, and sets aside a step it has no tool for as a part left out. It never cuts a step's
words, fills in a value or picks between two projects the words name. What it can't repair,
check_card still flags, and the Planner says how to go on.
"""

import re
from collections.abc import Collection, Sequence
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
    names_kind,
    needed_kinds,
    with_needed_inputs,
)
from platform_api.builder.models import (
    CardApprovalView,
    CardBlock,
    CardDefinition,
    CardInput,
    CardProblem,
)
from platform_api.orchestration import INPUT_KINDS, RULES

NEW_AGENT_NAME: Final = "New agent"
NAMELESS: Final = {
    "github_repo": "GitHub repository",
    "jira_project": "Jira project",
    "text": "Detail",
}
KIND_OF: Final = {
    "jiraproject": "jira_project",
    "jiraprojectkey": "jira_project",
    "jirakey": "jira_project",
    "project": "jira_project",
    "projectkey": "jira_project",
    "githubrepo": "github_repo",
    "githubrepository": "github_repo",
    "repo": "github_repo",
    "repository": "github_repo",
}
"""The kinds a model writes for one the platform has, by the whole name less case and
punctuation. A kind such as jira_user or report_format is none of them, so it is text."""


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


KEY_SHAPED: Final = re.compile(r"(?<![\w-])[A-Za-z][A-Za-z0-9_]{1,9}(?!\w)")
NOT_PROJECTS: Final = _words(
    "AM PM SGT UTC GMT BST CET CEST EST EDT CST CDT PST PDT IST JST HKT AEST AEDT "
    "PDF CSV JSON XML HTML TXT PNG JPG XLSX DOCX PPTX "
    "AI API CI CD DM HR ID IT KPI MR NCS PR QA SLA SQL SSO UI URL UX VPN "
    "JIRA GITHUB GITLAB SLACK TEAMS CONFLUENCE ENTRA N8N "
    "MON TUE WED THU FRI SAT SUN JAN FEB MAR APR JUN JUL AUG SEP SEPT OCT NOV DEC "
    "ALL AND ANY ASAP BUT EOD EOW FYI NEW NO NOT NOW OK OLD ONE ONLY OR THE TBC TBD TODO "
    "URGENT YES P0 P1 P2 P3 P4"
)
"""Words in capitals that name no Jira project: time zones, file types, systems, days, months and
common words a person types in capitals."""


def _squashed(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


TOOL_OF: Final = {_squashed(tool): tool for tool in RULES}
"""Each tool by its id less case and punctuation, so "Jira.Search" or "jira_search" is it. Digits
stay, so "jira.create_ticket2" is no tool."""
assert len(TOOL_OF) == len(RULES), "two tool ids are one less case and punctuation"


@dataclass(frozen=True)
class Repaired:
    """The card as code repaired it, and each step set aside because no tool does it yet, in
    the step's own words."""

    card: CardDefinition
    left_out: list[str]


@dataclass(frozen=True)
class TwoProjects:
    """A Jira card for a task that names two or more projects. An agent reads and writes in one,
    so which is the person's choice."""

    keys: list[str]


@dataclass(frozen=True)
class TwoProjectInputs:
    """A Jira card the model drafted with an input for each of two projects, for a task that
    names none. Joining them would decide for the person that they are one."""

    names: list[str]


@dataclass(frozen=True)
class NotUsable:
    """A draft code can't repair without changing what it asks for, as an approval for a tool
    no step can be read as."""

    why: str


def _and_list(items: Sequence[str]) -> str:
    return ", ".join(items[:-1]) + f" and {items[-1]}" if len(items) > 1 else "".join(items)


def one_project_only(keys: Sequence[str]) -> str:
    return (
        f"An agent reads and writes in one Jira project, and your words name {_and_list(keys)}. "
        "Say which one it should use."
    )


def one_project_input(names: Sequence[str]) -> str:
    quoted = _and_list([f'"{name}"' for name in names])
    return (
        f"An agent reads and writes in one Jira project, but this one was drafted with {quoted}. "
        "Say in your words which project it should use."
    )


def projects_named(task: str, known: Collection[str] = ()) -> list[str]:
    """Each Jira project the task names, once, in the order it names them: a key in capitals,
    such as MOCK or MOCK in MOCK-14, and a key the team's Jira allows in any case, such as
    "mock". A word in capitals that is no project, such as SGT or PDF, is not one."""
    allowed = {key.upper() for key in known}
    found: list[str] = []
    for match in KEY_SHAPED.finditer(task):
        word = match.group(0)
        key = word.upper()
        if key in allowed or (word == key and key not in NOT_PROJECTS):
            found.append(key)
    return list(dict.fromkeys(found))


def repaired(
    card: CardDefinition, task: str, known: Collection[str] = ()
) -> Repaired | TwoProjects | TwoProjectInputs | NotUsable:
    """The draft repaired where code can: its labels tidied, each tool id as the platform writes
    it, approvals and all, the one input each tool needs, and one input for each name.

    A Jira card is checked against the task's words before any input is joined or renamed. Two
    projects named is the person's choice, as is one project for two inputs when the words name
    none. Two inputs become one only when the words name one project, since the Portal fills
    both with it."""
    blocks, left_out, unknown = _steps(card.blocks)
    approvals = _approvals(card.approvals, unknown)
    if isinstance(approvals, NotUsable):
        return approvals
    inputs = [_tidied(i) for i in card.inputs]
    needed = needed_kinds(blocks)
    if "jira_project" in needed:
        keys = projects_named(task, known)
        if len(keys) > 1:
            return TwoProjects(keys)
        named = [
            i.name for i in inputs if i.kind == "jira_project" or names_kind(i, "jira_project")
        ]
        if len(named) > 1 and not keys:
            return TwoProjectInputs(named)
    tidied = card.model_copy(update={"blocks": blocks, "inputs": inputs, "approvals": approvals})
    inputs = with_needed_inputs(tidied).inputs
    for kind in needed:
        of_kind = [n for n, item in enumerate(inputs) if item.kind == kind]
        if len(of_kind) > 1:
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


def _steps(blocks: Sequence[CardBlock]) -> tuple[list[CardBlock], list[str], set[str]]:
    """The steps with each tool id as the platform writes it, the words of each step whose tool
    the platform doesn't have, and those tools less case and punctuation. A step with no words
    says its tool's name, or goes when it has no tool either."""
    kept: list[CardBlock] = []
    left_out: list[str] = []
    unknown: set[str] = set()
    for block in blocks:
        say = " ".join(block.say.split())
        given = (block.tool or "").strip()
        tool = TOOL_OF.get(_squashed(given)) if given else None
        if given and tool is None:
            unknown.add(_squashed(given))
            left_out.append(say.rstrip(" .") or f'A step with no words, for "{given}"')
        elif tool is not None:
            kept.append(CardBlock(say=say or f"{RULES[tool].name}.", tool=tool))
        elif say:
            kept.append(CardBlock(say=say, tool=None))
    return kept, left_out, unknown


def _approvals(
    approvals: Sequence[CardApprovalView], unknown: set[str]
) -> list[CardApprovalView] | NotUsable:
    """Each approval with its tool id written as the steps' are, and its count as the model gave
    it, so a count is never lowered. An approval for a step set aside goes with it. One for a
    tool no step names in any way, or two that are one tool written two ways, can't be read for
    sure."""
    kept: dict[str, tuple[str, CardApprovalView]] = {}
    for approval in approvals:
        given = approval.tool.strip()
        tool = TOOL_OF.get(_squashed(given))
        if tool is None:
            if _squashed(given) in unknown:
                continue
            return NotUsable(f"an approval names {given!r}, which is no tool")
        first = kept.get(tool)
        if first is not None and first[0] != given:
            return NotUsable(f"two approvals name {tool}")
        approvers = max(approval.approvers, first[1].approvers if first else 0)
        kept[tool] = (given, CardApprovalView(tool=tool, approvers=approvers))
    return [approval for _, approval in kept.values()]


def _kind(given: str) -> str:
    """A kind the platform has: the model's own, or the one its whole name means, else text."""
    if given.strip() in INPUT_KINDS:
        return given.strip()
    return KIND_OF.get(_squashed(given), "text")


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
