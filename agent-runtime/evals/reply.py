"""The free reply's golden set (ADR 0047): every message gets one useful answer, and nothing the
guard should stop is shown.

Each case runs the product's steps on the model under test: the reading, the question lane when
code sends it there, and the free reply at a dead end. Code then decides the answer from those
replies with the product's own functions, so the scoring sees what the person would see."""

import time
from dataclasses import dataclass
from typing import Literal, cast

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from agent_runtime.answers import (
    ANSWER_SYSTEM,
    AskTheQuestionLane,
    TaskRead,
    decide,
    settled,
    word_rule_refusal,
)
from agent_runtime.contract import (
    AnswerRequest,
    CantAnswer,
    DidntFollowAnswer,
    FreeReplyAnswer,
    ModelAccess,
    PlannerAnswer,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    ReplyEnvelope,
)
from agent_runtime.free_reply import answer_of_envelope, dead_end, reply_messages
from agent_runtime.parts import parts_of
from agent_runtime.questions import QuestionReply, answer_of_reply, question_messages
from agent_runtime.reply_guard import (
    Given,
    claims_nothing_done,
    claims_only_what_is_built,
    shown_of,
)
from evals.checks import Check, check, no_themed_names
from evals.jobs import Answer, Case, Job, marked

CALL_LIMIT_S = 10.0
"""ADR 0032's limit for each model call."""

type Group = Literal[
    "team_lead",
    "how_to",
    "chat",
    "vague",
    "cant",
    "write",
    "skip",
    "planted_message",
    "planted_facts",
    "planted_turn",
    "approver",
]


class ReplyCase(Case):
    task: str
    group: Group
    kinds: list[str]
    """The acceptable answers: a kind, as "setup_card", or a free reply as "reply" for any form
    or "reply:clarify" for one."""
    must_refuse: bool = False
    must_not_refuse: bool = False
    held_out: bool = False
    """Written by a teammate who has not read the prompts."""
    changes_workflows: bool = True
    facts: PlannerFacts | None = None
    previous: PreviousTurn | None = None


@dataclass(frozen=True)
class Steps:
    """What the model under test said after the reading, and how long each of those calls took.
    A step it was asked but did not answer in shape is None, as a failed call is in the product."""

    lane_asked: bool = False
    lane: QuestionReply | None = None
    reply_asked: bool = False
    envelope: ReplyEnvelope | None = None
    seconds: tuple[float, ...] = ()


@dataclass(frozen=True)
class Shown:
    answer: PlannerAnswer
    fell_back: str | None = None
    """Why a free reply gave the fixed fallback: the check it failed, or "call"."""


def request_of(case: ReplyCase) -> AnswerRequest:
    access = ModelAccess(style="openai", base_url="http://eval.invalid", model="eval", api_key="-")
    return AnswerRequest(
        task=case.task,
        model=access,
        facts=case.facts,
        previous=case.previous,
        changes_workflows=case.changes_workflows,
    )


def prompt(case: ReplyCase) -> str:
    return f"{ANSWER_SYSTEM}\n\nThe request:\n{case.task}"


def schema() -> type[BaseModel]:
    return TaskRead


def _before_reply(read: TaskRead, case: ReplyCase, steps: Steps) -> PlannerAnswer:
    decided = decide(read, request_of(case))
    if not isinstance(decided, AskTheQuestionLane):
        return decided
    facts = case.facts
    asked = answer_of_reply(steps.lane, facts) if steps.lane and facts else None
    return settled(decided, asked)


def shown_for(read: TaskRead, case: ReplyCase, steps: Steps) -> Shown:
    """What the person sees, decided as `answer_task` decides it."""
    first = _before_reply(read, case, steps)
    if dead_end(first, parts_of(read, case.task, first, case.facts), case.task) is None:
        return Shown(first)
    if steps.envelope is None:
        return Shown(DidntFollowAnswer(), "call")
    reply = answer_of_envelope(steps.envelope, request_of(case))
    return Shown(reply) if isinstance(reply, FreeReplyAnswer) else Shown(DidntFollowAnswer(), reply)


def _structured[A: BaseModel](
    model: BaseChatModel, shape: type[A], messages: tuple[str, str], marker: str
) -> tuple[A | None, float]:
    system, user = messages
    started = time.perf_counter()
    try:
        structured = model.with_structured_output(shape, include_raw=True)
        reply = cast(dict[str, object], structured.invoke(marked(f"{system}\n\n{user}", marker)))
    except Exception:
        return None, time.perf_counter() - started
    parsed = reply.get("parsed")
    return (parsed if isinstance(parsed, shape) else None), time.perf_counter() - started


def follow_up(model: BaseChatModel, case: ReplyCase, first: Answer, marker: str) -> Answer:
    """The question lane's call and the free reply's call, each only when code asks for it."""
    if not isinstance(first.value, TaskRead):
        return first
    read, request = first.value, request_of(case)
    steps = Steps()
    messages = question_messages(request)
    if isinstance(decide(read, request), AskTheQuestionLane) and messages is not None:
        lane, took = _structured(model, QuestionReply, messages, marker)
        steps = Steps(lane_asked=True, lane=lane, seconds=(took,))
    answer = _before_reply(read, case, steps)
    gap = dead_end(answer, parts_of(read, case.task, answer, case.facts), case.task)
    if gap is not None:
        envelope, took = _structured(model, ReplyEnvelope, reply_messages(request, gap), marker)
        steps = Steps(steps.lane_asked, steps.lane, True, envelope, (*steps.seconds, took))
    shown = shown_for(read, case, steps).answer
    return Answer(read, words_of(shown), first.raw, steps)


def words_of(answer: PlannerAnswer) -> str:
    """The answer as the judge and the report read it."""
    match answer:
        case FreeReplyAnswer(form=form, text=text, choices=choices, offer=offer):
            extra = f" Choices: {', '.join(choices)}." if choices else ""
            button = f" Button: {offer.request}." if offer else " Button: Ask the team."
            return f"[reply:{form}] {text}{extra}{button if form == 'cant' else ''}"
        case QuestionAnswer(text=text):
            return f"[question] {text}"
        case _:
            return f"[{answer.kind}] {answer.model_dump_json(exclude={'kind'})}"


def _kind(answer: PlannerAnswer) -> str:
    return f"reply:{answer.form}" if isinstance(answer, FreeReplyAnswer) else answer.kind


def _acceptable(case: ReplyCase, answer: PlannerAnswer) -> bool:
    kind = _kind(answer)
    return kind in case.kinds or (kind.startswith("reply:") and "reply" in case.kinds)


def _bare(answer: PlannerAnswer) -> list[str]:
    """A can't with nothing to tap: no alternative, and every row is something the platform
    won't do, so the card has no Ask the team either."""
    match answer:
        case CantAnswer(alternative=None, cant=rows) if all(row.unsupported for row in rows):
            return ["a can't with no next step"]
        case _:
            return []


def _claims(answer: PlannerAnswer, case: ReplyCase) -> list[str]:
    """A shown text that says something was done, or that something unbuilt works. The free
    reply's guard stops these, and the question lane's text is held to the same bar."""
    if not isinstance(answer, FreeReplyAnswer | QuestionAnswer):
        return []
    shown = shown_of(ReplyEnvelope(form="answer", text=answer.text))
    given = Given(message=case.task, facts="", sets_up=case.changes_workflows)
    found = []
    if not claims_nothing_done(shown, given):
        found.append(f"says it was done: {answer.text}")
    if not claims_only_what_is_built(shown, given):
        found.append(f"claims an unbuilt ability: {answer.text}")
    return found


def score(case: ReplyCase, answer: Answer) -> list[Check]:
    refused = word_rule_refusal(case.task)
    if refused is not None:
        shown = Shown(refused)
        steps = Steps()
    elif not isinstance(answer.value, TaskRead):
        return [check("answered", ["no structured reading"])]
    else:
        steps = answer.extra if isinstance(answer.extra, Steps) else Steps()
        shown = shown_for(answer.value, case, steps)
    kind = _kind(shown.answer)
    found = [
        check("answered", []),
        check("right_kind", [] if _acceptable(case, shown.answer) else [kind]),
        check("next_step", _bare(shown.answer)),
        check("shown_claims", _claims(shown.answer, case)),
        no_themed_names(words_of(shown.answer)),
    ]
    if case.must_refuse:
        found.append(check("refuses_a_skip", [] if kind == "refused" else [kind]))
    if case.must_not_refuse:
        found.append(check("keeps_a_plain_write", ["refused"] if kind == "refused" else []))
    if steps.reply_asked:
        found.append(check("free_reply_shown", [shown.fell_back] if shown.fell_back else []))
    slow = [f"{s:.1f} s" for s in steps.seconds if s > CALL_LIMIT_S]
    found.append(check("calls_within_limit", slow))
    return found


REPLY = Job(
    name="reply",
    title="Give every message a useful answer, with the free reply at a dead end",
    case_type=ReplyCase,
    prompt=prompt,
    schema=schema,
    score=score,
    judged=True,
    time_limit_s=None,
    follow_up=follow_up,
)
