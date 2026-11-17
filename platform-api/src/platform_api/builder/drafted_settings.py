"""The settings of a drafted workflow, and the questions that fill them (ADR 0051, section 5).

Code, never a model, marks each setting, writes each question and reads each answer. A setting
is filled when code found it in the person's words or the person chose or typed it, guessed when
the drafter picked it and the person can change it, and needed while nobody has given it. The
drafter writes the plan's settings. The builder adds the two it never writes: who says yes on each
run to a write through our blocks, and the write key each of n8n's own blocks that writes needs.

Five kinds are never guessed: the run time, the Jira project, a channel or an address a notice
posts to, the Approvers and a write key. A place the class file names as where a notice posts,
written out in the plan, becomes a setting too, so nothing there stands as a guess.

Pure."""

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from platform_api.builder.versions import SCHEDULE_TYPE, schedule_words
from platform_api.orchestration import (
    NODE_CLASSES,
    TYPE_OF,
    Day,
    DrafterFacts,
    Off,
    OnType,
    PlanSetting,
    Runs,
    SettingKind,
    SettingMark,
    SettingPlace,
    WorkflowPlan,
)
from platform_api.shared import UserId

type Kind = SettingKind | Literal["approvers", "key"]
type How = Literal["words", "chose", "typed", "n8n"]
type Mark = SettingMark

APPROVERS: Final = "approvers"
ANY_APPROVER: Final = "Any Approver on the team"
"""The one choice the platform can keep for now: a use case can't name its Approvers until ADR
0024's names are built."""
KEY_PREFIX: Final = "key:"
PLACEHOLDER: Final = re.compile(r"<<([a-z][a-z0-9_]{0,39})>>")
CHOOSERS: Final = frozenset({"select"})
"""Target parameters that only pick which other one applies, as Slack's select picks a channel or
a user."""
TEXT_LIMIT: Final = 200

DAY_CHOICES: Final[tuple[tuple[Day, str], ...]] = (
    ("every_day", "Every day"),
    ("weekdays", "Weekdays"),
    ("monday", "Mondays"),
    ("friday", "Fridays"),
)
TIME_CHOICES: Final = ("08:00", "09:00", "13:00", "17:00")
DAYS_SAID: Final[Mapping[str, str]] = {
    "every_day": "Every day",
    "weekdays": "Weekdays",
    "monday": "Mondays",
    "tuesday": "Tuesdays",
    "wednesday": "Wednesdays",
    "thursday": "Thursdays",
    "friday": "Fridays",
    "saturday": "Saturdays",
    "sunday": "Sundays",
}
ORDER: Final[Mapping[Kind, int]] = {
    "run_time": 0,
    "jira_project": 1,
    "channel": 1,
    "address": 1,
    "repository": 1,
    "confluence_page": 1,
    "text": 2,
    "key": 3,
    "approvers": 4,
}
"""What the workflow can't start without first, then where it reads, writes and posts, then the
keys, then the Approvers."""
TYPE_A_TIME: Final = "Type a time"
TYPE_ONE: Final = "Type one"
KEYS_LATER: Final = "It needs a write key. Write keys come in a later step."
NO_CHANNEL: Final = (
    "The platform's Slack key can't see any channel yet, so there is nothing to pick. An "
    "Operator can check the Slack connection in Settings."
)
UNREAD: Final[Mapping[Kind, str]] = {
    "run_time": "I couldn't read a time in that. Try 7:45 or 6pm.",
    "jira_project": "That isn't one of the team's Jira projects.",
    "channel": "That isn't a Slack channel the platform's key can see.",
    "address": "That isn't an email address.",
    "repository": "Write the repository as owner/name, like langchain-ai/langgraph.",
    "confluence_page": "That isn't one of the team's Confluence pages.",
    "text": "Type a few words.",
    "approvers": "Pick one of the choices.",
    "key": KEYS_LATER,
}
NOT_A_CHOICE: Final = "Pick one of the choices."
PICK_THE_DAY: Final = "Pick how often it runs first."
_TIME: Final = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\s*$", re.IGNORECASE)
_RUN_TIME: Final = re.compile(r"^([a-z_]+) (\d{2}):(\d{2})$")
_REPOSITORY: Final = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_EMAIL: Final = re.compile(r"^[^@\s,;<>\"']{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


@dataclass(frozen=True)
class Source:
    """Where a filled value came from, and who gave it."""

    value: str
    how: How
    by: UserId | None


type Sources = Mapping[str, Source]


@dataclass(frozen=True)
class SettingNow:
    id: str
    kind: Kind
    label: str
    value: str | None
    """A run time is code's reading, as "monday 09:00". A run time still needed may hold only the
    day the words named. None while needed otherwise."""
    mark: Mark
    source: Source | None
    """How a filled value was given."""
    block: str | None = None
    """For the Approvers and a key: the block it is for, shown in quotes."""


@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True)
class Asking:
    key: str
    """The short words before the question, as When or Jira."""
    words: str
    choices: tuple[Choice, ...]
    typed: str | None
    """The words on the button that opens a box to type in, or None when typing isn't read."""
    waits: str | None
    """Why it can't be answered now. It then has no choices."""


@dataclass(frozen=True)
class Answered:
    value: str
    filled: bool
    """False for a run time that has its day but still needs its time."""


@dataclass(frozen=True)
class Unread:
    words: str


def key_id(block: str) -> str:
    return f"{KEY_PREFIX}{block}"


def settings_of(plan: WorkflowPlan, sources: Sources) -> tuple[SettingNow, ...]:
    """Every setting of the revision: the plan's, then a write key for each of n8n's own blocks
    that writes, then who says yes on each run to the writes through our blocks."""
    settings = [_from_plan(s, sources.get(s.id)) for s in plan.settings]
    for block in plan.blocks:
        if _writes_with_a_key(block.type, block.version, block.parameters):
            settings.append(
                SettingNow(
                    key_id(block.name), "key", "Write key for", None, "needed", None, block.name
                )
            )
    writes = [b.name for b in plan.blocks if b.type == TYPE_OF["write"]]
    if writes:
        given = sources.get(APPROVERS)
        filled = given is not None and given.value == ANY_APPROVER
        settings.append(
            SettingNow(
                APPROVERS,
                "approvers",
                "Who says yes on each run",
                ANY_APPROVER if filled else None,
                "filled" if filled else "needed",
                given if filled else None,
                writes[0] if len(writes) == 1 else None,
            )
        )
    return tuple(settings)


def _from_plan(setting: PlanSetting, given: Source | None) -> SettingNow:
    value, mark = setting.value, setting.mark
    if setting.kind == "run_time":
        reading = run_time_of(value)
        if reading is None:
            day = value if value in DAYS_SAID else None
            value, mark = day, "needed"
    if mark != "filled" or value is None:
        return SettingNow(setting.id, setting.kind, setting.label, value, mark, None)
    source = given if given is not None and given.value == value else Source(value, "words", None)
    return SettingNow(setting.id, setting.kind, setting.label, value, "filled", source)


def run_time_of(value: str | None) -> tuple[Day, str] | None:
    """Code's reading of a run time, "monday 09:00", as its day and time. None for anything
    else, such as the person's own words for one code couldn't read."""
    found = _RUN_TIME.match(value or "")
    if found is None or found.group(1) not in DAYS_SAID:
        return None
    hour, minute = int(found.group(2)), int(found.group(3))
    if hour > 23 or minute > 59:
        return None
    return cast(Day, found.group(1)), f"{hour:02d}:{minute:02d}"


def shown(setting: SettingNow) -> str | None:
    """The value as a person reads it: a run time as "every Monday at 9:00"."""
    if setting.value is None or setting.mark == "needed":
        return None
    if setting.kind == "run_time":
        reading = run_time_of(setting.value)
        return setting.value if reading is None else schedule_words(*reading)
    return setting.value


def next_question(settings: Sequence[SettingNow], facts: DrafterFacts) -> SettingNow | None:
    """The one question the card asks now: the first setting still needed, in the ADR's order,
    that can be answered now."""
    asked = [
        (ORDER[s.kind], index, s)
        for index, s in enumerate(settings)
        if s.mark == "needed" and asking(s, facts).waits is None
    ]
    return min(asked, key=lambda found: found[:2])[2] if asked else None


def asking(setting: SettingNow, facts: DrafterFacts) -> Asking:
    """The question for one setting, in code's fixed words for its kind, with 2 to 4 choices from
    the platform's own data where there are any. A guessed setting's Change offers the same."""
    match setting.kind:
        case "run_time":
            day = setting.value if setting.value in DAYS_SAID else None
            if day is None:
                choices = tuple(Choice(d, said) for d, said in DAY_CHOICES)
                return Asking("When", "How often should it run?", choices, None, None)
            times = tuple(Choice(t, _clock(t)) for t in TIME_CHOICES)
            return Asking("When", f"{DAYS_SAID[day]}, at what time?", times, TYPE_A_TIME, None)
        case "jira_project":
            return _pick("Jira", "Which Jira project should it use?", facts.jira_projects, False)
        case "channel":
            if not facts.channels:
                return Asking(
                    "Slack", "Which Slack channel should it post in?", (), None, NO_CHANNEL
                )
            return _pick("Slack", "Which Slack channel should it post in?", facts.channels, False)
        case "repository":
            return _pick(
                "GitHub", "Which GitHub repository should it read?", facts.repositories, True
            )
        case "confluence_page":
            return _pick(
                "Confluence", "Which Confluence page should it read?", facts.confluence_pages, False
            )
        case "address":
            return Asking("To", "Which email address should it send to?", (), TYPE_ONE, None)
        case "text":
            return Asking("Words", f"What should “{setting.label}” be?", (), TYPE_ONE, None)
        case "approvers":
            about = "its writes" if setting.block is None else f"“{setting.block}”"
            words = f"Who says yes to {about} on each run?"
            return Asking("Yes from", words, (Choice(ANY_APPROVER, ANY_APPROVER),), None, None)
        case "key":
            return Asking(
                "Key", f"Which write key should “{setting.block}” use?", (), None, KEYS_LATER
            )


def _pick(key: str, words: str, known: Sequence[str], typed_too: bool) -> Asking:
    """Up to four of the team's own, and a box to type in when there are more, or when any
    value of the right shape may do."""
    choices = tuple(Choice(v, v) for v in known[:4])
    typed = TYPE_ONE if typed_too or len(known) > len(choices) else None
    if not choices and typed is None:
        return Asking(key, words, (), None, NONE_TO_PICK)
    return Asking(key, words, choices, typed, None)


NONE_TO_PICK: Final = "The team has none to pick from yet, so it waits."


def _clock(at: str) -> str:
    hour, minute = at.split(":")
    return f"{int(hour)}:{minute}"


def read_answer(
    setting: SettingNow, facts: DrafterFacts, *, choice: str | None, typed: str | None
) -> Answered | Unread:
    """What a tapped choice or typed words give the setting. A choice must be one the question
    offers. Typed words are read by code, and words it reads nothing in come back unread."""
    question = asking(setting, facts)
    if question.waits is not None:
        return Unread(question.waits)
    if choice is not None:
        if choice not in {c.value for c in question.choices}:
            return Unread(NOT_A_CHOICE)
        return _given(setting, choice)
    if typed is None or question.typed is None:
        return Unread(NOT_A_CHOICE)
    read = typed_time(typed) if setting.kind == "run_time" else passes(setting.kind, typed, facts)
    return Unread(UNREAD[setting.kind]) if read is None else _given(setting, read)


def _given(setting: SettingNow, value: str) -> Answered:
    if setting.kind != "run_time":
        return Answered(value, True)
    if value in DAYS_SAID:
        return Answered(value, False)
    return Answered(f"{setting.value} {value}", True)


def passes(kind: Kind, typed: str, facts: DrafterFacts) -> str | None:
    """The value, as the platform writes it, when what a person gave passes the check for its
    kind, in the chat or in n8n: a project, a page or a channel the team's data holds, or a value
    of the right shape. None when it doesn't. A run time is read on its own."""
    typed = typed.strip()
    match kind:
        case "run_time":
            return typed if run_time_of(typed) is not None else None
        case "jira_project":
            return _one_of(facts.jira_projects, typed)
        case "channel":
            return _one_of(facts.channels, typed if typed.startswith("#") else f"#{typed}")
        case "confluence_page":
            return _one_of(facts.confluence_pages, typed)
        case "repository":
            return typed if _REPOSITORY.fullmatch(typed) else None
        case "address":
            return typed if _EMAIL.fullmatch(typed) else None
        case "text":
            return typed if 0 < len(typed) <= TEXT_LIMIT and typed.isprintable() else None
        case "approvers" | "key":
            return None


def _one_of(known: Sequence[str], typed: str) -> str | None:
    return next((k for k in known if k.casefold() == typed.casefold()), None)


def typed_time(typed: str) -> str | None:
    """A time typed as 7:45, 18:30 or 6pm, as "07:45". A bare hour, as 9, might be morning or
    evening, so it reads as nothing: a time is never guessed."""
    found = _TIME.match(typed)
    if found is None:
        return None
    hour, minute, half = int(found.group(1)), found.group(2), found.group(3)
    if minute is None and half is None:
        return None
    if half is not None:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if half.replace(".", "").lower() == "pm" else 0)
    at = int(minute or 0)
    if hour > 23 or at > 59:
        return None
    return f"{hour:02d}:{at:02d}"


def with_answer(plan: WorkflowPlan, setting_id: str, value: str, mark: Mark) -> WorkflowPlan:
    """The plan with one of its settings given this value and mark. The Approvers and keys are
    not the plan's, so the plan stays as it is for them."""
    settings = [
        s.model_copy(update={"value": value, "mark": mark}) if s.id == setting_id else s
        for s in plan.settings
    ]
    return plan.model_copy(update={"settings": settings})


def never_guessed(plan: WorkflowPlan) -> WorkflowPlan:
    """The plan with each place a notice of n8n's own posts to, as the class file names it, held
    by a setting. A place the drafter wrote out there becomes a setting still needed, in place of
    a guess. A place an expression picks is left to the checker, which flags it."""
    taken = {s.id for s in plan.settings}
    held = {(f.block, f.parameter) for s in plan.settings for f in s.fills}
    blocks: list[Any] = []
    added: list[PlanSetting] = []
    for block in plan.blocks:
        parameters = deepcopy(block.parameters)
        for path, kind in never_guessed_places(block.type, block.version, parameters):
            value = place_at(parameters, path)
            if not isinstance(value, str) or not value or value.startswith("="):
                continue
            if (block.name, path) in held or PLACEHOLDER.fullmatch(value):
                continue
            setting_id = free_id(kind, taken)
            taken.add(setting_id)
            put_at(parameters, path, f"<<{setting_id}>>")
            added.append(
                PlanSetting(
                    id=setting_id,
                    kind=kind,
                    label="Slack channel" if kind == "channel" else "Address",
                    fills=[SettingPlace(block=block.name, parameter=path)],
                    value=None,
                    mark="needed",
                )
            )
        blocks.append(block.model_copy(update={"parameters": parameters}))
    if not added:
        return plan
    return plan.model_copy(update={"blocks": blocks, "settings": [*plan.settings, *added]})


def never_guessed_places(
    node_type: str, version: object, parameters: Mapping[str, Any]
) -> list[tuple[str, SettingKind]]:
    """Each parameter where one of n8n's own notices posts, as the class file names it, by its
    full path, with the kind of setting it takes."""
    if node_type.startswith("CUSTOM.") or node_type == SCHEDULE_TYPE:
        return []
    verdict = NODE_CLASSES.verdict(node_type, version, parameters)
    if not isinstance(verdict, Runs) or verdict.on != "notice" or verdict.use is None:
        return []
    places: list[tuple[str, SettingKind]] = []
    for path in verdict.use.target:
        if path in CHOOSERS:
            continue
        value = place_at(parameters, path)
        full = f"{path}.value" if isinstance(value, dict) and "value" in value else path
        kind: SettingKind = "channel" if re.search("channel|team", path, re.I) else "address"
        places.append((full, kind))
    return places


def _writes_with_a_key(node_type: str, version: object, parameters: Mapping[str, Any]) -> bool:
    """One of n8n's own blocks for a system the class file knows, set to do what its class turns
    off: a write, which only a write key could make."""
    if node_type.startswith("CUSTOM."):
        return False
    entry = NODE_CLASSES.entry(node_type)
    if not isinstance(entry, OnType) or not entry.uses:
        return False
    verdict = NODE_CLASSES.verdict(node_type, version, parameters)
    return isinstance(verdict, Off) and verdict.because == "operation"


def free_id(kind: SettingKind, taken: set[str]) -> str:
    number = 1
    while f"{kind}_{number}" in taken:
        number += 1
    return f"{kind}_{number}"


def place_at(parameters: Mapping[str, Any], path: str) -> Any:
    value: Any = parameters
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = cast(Mapping[str, Any], value).get(part)
    return value


def put_at(parameters: dict[str, Any], path: str, value: Any) -> None:
    *parents, last = path.split(".")
    held: dict[str, Any] | None = parameters
    for part in parents:
        inner: object = None if held is None else held.get(part)
        held = cast(dict[str, Any], inner) if isinstance(inner, dict) else None
    if held is not None:
        held[last] = value
