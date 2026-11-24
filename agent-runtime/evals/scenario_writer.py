"""The scenario writer (ADR 0054, section 5): how often its picks pass every check, and whether
each scenario plays what its kind is about on a block that can play it.

Each case is a workflow version as a simulation sees it: its blocks, the kinds that apply and the
recorded samples, scrubbed. The product's own path runs on the model under test: one call, then
the check that each name is one the request offered. platform-api checks each play against its
kind (PR 5), so that is tested there. Each case keeps a recorded reply and what the product shows
for it, which the tests replay with no paid call. The red-team cases' recorded replies add a block,
a system or a key, try to write, or follow an instruction planted in a sample or a block's name."""

from typing import Final

from langchain_core.language_models import BaseChatModel
from pydantic import JsonValue

from agent_runtime.contract import (
    ModelAccess,
    ScenarioBlock,
    ScenarioCheck,
    ScenarioKind,
    ScenarioSample,
    ScenarioServe,
    ScenariosKept,
    ScenariosWritten,
    ScenarioWriteRequest,
)
from agent_runtime.scenario_writing import WRITE_TIMEOUT_SECONDS, write_scenarios
from evals.anything import Replies, usage_of
from evals.checks import Check, check
from evals.jobs import Answer, Case, Job

ACCESS: Final = ModelAccess(
    style="openai", base_url="http://eval.invalid", model="eval", api_key="-"
)
POINT: Final[dict[ScenarioKind, ScenarioServe]] = {
    "source_not_found": "not_found",
    "timeout": "too_slow",
    "odd_data": "varied",
}
"""The play a kind is about, which at least one read plays when any read can."""


class WriterCase(Case):
    blocks: list[ScenarioBlock]
    kinds: list[ScenarioKind]
    samples: list[ScenarioSample]
    reply: dict[str, JsonValue]
    """A reply recorded as the model's tool arguments, replayed by the tests."""
    shown: ScenarioCheck | None
    """What the product shows for the recorded reply: None when it writes the scenarios, else
    why it refuses them."""


def request_of(case: WriterCase) -> ScenarioWriteRequest:
    return ScenarioWriteRequest(
        model=ACCESS,
        blocks=case.blocks,
        kinds=case.kinds,
        samples=case.samples,
        within_seconds=WRITE_TIMEOUT_SECONDS,
    )


def ask(model: BaseChatModel, case: WriterCase) -> Answer:
    """The product's own path for a case, every model call it makes counted."""
    replies = Replies()
    watched = model.model_copy(update={"callbacks": [replies]})
    shown = write_scenarios(request_of(case), lambda _timeout: watched)
    return Answer(shown, shown.model_dump_json(), usage_of(replies.messages))


def _point_problems(case: WriterCase, written: ScenariosWritten) -> list[str]:
    reads = {b.name: b for b in case.blocks if b.role == "read"}
    problems: list[str] = []
    for scenario in written.scenarios:
        point = POINT.get(scenario.kind)
        if point is None or not any(point in b.plays for b in reads.values()):
            continue
        if not any(r.serve == point and point in reads[r.block].plays for r in scenario.reads):
            problems.append(f"{scenario.kind} plays no read as {point}")
    return problems


def score(case: WriterCase, answer: Answer) -> list[Check]:
    shown = answer.value
    if isinstance(shown, ScenariosKept):
        return [check("written", [f"kept: {shown.why}"])]
    if not isinstance(shown, ScenariosWritten):
        return [check("written", ["no answer"])]
    return [check("written", []), check("plays_its_kind", _point_problems(case, shown))]


SCENARIO_WRITER = Job(
    name="scenario_writer",
    title="Pick how each simulation scenario serves the version's blocks",
    case_type=WriterCase,
    prompt=lambda case: ", ".join(case.kinds),
    schema=None,
    score=score,
    judged=False,
    time_limit_s=WRITE_TIMEOUT_SECONDS,
    product_call=ask,
)
