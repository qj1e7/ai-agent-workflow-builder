"""platform-api's side of a simulation (ADR 0054, PR 7). It sends one workflow version to the
simulation gateway's signed routes and reads back code's grades. It never reaches the simulation
n8n itself, and holds only the gateway's address and the simulation's start secret.

Without the model setting, the gateway runs code's six templates and no model is asked, so a
simulation costs nothing. With it, the scenario writer writes the scenarios from the version's
plan and they go with fall_back, so code's templates run in place of any that don't fit, and the
explainer explains each failed scenario in one sentence code writes (simulation_model.py). The
grade stays the verdict.

A simulation is not a run: nothing here writes a run or an activity event."""

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import httpx
from pydantic import ValidationError

from platform_api.orchestration.scenario_grades import WAIT_LIMIT_SECONDS
from platform_api.orchestration.scenarios import KINDS, ScenarioSpec
from platform_api.orchestration.simulation_gateway import (
    AHEAD,
    EXPIRES_HEADER,
    SIGNATURE_HEADER,
    CopyRefused,
    PlanOut,
    ResultOut,
    SimulationOut,
    control_signature,
)

log = logging.getLogger(__name__)

SIMULATION_SECONDS: Final = len(KINDS) * WAIT_LIMIT_SECONDS + 120
"""The most a whole simulation takes: each kind's wait for its run to end, and two minutes for
the copies, the plan and the explainer."""
DIDNT_ANSWER: Final = "The practice systems didn't answer, so nothing was tried."
CANT_RUN: Final = "Nothing was tried. Practice systems can't run {blocks}."
DONT_FIT: Final = "Nothing was tried. The cases don't fit this version."
VERSION_FIELDS: Final = ("name", "nodes", "connections", "settings")
"""What a simulation reads of a version. Its pinned output never goes: a copy takes only a
scenario's (ADR 0054, PR 5)."""


@dataclass(frozen=True)
class NotSimulated:
    """Why nothing was tried, in words the card shows, and whether trying again may help."""

    words: str
    again: bool


@dataclass(frozen=True)
class Simulated:
    out: SimulationOut
    notes: Mapping[str, str] = field(default_factory=dict[str, str])
    """The explainer's sentence for each failed scenario it explained, by the scenario's name."""


class Gateway(Protocol):
    async def plan(self, version: Mapping[str, Any]) -> PlanOut | NotSimulated: ...

    async def simulate(
        self,
        version: Mapping[str, Any],
        scenarios: Sequence[ScenarioSpec] | None = None,
        *,
        fall_back: bool = False,
    ) -> SimulationOut | NotSimulated: ...


class Writing(Protocol):
    """The scenario writer and the explainer, as SimulationModel asks them."""

    async def write(self, plan: PlanOut) -> list[ScenarioSpec] | None: ...

    async def explain(self, results: Sequence[ResultOut]) -> dict[str, str]: ...


def version_of(document: Mapping[str, Any]) -> dict[str, Any]:
    return {name: document[name] for name in VERSION_FIELDS if name in document}


def _quoted(names: Sequence[str]) -> str:
    quoted = [f'"{name}"' for name in names]
    return quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} or {quoted[-1]}"


class SimulationClient:
    """The gateway's control routes, each signed with the simulation's start secret."""

    def __init__(
        self,
        base_url: str,
        start_secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = SIMULATION_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = start_secret
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._clock = clock

    async def close(self) -> None:
        await self._client.aclose()

    async def plan(self, version: Mapping[str, Any]) -> PlanOut | NotSimulated:
        answer = await self._post("/simulation/v1/plans", {"version": version_of(version)})
        if isinstance(answer, NotSimulated):
            return answer
        try:
            return PlanOut.model_validate_json(answer.content)
        except ValidationError:
            log.warning("the simulation gateway answered a plan platform-api can't read")
            return NotSimulated(DIDNT_ANSWER, again=True)

    async def simulate(
        self,
        version: Mapping[str, Any],
        scenarios: Sequence[ScenarioSpec] | None = None,
        *,
        fall_back: bool = False,
    ) -> SimulationOut | NotSimulated:
        body = {
            "version": version_of(version),
            "scenarios": None
            if scenarios is None
            else [s.model_dump(mode="json") for s in scenarios],
            "fall_back": fall_back,
        }
        answer = await self._post("/simulation/v1/simulations", body)
        if isinstance(answer, NotSimulated):
            return answer
        try:
            return SimulationOut.model_validate_json(answer.content)
        except ValidationError:
            log.warning("the simulation gateway answered a simulation platform-api can't read")
            return NotSimulated(DIDNT_ANSWER, again=True)

    async def _post(self, path: str, body: Mapping[str, Any]) -> httpx.Response | NotSimulated:
        content = json.dumps(body, separators=(",", ":")).encode()
        expires = int(self._clock()) + AHEAD // 2
        headers = {
            "Content-Type": "application/json",
            EXPIRES_HEADER: str(expires),
            SIGNATURE_HEADER: control_signature(self._secret, "POST", path, expires, content),
        }
        try:
            answer = await self._client.post(
                f"{self._base_url}{path}", content=content, headers=headers
            )
        except httpx.HTTPError as error:
            log.warning("the simulation gateway did not answer: %s", type(error).__name__)
            return NotSimulated(DIDNT_ANSWER, again=True)
        if answer.status_code == 422:
            return _refused(answer)
        if answer.status_code != 200:
            log.warning("the simulation gateway answered %d", answer.status_code)
            return NotSimulated(DIDNT_ANSWER, again=True)
        return answer


def _refused(answer: httpx.Response) -> NotSimulated:
    """A version the mock setup refuses names each block it can't run. Anything else that fits
    no scenario is the cases'. Neither changes on a second try."""
    try:
        refused = CopyRefused.model_validate_json(answer.content)
    except ValidationError:
        return NotSimulated(DONT_FIT, again=False)
    names = list(dict.fromkeys(b.block for b in refused.blocks))
    if not names:
        return NotSimulated(DONT_FIT, again=False)
    return NotSimulated(CANT_RUN.format(blocks=_quoted(names)), again=False)


class SimulationDriver:
    def __init__(self, gateway: Gateway, model: Writing | None = None) -> None:
        self._gateway = gateway
        self._model = model

    async def run(self, version: Mapping[str, Any]) -> Simulated | NotSimulated:
        scenarios: list[ScenarioSpec] | None = None
        if self._model is not None:
            plan = await self._gateway.plan(version)
            if isinstance(plan, PlanOut):
                scenarios = await self._model.write(plan)
        done = await self._gateway.simulate(version, scenarios, fall_back=scenarios is not None)
        if isinstance(done, NotSimulated):
            return done
        if self._model is None:
            return Simulated(done)
        return Simulated(done, await self._model.explain(done.results))
