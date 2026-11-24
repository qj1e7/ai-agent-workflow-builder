"""A workflow version tried on practice systems (ADR 0054). Once the safety checker has graded a
version, code runs it through its scenarios in the simulation n8n, in the background, and keeps
code's grades by the version's digest. A Check card reads them back for the digest of the version
it shows, so a changed version never shows an older result. A digest is tried once, whichever
workflow holds it: a drafted revision and the workflow it is set up as share one try.

A version's running row is written in the transaction that keeps it (`claim`), and the
simulation starts once it commits (`start`), so a poll never reads a new version as untried.

A simulation is not a run. It never writes a run or an activity event, and never stands in for
the test run that Turn on starts. A failed case blocks nothing: the card leads with it, and the
person decides. Where there is no simulation n8n, the card says so and claims no result, and a
try that runs past its limit counts as ended: the card shows it as not finished, never as
running for good."""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Protocol, cast

from platform_api.builder.simulation_views import (
    SimulatedBlockView,
    SimulatedCaseView,
    SimulationView,
)
from platform_api.db import Connection, Database, json
from platform_api.orchestration import (
    DIDNT_ANSWER,
    SIMULATION_SECONDS,
    WAIT_LIMIT_SECONDS,
    NotSimulated,
    Simulated,
    SimulationOut,
    workflow_digest,
)

log = logging.getLogger(__name__)

NO_SIMULATION: Final = "Simulation on practice systems isn't available here."
SIMULATING: Final = "Trying it on practice systems."
"""The running state's one wording, which the card shows too."""
NOTHING_TO_TRY: Final = "There's nothing to try again on practice systems."


@dataclass(frozen=True)
class Claimed:
    """A version's try, claimed in the transaction that keeps the version and started after."""

    digest: str
    document: Mapping[str, Any]
    started_at: datetime


class Simulating(Protocol):
    async def run(self, version: Mapping[str, Any]) -> Simulated | NotSimulated: ...


def _short(digest: str) -> str:
    """Enough of a digest to name its try in a log line."""
    return digest[:12]


class Simulations:
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
        self._closed = False
        self._running: dict[str, tuple[asyncio.Task[None], datetime]] = {}

    @property
    def available(self) -> bool:
        """Whether there is a simulation n8n here."""
        return self._driver is not None

    def _going(self, digest: str) -> bool:
        """A try still under way. Past its limit it counts as ended, whatever its task does."""
        going = self._running.get(digest)
        if going is None:
            return False
        task, started_at = going
        return not task.done() and self._db.clock() - started_at <= self._limit

    async def claim(
        self, conn: Connection, document: Mapping[str, Any], now: datetime
    ) -> Claimed | None:
        """The one claim for every version, a drafted revision's and a workflow's: the running
        row for its digest's first try, in the transaction that keeps the version. None where
        there is no simulation n8n, once shutdown began, or when the digest has a try already.
        The caller starts it once the transaction commits."""
        if self._driver is None or self._closed:
            return None
        digest = workflow_digest(document)
        started_at = await _insert(conn, digest, now)
        return None if started_at is None else Claimed(digest, dict(document), started_at)

    async def start(self, claimed: Claimed | None) -> None:
        """Runs the try a claim began, in the background. Should that fail, its row reads as not
        finished once past the limit, with Try again."""
        driver = self._driver
        if claimed is None or driver is None or self._closed:
            return
        digest = claimed.digest
        try:
            if (older := self._running.get(digest)) is not None:
                older[0].cancel()
            run = self._run(driver, digest, dict(claimed.document), claimed.started_at)
            task = asyncio.create_task(run)
            self._running[digest] = (task, claimed.started_at)
            task.add_done_callback(lambda _: self._forget(digest, task))
        except Exception as error:
            log.error("could not start simulating %s: %s", _short(digest), type(error).__name__)

    async def again(self, digest: str, document: Mapping[str, Any]) -> bool:
        """Tries the version again when it was never tried, wasn't run or ran past its limit.
        False when nothing was started."""
        if self._driver is None or self._closed or self._going(digest):
            return False
        async with self._db.transaction("builder") as uow:
            started_at = await _insert(uow.conn, digest, uow.now)
            if started_at is None:
                row = await (
                    await uow.conn.execute(
                        "UPDATE builder.simulations SET state = 'running', started_at = %s,"
                        " finished_at = NULL, result = NULL, said = NULL, again = false"
                        " WHERE digest = %s"
                        " AND (state = 'not_run' OR (state = 'running' AND started_at < %s))"
                        " RETURNING started_at",
                        (uow.now, digest, uow.now - self._limit),
                    )
                ).fetchone()
                started_at = None if row is None else cast(datetime, row["started_at"])
        if started_at is None:
            return False
        await self.start(Claimed(digest, dict(document), started_at))
        return True

    def _forget(self, digest: str, task: asyncio.Task[None]) -> None:
        going = self._running.get(digest)
        if going is not None and going[0] is task:
            del self._running[digest]

    def cancel(self) -> None:
        """Stops every simulation this process started and refuses new ones, as a shutdown does.
        Each stays running in the table, so past its limit the card shows it as not finished."""
        self._closed = True
        for task, _ in self._running.values():
            task.cancel()

    async def settle(self) -> None:
        """Waits for every simulation this process started, as a test or a shutdown does."""
        while going := [task for task, _ in self._running.values() if not task.done()]:
            await asyncio.gather(*going, return_exceptions=True)

    async def _run(
        self, driver: Simulating, digest: str, version: dict[str, Any], started_at: datetime
    ) -> None:
        try:
            done = await asyncio.wait_for(driver.run(version), self._limit.total_seconds())
        except TimeoutError:
            # Kept as it is: past its limit the card shows it as not finished.
            log.warning("the simulation of %s ran past its limit", _short(digest))
            return
        except Exception as error:
            # Only the error's type: its words could hold the version's.
            log.error("the simulation of %s failed: %s", _short(digest), type(error).__name__)
            done = NotSimulated(DIDNT_ANSWER, again=True)
        try:
            await self._keep(digest, started_at, done)
        except Exception as error:
            log.error(
                "could not keep the simulation of %s: %s", _short(digest), type(error).__name__
            )

    async def _keep(
        self, digest: str, started_at: datetime, done: Simulated | NotSimulated
    ) -> None:
        """Kept only for the try it began, so an older try never overwrites a newer one."""
        match done:
            case Simulated(out=out, notes=notes):
                state, result, said, again = "done", _result(out, notes), None, False
            case NotSimulated(words=words, again=again):
                state, result, said = "not_run", None, words
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.simulations SET state = %s, finished_at = %s, result = %s,"
                " said = %s, again = %s WHERE digest = %s AND state = 'running'"
                " AND started_at = %s",
                (
                    state,
                    uow.now,
                    None if result is None else json(result),
                    said,
                    again,
                    digest,
                    started_at,
                ),
            )

    def _empty(self) -> SimulationView:
        return SimulationView(
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

    def waiting(self) -> SimulationView:
        """A version that still needs a setting, tried once every setting is filled. Where there
        is no simulation n8n it is never tried, and the card says so instead."""
        empty = self._empty()
        return empty.model_copy(update={"state": "waiting"}) if self.available else empty

    async def view(self, digest: str, operator: bool) -> SimulationView:
        """A version's simulation, by its digest, as this person may act on it."""
        empty = self._empty()
        if not self.available:
            return empty
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT state, started_at, result, said, again FROM builder.simulations"
                    " WHERE digest = %s",
                    (digest,),
                )
            ).fetchone()
        can_start = operator and not self._closed
        if row is None:
            return empty.model_copy(update={"state": "not_started", "can_try_again": can_start})
        started_at = cast(datetime, row["started_at"])
        at = {"started_at": started_at}
        match row["state"]:
            case "running" if self._db.clock() - started_at > self._limit:
                return empty.model_copy(
                    update={**at, "state": "not_finished", "can_try_again": can_start}
                )
            case "running":
                return empty.model_copy(update={**at, "state": "running"})
            case "not_run":
                return empty.model_copy(
                    update={
                        **at,
                        "state": "not_run",
                        "said": row["said"],
                        "can_try_again": can_start and bool(row["again"]),
                    }
                )
            case _:
                return _done(empty.model_copy(update=at), row["result"])


async def _insert(conn: Connection, digest: str, now: datetime) -> datetime | None:
    """A first try for the digest, or None when it has one already."""
    row = await (
        await conn.execute(
            "INSERT INTO builder.simulations (digest, state, started_at)"
            " VALUES (%s, 'running', %s) ON CONFLICT (digest) DO NOTHING RETURNING started_at",
            (digest, now),
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


def _done(view: SimulationView, result: Mapping[str, Any]) -> SimulationView:
    return view.model_copy(
        update={
            "state": "done",
            "tried": result["tried"],
            "passed": result["passed"],
            "cases": [SimulatedCaseView.model_validate(c) for c in result["cases"]],
            "not_tried": [SimulatedBlockView.model_validate(n) for n in result["not_tried"]],
        }
    )
