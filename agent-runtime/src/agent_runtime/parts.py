"""Every part of a request, marked (plan 4.1, spec 6.5).

Each clause the person typed comes back with what happened to it: a tick for a clause the answer
does, a cross with its reason for one it doesn't, or the question the answer asks. No clause is
dropped. The marks are read off the answer code already decided and the request, so they never
claim more than the answer holds.
"""

import re
from dataclasses import dataclass
from typing import Final

from agent_runtime.abilities import (
    change_verbs_in,
    changes_beyond_the_abilities,
    commands_a_change,
    orders_only_what_it_can,
    other_systems,
    why_not,
)
from agent_runtime.contract import (
    AbilitiesAnswer,
    CantAnswer,
    CantRow,
    CheckWorkflowsAnswer,
    DidntFollowAnswer,
    EditAnswer,
    FreeReplyAnswer,
    NeedsMeAnswer,
    PartAnswer,
    PartMark,
    PartReason,
    PauseAnswer,
    PlannerAnswer,
    PlannerFacts,
    QuestionAnswer,
    RefusedAnswer,
    RemoveSoftwareAnswer,
    RequestPart,
    ResumeAnswer,
    SetupCardAnswer,
    WatchlistAnswer,
    WhichSoftwareAnswer,
    WhyStoppedAnswer,
)
from agent_runtime.edits import (
    QUESTION_START,
    STATE_WORDS,
    asks,
    commanded,
    edit_marks,
    switch_marks,
)
from agent_runtime.planner import NOTE_LIMIT, TEXT_LIMIT, plain, visible_words
from agent_runtime.reading import (
    FILLER,
    KNOWN_WORDS,
    POLITE,
    TaskRead,
    clauses_of,
    days_asked,
    instructs_the_planner,
    names_a_yes,
    negated,
    polite,
    schedule_clashes,
    trim,
    without_runs_by_itself,
)
from agent_runtime.removals import another, points_back, removal_of

NOT_FOLLOWED: Final = "I didn't follow this part."
SKIP_PART_NOTE: Final = "I can't skip the yes. Nothing is written without a yes."
OWN_TIME: Final = (
    "The Software watchlist checks all your software together, on one schedule. I can't give "
    "one software its own time yet."
)
HOW_OFTEN: Final = "I can't run things that often yet."
REASON_OF_NOTE: Final[dict[str, PartReason]] = {
    NOT_FOLLOWED: "not_followed",
    OWN_TIME: "own_time",
    HOW_OFTEN: "how_often",
}
"""The can't rows whose note is a reason the Portal words itself. Any other note is the
registry's words for a part the platform can't do."""

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
"""A question about what the Planner can do, as "what can you do"."""
A_WORKFLOW: Final = (
    r"(?:set\s+up|create|make|build|add)\s+(?:(?:a|an|my|our|the|new|another|one)\s+)*workflows?"
)
"""Making a workflow here, as "create a workflow". Asked how to, it writes nothing in Jira."""
HOW_TO_START: Final = re.compile(
    r"^(?:please\s+)?help(?:\s+(?:me|us))?(?:\s+please)?$|"
    r"\bneed\s+(?:some\s+|a\s+little\s+)?help\b|"
    rf"\bhow\s+(?:do|can|should|could)\s+(?:i|we)\s+(?:start|begin|use|get\s+started|{A_WORKFLOW})\b|"
    rf"\bhow\s+to\s+(?:start|begin|use|get\s+started|{A_WORKFLOW})\b|"
    r"\bhow\s+does\s+(?:this|it|the)(?:\s+(?:app|platform|tool|thing))?\s+work\b|"
    r"\bwhere\s+(?:(?:do|should|can)\s+(?:i|we)\s+|to\s+)(?:start|begin)\b|"
    r"\bwhat(?:\s+is|'s|’s)\s+this\b|"
    r"\b(?:get(?:ting)?\s+started|steps|guide|tutorial|walkthrough|first\s+time|new\s+here)\b",
    re.IGNORECASE,
)
"""A question about how to start using the app, as "how do I start", "list the steps to use this
app" or "help"."""
SET_UP_BY_THEM: Final = re.compile(r"\b(?:i|we)\s+(?:have\s+|had\s+)?set\s+up\b", re.IGNORECASE)
"""A workflow already set up, as "what I set up"."""

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


def parts_of(
    read: TaskRead | None,
    request: str,
    answer: PlannerAnswer,
    facts: PlannerFacts | None = None,
) -> list[RequestPart]:
    """Each clause of the request, in order, marked by what `answer` does with it. `read` is the
    model's reading, or None for a refusal made before any model call. `facts` name the person's
    workflows, as the answer read them."""
    text = visible_words(request)
    clauses = [c for c in clauses_of(text) if not polite(text[c[0] : c[1]])]
    if isinstance(answer, FreeReplyAnswer | DidntFollowAnswer):
        mark, reason = _whole_message(answer)
        return [_part(text, c, mark, reason) for c in clauses]
    skips = [c for c in clauses if _skips_a_yes(read, text[c[0] : c[1]], facts)]
    if isinstance(answer, STATE_ANSWERS):
        asked = _about_state(text, clauses, _names_of(answer))
        return _answered(text, clauses, asked or _the_only_question(text, clauses), skips)
    if isinstance(answer, AbilitiesAnswer):
        about = [c for c in clauses if _about_the_app(text[c[0] : c[1]])]
        return _answered(text, clauses, about, skips)
    if isinstance(answer, EditAnswer | PauseAnswer | ResumeAnswer):
        marked = (
            edit_marks(read, text, answer, clauses, facts)
            if isinstance(answer, EditAnswer)
            else switch_marks(read, text, answer, clauses, facts)
        )
        return [
            _part(text, trim(text, m.start, m.end), m.mark, m.reason, choices=m.choices)
            for m in marked
        ]
    if isinstance(answer, RemoveSoftwareAnswer):
        return _removal_parts(text, clauses, facts)
    crosses = _crosses(read, text, answer)
    alone = len(clauses) == 1
    found: list[RequestPart] = []
    for clause in clauses:
        inside = [c for c in crosses if c.start < clause[1] and c.end > clause[0]]
        if inside:
            found += [_crossed(text, clause, cross, alone) for cross in inside]
        else:
            found.append(_unmarked(answer, text, clause))
    return found


def _removal_parts(text: str, clauses: list[Span], facts: PlannerFacts | None) -> list[RequestPart]:
    """A removal ticks the words that ask for it, and a clause that asks for it again, as "remove
    it". Anything else in its clause comes back as not followed, and each other clause, a second
    removal included, is asked on its own when it asks for something."""
    found = removal_of(text, facts)
    parts: list[RequestPart] = []
    for clause in clauses:
        said = text[clause[0] : clause[1]]
        if found is not None and clause != found.clause and points_back(said):
            parts.append(_part(text, clause, "will_do"))
            continue
        again = None
        if found is not None and clause != found.clause and not _orders(said):
            again = another(found, said)
        if again is not None:
            words = plain(again, TEXT_LIMIT)
            parts.append(RequestPart(text=words, mark="cant", reason="ask_on_its_own"))
            continue
        if found is None or clause != found.clause:
            ask = _asks(text, clause) or _a_task(said) or removal_of(said, facts) is not None
            parts.append(_part(text, clause, "cant", "ask_on_its_own" if ask else "not_followed"))
            continue
        marked = [
            (found.asked, _part(text, found.asked, "will_do")),
            *((span, _part(text, span, "cant", "not_followed")) for span in found.unread),
        ]
        parts += [part for _, part in sorted(marked, key=lambda m: m[0])]
    return parts


def _whole_message(
    answer: FreeReplyAnswer | DidntFollowAnswer,
) -> tuple[PartMark, PartReason | None]:
    """A free reply answers the whole message at once, so every clause gets its one mark: a tick
    for an answer, the question for a clarifying question, and a cross for a can't. The fallback
    followed none of it."""
    match answer:
        case FreeReplyAnswer(form="answer"):
            return "will_do", None
        case FreeReplyAnswer(form="clarify"):
            return "question", None
        case FreeReplyAnswer():
            return "cant", "cant_do"
        case DidntFollowAnswer():
            return "cant", "not_followed"


def _about_the_app(clause: str) -> bool:
    """Whether the clause asks what the Planner can do or how to start using the app, and orders
    nothing, so "help me close the done tickets" is no question about the app."""
    asks = ABOUT_THE_PLANNER.search(clause) or HOW_TO_START.search(clause)
    how = re.sub(A_WORKFLOW, " ", clause, flags=re.IGNORECASE)
    return bool(asks) and not _orders(clause) and not _writes(how)


def _writes(clause: str) -> bool:
    """Whether the clause holds a write, as "delete the old tickets". "what I set up" names a
    workflow she has, and writes nothing."""
    return bool(change_verbs_in(SET_UP_BY_THEM.sub(" ", clause)))


def only_about_the_app(request: str) -> bool:
    """Whether every clause of the request asks what the Planner can do or how to start."""
    text = visible_words(request)
    clauses = [c for c in clauses_of(text) if not polite(text[c[0] : c[1]])]
    return bool(clauses) and all(_about_the_app(text[a:b]) for a, b in clauses)


def a_lone_write(request: str) -> bool:
    """Whether the request is one clause that orders or writes something, as "could you delete
    the old tickets", which no answer to a question carries out. A question, a "don't" and a
    write that names a yes are not: the last is a skip of the yes, which its part answers."""
    text = visible_words(request)
    alone = [(a, b) for a, b in clauses_of(text) if not polite(text[a:b])]
    if len(alone) != 1:
        return False
    clause = text[alone[0][0] : alone[0][1]]
    plain_order = not asks(text, alone[0]) and not negated(clause) and not names_a_yes(clause)
    return plain_order and (_orders(clause) or _writes(clause))


def asks_how_to_start(request: str) -> bool:
    """Whether a clause of the request asks how to start using the app."""
    text = visible_words(request)
    return any(
        _about_the_app(text[a:b]) and HOW_TO_START.search(text[a:b]) for a, b in clauses_of(text)
    )


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


def _the_only_question(text: str, clauses: list[Span]) -> list[Span]:
    """The request's one clause when it orders and writes nothing: the answer was chosen for it."""
    alone = [text[a:b] for a, b in clauses if len(clauses) == 1]
    return clauses if alone and not _orders(alone[0]) and not _writes(alone[0]) else []


def _skips_a_yes(read: TaskRead | None, clause: str, facts: PlannerFacts | None) -> bool:
    """Whether the clause names a yes and asks for a change, as "stop asking Bob for a yes":
    a skip of the yes, whichever answer the request got."""
    return names_a_yes(clause) and commanded(read, clause, facts)


def _answered(
    text: str, clauses: list[Span], asked: list[Span], skips: list[Span]
) -> list[RequestPart]:
    """An answer to a question sets nothing up: it ticks the clauses it answers. Every other
    clause keeps a cross: a skip of the yes says the yes can't be skipped, a task or an order
    beside a clause it answers, asked on its own, gets its own answer, and anything else was not
    followed."""
    return [
        _part(text, c, "cant", "cant_do", SKIP_PART_NOTE)
        if c in skips
        else _part(text, c, "will_do")
        if c in asked
        else _part(
            text,
            c,
            "cant",
            "ask_on_its_own" if asked and _a_task(text[c[0] : c[1]]) else "not_followed",
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


def _crossed(text: str, clause: Span, cross: _Cross, alone: bool) -> RequestPart:
    """The cross on its clause. A question that no structure read, beside the rest of the
    request, is asked on its own, whole. A question that is the whole request keeps its cross."""
    if not alone and cross.reason in ("not_followed", "cant_do") and _asks(text, clause):
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
            if _asks(text, clause):
                return _part(text, clause, "cant", "ask_on_its_own")
            if answer.rest:
                return _part(text, clause, "cant", "with_a_yes")
            return _not_offered(text, clause)
        case CantAnswer(alternative=None):
            return _part(text, clause, "cant", "needs_the_rest")
        case _:
            return _part(text, clause, "will_do")


def _not_offered(text: str, clause: Span) -> RequestPart:
    """A clause beside a refusal that offers no set-up: the registry's can't for a change no
    ability makes or a system the platform doesn't reach; "It can't run without the part I
    can't do" for an order an ability gives, or words that say it runs by itself; and not
    followed for words that tell the Planner what to say or that name nothing."""
    words = text[clause[0] : clause[1]]
    if instructs_the_planner(words):
        return _part(text, clause, "cant", "not_followed")
    task = without_runs_by_itself(words)
    if not task:
        return _part(text, clause, "cant", "needs_the_rest")
    note = why_not("schedule", task) or why_not("do", task)
    if note is not None and (changes_beyond_the_abilities(task) or other_systems(task)):
        return _part(text, clause, "cant", "cant_do", note)
    if orders_only_what_it_can([task]):
        return _part(text, clause, "cant", "needs_the_rest")
    return _part(text, clause, "cant", "not_followed")
