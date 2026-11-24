"""The AI troubleshooter's model version (ADR 0032, ADR 0055 section 10): how often its fields
pass every check, and whether each one is right.

Each case is a stopped run as the platform sends it: the stop, the blocks of the version that ran,
where it stopped and the run's activity. The product's own path runs on the model under test: one
call, then code's check of every field. The score holds each field to the case's truth: the
failed part, the system, the kind of failure and the detail. The model writes no words, so
platform-api's templates are tested there, not here. Each case also keeps a recorded reply, which
the tests replay with no paid call."""

from collections.abc import Sequence
from typing import Final

from langchain_core.language_models import BaseChatModel

from agent_runtime.contract import (
    CauseFound,
    CauseKept,
    CauseRequest,
    CauseSystem,
    FailureKind,
    ModelAccess,
    StoppedRun,
)
from agent_runtime.troubleshooting import CAUSE_TIMEOUT_SECONDS, ModelCause, find_cause
from evals.anything import Replies, usage_of
from evals.checks import Check, check
from evals.jobs import Answer, Case, Job

ACCESS: Final = ModelAccess(
    style="openai", base_url="http://eval.invalid", model="eval", api_key="-"
)


class TroubleshootCase(Case):
    stop: StoppedRun
    events: list[str]
    blocks: list[str]
    stopped_at: list[str]
    failed_part: list[str]
    """The blocks the cause is really in."""
    systems: list[CauseSystem | None]
    """The systems that are right, None when no system is."""
    failure_kinds: list[FailureKind]
    """The kinds of failure that are right."""
    details: list[str | None]
    """The details that are right, None when no detail is."""
    reference: ModelCause
    """A reply the product shows for this case, replayed by the tests as a recorded reply."""


def request_of(case: TroubleshootCase) -> CauseRequest:
    return CauseRequest(
        model=ACCESS,
        stop=case.stop,
        events=case.events,
        blocks=case.blocks,
        stopped_at=case.stopped_at,
        within_seconds=CAUSE_TIMEOUT_SECONDS,
    )


def ask(model: BaseChatModel, case: TroubleshootCase) -> Answer:
    """The product's own path for a case, every model call it makes counted."""
    replies = Replies()
    watched = model.model_copy(update={"callbacks": [replies]})
    shown = find_cause(request_of(case), lambda _timeout: watched)
    return Answer(shown, shown.model_dump_json(), usage_of(replies.messages))


def _picked(name: str, said: object, right: Sequence[object]) -> Check:
    return check(name, [] if said in right else [f"picked {said}, right {right}"])


def score(case: TroubleshootCase, answer: Answer) -> list[Check]:
    shown = answer.value
    if not isinstance(shown, CauseFound | CauseKept):
        return [check("answered", ["no answer"])]
    if isinstance(shown, CauseKept):
        return [check("answered", []), check("found", [f"kept: {shown.why}"])]
    return [
        check("answered", []),
        check("found", []),
        _picked("failed_part", sorted(shown.failed_part), [sorted(case.failed_part)]),
        _picked("system", shown.system, case.systems),
        _picked("failure_kind", shown.failure_kind, case.failure_kinds),
        _picked("detail", shown.detail, case.details),
    ]


TROUBLESHOOT = Job(
    name="troubleshoot",
    title="Pick why a run stopped and the failed part",
    case_type=TroubleshootCase,
    prompt=lambda case: case.stop.message,
    schema=None,
    score=score,
    judged=False,
    time_limit_s=CAUSE_TIMEOUT_SECONDS,
    product_call=ask,
)
