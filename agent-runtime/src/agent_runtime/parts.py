"""Every part of a request, marked (plan 4.1, spec 6.5).

Each clause the person typed comes back with what happened to it: a tick for a clause the answer
does, a cross with its reason for one it doesn't, or the question the answer asks. No clause is
dropped. The marks are read off the answer code already decided and the request, so they never
claim more than the answer holds.
"""

import re
from dataclasses import dataclass
from typing import Final

from agent_runtime.abilities import commands_a_change
from agent_runtime.contract import (
    AbilitiesAnswer,
    CantAnswer,
    CantRow,
    CheckWorkflowsAnswer,
    NeedsMeAnswer,
    PartAnswer,
    PartMark,
    PartReason,
    PlannerAnswer,
    QuestionAnswer,
    RefusedAnswer,
    RequestPart,
    SetupCardAnswer,
    WatchlistAnswer,
    WhichSoftwareAnswer,
    WhyStoppedAnswer,
)
from agent_runtime.planner import NOTE_LIMIT, TEXT_LIMIT, plain, visible_words
from agent_runtime.reading import (
    FILLER,
    KNOWN_WORDS,
    POLITE,
    TaskRead,
    clauses_of,
    days_asked,
    polite,
    schedule_clashes,
    trim,
)

NOT_FOLLOWED: Final = "I didn't follow this part."
OWN_TIME: Final = (
    "The Software watchlist checks all your software together, on one schedule. I can't give "
    "one software its own time yet."
)
REASON_OF_NOTE: Final[dict[str, PartReason]] = {
    NOT_FOLLOWED: "not_followed",
    OWN_TIME: "own_time",
}
"""The can't rows whose note is a reason the Portal words itself. Any other note is the
registry's words for a part the platform can't do."""

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
"""Words that ask about the person's workflows, approvals or software. Only a clause with one
of them, or with the workflow or the software the answer names, is the one a state answer
answers."""
COMMAND: Final = re.compile(
    r"^(?:please\s+)?(?:pause|resume|stop|delete|remove|rename|disable|enable|cancel|restart|"
    r"retry|turn|make|change|move|set|run|start|edit|update|add|open|close|create|raise|watch|"
    r"track|monitor)\b",
    re.IGNORECASE,
)
"""A clause that opens with an order, as "Pause the morning check", which no answer to a
question carries out."""
ABOUT_THE_PLANNER: Final = re.compile(
    r"\byou\b.*\b(?:do|help|able|offer)\b|\b(?:abilities|capabilities)\b", re.IGNORECASE
)

STATE_ANSWERS: Final = (CheckWorkflowsAnswer, WhyStoppedAnswer, NeedsMeAnswer, QuestionAnswer)
"""The answers that read platform state for a question, and set nothing up."""

type Span = tuple[int, int]


@dataclass(frozen=True)
class _Cross:
    """A stretch of the request the answer doesn't do, with why, or the question it asks about
    it. `quote` is the row's own words, kept when the row cut them at its limit."""

    start: int
    end: int
    reason: PartReason
    note: str | None = None
    choices: tuple[str, ...] = ()
    mark: PartMark = "cant"
    quote: str | None = None


def parts_of(read: TaskRead | None, request: str, answer: PlannerAnswer) -> list[RequestPart]:
    """Each clause of the request, in order, marked by what `answer` does with it. `read` is the
    model's reading, or None for a refusal made before any model call."""
    text = visible_words(request)
    clauses = [c for c in clauses_of(text) if not polite(text[c[0] : c[1]])]
    if isinstance(answer, STATE_ANSWERS):
        return _answered(text, clauses, _about_state(text, clauses, _names_of(answer)))
    if isinstance(answer, AbilitiesAnswer):
        about = [c for c in clauses if ABOUT_THE_PLANNER.search(text[c[0] : c[1]])]
        return _answered(text, clauses, about)
    crosses = _crosses(read, text, answer)
    found: list[RequestPart] = []
    for clause in clauses:
        inside = [c for c in crosses if c.start < clause[1] and c.end > clause[0]]
        if inside:
            found += [_crossed(text, clause, cross) for cross in inside]
        else:
            found.append(_unmarked(answer, text, clause))
    return found


def _asks(text: str, clause: Span) -> bool:
    """Whether the clause is a question: it opens like one or ends at a question mark."""
    words = text[clause[0] : clause[1]]
    return bool(QUESTION_START.match(words) or re.match(r"\s*\?", text[clause[1] :]))


def _names_of(answer: PlannerAnswer) -> list[str]:
    """The workflow or the software a state answer is about, in the request's words."""
    match answer:
        case CheckWorkflowsAnswer() | WhyStoppedAnswer():
            return [answer.workflow_words] if answer.workflow_words else []
        case QuestionAnswer():
            return answer.about_software
        case _:
            return []


def _orders(clause: str) -> bool:
    return commands_a_change(clause) or COMMAND.match(clause) is not None


def _about_state(text: str, clauses: list[Span], names: list[str]) -> list[Span]:
    """The clauses a state answer answers: each that asks about workflows, approvals or
    software, or names the one the answer is about, and orders nothing. No other is ticked."""
    return [
        c
        for c in clauses
        if not _orders(text[c[0] : c[1]])
        and (
            STATE_WORDS.search(text[c[0] : c[1]])
            or any(locate(text[c[0] : c[1]], n) for n in names)
        )
    ]


def _answered(text: str, clauses: list[Span], asked: list[Span]) -> list[RequestPart]:
    """An answer to a question sets nothing up: it ticks the clauses it answers. Every other
    clause keeps a cross: a task or an order, asked on its own, gets its own answer, and
    anything else was not followed."""
    return [
        _part(text, c, "will_do")
        if c in asked
        else _part(
            text, c, "cant", "ask_on_its_own" if _a_task(text[c[0] : c[1]]) else "not_followed"
        )
        for c in clauses
    ]


def _a_task(clause: str) -> bool:
    """Whether the clause orders something or names part of a task, as "every Friday sum up the
    closed tickets"."""
    task_words = KNOWN_WORDS - FILLER - POLITE
    return _orders(clause) or any(
        w in task_words for w in re.findall(r"[\w'-]+", clause.casefold())
    )


def _part(
    text: str,
    span: Span,
    mark: PartMark,
    reason: PartReason | None = None,
    note: str | None = None,
    choices: tuple[str, ...] = (),
) -> RequestPart:
    return RequestPart(
        text=plain(text[span[0] : span[1]], TEXT_LIMIT),
        mark=mark,
        reason=reason,
        note=None if note is None else plain(note, NOTE_LIMIT),
        choices=list(choices),
    )


def _rows(answer: PlannerAnswer | None) -> list[CantRow]:
    match answer:
        case PartAnswer() | CantAnswer():
            alternative = answer.alternative if isinstance(answer, CantAnswer) else None
            return answer.cant + _rows(alternative)
        case WatchlistAnswer():
            return _rows(answer.also)
        case _:
            return []


def _sets_up(answer: PlannerAnswer | None) -> bool:
    match answer:
        case SetupCardAnswer() | PartAnswer():
            return True
        case CantAnswer():
            return _sets_up(answer.alternative)
        case WatchlistAnswer():
            return _sets_up(answer.also)
        case _:
            return False


def _crosses(read: TaskRead | None, text: str, answer: PlannerAnswer) -> list[_Cross]:
    found: list[_Cross] = []
    if isinstance(answer, RefusedAnswer):
        # The refusal names the clause that asks to skip the yes, as the person wrote it.
        at = locate(text, answer.said)
        clauses = [c for c in clauses_of(text) if at and c[0] < at[1] and c[1] > at[0]]
        found += [_Cross(*c, "skip_approval") for c in clauses]
    for row in _rows(answer):
        at = locate(text, row.text)
        if at is None:
            continue
        if row.system is not None and row.text.casefold() == row.system.casefold():
            at = next((c for c in clauses_of(text) if c[0] <= at[0] < c[1]), at)
        reason = REASON_OF_NOTE.get(row.note, "cant_do")
        note = row.note if reason == "cant_do" else None
        found.append(_Cross(*at, reason, note, quote=row.text))
    if read is not None and _sets_up(answer):
        found += [
            _Cross(c.start, c.end, c.reason, choices=c.choices)
            for c in schedule_clashes(read.schedule, text)
        ]
        asked = days_asked(read.search, text)
        if asked is not None:
            found.append(_Cross(*asked, "how_many_days", mark="question"))
    return found


def locate(text: str, quote: str) -> Span | None:
    """Where the request writes a row's words, spacing and case aside. A row cut at its limit
    is found by the words it kept."""
    words = re.findall(r"\w+", quote.removesuffix("…"))
    if not words:
        return None
    pattern = r"\W+".join(re.escape(w) for w in words)
    found = re.search(rf"(?<!\w){pattern}", text, re.IGNORECASE)
    return None if found is None else (found.start(), found.end())


def _crossed(text: str, clause: Span, cross: _Cross) -> RequestPart:
    """The cross on its clause. A question that no structure read is asked on its own, whole."""
    if cross.reason in ("not_followed", "cant_do") and _asks(text, clause):
        return _part(text, clause, "cant", "ask_on_its_own")
    span = trim(text, max(cross.start, clause[0]), min(cross.end, clause[1]))
    part = _part(text, span, cross.mark, cross.reason, cross.note, cross.choices)
    if cross.quote is not None and cross.quote.endswith("…") and clause[0] <= cross.start:
        return part.model_copy(update={"text": cross.quote})
    return part


def _unmarked(answer: PlannerAnswer, text: str, clause: Span) -> RequestPart:
    """A clause no cross reaches, marked by what the answer does with clauses it read."""
    match answer:
        case WhichSoftwareAnswer():
            return _part(text, clause, "question")
        case RefusedAnswer():
            reason: PartReason = "ask_on_its_own" if _asks(text, clause) else "with_a_yes"
            return _part(text, clause, "cant", reason)
        case CantAnswer(alternative=None):
            return _part(text, clause, "cant", "needs_the_rest")
        case _:
            return _part(text, clause, "will_do")
