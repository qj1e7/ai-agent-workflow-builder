"""The Check of a workflow the Planner built from our blocks: its current version tried on practice
systems (ADR 0054, section 1, and "What every version chose").

A version is tried the first time its Check is read, by its digest. One place covers every way
such a version is made: Set up, a new schedule, Done in n8n and a restore. The safety checker
graded each of them as it was kept, so its grade is there by then. The read keeps the running
row before it answers, so it never shows the version as untried. The try is the drafted card's
(simulations.py): one try for each digest, Try again for Operators only, and nothing written as a
run or in the activity log. A pass turns nothing on, and Turn on still runs the real test run.

A workflow made in n8n, the Software watchlist and a workflow on the shared n8n workflow have
nothing to try here: the Check says nothing of practice systems."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from platform_api.builder.simulation_views import UseCaseSimulationView
from platform_api.builder.simulations import (
    NO_SIMULATION,
    NOTHING_TO_TRY,
    SIMULATING,
    Simulations,
)
from platform_api.builder.templates import AGENT_CARDS
from platform_api.db import Database
from platform_api.orchestration import workflow_digest
from platform_api.shared import Principal, Role

CHANGED: Final = "It changed since you opened it. Open it again."


@dataclass(frozen=True)
class NotTried:
    """Why Try again started nothing, in words to show."""

    words: str


@dataclass(frozen=True)
class _Current:
    version: int
    document: Mapping[str, Any] | None


class UseCaseSimulations:
    def __init__(self, db: Database, simulations: Simulations) -> None:
        self._db = db
        self._simulations = simulations

    async def view(self, use_case_id: str, viewer: Principal) -> UseCaseSimulationView | None:
        """The current version's simulation, started on its first read. None when there is no
        such workflow, or it was deleted."""
        current = await self._current(use_case_id)
        if current is None:
            return None
        shown = await self._view(use_case_id, current, viewer)
        if current.document is None or shown.simulation is None:
            return shown
        if shown.simulation.state != "not_started":
            return shown
        # Never tried: its first try starts here, and the answer reads it running.
        await self._simulations.begin(workflow_digest(current.document), current.document)
        return await self._view(use_case_id, current, viewer)

    async def again(
        self, use_case_id: str, person: Principal, version: int
    ) -> UseCaseSimulationView | NotTried | None:
        """Tries the current version again, once it was never tried, wasn't run or didn't
        finish."""
        current = await self._current(use_case_id)
        if current is None:
            return None
        if version != current.version:
            return NotTried(CHANGED)
        if not self._simulations.available:
            return NotTried(NO_SIMULATION)
        shown = (await self._view(use_case_id, current, person)).simulation
        if current.document is None or shown is None or not shown.can_try_again:
            running = shown is not None and shown.state == "running"
            return NotTried(SIMULATING if running else NOTHING_TO_TRY)
        if not await self._simulations.again(workflow_digest(current.document), current.document):
            return NotTried(SIMULATING)
        return await self._view(use_case_id, current, person)

    async def _view(
        self, use_case_id: str, current: _Current, viewer: Principal
    ) -> UseCaseSimulationView:
        simulation = (
            None
            if current.document is None
            else await self._simulations.view(
                workflow_digest(current.document), Role.OPERATOR in viewer.roles
            )
        )
        return UseCaseSimulationView(
            use_case_id=use_case_id, version=current.version, simulation=simulation
        )

    async def _current(self, use_case_id: str) -> _Current | None:
        """The current version, with its document only when it is one to try: the Planner's
        own layout from our blocks, saved in n8n and graded."""
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT v.version, v.template, v.document, v.grade, u.made_in_n8n_by"
                    " FROM builder.use_cases u JOIN builder.use_case_versions v"
                    " ON v.use_case_id = u.use_case_id AND v.version = u.current_version"
                    " WHERE u.use_case_id = %s AND u.deleted_at IS NULL",
                    (use_case_id,),
                )
            ).fetchone()
        if row is None:
            return None
        tried = (
            row["template"] == AGENT_CARDS.key
            and row["made_in_n8n_by"] is None
            and row["document"] is not None
            and row["grade"] is not None
        )
        return _Current(row["version"], row["document"] if tried else None)
