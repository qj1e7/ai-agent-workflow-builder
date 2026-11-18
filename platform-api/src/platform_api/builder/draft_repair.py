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


KEY: Final = r"[A-Za-z][A-Za-z0-9_]{1,9}"
LEAD: Final = re.compile(
    rf"(?<![\w-])(?:[Pp]rojects?|[Ii]n|[Ii]nto|[Ff]rom|[Tt]o)\s+"
    rf"(?P<lead>(?:(?:[Tt]he|[Jj]ira|[Pp]rojects?)\s+)*)(?P<keys>{KEY}(?:\s*(?:,|and|or|&)\s*{KEY})*)"
    r"(?!\w)"
)
"""A key where a project stands: after "project", "in", "into", "from" or "to", as "in MOCK",
"from MOCK to OPS" or "in projects MOCK and OPS". "IN" in capitals is no lead, so "status IN
PROGRESS" names no project."""
BEFORE_A_PROJECT_WORD: Final = re.compile(
    r"(?<![\w-])(?P<key>[A-Z][A-Z0-9_]{1,9})(?:-\d+\b|\s+(?:tickets?|issues?|board|backlog|"
    r"project)\b)"
)
"""A key before a ticket number or a ticket word, as "MOCK-14" or "the MOCK tickets"."""
IN_A_LINK: Final = re.compile(rf"/(?:browse|projects)/(?P<key>{KEY})(?:-\d+)?(?![\w])")
"""A key in a Jira link, as /browse/MOCK-12 or /projects/mock/issues."""
NEVER_PROJECTS: Final = _words(
    "AM PM SGT UTC GMT BST CET CEST EST EDT CST CDT PST PDT IST JST HKT AEST AEDT "
    "PDF CSV JSON XML HTML TXT PNG JPG XLSX DOCX PPTX "
    "ALL ANY EACH EVERY BOTH THE "
    "DONE TODO OPEN CLOSED RESOLVED BLOCKED BACKLOG PROGRESS "
    "Q1 Q2 Q3 Q4 UAT PROD DEV SIT STAGING L1 L2 L3"
)
"""Words that stand where a project could and name none: a time zone, a file type, a word such as
ALL, or a ticket status, as "in SGT", "to PDF" or "moved to DONE"."""
NOT_PROJECTS: Final = NEVER_PROJECTS | _words(
    "AI API CI CD DM HR ID IT KPI MR NCS PR QA SLA SQL SSO UI URL UX VPN "
    "CVE EOL LTS SRE NPS BUG BUGS NOTE ISO RFC SHA UTF HTTP HTTPS COVID "
    "JIRA GITHUB GITLAB SLACK TEAMS CONFLUENCE ENTRA N8N "
    "ASAP EOD EOW FYI NEW NO NOT NOW OK OLD ONE ONLY OR TBC TBD URGENT YES P0 P1 P2 P3 P4 "
    "HIGH LOW MEDIUM CRITICAL MAJOR MINOR"
)
"""Capital words before a ticket number or a ticket word that name no project, as CVE-2024-3094
or "the BUG tickets". After "in" or "project", IT, HR and QA are projects."""
PLAIN_WORDS: Final = _words(
    "the a an me us you him her them it this that these those my our your their its each every "
    "all any some for of with about from to into in on at by and or which what where when there "
    "here jira teams slack confluence github gitlab email chat time order case progress review "
    "detail line full general short summary list table team channel backlog board status update "
    "updates management page name lead manager owner plan today tomorrow week month year day "
    "morning afternoon evening night english bulk advance addition total place front mind "
    "january february march april may june july august september october november december"
)
"""Words in small letters that follow "in", "to" or "project" and name no project, as "in the
backlog", "to me" or "project status"."""


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
    project: str | None = None
    """The one Jira project the task's words name, for a card that uses a Jira tool."""


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
    """Each Jira project the task names, once, in the order it names them. A key counts where a
    project stands: in capitals after "project", "in", "into", "from" or "to"; in any case after
    the word "project" or when the team's Jira allows it; in capitals before a ticket number or
    a ticket word; and in a Jira link. A project the team's Jira allows counts in capitals
    anywhere. A status, a time zone or a word such as CVE is never one."""
    allowed = {key.upper() for key in known}
    found: list[tuple[int, str]] = []
    for match in LEAD.finditer(task):
        named = "project" in match.group("lead").casefold()
        keys = [k for k in re.finditer(KEY, match.group("keys")) if k.group(0) not in ("and", "or")]
        for n, key in enumerate(keys):
            word = key.group(0)
            upper = word.upper()
            # The first key may be in small letters after "project". One after "and" or a comma
            # is a project only in capitals, as "projects MOCK and OPS", so "and raise" is not.
            small = named and word.casefold() not in PLAIN_WORDS
            first = n == 0 and (word == upper or small) and upper not in NEVER_PROJECTS
            listed = n > 0 and word == upper and upper not in NOT_PROJECTS
            if upper in allowed or first or listed:
                found.append((match.start("keys") + key.start(), upper))
    for match in BEFORE_A_PROJECT_WORD.finditer(task):
        if match.group("key") not in NOT_PROJECTS or match.group("key") in allowed:
            found.append((match.start(), match.group("key")))
    for match in IN_A_LINK.finditer(task):
        found.append((match.start("key"), match.group("key").upper()))
    for match in re.finditer(rf"(?<![\w-]){KEY}(?!\w)", task):
        if match.group(0) in allowed:
            found.append((match.start(), match.group(0)))
    return list(dict.fromkeys(key for _, key in sorted(found)))


ELSEWHERE: Final = re.compile(
    r"\b(?:elsewhere|somewhere\s+else|(?:different|another|other|separate)\s+(?:jira\s+)?"
    r"(?:project|board|queue|place|team))\b",
    re.IGNORECASE,
)
"""Words that send the ticket away from the project named, as "elsewhere" or "a different
project", so the project is never filled for it."""
PLACE_WORD: Final = re.compile(r"\s+(?:projects?|board|queue|space|team)\b", re.IGNORECASE)
BEFORE_THE_PLACE: Final = (
    r"tickets?|issues?|bugs?|tasks?|stor(?:y|ies)|epics?|items?|incidents?|requests?|problems?|"
    r"changes?|ones?|it|them|everything|anything|all|work|raised?|created?|filed?|logged?|"
    r"opened?|open|closed?|finished|resolved?|done|updated?|found|find|listed?|put|added?|made|"
    r"make|posted?|moved?|stale|idle|new|old|latest"
)
"""The words that may stand right before "in", "into" or "from" when the project after it is
the place the words name, as "tickets" in "tickets in MOCK" or "finished" in "the tickets we
finished in MOCK". Any other, as "not" or "except", leaves the place unsure."""
THE_PLACE: Final = (
    rf"(?:^|(?<=[,.;:!?(])\s*|\b(?:{BEFORE_THE_PLACE})\s+)(?:in|into|from)\s+"
    r"(?:(?:the|jira|projects?)\s+)*(?P<key>{key})\b",
    r"(?:^|(?<=[,.;:!?(])\s*)(?:the\s+)?(?:jira\s+)?project\s+(?P<key>{key})\b",
    r"(?:^|(?<=[,.;:!?(])\s*|\b(?:the|all|any|open|stale|idle|new|old|our|my|each|every|find|"
    r"list|check|raise|get|show|read|search|sum\s+up|summarise|summarize)\s+)"
    r"(?P<key>{key})\s+(?:tickets?|issues?|bugs?|project|board|backlog)\b",
)
"""Where the words name the project as the place: after "in", "into" or "from" that follows a
ticket word, as "tickets in MOCK"; after "project" at a clause's start, as "Where it goes: Jira
project MOCK"; or before a ticket word, as "the MOCK tickets". Each mention of the project must
stand so, never inside a negation such as "not in MOCK" or "anywhere but MOCK"."""
A_PLACE_LEAD: Final = re.compile(
    r"(?<![\w-])(?:in|into|to|from|on|onto|under|for|with|at|inside|within|via|outside|beyond)\s+"
    r"(?:(?:the|a|an|our|my|your|their|its|this|that|these|those|jira|projects?)\s+)*"
    r"(?P<word>[^\W\d_][\w-]*)",
    re.IGNORECASE,
)
"""A word where another place could stand: after a word such as "in", "for", "with" or "on"."""
NO_PLACE: Final = PLAIN_WORDS | _words(
    "new latest last next no none nobody every each all any both other same status priority "
    "label labels assignee approval approvals approver approvers release releases version "
    "versions software update ticket tickets issue issues bug bugs it them me us one two three "
    "four five six seven eight nine ten days weeks hours minutes monday tuesday wednesday "
    "thursday friday saturday sunday mondays tuesdays wednesdays thursdays fridays saturdays "
    "sundays weekday weekdays weekend weekends noon midday midnight end start beginning close "
    "least most details link links comment comments sprint"
)
"""Words in small letters after "in", "for", "with", "on" and the like that name no place, as
"each" in "for each release" or "status" in "with status DONE". Any other word there may be a
place, as "ops" in "for ops" or "service" in "with the service desk", so the project is asked."""


def project_to_fill(task: str, known: Collection[str] = ()) -> str | None:
    """The one Jira project to fill the agent's project input with, or None so the Portal asks.
    It decides where the ticket is written, so it is read narrowly, from a list of what is
    allowed: the one project the words name must be one the team's Jira allows, and every
    mention of it must name it as the place, as "tickets in MOCK", never inside a negation such
    as "not in MOCK". It is filled only when it is the one place the words name: every word after
    "in", "for", "with", "on" and the like must be one that names no place, so "for ops" or
    "with the service desk" leaves it unsure, and so does another key anywhere, as "for OPS", or
    "elsewhere". With no list of the team's projects, nothing is filled."""
    allowed = {k.upper() for k in known}
    keys = projects_named(task, known)
    if len(keys) != 1 or keys[0] not in allowed or ELSEWHERE.search(task):
        return None
    key = keys[0]
    frames = [re.compile(frame.format(key=re.escape(key)), re.IGNORECASE) for frame in THE_PLACE]
    placed = {m.start("key") for frame in frames for m in frame.finditer(task)}
    mentions = [m.start() for m in re.finditer(rf"(?<![\w-]){re.escape(key)}(?![\w-])", task, re.I)]
    if not mentions or any(at not in placed for at in mentions):
        return None
    for match in A_PLACE_LEAD.finditer(task):
        word = match.group("word")
        if word.upper() == key or word.casefold() in NO_PLACE or word.upper() in NOT_PROJECTS:
            continue
        return None
    for match in re.finditer(rf"(?<![\w-]){KEY}(?!\w)", task):
        # Another place anywhere: a key in capitals, a project the team allows in any case, or a
        # word before "project" or "board". The ticket may go there, so the Portal asks.
        word = match.group(0)
        upper = word.upper()
        if upper == key:
            continue
        before_a_place = PLACE_WORD.match(task, match.end()) and word.casefold() not in PLAIN_WORDS
        if (word == upper and upper not in NOT_PROJECTS) or upper in allowed or before_a_place:
            return None
    return key


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
    keys: list[str] = []
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
        project=project_to_fill(task, known) if "jira_project" in needed else None,
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
