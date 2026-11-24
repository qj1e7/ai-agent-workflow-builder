"""The Check of a workflow the Planner built from our blocks: its current version tried on practice
systems (ADR 0054, section 1, and "What every version chose").

A version is tried where the safety checker grades it safe. Every path that keeps a graded version
calls `claim` in its own transaction, which keeps the running row with the version, and `start`
once it commits: Set up, a new schedule, a version put back, a version published in n8n that the
sweep grades, a move to n8n, a restore and a drafted workflow's set-up. So a poll never reads a
new version as untried. Reading the Check never starts a try.

The try is the drafted card's (simulations.py): one try for each digest, Try again for Operators
only, and nothing written as a run or in the activity log. A pass turns nothing on, and Turn on
still runs the real test run.

A workflow made in n8n, the Software watchlist and a workflow on the shared n8n workflow have
nothing to try here: the Check says nothing of practice systems."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from platform_api.builder.simulation_views import UseCaseSimulationView
from platform_api.builder.simulations import (
    NO_SIMULATION,
    NOTHING_TO_TRY,
    SIMULATING,
    Claimed,
    Simulations,
)
from platform_api.builder.templates import AGENT_CARDS
from platform_api.db import Connection, Database
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

    async def claim(self, conn: Connection, use_case_id: str, now: datetime) -> Claimed | None:
        """The current version's running row, through the one claim, in the transaction that
        keeps the version the safety checker graded. None when it has nothing to try, or its
        digest has a try already. The caller starts it once the transaction commits."""
        current = await _current(conn, use_case_id)
        if current is None or current.document is None:
            return None
        return await self._simulations.claim(conn, current.document, now)

    async def start(self, claimed: Claimed | None) -> None:
        """Starts the try a version claimed, once its transaction committed."""
        await self._simulations.start(claimed)

    async def view(self, use_case_id: str, viewer: Principal) -> UseCaseSimulationView | None:
        """The current version's simulation. It only reads. None when there is no such
        workflow, or it was deleted."""
        async with self._db.connection("builder") as conn:
            current = await _current(conn, use_case_id)
        return None if current is None else await self._view(use_case_id, current, viewer)

    async def again(
        self, use_case_id: str, person: Principal, version: int
    ) -> UseCaseSimulationView | NotTried | None:
        """Tries the current version again, once it was never tried, wasn't run or didn't
        finish."""
        async with self._db.connection("builder") as conn:
            current = await _current(conn, use_case_id)
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


async def _current(conn: Connection, use_case_id: str) -> _Current | None:
    """The current version, with its document only when it is one to try: the Planner's own
    layout from our blocks, saved in n8n and graded safe. One graded Needs a fix or writes
    refused can't be turned on, so it isn't tried."""
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
        and row["grade"] == "safe"
    )
    return _Current(row["version"], row["document"] if tried else None)
