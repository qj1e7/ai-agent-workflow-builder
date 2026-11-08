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
    rewrite_follow_up,
    word_rule_refusal,
)
from agent_runtime.contract import (
    AnswerRequest,
    CantAnswer,
    CantRow,
    ModelAccess,
    PartAnswer,
    PlannerAnswer,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    RowState,
    SetupCardAnswer,
    UnderstoodRow,
    WatchlistAnswer,
)
from agent_runtime.planner import said_in
from agent_runtime.questions import QuestionReply, answer_of_reply, question_messages
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
    facts: PlannerFacts | None = None
    previous: PreviousTurn | None = None


def _request(case: AnswerCase) -> AnswerRequest:
    """The request the decision reads. The eval never calls the model again."""
    access = ModelAccess(style="openai", base_url="http://eval.invalid", model="eval", api_key="-")
    request = AnswerRequest(task=case.task, model=access, facts=case.facts, previous=case.previous)
    rewritten = rewrite_follow_up(request)
    return request if rewritten is None else request.model_copy(update={"task": rewritten})


def prompt(case: AnswerCase) -> str:
    """What the model reads: the request, or its follow-up rewrite, as the product sends it."""
    return f"{ANSWER_SYSTEM}\n\nThe request:\n{_request(case).task}"


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
                "needs", [] if any(c.needs == case.needs for c in cant) else [c.needs for c in cant]
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
    if isinstance(shown, QuestionAnswer):
        # Its words quote the person's own software names, such as n8n, so the jargon check
        # does not apply. The model's text is still held to the themed-name rule.
        return [check("answered", []), *_kind_checks(case, shown.kind), no_themed_names(text)]
    return [
        check("answered", []),
        *_kind_checks(case, shown.kind),
        *_field_checks(case, shown),
        *_cant_checks(case, shown),
        *_card_checks(case, shown),
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
