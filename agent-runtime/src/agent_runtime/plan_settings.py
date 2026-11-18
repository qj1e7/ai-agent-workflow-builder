"""The settings of a drafted workflow, each marked by code, never by the model (ADR 0051, section
5). A setting is filled when code finds its value in the person's own words, as ADR 0049 locates a
tool's argument, guessed when the drafter picked it and the person can change it, and needed when
nobody has given it. A run time, a Jira project, and a channel or an address a notice posts to are
never guessed: each counts as filled only when code finds it in the words and in the team's facts,
and is needed otherwise. Plain code, with no model.

In an edit, a setting with the same id and kind as one in the current plan keeps its value and its
mark unless the new words give it a value."""

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Final

from agent_runtime.contract import (
    SETTING_ID_PATTERN,
    DrafterFacts,
    PlanProblem,
    PlanSetting,
    SettingKind,
    SettingMark,
    SettingPlace,
    WorkflowPlan,
)
from agent_runtime.planner_led import words_span
from agent_runtime.reading import when_said
from agent_runtime.workflow_plan import KIND_WORDS, ProposedSetting

MOST_SETTINGS: Final = 20
LABEL_LIMIT: Final = 80
NEVER_GUESSED_KINDS: Final[frozenset[SettingKind]] = frozenset(
    {"run_time", "jira_project", "channel", "address"}
)

type Located = Callable[[str, str], bool]


def settle(
    proposed: Sequence[ProposedSetting],
    places: Sequence[tuple[str, SettingPlace, SettingKind | None]],
    words: str,
    facts: DrafterFacts,
    current: WorkflowPlan | None,
) -> tuple[list[PlanSetting], list[PlanProblem]]:
    """Each setting with the parameters it fills and its mark, or every problem with them."""
    problems = shape_problems(proposed)
    by_id = {s.id: s for s in proposed}
    fills: dict[str, list[SettingPlace]] = {}
    for said, place, kind in places:
        setting = by_id.get(said)
        where = f'"{place.block}": {place.parameter} holds <<{said}>>'
        if setting is None:
            problems.append(
                PlanProblem(
                    code="setting",
                    block=place.block,
                    text=f"{where}, but the plan has no setting {said!r}. Add it.",
                )
            )
        elif kind is not None and setting.kind != kind:
            problems.append(
                PlanProblem(
                    code="setting",
                    block=place.block,
                    text=f"{where}, which is {KIND_WORDS[kind]}, so the setting {said!r} is of "
                    f"kind {kind}, not {setting.kind}.",
                )
            )
        fills.setdefault(said, []).append(place)
    problems += [
        PlanProblem(
            code="setting",
            text=f"The setting {s.id!r} stands in no parameter. Put <<{s.id}>> where its value "
            "goes, or leave the setting out.",
        )
        for s in by_id.values()
        if s.id not in fills
    ]
    if problems:
        return [], problems
    before = {(s.id, s.kind): s for s in (current.settings if current else [])}
    marked = [
        _marked(setting, fills[setting.id], words, facts, before.get((setting.id, setting.kind)))
        for setting in by_id.values()
    ]
    return marked, []


def shape_problems(proposed: Sequence[ProposedSetting]) -> list[PlanProblem]:
    """What is wrong with the settings themselves, before any is placed."""
    problems: list[PlanProblem] = []
    if len(proposed) > MOST_SETTINGS:
        problems.append(
            PlanProblem(code="setting", text=f"A plan has at most {MOST_SETTINGS} settings.")
        )
    seen: set[str] = set()
    for setting in proposed:
        if re.fullmatch(SETTING_ID_PATTERN, setting.id) is None:
            problems.append(
                PlanProblem(
                    code="setting",
                    text=f"The setting id {setting.id!r} must be lowercase letters, digits and _, "
                    "starting with a letter, at most 40 characters.",
                )
            )
        elif setting.id in seen:
            problems.append(PlanProblem(code="setting", text=f"Two settings are {setting.id!r}."))
        seen.add(setting.id)
        label = setting.label.strip()
        if not label or len(label) > LABEL_LIMIT or not label.isprintable():
            problems.append(
                PlanProblem(
                    code="setting",
                    text=f"The setting {setting.id!r} needs a label of 2 to 6 plain words.",
                )
            )
    return problems


def _marked(
    setting: ProposedSetting,
    fills: list[SettingPlace],
    words: str,
    facts: DrafterFacts,
    before: PlanSetting | None,
) -> PlanSetting:
    value, mark = _value_and_mark(setting, words, facts, before)
    return PlanSetting(
        id=setting.id,
        kind=setting.kind,
        label=" ".join(setting.label.split()),
        fills=fills,
        value=value,
        mark=mark,
    )


def _value_and_mark(
    setting: ProposedSetting, words: str, facts: DrafterFacts, before: PlanSetting | None
) -> tuple[str | None, SettingMark]:
    said = (setting.value or "").strip() or None
    if setting.kind == "run_time":
        # Only code's own reading of the words fills a run time, never the drafter's value.
        reading, tried = run_time_in(words, before.value if before else None)
        if reading is not None:
            return reading, "filled"
        if tried:
            # The words say when it runs, but not in a way a schedule holds whole. Ask, keeping
            # only a day they name whole, so the question asks only for what is missing. The
            # run time before is never kept for them.
            return day_in(words, before.value if before else None), "needed"
    else:
        found = found_in(setting.kind, said, words, facts)
        if found is not None:
            return found, "filled"
    if before is not None and before.value is not None:
        return before.value, before.mark
    if setting.kind not in NEVER_GUESSED_KINDS and said is not None:
        return said, "guessed"
    return None, "needed"


def run_time_in(words: str, before: str | None = None) -> tuple[str | None, bool]:
    """The run time the words name, as code reads it ("monday 09:00", "every_day 08:30"), by the
    same list of what a schedule holds as the card's schedule row, with the day or the time of
    `before` where the words don't name the other. The second value says whether the words say
    anything about when it runs. A day or a time they name that a schedule can't hold whole,
    as "every other Friday", "9am or so" or two days, is asked, so `before` never stands in
    for it."""
    said = when_said(words)
    old_day, _, old_at = (before or "").partition(" ")
    day = said.day or (None if said.day_asked else old_day or None)
    at = said.at or (None if said.time_asked else old_at or None)
    if day and at:
        return f"{day} {at}", said.said
    return None, said.said


def day_in(words: str, before: str | None = None) -> str | None:
    """The day the words name, as "monday", or the day `before` held when the words name none.
    A run time still needed keeps it as its value. A day the words name that a schedule can't
    hold whole gives none, so the question asks how often it runs."""
    said = when_said(words)
    if said.day_asked:
        return None
    return said.day or ((before or "").partition(" ")[0] or None)


def found_in(kind: SettingKind, said: str | None, words: str, facts: DrafterFacts) -> str | None:
    """The value code finds for a setting of this kind in the person's words: the drafter's value
    when the words hold it, else the one fact the words name. A kind that is never guessed must be
    in the team's facts too."""
    match kind:
        case "jira_project":
            return _one(facts.jira_projects, words, said, _names_project, strict=True)
        case "channel":
            return _one(facts.channels, words, said, _names_channel, strict=True)
        case "repository":
            return _one(facts.repositories, words, said, _names_it, strict=False)
        case "confluence_page":
            return _one(facts.confluence_pages, words, said, _names_it, strict=False)
        case "text":
            return _span_of(words, said) if said and words_span(words, said) else None
        case "address" | "run_time":
            # The platform has no list of addresses to find one in, and run times are read above.
            return None


def _one(
    known: Sequence[str], words: str, said: str | None, names: Located, strict: bool
) -> str | None:
    named = [fact for fact in known if names(words, fact)]
    if said is not None:
        same = [fact for fact in named if _same(fact, said)]
        if same:
            return same[0]
        if strict or not names(words, said):
            return None
        return _span_of(words, said)
    return named[0] if len(named) == 1 else None


def _same(a: str, b: str) -> bool:
    return a.lstrip("#").casefold() == b.lstrip("#").casefold()


def _names_project(words: str, key: str) -> bool:
    """Whether the words name the Jira project's key as written, as MOCK, never mock or MOCK-142."""
    return re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", words) is not None


def _names_channel(words: str, channel: str) -> bool:
    name = re.escape(channel.lstrip("#"))
    return (
        re.search(rf"(?<![\w#-])#{name}(?![\w-])", words, re.IGNORECASE) is not None
        or re.search(rf"(?<![\w#-]){name}\s+channel\b", words, re.IGNORECASE) is not None
    )


def _names_it(words: str, value: str) -> bool:
    return words_span(words, value) is not None


def _span_of(words: str, said: str) -> str:
    """The person's own spelling of what they said."""
    span = words_span(words, said)
    return said if span is None else words[span[0] : span[1]]


def kinds_marked(settings: Sequence[PlanSetting]) -> Mapping[SettingMark, list[SettingKind]]:
    """The kinds of the settings with each mark, for the eval and the tests."""
    marked: dict[SettingMark, list[SettingKind]] = {"filled": [], "guessed": [], "needed": []}
    for setting in settings:
        marked[setting.mark].append(setting.kind)
    return marked
