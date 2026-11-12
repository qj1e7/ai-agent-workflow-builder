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
    POLITE,
    TaskRead,
    clauses_of,
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
    r"\b(?:workflows?|running|stopped|paused|status|waiting|attention|approv\w*|decided|"
    r"declined|behind|up\s+to\s+date|next\s+run|needs?\s+(?:me|my))\b",
    re.IGNORECASE,
)
"""Words that ask about the person's workflows, approvals or software."""
ABOUT_THE_PLANNER: Final = re.compile(
    r"\byou\b.*\b(?:do|help|able|offer)\b|\b(?:abilities|capabilities)\b", re.IGNORECASE
)

STATE_ANSWERS: Final = (CheckWorkflowsAnswer, WhyStoppedAnswer, NeedsMeAnswer, QuestionAnswer)
"""The answers that read platform state for a question, and set nothing up."""

type Span = tuple[int, int]


@dataclass(frozen=True)
class _Cross:
    """A stretch of the request the answer doesn't do, with why."""

    start: int
    end: int
    reason: PartReason
    note: str | None = None
    choices: tuple[str, ...] = ()


def parts_of(read: TaskRead | None, request: str, answer: PlannerAnswer) -> list[RequestPart]:
    """Each clause of the request, in order, marked by what `answer` does with it. `read` is the
    model's reading, or None for a refusal made before any model call."""
    text = visible_words(request)
    clauses = [c for c in clauses_of(text) if not _polite(text, c)]
    if isinstance(answer, STATE_ANSWERS):
        return _answered(text, clauses, _state_questions(text, clauses))
    if isinstance(answer, AbilitiesAnswer):
        about = [c for c in clauses if ABOUT_THE_PLANNER.search(text[c[0] : c[1]])]
        return _answered(text, clauses, about, "ask_on_its_own" if about else "not_followed")
    crosses = _crosses(read, text, answer)
    found: list[RequestPart] = []
    for clause in clauses:
        inside = [c for c in crosses if c.start < clause[1] and c.end > clause[0]]
        if inside:
            found += [_crossed(text, clause, cross) for cross in inside]
        else:
            found.append(_unmarked(answer, text, clause))
    return found


def _polite(text: str, clause: Span) -> bool:
    return all(w in POLITE for w in re.findall(r"[\w']+", text[clause[0] : clause[1]].casefold()))


def _asks(text: str, clause: Span) -> bool:
    """Whether the clause is a question: it opens like one or ends at a question mark."""
    words = text[clause[0] : clause[1]]
    return bool(QUESTION_START.match(words) or re.match(r"\s*\?", text[clause[1] :]))


def _state_questions(text: str, clauses: list[Span]) -> list[Span]:
    """The clauses a state answer answers: the questions about workflows, approvals or
    software that change nothing, else the first clause that changes nothing."""
    asked = [
        c
        for c in clauses
        if (_asks(text, c) or STATE_WORDS.search(text[c[0] : c[1]]))
        and not commands_a_change(text[c[0] : c[1]])
    ]
    if asked or not clauses:
        return asked
    return [next((c for c in clauses if not commands_a_change(text[c[0] : c[1]])), clauses[0])]


def _answered(
    text: str, clauses: list[Span], asked: list[Span], unasked: PartReason = "ask_on_its_own"
) -> list[RequestPart]:
    """An answer to a question sets nothing up: it answers the clauses it was asked, and every
    other clause keeps a cross. Asked on its own, a request or a change gets its own answer."""
    return [
        _part(text, c, "will_do") if c in asked else _part(text, c, "cant", unasked)
        for c in clauses
    ]


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
        at = locate(text, answer.said)
        if at is not None:
            found.append(_Cross(*at, "skip_approval"))
    for row in _rows(answer):
        at = locate(text, row.text)
        if at is None:
            continue
        if row.system is not None and row.text.casefold() == row.system.casefold():
            at = next((c for c in clauses_of(text) if c[0] <= at[0] < c[1]), at)
        reason = REASON_OF_NOTE.get(row.note, "cant_do")
        found.append(_Cross(*at, reason, row.note if reason == "cant_do" else None))
    if read is not None and _sets_up(answer):
        found += [
            _Cross(c.start, c.end, c.reason, choices=c.choices)
            for c in schedule_clashes(read.schedule, text)
        ]
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
    return _part(text, span, "cant", cross.reason, cross.note, cross.choices)


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
