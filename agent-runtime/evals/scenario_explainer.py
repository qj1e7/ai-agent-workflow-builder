"""The explainer (ADR 0054, section 5): for each failed scenario, whether its picks pass every
check and are right.

Each case is a simulation's failed scenarios as code graded them: the kind, how it ended, where it
stopped, what happened in code's words, the blocks that ran and how the scenario played each read.
The product's own path runs on the model under test: one call, then code's check of every pick.
The score holds each pick to the case's truth: the block, the kind of failure, the play that led
to it and the name from what happened. The model writes no words, so platform-api's sentences are
tested there, not here. Each case keeps a recorded reply and what the product shows for it, which
the tests replay with no paid call. The red-team cases' recorded replies blame a person, give
advice, or follow an instruction planted in what happened."""

from collections.abc import Sequence
from typing import Final

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, JsonValue

from agent_runtime.contract import (
    FailedScenario,
    ModelAccess,
    NoteKind,
    ScenarioExplainRequest,
    ScenariosExplained,
)
from agent_runtime.scenario_explaining import EXPLAIN_TIMEOUT_SECONDS, explain_failures
from evals.anything import Replies, usage_of
from evals.checks import Check, check
from evals.jobs import Answer, Case, Job

ACCESS: Final = ModelAccess(
    style="openai", base_url="http://eval.invalid", model="eval", api_key="-"
)


class NoteTruth(BaseModel):
    """The picks that are right for one failed scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    blocks: list[str]
    kinds: list[NoteKind]
    sources: list[str | None]
    details: list[str | None]


class ExplainerCase(Case):
    failed: list[FailedScenario]
    truth: dict[str, NoteTruth]
    """By scenario name."""
    reply: dict[str, JsonValue]
    """A reply recorded as the model's tool arguments, replayed by the tests."""
    shown: ScenariosExplained
    """What the product shows for the recorded reply."""


def request_of(case: ExplainerCase) -> ScenarioExplainRequest:
    return ScenarioExplainRequest(
        model=ACCESS, failed=case.failed, within_seconds=EXPLAIN_TIMEOUT_SECONDS
    )


def ask(model: BaseChatModel, case: ExplainerCase) -> Answer:
    """The product's own path for a case, every model call it makes counted."""
    replies = Replies()
    watched = model.model_copy(update={"callbacks": [replies]})
    shown = explain_failures(request_of(case), lambda _timeout: watched)
    return Answer(shown, shown.model_dump_json(), usage_of(replies.messages))


def _picked(name: str, said: object, right: Sequence[object]) -> list[str]:
    return [] if said in right else [f"{name}: picked {said}, right {list(right)}"]


def score(case: ExplainerCase, answer: Answer) -> list[Check]:
    shown = answer.value
    if not isinstance(shown, ScenariosExplained):
        return [check("answered", ["no answer"])]
    notes = {note.scenario: note for note in shown.notes}
    checks = [check("answered", [f"kept: {why}" for why in shown.kept if why == "call"])]
    for name, truth in case.truth.items():
        note = notes.get(name)
        if note is None:
            checks.append(check(name, ["no note"]))
            continue
        problems = [
            *_picked("block", note.block, truth.blocks),
            *_picked("kind", note.kind, truth.kinds),
            *_picked("source", note.source, truth.sources),
            *_picked("detail", note.detail, truth.details),
        ]
        checks.append(check(name, problems))
    return checks


SCENARIO_EXPLAINER = Job(
    name="scenario_explainer",
    title="Pick why each failed simulation scenario failed",
    case_type=ExplainerCase,
    prompt=lambda case: "; ".join(f.happened for f in case.failed),
    schema=None,
    score=score,
    judged=False,
    time_limit_s=EXPLAIN_TIMEOUT_SECONDS,
    product_call=ask,
)
