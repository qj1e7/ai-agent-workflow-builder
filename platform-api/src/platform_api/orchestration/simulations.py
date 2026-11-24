"""A simulation (ADR 0054): one workflow version run through its scenarios in the simulation n8n,
each graded by code. It runs in the simulation gateway, which holds the simulation n8n's owner,
and reaches nothing else but mock GitHub.

For each scenario, in turn:

1. the mock setup makes a copy of the version with the scenario's pins (mock_setup.py);
2. mock GitHub is set for the scenario, when a block reads it;
3. the gateway issues a start for the scenario, and n8n runs the copy by hand from it;
4. code waits for the run to end, reads the gateway's record and n8n's, and grades them
   (scenario_grades.py);
5. the copy is deleted, and mock GitHub set back, whatever happened, since nothing else removes
   either.

A scenario that no block can play is not run, and shows as not tried. One simulation runs at a
time, since mock GitHub serves one scenario at a time.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

import httpx

from platform_api.orchestration.mock_setup import BlockMode, MockSetups, SetupRefused
from platform_api.orchestration.n8n import ExecutionRecord, N8nError
from platform_api.orchestration.recorded_samples import RecordedSamples
from platform_api.orchestration.scenario_grades import (
    ENDED,
    WAIT_LIMIT_SECONDS,
    Coverage,
    Graded,
    coverage,
    grade,
    not_tried,
)
from platform_api.orchestration.scenarios import (
    ScenarioSpec,
    SimulationPlan,
    Staged,
    check_all,
    kinds_that_apply,
    plan_of,
    stage,
    templates,
)
from platform_api.orchestration.simulated_calls import GitHubPlay, SimulatedCalls

log = logging.getLogger(__name__)

POLL_GAP: Final = 0.5
DONT_FIT: Final = "The scenarios don't fit this version, so nothing ran."
NOTHING_TO_RUN: Final = "There is no scenario to run."


class RunsByHand(Protocol):
    """The simulation n8n, as N8nApi reaches it with that n8n's own owner and API key."""

    async def run_draft(self, workflow_id: str, item: Mapping[str, Any]) -> str: ...

    async def execution(self, execution_id: str, data: bool = True) -> ExecutionRecord | None: ...

    async def delete(self, workflow_id: str) -> None: ...


class GitHubPlays(Protocol):
    async def play(self, play: GitHubPlay | None) -> None: ...


@dataclass(frozen=True)
class SimulationRefused:
    problems: tuple[str, ...]
    detail: str = DONT_FIT


@dataclass(frozen=True)
class Simulation:
    results: tuple[Graded, ...]
    coverage: Coverage
    blocks: tuple[BlockMode, ...]
    """How the copies ran each block of the version."""

    @property
    def tried(self) -> int:
        return sum(1 for graded in self.results if graded.verdict != "not_tried")

    @property
    def passed(self) -> int:
        return sum(1 for graded in self.results if graded.verdict == "passed")


class Simulations:
    def __init__(
        self,
        setups: MockSetups,
        calls: SimulatedCalls,
        n8n: RunsByHand,
        github: GitHubPlays | None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        wait_limit: float = WAIT_LIMIT_SECONDS,
    ) -> None:
        self._setups = setups
        self._calls = calls
        self._n8n = n8n
        self._github = github
        self._sleep = sleep
        self._clock = clock
        self._wait_limit = wait_limit
        self._lock = asyncio.Lock()

    async def simulate(
        self,
        version: Mapping[str, Any],
        scenarios: Sequence[ScenarioSpec] | None,
        samples: RecordedSamples,
    ) -> Simulation | SimulationRefused | SetupRefused:
        """Runs the given scenarios, or code's templates when None. Nothing is made when the
        mock setup refuses the version or a scenario doesn't fit it."""
        modes = self._setups.modes(version)
        if isinstance(modes, SetupRefused):
            return modes
        plan = plan_of(version, modes)
        if isinstance(plan, str):
            return SimulationRefused((plan,))
        specs = templates(plan, samples) if scenarios is None else tuple(scenarios)
        problems = check_all(specs, plan, samples) if specs else (NOTHING_TO_RUN,)
        if problems:
            return SimulationRefused(problems)
        async with self._lock:
            results: list[Graded] = []
            for spec in specs:
                results.append(await self._one(version, plan, stage(spec, plan, samples)))
        found = coverage(plan, results, kinds_that_apply(plan))
        return Simulation(tuple(results), found, modes)

    async def _one(
        self, version: Mapping[str, Any], plan: SimulationPlan, staged: Staged
    ) -> Graded:
        if not staged.runs:
            return not_tried(staged)
        copied = await self._setups.copy(version, staged.pins)
        if isinstance(copied, SetupRefused):
            raise AssertionError(f"the mock setup refused the pins of {staged.name}")
        github = None if staged.github is None else self._github
        try:
            if github is not None:
                await github.play(staged.github)
            run = self._calls.start(copied.workflow_id, staged.gateway)
            item = {"nonce": run.nonce, "kind": "test", "workflow_id": copied.workflow_id}
            execution = await self._n8n.run_draft(copied.workflow_id, item)
            ended = await self._ended(execution)
            return grade(plan, staged, self._calls.run(run.nonce), ended)
        finally:
            await self._remove(copied.workflow_id)
            if github is not None:
                await github.play(None)

    async def _ended(self, execution: str) -> ExecutionRecord | None:
        """n8n's record with its data, once the run ends or the wait is over."""
        deadline = self._clock() + self._wait_limit
        while True:
            found = await self._n8n.execution(execution, data=False)
            if (found is not None and found.status in ENDED) or self._clock() > deadline:
                break
            await self._sleep(POLL_GAP)
        return await self._n8n.execution(execution, data=True)

    async def _remove(self, workflow_id: str) -> None:
        try:
            await self._n8n.delete(workflow_id)
        except N8nError, httpx.HTTPError:
            log.warning("could not delete the simulation's copy %s", workflow_id)
