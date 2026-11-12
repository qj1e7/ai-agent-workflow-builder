"""A change to a workflow the person already has, asked for in the chat (plan 4.2, spec 6.4, 6.7).

Commands fail closed. Code takes the question's own words and the workflows' names out of the
request, and a change word left over makes it a command, never a status answer. A schedule word
inside a workflow's own name is neither. In this first version an edit changes only when a
workflow runs: any other change, and a frequency the schedule can't hold, comes back as what the
chat can't do yet. The answer only proposes. Nothing changes until the person saves it.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from agent_runtime.abilities import change_verbs_in, commands_a_change, words
from agent_runtime.contract import (
    EditAnswer,
    EditCant,
    PartMark,
    PartReason,
    PlannerFacts,
    ScheduleChange,
    WatchDay,
)
from agent_runtime.planner import visible_words, whole_word_of
from agent_runtime.reading import (
    DAY_NAMES,
    FILLER,
    FREQUENCY,
    OFTEN,
    SCHEDULE_VOCAB,
    Clash,
    TaskRead,
    clashes_in,
    clauses_of,
    said_schedule,
)

type Span = tuple[int, int]

QUESTION_START: Final = re.compile(
    r"^(?:which|what|what's|how|is|are|do|does|did|when|why|who|whose|has|have|any|anything)\b",
    re.IGNORECASE,
)
STATE_WORDS: Final = re.compile(
    r"\b(?:workflows?|running|runs?\s+next|next\s+run|stopped|stop|failed|fail|broke|broken|"
    r"wrong|paused|status|doing|going|waiting|attention|approv\w*|decided|decisions?|"
    r"declined?|behind|up\s+to\s+date|versions?|software|watchlist|watching|watched|latest|"
    r"newest|releases?|needs?\s+(?:me|my)|for\s+me|on\s+me)\b",
    re.IGNORECASE,
)
"""Words that ask about the person's workflows, approvals or software."""
ASKING_VERBS: Final = re.compile(
    r"\b(?:run|runs|running|ran|start|starts|started|starting|stops?|stopping)\b", re.IGNORECASE
)
"""Verbs a question uses about a workflow's state, as "when does it run" or "why did it stop"."""
ORDER_LEAD: Final = re.compile(
    r"^(?:please\s+)?(?:can|could|would|will)\s+you\b|^please\b", re.IGNORECASE
)
"""A clause that opens like this asks for something to be done, whatever its question mark."""
LANE_BLOCKERS: Final = re.compile(
    r"\b(?:stop\s+watching|unwatch(?:ing)?|stop\s+tracking)\b", re.IGNORECASE
)
"""Changes that `change_verbs_in` misses. They stay out of it because it feeds other answers."""

SCHEDULE_VERBS: Final = words("make change switch move set reschedule shift run start update edit")
"""Verbs that change when a workflow runs, as "make it run on Mondays"."""
OTHER_CHANGES: Final = words(
    "pause resume unpause stop restart delete remove rename turn cancel disable enable retry rerun"
)
"""Verbs that change a workflow some other way, which the chat can't do yet."""
EDIT_VERBS: Final = SCHEDULE_VERBS | OTHER_CHANGES
HOW_OFTEN_WORDS: Final = words("week weekly")
CANT_HOLD: Final = frozenset({"month", "quarter", "year", "fortnight", "hour"})
EVERY_SO_OFTEN: Final = re.compile(
    r"\bevery\s+(?:other|second|third|\d+|two|three|four|five|six)\s+"
    r"(?:days?|weeks?|months?|hours?|monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b",
    re.IGNORECASE,
)
"""A frequency the schedule can't hold, as "every other day" or "every 2 weeks"."""
NOT_AN_EDIT: Final = re.compile(
    r"\b(?:watch|watching|track|tracking|monitor|monitoring|keep\s+(?:track|an\s+eye|tabs))\b",
    re.IGNORECASE,
)
"""A watch request goes to the Software watchlist's answers, not to the edit."""
NEW_WORKFLOW: Final = re.compile(
    r"^(?:(?:and|then|also|please)\s+)*(?:(?:can|could|would|will)\s+you\s+)?set\s+up\s+"
    r"(?:a|an|another|one|some|new)\b",
    re.IGNORECASE,
)
"""A clause that asks for a new workflow. It changes nothing that exists, so it is a task beside
a question, never a command on one."""
REFERENCE: Final = re.compile(
    r"\b(?:the|my|our|that|this)\s+((?:[\w.+'’-]+\s+){1,4})"
    r"(?:checks?|summary|summaries|workflow|review|report|list|one)\b|"
    r"\bthe\s+(?:software\s+)?watchlist\b",
    re.IGNORECASE,
)
"""A short form of a workflow's name, as "the morning check", "the React check" or "the weekly
one"."""
ARTICLE: Final = re.compile(r"^(?:the|my|our|that|this|a|an)\s+", re.IGNORECASE)
INSTEAD: Final = re.compile(
    r"\b(?:instead\s+of|rather\s+than)\b[^,.;!?]*|\bfrom\b[^,.;!?]*?(?=\bto\b)", re.IGNORECASE
)
"""The schedule it runs on now, as "instead of every Friday" or "from Mondays to"."""
TOKEN: Final = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")
TIME: Final = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b|\bat\s+\d{1,2}\b|"
    r"\b(?:noon|midday|midnight)\b",
    re.IGNORECASE,
)
EDIT_WORDS: Final = FILLER | SCHEDULE_VOCAB | EDIT_VERBS | words("runs only instead rather than")
"""Words a clause that changes a schedule may hold beside the workflow's name and the schedule."""
STATE_KINDS: Final = ("my_workflows", "why_stopped", "needs_me")


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0).casefold(), m.start(), m.end()) for m in TOKEN.finditer(text)]


def _blank(text: str, spans: Iterable[Span]) -> str:
    """The text with each span turned to spaces, so every other word keeps its place."""
    out = list(text)
    for start, end in spans:
        out[start:end] = " " * (end - start)
    return "".join(out)


def asks(text: str, clause: Span) -> bool:
    """Whether the clause asks a question: it opens like one, or ends at a question mark, and it
    doesn't open by asking for something to be done, as "can you pause it?"."""
    words_ = text[clause[0] : clause[1]]
    if ORDER_LEAD.match(words_):
        return False
    return bool(QUESTION_START.match(words_) or re.match(r"\s*\?", text[clause[1] :]))


def _names(read: TaskRead | None, text: str, facts: PlannerFacts | None) -> list[Span]:
    """Where the request names a workflow or a watched software: the reading's words for one,
    each workflow's whole name or a run of two or more of its words, and a short form such as
    "the morning check"."""
    found: list[Span] = [m.span() for m in REFERENCE.finditer(text)]
    said = _said(read.workflow_words if read is not None else None, text)
    if said is not None:
        found.append(said)
    workflows = facts.workflows if facts is not None else None
    for name in [w.name for w in workflows or []]:
        found += _name_runs(text, name)
    for name in [w.name for w in (facts.watchlist if facts is not None else None) or []]:
        at = _whole(text, name)
        if at is not None:
            found.append(at)
    return found


def _whole(text: str, words_: str) -> Span | None:
    wanted = visible_words(words_)
    if not wanted:
        return None
    found = re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", text, re.IGNORECASE)
    return None if found is None else found.span()


def _said(words_: str | None, text: str) -> Span | None:
    """Where the request writes the reading's words for a workflow, articles aside."""
    wanted = ARTICLE.sub("", visible_words(words_))
    return _whole(text, wanted) if wanted else None


def _name_runs(text: str, name: str) -> list[Span]:
    """The stretches of the request made of a workflow's own words: its whole name, or two or more
    of its words in a row, as "weekly summary" for "Weekly closed-ticket summary"."""
    whole = _whole(text, name)
    if whole is not None:
        return [whole]
    own = {w for w, _, _ in _tokens(name)}
    runs: list[Span] = []
    run: list[tuple[str, int, int]] = []
    for token in [*_tokens(text), ("", len(text), len(text))]:
        if token[0] in own:
            run.append(token)
            continue
        if len(run) >= 2:
            runs.append((run[0][1], run[-1][2]))
        run = []
    return runs


def _without_questions(text: str, rest: str) -> str:
    """`rest` with the question's own words taken out of each clause that asks one."""
    out = rest
    for clause in clauses_of(text):
        if not asks(text, clause):
            continue
        part = out[clause[0] : clause[1]]
        for pattern in (QUESTION_START, STATE_WORDS, ASKING_VERBS):
            part = pattern.sub(lambda m: " " * len(m.group(0)), part)
        out = out[: clause[0]] + part + out[clause[1] :]
    return out


def _new_workflows(text: str) -> list[Span]:
    return [c for c in clauses_of(text) if NEW_WORKFLOW.match(text[c[0] : c[1]])]


def _left(text: str, names: list[Span]) -> str:
    """The request with the names, the new workflows asked for and the questions' own words
    taken out: what is left to be a command."""
    return _without_questions(text, _blank(text, names + _new_workflows(text)))


def _edit_words(rest: str) -> bool:
    """A verb that changes a workflow, as "make", "pause" or "rename". A schedule beside a
    question with no such verb, as "every Friday sum up the closed tickets", is a new task."""
    tokens = [w for w, _, _ in _tokens(rest)]
    return any(
        w in EDIT_VERBS and not (w == "make" and tokens[at + 1 : at + 2] == ["sure"])
        for at, w in enumerate(tokens)
    )


def left_over(read: TaskRead | None, text: str, facts: PlannerFacts | None) -> str:
    """The request with the names, the new workflows asked for and the questions' own words taken
    out, each turned to spaces: what is left to be a command."""
    return _left(text, _names(read, text, facts))


def commanded(read: TaskRead | None, text: str, facts: PlannerFacts | None) -> bool:
    """Whether a change word is left once the question's own words and the names are out: a
    write, or a change to a workflow. The question lane stays closed to it."""
    rest = left_over(read, text, facts)
    return bool(
        change_verbs_in(rest)
        or commands_a_change(rest)
        or LANE_BLOCKERS.search(rest)
        or _edit_words(rest)
    )


def edit_of(read: TaskRead, text: str, facts: PlannerFacts | None) -> EditAnswer | None:
    """The edit a request asks for, or None. The reading calls it a change; or it asks about
    the person's workflows and a change word is left over, which fails closed to the edit; or an
    order to change one stands beside a workflow the person has, whatever the reading said."""
    names = _names(read, text, facts)
    if NOT_AN_EDIT.search(_blank(text, names)):
        return None
    rest = _left(text, names)
    if read.asks_about != "change":
        if not _edit_words(rest):
            return None
        if read.asks_about not in STATE_KINDS and not _orders_one(read, text, facts):
            return None
    target = _target(read, text, facts)
    schedule, cant, clashes = _schedule_of(text, names)
    return EditAnswer(
        workflow_words=target,
        software=_software(read, text, target),
        schedule=schedule,
        cant=cant,
        holds_save=bool(clashes) and cant is None,
    )


def _orders_one(read: TaskRead, text: str, facts: PlannerFacts | None) -> bool:
    """Whether a clause orders a change with a verb and names one of the person's workflows, the
    workflow the reading named, or a software's check, as "make the React check run daily"."""
    named = [s for s in [_said(read.workflow_words, text)] if s is not None]
    for name in [w.name for w in (facts.workflows if facts is not None else None) or []]:
        named += _name_runs(text, name)
    software = whole_word_of(text, read.software)
    named += [
        m.span()
        for m in REFERENCE.finditer(text)
        if software is not None and whole_word_of(m.group(0), software) is not None
    ]
    left = _blank(text, named)
    return any(
        any(start <= a < end for a, _ in named)
        and any(w in EDIT_VERBS for w, _, _ in _tokens(left[start:end]))
        for start, end in clauses_of(text)
    )


def _target(read: TaskRead, text: str, facts: PlannerFacts | None) -> str | None:
    """The words that name the workflow to change, as the request wrote them: the reading's,
    else one of the person's workflow names or a run of its words, else a short form such as
    "the morning check", else the software the reading named. None for "make it daily"."""
    said = _said(read.workflow_words, text)
    if said is not None:
        return text[said[0] : said[1]]
    for name in [w.name for w in (facts.workflows if facts is not None else None) or []]:
        runs = _name_runs(text, name)
        if runs:
            return text[runs[0][0] : runs[0][1]]
    reference = REFERENCE.search(text)
    if reference is not None:
        return ARTICLE.sub("", reference.group(0))
    software = whole_word_of(text, read.software)
    return software


def _software(read: TaskRead, text: str, target: str | None) -> str | None:
    """The software the target names, as the request wrote it."""
    software = whole_word_of(text, read.software)
    if software is None or target is None or whole_word_of(target, software) is None:
        return None
    return software


def change_clauses(text: str, names: list[Span]) -> list[Span]:
    """The clauses that hold the change: each that doesn't ask a question and orders one with a
    verb, names the workflow or says "it", or holds nothing but a schedule. A clause beside them,
    as "every Friday sum up the closed tickets", is a task of its own."""
    unnamed = _blank(text, names)
    found: list[Span] = []
    for clause in clauses_of(text):
        if asks(text, clause) or NEW_WORKFLOW.match(text[clause[0] : clause[1]]):
            continue
        words_ = {w for w, _, _ in _tokens(unnamed[clause[0] : clause[1]])}
        named = any(clause[0] <= a < clause[1] for a, _ in names)
        if words_ & EDIT_VERBS or named or "it" in words_ or words_ <= EDIT_WORDS:
            found.append(clause)
    return found


def schedule_blanks(text: str, names: list[Span]) -> list[Span]:
    """What is not the new schedule: the names, the schedule it runs on now, and each clause that
    doesn't hold the change."""
    now = [m.span() for m in INSTEAD.finditer(text)]
    kept = change_clauses(text, names)
    others = [c for c in clauses_of(text) if c not in kept]
    return names + now + others


def _schedule_of(
    text: str, names: list[Span]
) -> tuple[ScheduleChange | None, EditCant | None, list[Clash]]:
    """The new schedule in the request's own words, in the schedule's terms. A frequency it
    can't hold is a can't. Two days, two times or two frequencies are a clash, never the first.
    Any other change, as "pause it" or "rename it", and no schedule at all, are a change of
    something else, which the chat can't make yet."""
    rest = _blank(text, schedule_blanks(text, names))
    if OTHER_CHANGES & {w for w, _, _ in _tokens(rest)}:
        return None, "only_schedule", []
    if how_often(rest) is not None:
        return None, "how_often", []
    clashes = clashes_in(rest)
    if clashes:
        return None, None, clashes
    day, at = said_schedule(rest)
    often = {OFTEN.get(w, w) for m in FREQUENCY.finditer(rest) for w in m.groups() if w}
    weekly = day is None and bool(often & HOW_OFTEN_WORDS)
    hour = None
    if at is not None and at.isdigit():
        hour, at = _hour(int(at))
    if day is None and at is None and hour is None and not weekly:
        return None, "only_schedule", []
    return ScheduleChange(day=_day(day), weekly=weekly, at=at, hour=hour), None, []


def _hour(hour: int) -> tuple[int | None, str | None]:
    """A bare hour: 1 to 12 could be morning or evening, so the person picks; 0 and 13 to 23 can
    only be one time; anything else is no time at all."""
    if 1 <= hour <= 12:
        return hour, None
    return None, (f"{hour:02d}:00" if hour <= 23 else None)


def _day(day: str | None) -> WatchDay | None:
    match day:
        case (
            "every_day"
            | "weekdays"
            | "monday"
            | "tuesday"
            | "wednesday"
            | "thursday"
            | "friday"
            | "saturday"
            | "sunday"
        ):
            return day
        case _:
            return None


def how_often(rest: str) -> Span | None:
    """Where the words ask for a frequency the schedule can't hold, as "monthly"."""
    for match in FREQUENCY.finditer(rest):
        word = (match.group(1) or match.group(2)).casefold()
        if OFTEN.get(word, word) in CANT_HOLD:
            return match.span()
    found = EVERY_SO_OFTEN.search(rest)
    return None if found is None else found.span()


@dataclass(frozen=True)
class EditMark:
    """What the edit does with one stretch of the request."""

    start: int
    end: int
    mark: PartMark
    reason: PartReason | None = None
    choices: tuple[str, ...] = ()


SCHEDULE_SAID: Final = re.compile(
    rf"\b(?:{DAY_NAMES})s?\b|\bweekdays?\b|{TIME.pattern}|{FREQUENCY.pattern}", re.IGNORECASE
)


def edit_marks(
    read: TaskRead | None, text: str, answer: EditAnswer, clauses: list[Span]
) -> list[EditMark]:
    """Each clause of a request the edit answers, marked: the change it reads, a cross on what it
    can't make or didn't follow, and a question or a task beside it kept to ask on its own."""
    names = _names(read, text, None)
    said = _said(answer.workflow_words, text)
    names += [said] if said is not None else []
    blanks = schedule_blanks(text, names)
    rest = _blank(text, blanks)
    edit = _Edit(
        answer=answer,
        unnamed=_blank(text, names),
        kept=change_clauses(text, names),
        clashes=clashes_in(rest) if answer.holds_save else [],
        often=how_often(rest) if answer.cant == "how_often" else None,
        read=names + blanks,
    )
    return [mark for clause in clauses for mark in _clause_marks(text, clause, edit)]


@dataclass(frozen=True)
class _Edit:
    """What marking a clause of an edit needs to know of the whole request."""

    answer: EditAnswer
    unnamed: str
    kept: list[Span]
    clashes: list[Clash]
    often: Span | None
    read: list[Span]


def _clause_marks(text: str, clause: Span, edit: _Edit) -> list[EditMark]:
    start, end = clause
    words_ = text[start:end]
    tokens = {w for w, _, _ in _tokens(edit.unnamed[start:end])}
    changes = clause in edit.kept
    if asks(text, clause) or (
        not changes and not tokens & EDIT_VERBS and STATE_WORDS.search(words_)
    ):
        return [EditMark(start, end, "cant", "ask_on_its_own")]
    others = (tokens & OTHER_CHANGES) | (
        set(change_verbs_in(edit.unnamed[start:end])) - SCHEDULE_VERBS
    )
    if others or (edit.answer.cant == "only_schedule" and changes):
        return [EditMark(start, end, "cant", "only_schedule")]
    if not changes:
        task = NEW_WORKFLOW.match(words_) or SCHEDULE_SAID.search(words_) or tokens & EDIT_VERBS
        return [EditMark(start, end, "cant", "ask_on_its_own" if task else "not_followed")]
    marks = [
        EditMark(c.start, c.end, "cant", c.reason, c.choices)
        for c in edit.clashes
        if c.start < end and c.end > start
    ]
    if edit.often is not None and edit.often[0] < end and edit.often[1] > start:
        marks.append(EditMark(*edit.often, "cant", "how_often"))
    reads = edit.read + times_in(text) + [(m.start, m.end) for m in marks]
    marks += [EditMark(*s, "cant", "not_followed") for s in unexplained(text, clause, reads)]
    return sorted(marks, key=lambda m: m.start) or [EditMark(start, end, "will_do")]


def unexplained(text: str, clause: Span, explained: list[Span]) -> list[Span]:
    """The runs of words in a clause that changes a schedule that no part of the edit reads."""
    found: list[Span] = []
    run: list[tuple[str, int, int]] = []
    tokens = [
        t
        for t in _tokens(text[clause[0] : clause[1]])
        if not any(a <= clause[0] + t[1] < b for a, b in explained)
    ]
    for word, start, end in [*tokens, ("", -1, -1)]:
        if word and (word not in EDIT_WORDS or (run and word in FILLER)):
            run.append((word, start, end))
            continue
        while run and run[-1][0] in FILLER:
            run.pop()
        if run:
            found.append((clause[0] + run[0][1], clause[0] + run[-1][2]))
        run = []
    return found


def times_in(text: str) -> list[Span]:
    return [m.span() for m in TIME.finditer(text)]
