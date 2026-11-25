"""The scenario writer and the explainer (ADR 0054, section 5), as a simulation's driver asks them.
Like the troubleshooter's model version (run_causes.py), each is off unless a caller asks, needs
the connected model, and answers in picks that code turns into scenarios or words. The model key
goes from the settings store into the request to the runtime and nowhere else.

The writer: the driver gets the version's plan from the simulation gateway (`POST
/simulation/v1/plans`), and `write` asks the runtime for one scenario for each kind that applies.
The picks become scenarios in PR 5's schema (`specs_of`). The driver sends them to the gateway with
`fall_back`, so PR 5's own check (`scenarios.check_all`) refuses any that doesn't fit, and code's
templates run in their place. Without a model, or with any answer but written scenarios, `write`
gives None, and the driver sends none, so the templates run as before.

The explainer: once the gateway graded the simulation, `explain` asks once for every failed
scenario. Each note is checked again against its scenario's facts, and code writes one plain
sentence from it (`note_words`). The sentence helps the reader. The grade stays the verdict, and
a failure with no note keeps code's own words.

A simulation asks each at most once, and each call's prompt and answer are capped in the runtime,
so one simulation costs at most the runtime's SIMULATION_COST_CAP_USD."""

import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Final, Protocol

from pydantic import ValidationError

from platform_api.db import Database
from platform_api.orchestration.agents import (
    MOST_FAILED,
    MOST_RUN_BLOCKS,
    MOST_SAMPLE_ITEMS,
    MOST_SAMPLES,
    STOP_MESSAGE_LIMIT,
    AgentRejected,
    AgentUnavailable,
    CoverBlock,
    FailedScenario,
    FailureNote,
    ModelAccess,
    NoteKind,
    ScenarioBlock,
    ScenarioExplainRequest,
    ScenarioExplainResult,
    ScenarioPlay,
    ScenarioSample,
    ScenariosExplained,
    ScenariosWritten,
    ScenarioVariation,
    ScenarioWriteRequest,
    ScenarioWriteResult,
)
from platform_api.orchestration.scenarios import Play, Reply, ScenarioSpec
from platform_api.orchestration.service import ActiveModel
from platform_api.orchestration.simulation_gateway import PlanOut, PlayOut, ResultOut

log = logging.getLogger(__name__)

WRITE_SECONDS: Final = 30.0
EXPLAIN_SECONDS: Final = 15.0

NOTE_SAID: Final[Mapping[NoteKind, str]] = {
    "stopped": '"{block}" stopped the run with no reason people can act on',
    "went_on": '"{block}" let the run go on',
    "ended_early": '"{block}" ended the run before the yes',
    "changes": '"{block}" asked for other changes than expected',
    "no_end": '"{block}" kept the run from ending',
    "unknown": 'Something went wrong at "{block}"',
}
SERVED_SAID: Final[Mapping[str, str]] = {
    "empty": "found nothing new",
    "not_found": "could not find its source",
    "too_slow": "did not answer in time",
}
VARIED_SAID: Final[Mapping[ScenarioVariation, str]] = {
    "suffix": "a version with a suffix",
    "empty_field": "an empty field",
    "long_text": "very long text",
}
DETAIL_SAID: Final = " The records name {detail}."
NAME_IN_WORDS: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]*")
"""A name in what happened, as the runtime reads one (troubleshooting.DETAIL): a word that may
hold a slash, a dot, a dash or an underscore."""

type Access = Callable[[], Awaitable[ModelAccess | None]]


def connected_model(db: Database, models: ActiveModel) -> Access:
    """The model connected in Settings, read afresh for each ask."""

    async def access() -> ModelAccess | None:
        async with db.transaction("orchestration") as uow:
            return await models.access(uow)

    return access


class ScenarioAgents(Protocol):
    async def write_scenarios(
        self, request: ScenarioWriteRequest
    ) -> ScenarioWriteResult | AgentUnavailable | AgentRejected: ...

    async def explain_scenarios(
        self, request: ScenarioExplainRequest
    ) -> ScenarioExplainResult | AgentUnavailable | AgentRejected: ...


def specs_of(written: ScenariosWritten, reaching: bool = False) -> list[ScenarioSpec]:
    """The writer's picks as scenarios in PR 5's schema, each named by its kind. A read or Agent
    block it leaves out is served as its kind's template serves it. Scenarios written to reach
    blocks no scenario reached are named by how they play, so the same plays get the same name,
    which a fix or a refinement already holds (ADR 0054, section 7)."""
    specs = [
        ScenarioSpec(
            kind=w.kind,
            name=w.kind,
            reads={r.block: Play(serve=r.serve, sample=r.sample, vary=r.vary) for r in w.reads},
            agents={name: Reply(serve="too_slow") for name in w.slow_agents},
        )
        for w in written.scenarios
    ]
    if not reaching:
        return specs
    return [spec.model_copy(update={"name": reach_name(spec)}) for spec in specs]


def reach_name(spec: ScenarioSpec) -> str:
    """A scenario written to reach blocks, named by its plays: reach_ and twelve hex digits."""
    plays = spec.model_dump_json(include={"kind", "reads", "agents"})
    return f"reach_{hashlib.sha256(plays.encode()).hexdigest()[:12]}"


def _joined(parts: Sequence[str]) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def note_words(note: FailureNote, plays: Sequence[PlayOut]) -> str:
    """The one sentence people see for a failed scenario, written by code from the picks."""
    said = NOTE_SAID[note.kind].format(block=note.block)
    play = next((p for p in plays if p.block == note.source), None)
    if play is not None and play.serve == "varied" and play.vary:
        said += f' when "{play.block}" gave {_joined([VARIED_SAID[v] for v in play.vary])}'
    elif play is not None and play.serve in SERVED_SAID:
        said += f' when "{play.block}" {SERVED_SAID[play.serve]}'
    detail = "" if note.detail is None else DETAIL_SAID.format(detail=note.detail)
    return f"{said}.{detail}"


def _failed(result: ResultOut) -> FailedScenario:
    return FailedScenario(
        name=result.name,
        kind=result.kind,
        ending=result.ending,
        stopped_at=result.stopped_at,
        expected=result.expected[:300],
        happened=result.happened[:STOP_MESSAGE_LIMIT],
        ran=result.ran[:MOST_RUN_BLOCKS],
        plays=[ScenarioPlay(block=p.block, serve=p.serve, vary=p.vary) for p in result.plays],
    )


def _fits(note: FailureNote, results: Mapping[str, ResultOut]) -> bool:
    """The runtime checked each pick. Code checks again that the note names a failed scenario, a
    block that ran or stopped it, a block the scenario played, and a whole name from what happened
    as the explainer was sent it, before it writes words."""
    result = results.get(note.scenario)
    if result is None or result.verdict != "failed":
        return False
    if note.block not in {*result.ran, result.stopped_at}:
        return False
    if note.source is not None and note.source not in {p.block for p in result.plays}:
        return False
    sent = result.happened[:STOP_MESSAGE_LIMIT]
    return note.detail is None or note.detail in _names(sent)


def _names(words: str) -> set[str]:
    return {name.rstrip("./-") for name in NAME_IN_WORDS.findall(words)}


class SimulationModel:
    def __init__(self, agents: ScenarioAgents, access: Access) -> None:
        self._agents = agents
        self._access = access

    async def write(
        self, plan: PlanOut, cover: Sequence[CoverBlock] = ()
    ) -> list[ScenarioSpec] | None:
        """The scenarios the model wrote for the plan, or None for code's templates: no model,
        a failed call, or an answer a check kept back. With `cover`, one to three scenarios that
        reach those blocks, or None when it wrote none."""
        model = await self._access()
        if model is None:
            return None
        try:
            request = ScenarioWriteRequest(
                cover=list(cover),
                model=model,
                blocks=[
                    ScenarioBlock(
                        name=b.name, role=b.role, answer=b.answer, plays=b.plays, varies=b.varies
                    )
                    for b in plan.blocks
                ],
                kinds=plan.kinds,
                samples=[
                    ScenarioSample(
                        id=s.id, answer=s.answer, block=s.block, items=s.items[:MOST_SAMPLE_ITEMS]
                    )
                    for s in plan.samples[:MOST_SAMPLES]
                ],
                within_seconds=WRITE_SECONDS,
            )
        except ValidationError:
            log.warning("The version's plan doesn't fit a scenario request, so no model is asked")
            return None
        match await self._agents.write_scenarios(request):
            case ScenariosWritten() as written:
                try:
                    return specs_of(written, reaching=bool(cover))
                except ValidationError:
                    log.warning("The written scenarios don't parse here, so the templates run")
                    return None
            case answer:
                log.info("The scenario writer fell back to the templates: %s", _why(answer))
                return None

    async def explain(self, results: Sequence[ResultOut]) -> dict[str, str]:
        """A plain sentence for each failed scenario the model could explain, by its name. A
        failure with none keeps code's own words."""
        plays = {r.name: r.plays for r in results}
        noted = await self.notes(results)
        return {name: note_words(note, plays[name]) for name, note in noted.items()}

    async def notes(self, results: Sequence[ResultOut]) -> dict[str, FailureNote]:
        """The picks for each failed scenario the model could explain, by its name, each checked
        again against its scenario's facts. A fix's coordinator reads them (ADR 0055, PR 5)."""
        failed = [r for r in results if r.verdict == "failed"][:MOST_FAILED]
        if not failed:
            return {}
        model = await self._access()
        if model is None:
            return {}
        try:
            request = ScenarioExplainRequest(
                model=model, failed=[_failed(r) for r in failed], within_seconds=EXPLAIN_SECONDS
            )
        except ValidationError:
            log.warning("The failed scenarios don't fit an explain request, so no model is asked")
            return {}
        answer = await self._agents.explain_scenarios(request)
        if not isinstance(answer, ScenariosExplained):
            log.info("The explainer explained nothing: %s", _why(answer))
            return {}
        by_name = {r.name: r for r in failed}
        return {note.scenario: note for note in answer.notes if _fits(note, by_name)}


def _why(answer: object) -> str:
    match answer:
        case AgentUnavailable(detail=detail) | AgentRejected(detail=detail):
            return detail
        case _:
            return type(answer).__name__
