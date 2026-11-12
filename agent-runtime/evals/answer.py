import re
from typing import cast

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from agent_runtime.answers import (
    ANSWER_SYSTEM,
    ANSWER_TIMEOUT_SECONDS,
    AskTheQuestionLane,
    TaskRead,
    decide,
    word_rule_refusal,
)
from agent_runtime.contract import (
    AnswerRequest,
    CantAnswer,
    CantRow,
    EditAnswer,
    EditCant,
    ModelAccess,
    PartAnswer,
    PlannerAnswer,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    RequestPart,
    RowState,
    ScheduleChange,
    SetupCardAnswer,
    UnderstoodRow,
    WatchlistAnswer,
)
from agent_runtime.parts import parts_of
from agent_runtime.planner import said_in, visible_words
from agent_runtime.questions import QuestionReply, answer_of_reply, question_messages
from agent_runtime.reading import polite
from evals.checks import (
    Check,
    check,
    mentions,
    mentions_a_form,
    no_jargon,
    no_themed_names,
    ticket_keys,
)
from evals.jobs import Answer, Case, Job, marked

ACCEPTED = ("understood", "changed")
_PROJECT_KEY = re.compile(r"\b(?:[Pp]roject|[Ii]n)\s+([A-Z][A-Z0-9]{1,9})\b")
_ANY_KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
_CLOCK_WORDS = re.compile(
    r"\d+|\b(?:morning|afternoon|evening|night|noon|midday|midnight|am|pm|one|two|three|four|"
    r"five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)
_NO_UPDATE = re.compile(
    r"(?:\b(?:no|not|never|nobody|without)\b|n't\b)[^,;:.!?]*?\b(?:updates?|updated|touched)\b|"
    r"\buntouched\b",
    re.IGNORECASE,
)
"""A request that says a ticket has had no update: a negation before an update word in the
same stretch between punctuation, however far."""
_SPLIT = re.compile(r"[,;:.!?()]+|\b(?:and|then|but|also|plus|or)\b", re.IGNORECASE)
"""Where the scoring splits a request, on its own and more finely than the runtime does, so a
part the runtime never marks can't hide in a clause it chose."""
_UPDATED_WITHIN = re.compile(r"\bupdated\s+(?:in\s+the\s+last|today|since)\b", re.IGNORECASE)
_DAY_WORDS = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekday|weekdays|daily|"
    r"weekly|monthly|hourly)\b",
    re.IGNORECASE,
)


class AnswerCase(Case):
    task: str
    kind: list[str] = []
    not_kind: list[str] = []
    software: str | None = None
    word: list[str] = []
    workflow_words: str | None = None
    cant: list[str] = []
    needs: str | None = None
    system: str | None = None
    alternative: str | None = None
    also: str | None = None
    understood: list[str] = []
    schedule: list[RowState] = []
    crossed: list[str] = []
    reasons: list[str] = []
    change: ScheduleChange | None = None
    edit_cant: EditCant | None = None
    changes_workflows: bool = True
    facts: PlannerFacts | None = None
    previous: PreviousTurn | None = None


def _request(case: AnswerCase) -> AnswerRequest:
    """The request the decision reads. The eval never calls the model again."""
    access = ModelAccess(style="openai", base_url="http://eval.invalid", model="eval", api_key="-")
    return AnswerRequest(
        task=case.task,
        model=access,
        facts=case.facts,
        previous=case.previous,
        changes_workflows=case.changes_workflows,
    )


def prompt(case: AnswerCase) -> str:
    return f"{ANSWER_SYSTEM}\n\nThe request:\n{case.task}"


def schema() -> type[BaseModel]:
    return TaskRead


def card_of(shown: PlannerAnswer) -> list[UnderstoodRow] | None:
    match shown:
        case SetupCardAnswer() | PartAnswer():
            return shown.rows
        case CantAnswer():
            return (
                shown.alternative.rows if isinstance(shown.alternative, SetupCardAnswer) else None
            )
        case WatchlistAnswer():
            return card_of(shown.also) if shown.also is not None else None
        case _:
            return None


def cant_of(shown: PlannerAnswer) -> list[CantRow]:
    match shown:
        case PartAnswer() | CantAnswer():
            return shown.cant
        case WatchlistAnswer():
            return cant_of(shown.also) if shown.also is not None else []
        case _:
            return []


def watch_of(shown: PlannerAnswer) -> WatchlistAnswer | None:
    match shown:
        case WatchlistAnswer():
            return shown
        case CantAnswer():
            return shown.alternative if isinstance(shown.alternative, WatchlistAnswer) else None
        case _:
            return None


MACHINE_FIELDS = frozenset({"kind", "state", "status", "needs", "reason"})


def _texts(shown: PlannerAnswer) -> list[str]:
    if isinstance(shown, EditAnswer):
        # Its other fields are the schedule's own terms, which the Portal words.
        return [t for t in (shown.workflow_words, shown.software) if t]

    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            items = cast(dict[str, object], value).items()
            return [s for key, v in items if key not in MACHINE_FIELDS for s in strings(v)]
        if isinstance(value, list):
            return [s for v in cast(list[object], value) for s in strings(v)]
        return []

    return strings(shown.model_dump(mode="json"))


def _kind_checks(case: AnswerCase, kind: str) -> list[Check]:
    wrong = case.kind and kind not in case.kind
    forbidden = kind in case.not_kind
    return [check("right_kind", [kind] if wrong or forbidden else [])]


def _field_checks(case: AnswerCase, shown: PlannerAnswer) -> list[Check]:
    found: list[Check] = []
    watch = watch_of(shown)
    if case.software is not None:
        named = watch.software if watch is not None else None
        found.append(
            check(
                "names_the_software",
                [] if named and named.casefold() == case.software.casefold() else [str(named)],
            )
        )
    if case.word:
        said = watch.word if watch is not None else ""
        found.append(
            check("names_the_word", [] if any(mentions(said, w) for w in case.word) else [said])
        )
    if case.workflow_words is not None:
        said = getattr(shown, "workflow_words", None)
        ok = (said or "").casefold() == case.workflow_words.casefold()
        found.append(check("names_the_workflow", [] if ok else [str(said)]))
    if case.alternative is not None:
        offered = getattr(shown, "alternative", None)
        kind = "none" if offered is None else offered.kind
        found.append(check("offers_alternative", [] if kind == case.alternative else [kind]))
    if case.also is not None:
        also = getattr(shown, "also", None)
        kind = "none" if also is None else also.kind
        found.append(check("carries_the_rest", [] if kind == case.also else [kind]))
    edit = shown if isinstance(shown, EditAnswer) else None
    if case.change is not None:
        read = None if edit is None else edit.schedule
        found.append(check("reads_the_new_schedule", [] if read == case.change else [str(read)]))
    if case.edit_cant is not None:
        cant = None if edit is None else edit.cant
        found.append(
            check("names_the_change_it_cant_make", [] if cant == case.edit_cant else [str(cant)])
        )
    return found


def _cant_checks(case: AnswerCase, shown: PlannerAnswer) -> list[Check]:
    cant = cant_of(shown)
    card = card_of(shown) or []
    refused = [f"{c.text} {c.note}" for c in cant]
    accepted = " ".join(r.text for r in card if r.state in ACCEPTED)
    found = [
        check(
            "marks_cant_do",
            [w for w in case.cant if not any(mentions_a_form(t, w) for t in refused)],
        ),
        check("keeps_out", [f"{w} offered" for w in case.cant if mentions_a_form(accepted, w)]),
    ]
    if case.needs is not None:
        found.append(
            check(
                "needs",
                [] if any(c.needs == case.needs for c in cant) else [str(c.needs) for c in cant],
            )
        )
    if case.system is not None:
        systems = [c.system for c in cant]
        found.append(
            check("names_the_system", [] if case.system in systems else [str(s) for s in systems])
        )
    return found


def _guessed_time(schedule: UnderstoodRow, task: str) -> list[str]:
    """The words of a schedule the request never said: a time of day on any accepted row, and a
    day too on one the Planner called the person's own. A day shown as filled in is allowed."""
    if schedule.state not in ACCEPTED:
        return []
    patterns = [_CLOCK_WORDS] + ([_DAY_WORDS] if schedule.state == "understood" else [])
    return [w for p in patterns for w in p.findall(schedule.text) if not said_in(w, task)]


def _card_checks(case: AnswerCase, shown: PlannerAnswer) -> list[Check]:
    card = card_of(shown)
    if card is None:
        return [check("reads_the_parts", case.understood)] if case.understood else []
    explained = " ".join(f"{r.text} {r.note or ''}" for r in card if r.state in ACCEPTED)
    schedule = next(r for r in card if r.kind == "schedule")
    guessed = _guessed_time(schedule, case.task)
    words = [w for r in card for w in (r.text, r.note or "")]
    task_keys = set(_ANY_KEY.findall(case.task)) | ticket_keys(case.task)
    shown_keys = {k for text in words for k in _PROJECT_KEY.findall(text)}
    shown_keys |= {k for text in words for k in ticket_keys(text)}
    found = [
        check("reads_the_parts", [w for w in case.understood if not mentions(explained, w)]),
        check("no_guessed_time", guessed),
        check("no_invented_keys", sorted(shown_keys - task_keys)),
    ]
    if case.schedule:
        ok = schedule.state in case.schedule
        found.append(check("schedule_state", [] if ok else [f"schedule is {schedule.state}"]))
    return found


def dropped(task: str, parts: list[RequestPart]) -> list[str]:
    """Each piece of the request, split here, not by the runtime, that no part's words reach.
    Thanks and please ask for nothing, so they need no part."""
    text = visible_words(task)
    marked = [m for p in parts if (m := _found(text, p.text)) is not None]
    found: list[str] = []
    at = 0
    for cut in [*_SPLIT.finditer(text), None]:
        end = len(text) if cut is None else cut.start()
        piece = text[at:end].strip()
        start = at + text[at:end].find(piece)
        if (
            piece
            and not polite(piece)
            and not any(a < start + len(piece) and b > start for a, b in marked)
        ):
            found.append(f"dropped: {piece}")
        at = len(text) if cut is None else cut.end()
    return found


def _found(text: str, words: str) -> tuple[int, int] | None:
    pattern = r"\W+".join(re.escape(w) for w in re.findall(r"\w+", words.removesuffix("…")))
    hit = re.search(rf"(?<!\w){pattern}", text, re.IGNORECASE) if pattern else None
    return None if hit is None else (hit.start(), hit.end())


def flipped(task: str, rows: list[UnderstoodRow]) -> list[str]:
    """Each accepted row that shows an update within some days for a request that says no
    update: the meaning turned round with a tick."""
    if not _NO_UPDATE.search(task):
        return []
    return [
        f"flipped: {r.text}" for r in rows if r.state in ACCEPTED and _UPDATED_WITHIN.search(r.text)
    ]


def _part_checks(case: AnswerCase, shown: PlannerAnswer, parts: list[RequestPart]) -> list[Check]:
    """Every clause comes back as a part with a mark, and a request that says no update never
    gets a tick on an update within some days (plan 7.5)."""
    problems = dropped(case.task, parts) + flipped(case.task, card_of(shown) or [])
    found = [check("keeps_or_flags_each_part", problems)]
    if case.crossed:
        crosses = [p.text for p in parts if p.mark == "cant"]
        missing = [w for w in case.crossed if not any(mentions(t, w) for t in crosses)]
        found.append(check("crosses_the_part", missing))
    if case.reasons:
        given = {p.reason for p in parts}
        found.append(check("gives_the_reason", [r for r in case.reasons if r not in given]))
    return found


def follow_up(model: BaseChatModel, case: AnswerCase, first: Answer, marker: str) -> Answer:
    """The question lane's own call, for a request the decision sends there. The marker is on its
    own line so the gateway cannot answer it from its store."""
    if not isinstance(first.value, TaskRead):
        return first
    decided = decide(first.value, _request(case))
    messages = question_messages(_request(case))
    if not isinstance(decided, AskTheQuestionLane) or messages is None:
        return first
    system, user = messages
    structured = model.with_structured_output(QuestionReply, include_raw=True)
    reply: dict[str, object] = structured.invoke(marked(f"{system}\n\n{user}", marker))  # type: ignore[assignment]
    parsed = reply.get("parsed")
    return Answer(
        first.value, first.text, first.raw, parsed if isinstance(parsed, QuestionReply) else "none"
    )


def score(case: AnswerCase, answer: Answer) -> list[Check]:
    value = answer.value
    refused = word_rule_refusal(case.task)
    if refused is not None:
        shown: PlannerAnswer | None = refused
    elif not isinstance(value, TaskRead):
        return [check("answered", ["no structured answer"])]
    else:
        decided = decide(value, _request(case))
        if isinstance(decided, AskTheQuestionLane):
            if not isinstance(answer.extra, QuestionReply):
                return [check("answered", ["the question lane gave no structured answer"])]
            facts = case.facts
            asked = answer_of_reply(answer.extra, facts) if facts is not None else None
            shown = decided.otherwise if asked is None else asked
        else:
            shown = decided
    if shown is None:
        return [check("answered", []), check("right_kind", ["the reading does not hold together"])]
    text = " ".join(_texts(shown))
    reading = value if isinstance(value, TaskRead) else None
    parts = _part_checks(case, shown, parts_of(reading, case.task, shown, case.facts))
    if isinstance(shown, QuestionAnswer):
        # Its words quote the person's own software names, such as n8n, so the jargon check
        # does not apply. The model's text is still held to the themed-name rule.
        return [
            check("answered", []),
            *_kind_checks(case, shown.kind),
            *parts,
            no_themed_names(text),
        ]
    return [
        check("answered", []),
        *_kind_checks(case, shown.kind),
        *_field_checks(case, shown),
        *_cant_checks(case, shown),
        *_card_checks(case, shown),
        *parts,
        no_jargon(text),
        no_themed_names(text),
    ]


ANSWER = Job(
    name="answer",
    title="Give one Planner answer for a request typed on Home",
    case_type=AnswerCase,
    prompt=prompt,
    schema=schema,
    score=score,
    judged=False,
    time_limit_s=ANSWER_TIMEOUT_SECONDS,
    follow_up=follow_up,
)
