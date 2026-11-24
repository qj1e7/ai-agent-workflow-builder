"""A drafted revision tried on practice systems (ADR 0054, PR 7). Once the safety checker has
graded a revision with nothing still needed, code runs it through its scenarios in the simulation
n8n, in the background, and keeps code's grades by the revision's digest. The card reads them
back for the newest revision's digest only, so a changed version never shows an older result.

A simulation is not a run. It never writes a run or an activity event, and never stands in for
the test run that Turn on starts. A failed case blocks nothing: the card leads with it, and the
person decides. Where there is no simulation n8n, the card says so and claims no result, and a
try that runs past its limit shows as not finished, never as running for good."""

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final, Protocol, cast

from platform_api.builder.drafted_views import (
    DraftedSimulationView,
    SimulatedBlockView,
    SimulatedCaseView,
)
from platform_api.db import Connection, Database, json
from platform_api.orchestration import (
    DIDNT_ANSWER,
    SIMULATION_SECONDS,
    WAIT_LIMIT_SECONDS,
    NotSimulated,
    Simulated,
    SimulationOut,
)

log = logging.getLogger(__name__)

NOT_TRIED_YET: Final = "It hasn't been tried on practice systems yet."
NO_SIMULATION: Final = "Simulation on practice systems isn't available here."
TRYING_NOW: Final = "It's being tried on practice systems now."


class Simulating(Protocol):
    async def run(self, version: Mapping[str, Any]) -> Simulated | NotSimulated: ...


class DraftedSimulations:
    def __init__(
        self,
        db: Database,
        driver: Simulating | None,
        *,
        limit: timedelta = timedelta(seconds=SIMULATION_SECONDS),
    ) -> None:
        self._db = db
        self._driver = driver
        self._limit = limit
        self._running: dict[tuple[str, str], asyncio.Task[None]] = {}

    @property
    def available(self) -> bool:
        """Whether there is a simulation n8n here."""
        return self._driver is not None

    def _going(self, drafted_id: str, digest: str) -> bool:
        task = self._running.get((drafted_id, digest))
        return task is not None and not task.done()

    async def begin(
        self,
        drafted_id: str,
        revision: int,
        digest: str,
        document: Mapping[str, Any],
        *,
        again: bool = False,
    ) -> bool:
        """Starts trying the version in the background, once for its digest, or again when the
        last try wasn't run or ran past its limit. False when nothing was started."""
        driver = self._driver
        if driver is None or self._going(drafted_id, digest):
            return False
        async with self._db.transaction("builder") as uow:
            started_at = await _insert(uow.conn, drafted_id, revision, digest, uow.now)
            if started_at is None and again:
                row = await (
                    await uow.conn.execute(
                        "UPDATE builder.drafted_simulations SET state = 'running',"
                        " started_at = %s, finished_at = NULL, result = NULL, said = NULL,"
                        " again = false WHERE drafted_id = %s AND digest = %s"
                        " AND (state = 'not_run' OR (state = 'running' AND started_at < %s))"
                        " RETURNING started_at",
                        (uow.now, drafted_id, digest, uow.now - self._limit),
                    )
                ).fetchone()
                started_at = None if row is None else cast(datetime, row["started_at"])
        if started_at is None:
            return False
        task = asyncio.create_task(
            self._run(driver, drafted_id, digest, dict(document), started_at)
        )
        self._running[(drafted_id, digest)] = task
        task.add_done_callback(lambda _: self._forget(drafted_id, digest, task))
        return True

    def _forget(self, drafted_id: str, digest: str, task: asyncio.Task[None]) -> None:
        if self._running.get((drafted_id, digest)) is task:
            del self._running[(drafted_id, digest)]

    def cancel(self) -> None:
        """Stops every simulation this process started, as a shutdown does. Each stays running
        in the table, so past its limit the card shows it as not finished."""
        for task in self._running.values():
            task.cancel()

    async def settle(self) -> None:
        """Waits for every simulation this process started, as a test or a shutdown does."""
        while going := [task for task in self._running.values() if not task.done()]:
            await asyncio.gather(*going, return_exceptions=True)

    async def _run(
        self,
        driver: Simulating,
        drafted_id: str,
        digest: str,
        version: dict[str, Any],
        started_at: datetime,
    ) -> None:
        try:
            done = await asyncio.wait_for(driver.run(version), self._limit.total_seconds())
        except TimeoutError:
            # Kept as it is: past its limit the card shows it as not finished.
            log.warning("the simulation of %s ran past its limit", drafted_id)
            return
        except Exception as error:
            # Only the error's type: its words could hold the version's.
            log.error("the simulation of %s failed: %s", drafted_id, type(error).__name__)
            done = NotSimulated(DIDNT_ANSWER, again=True)
        try:
            await self._keep(drafted_id, digest, started_at, done)
        except Exception as error:
            log.error("could not keep the simulation of %s: %s", drafted_id, type(error).__name__)

    async def _keep(
        self, drafted_id: str, digest: str, started_at: datetime, done: Simulated | NotSimulated
    ) -> None:
        """Kept only for the try it began, so an older try never overwrites a newer one."""
        match done:
            case Simulated(out=out, notes=notes):
                state, result, said, again = "done", _result(out, notes), None, False
            case NotSimulated(words=words, again=again):
                state, result, said = "not_run", None, words
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.drafted_simulations SET state = %s, finished_at = %s,"
                " result = %s, said = %s, again = %s WHERE drafted_id = %s AND digest = %s"
                " AND state = 'running' AND started_at = %s",
                (
                    state,
                    uow.now,
                    None if result is None else json(result),
                    said,
                    again,
                    drafted_id,
                    digest,
                    started_at,
                ),
            )

    async def view(self, drafted_id: str, digest: str, operator: bool) -> DraftedSimulationView:
        """The newest revision's simulation, by its digest, as this person may act on it."""
        empty = DraftedSimulationView(
            state="unavailable",
            started_at=None,
            case_seconds=WAIT_LIMIT_SECONDS,
            tried=0,
            passed=0,
            cases=[],
            not_tried=[],
            said=None,
            can_try_again=False,
        )
        if not self.available:
            return empty
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT state, started_at, result, said, again"
                    " FROM builder.drafted_simulations WHERE drafted_id = %s AND digest = %s",
                    (drafted_id, digest),
                )
            ).fetchone()
        if row is None:
            return empty.model_copy(
                update={"state": "not_run", "said": NOT_TRIED_YET, "can_try_again": operator}
            )
        started_at = cast(datetime, row["started_at"])
        at = {"started_at": started_at}
        match row["state"]:
            case "running" if self._db.clock() - started_at > self._limit:
                return empty.model_copy(
                    update={**at, "state": "not_finished", "can_try_again": operator}
                )
            case "running":
                return empty.model_copy(update={**at, "state": "running"})
            case "not_run":
                return empty.model_copy(
                    update={
                        **at,
                        "state": "not_run",
                        "said": row["said"],
                        "can_try_again": operator and bool(row["again"]),
                    }
                )
            case _:
                return _done(empty.model_copy(update=at), row["result"])


async def _insert(
    conn: Connection, drafted_id: str, revision: int, digest: str, now: datetime
) -> datetime | None:
    """A first try for the digest, or None when it has one already."""
    row = await (
        await conn.execute(
            "INSERT INTO builder.drafted_simulations (drafted_id, digest, revision, state,"
            " started_at) VALUES (%s, %s, %s, 'running', %s)"
            " ON CONFLICT (drafted_id, digest) DO NOTHING RETURNING started_at",
            (drafted_id, digest, revision, now),
        )
    ).fetchone()
    return None if row is None else cast(datetime, row["started_at"])


def _result(out: SimulationOut, notes: Mapping[str, str]) -> dict[str, Any]:
    """What the card shows of code's grades, with the explainer's sentence beside a failure."""
    return {
        "tried": out.tried,
        "passed": out.passed,
        "cases": [
            {
                "kind": r.kind,
                "verdict": r.verdict,
                "expected": r.expected,
                "happened": r.happened,
                "note": notes.get(r.name) if r.verdict == "failed" else None,
            }
            for r in out.results
        ],
        "not_tried": [{"block": n.block, "why": n.why} for n in out.coverage.not_tried],
    }


def _done(view: DraftedSimulationView, result: Mapping[str, Any]) -> DraftedSimulationView:
    return view.model_copy(
        update={
            "state": "done",
            "tried": result["tried"],
            "passed": result["passed"],
            "cases": [SimulatedCaseView.model_validate(c) for c in result["cases"]],
            "not_tried": [SimulatedBlockView.model_validate(n) for n in result["not_tried"]],
        }
    )
