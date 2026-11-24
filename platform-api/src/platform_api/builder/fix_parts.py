"""What platform-api answers for a fix (ADR 0055, PR 5).

The coordinator runs in the agent runtime, which holds no simulation secret and can't reach the
simulation gateway (ADR 0054, "What the link chose"). So it asks platform-api, for one fix on one
stopped run, for four things:

- scenarios for the stopped version: code's template for each kind that applies, or, with
  Simulation mode's model turned on and the fix able to pay for it, the Scenario writer's;
- a simulation of a plan in those scenarios, with each run's grade, where it stopped, why, and
  what it reached, and, with the model on and paid for, the explainer's picks for each failure;
- the checker's grade of a plan;
- one of the fix's events, written on the stopped run.

Each plan is laid out first as any drafted plan is, with the yes before each write and the
platform's keys, so the simulation and the checker see what an Approver would approve. Nothing
here writes to a real system, stores a version, or turns anything on.

Each call carries a token for one fix on one stopped run. It ends a few minutes after the fix's
deadline, since after the deadline the hand-back for time is still written."""

import asyncio
import hashlib
import hmac
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import Field, StringConstraints

from platform_api.builder.layout import DraftedLayout, lay_out_drafted
from platform_api.monitoring import FixData, FixRefused
from platform_api.orchestration import (
    DIDNT_ANSWER,
    DONT_FIT,
    GITHUB_RELEASES,
    FailureNote,
    KnownOptions,
    NotSimulated,
    PlanOut,
    ResultOut,
    ScenarioSpec,
    SimulationOut,
    WorkflowPlan,
    add_yes,
    attach_keys,
    grade,
    version_of,
)
from platform_api.shared import RunId
from platform_api.wire import WireIn, WireModel

log = logging.getLogger(__name__)

FIX_TOKEN_HEADER: Final = "X-Fix-Token"
FIX_TOKEN_GRACE: Final = timedelta(minutes=5)
"""How long a fix's token lasts after its deadline, so the hand-back for time can be written."""
MOST_SECONDS: Final = 20 * 60
NOT_HERE: Final = "Simulation on practice systems isn't available here."
"""The Check card's words for a platform with no simulation gateway (ADR 0054, PR 7)."""

type FixId = Annotated[str, StringConstraints(pattern=r"^fix_[0-9A-Za-z]{1,40}$")]
type Document = dict[str, Any]


def fix_token(key: str, run_id: str, fix_id: str, ends_by: datetime) -> str:
    """The token for one fix on one stopped run, which ends FIX_TOKEN_GRACE after its deadline."""
    expires = int((ends_by + FIX_TOKEN_GRACE).timestamp())
    return f"{expires}.{_signature(key, run_id, fix_id, expires)}"


def fix_token_ok(key: str, run_id: str, fix_id: str, token: str, now: datetime) -> bool:
    expires_text, dot, signature = token.partition(".")
    if dot != "." or not expires_text.isdigit():
        return False
    expires = int(expires_text)
    if int(now.timestamp()) >= expires:
        return False
    return hmac.compare_digest(signature, _signature(key, run_id, fix_id, expires))


def _signature(key: str, run_id: str, fix_id: str, expires: int) -> str:
    message = f"fix|{run_id}|{fix_id}|{expires}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


# What the coordinator sends and gets back


Seconds = Annotated[float, Field(gt=0, le=MOST_SECONDS)]


class FixScenariosIn(WireIn):
    version: WorkflowPlan = Field(description="The stopped version, with each key kept out.")
    cover: list[str] = Field(
        default_factory=list[str],
        max_length=100,
        description="Blocks no scenario reached. The Scenario writer can't aim at a block yet, so "
        "an ask to cover blocks finds nothing new.",
    )
    may_ask_model: bool = Field(
        default=False,
        description="Whether the fix can still pay for the writer's call at its most.",
    )
    within_seconds: Seconds


class FixScenariosOut(WireModel):
    scenarios: list[ScenarioSpec]
    asked_model: bool = Field(description="Whether the Scenario writer's model was asked.")


class FixSimulationIn(WireIn):
    version: WorkflowPlan = Field(description="The plan to try: a draft, or the stopped version.")
    scenarios: list[ScenarioSpec] = Field(min_length=1, max_length=20)
    may_ask_model: bool = Field(
        default=False,
        description="Whether the fix can still pay for the explainer's call at its most.",
    )
    within_seconds: Seconds


class FixNoteOut(WireModel):
    """The explainer's picks for one failure, checked against the scenario's facts."""

    block: str
    kind: str
    source: str | None


class FixResultOut(WireModel):
    name: str
    verdict: Literal["passed", "failed", "not_tried"]
    step: str | None = Field(description="The block where the run stopped, if one did.")
    why: str | None = Field(description="How a failed run ended, as code read it.")
    reached: list[str] = Field(description="What the run reached, as the gateway's words say it.")
    note: FixNoteOut | None = Field(description="The explainer's picks, when it was asked.")


class FixSimulationOut(WireModel):
    results: list[FixResultOut]
    not_reached: list[str] = Field(description="Blocks that could run, but no scenario reached.")
    named: list[str] = Field(description="What the plan names in plain values.")
    asked_model: bool = Field(description="Whether the explainer's model was asked.")


class FixCheckOut(WireModel):
    passes: bool = Field(description="The checker graded the laid-out plan safe.")
    findings: list[str] = Field(description="The rule of each finding, when it didn't.")


# What platform-api answers with


class Facts(Protocol):
    async def known(self, adding: Mapping[str, Sequence[str]]) -> KnownOptions: ...


class ErrorWorkflow(Protocol):
    async def error_workflow_id(self) -> str | None: ...


class Gateway(Protocol):
    async def plan(self, version: Mapping[str, Any]) -> PlanOut | NotSimulated: ...

    async def simulate(
        self,
        version: Mapping[str, Any],
        scenarios: Sequence[ScenarioSpec] | None = None,
        *,
        fall_back: bool = False,
    ) -> SimulationOut | NotSimulated: ...


class Model(Protocol):
    """The Scenario writer and the explainer, as SimulationModel asks them."""

    async def write(self, plan: PlanOut) -> list[ScenarioSpec] | None: ...

    async def notes(self, results: Sequence[ResultOut]) -> dict[str, FailureNote]: ...


class FixLog(Protocol):
    async def note_fix(self, run_id: RunId, data: FixData) -> FixRefused | None: ...


@dataclass(frozen=True)
class Laid:
    document: Document
    known: KnownOptions
    error_workflow: str


class FixLayouts:
    """A fix's plan laid out as any drafted plan is: what every layout adds, the yes before each
    write, and the platform's keys."""

    def __init__(
        self, facts: Facts, n8n: ErrorWorkflow | None, public_base_url: str, time_zone: str
    ) -> None:
        self._facts = facts
        self._n8n = n8n
        self._link = f"{public_base_url.rstrip('/')}/workflows"
        self.time_zone = time_zone

    async def laid(self, fix_id: str, plan: WorkflowPlan) -> Laid | None:
        """None for a plan the layout can't read."""
        error_workflow = (None if self._n8n is None else await self._n8n.error_workflow_id()) or ""
        repos = [s.value for s in plan.settings if s.kind == "repository" and s.value]
        known = await self._facts.known({GITHUB_RELEASES: repos})
        values = {s.id: s.value for s in plan.settings if s.value is not None}
        layout = DraftedLayout(fix_id, self._link, plan, error_workflow, self.time_zone)
        try:
            document = attach_keys(
                add_yes(lay_out_drafted(layout, values), fix_id).document, known.keys
            )
        except (ValueError, KeyError, TypeError) as error:
            log.warning("fix %s: a plan the layout can't read: %s", fix_id, type(error).__name__)
            return None
        return Laid(document, known, error_workflow)


class FixParts:
    def __init__(
        self, layouts: FixLayouts, gateway: Gateway | None, model: Model | None, log: FixLog
    ) -> None:
        self._layouts = layouts
        self._gateway = gateway
        self._model = model
        self._log = log

    async def scenarios(self, fix_id: str, asked: FixScenariosIn) -> FixScenariosOut | NotSimulated:
        """Code's template for each kind that applies to the stopped version, named by its kind,
        or the Scenario writer's when the model is on and paid for."""
        if asked.cover:
            return FixScenariosOut(scenarios=[], asked_model=False)
        if self._gateway is None:
            return NotSimulated(NOT_HERE, again=False)
        gateway = self._gateway
        laid = await self._layouts.laid(fix_id, asked.version)
        if laid is None:
            return NotSimulated(DONT_FIT, again=False)
        asks = self._model is not None and asked.may_ask_model
        try:
            async with asyncio.timeout(asked.within_seconds):
                plan = await gateway.plan(version_of(laid.document))
                if isinstance(plan, NotSimulated):
                    return plan
                written = None if self._model is None or not asks else await self._model.write(plan)
        except TimeoutError:
            return NotSimulated(DIDNT_ANSWER, again=True)
        specs = written or [ScenarioSpec(kind=kind, name=kind) for kind in plan.kinds]
        return FixScenariosOut(scenarios=specs, asked_model=asks)

    async def simulate(
        self, fix_id: str, asked: FixSimulationIn
    ) -> FixSimulationOut | NotSimulated:
        """The plan run in the scenarios exactly as given: one that doesn't fit is refused, never
        swapped for code's templates, so each grade is the coordinator's own scenario's."""
        if self._gateway is None:
            return NotSimulated(NOT_HERE, again=False)
        gateway = self._gateway
        laid = await self._layouts.laid(fix_id, asked.version)
        if laid is None:
            return NotSimulated(DONT_FIT, again=False)
        notes: dict[str, FailureNote] = {}
        asks = False
        try:
            async with asyncio.timeout(asked.within_seconds):
                done = await gateway.simulate(version_of(laid.document), asked.scenarios)
                if isinstance(done, NotSimulated):
                    return done
                failed = any(r.verdict == "failed" for r in done.results)
                asks = self._model is not None and asked.may_ask_model and failed
                if self._model is not None and asks:
                    notes = await self._model.notes(done.results)
        except TimeoutError:
            return NotSimulated(DIDNT_ANSWER, again=True)
        return FixSimulationOut(
            results=[_result(r, notes.get(r.name)) for r in done.results],
            not_reached=list(done.coverage.not_reached),
            named=list(done.named),
            asked_model=asks,
        )

    async def check(self, fix_id: str, version: WorkflowPlan) -> FixCheckOut:
        """The checker's grade of the laid-out plan, as it grades any version."""
        laid = await self._layouts.laid(fix_id, version)
        if laid is None:
            return FixCheckOut(passes=False, findings=["unreadable"])
        graded = grade(laid.document, laid.error_workflow, self._layouts.time_zone, laid.known)
        findings = list(dict.fromkeys(str(f.rule) for f in graded.findings))
        return FixCheckOut(passes=graded.grade == "safe", findings=findings)

    async def note(self, run_id: RunId, data: FixData) -> str | None:
        """Writes one event of the fix on the stopped run, or gives the log's refusal."""
        refused = await self._log.note_fix(run_id, data)
        return None if refused is None else refused.why


def _result(result: ResultOut, note: FailureNote | None) -> FixResultOut:
    return FixResultOut(
        name=result.name,
        verdict=result.verdict,
        step=result.stopped_at,
        why=result.ending if result.verdict == "failed" else None,
        reached=list(result.reached),
        note=None
        if note is None
        else FixNoteOut(block=note.block, kind=note.kind, source=note.source),
    )
