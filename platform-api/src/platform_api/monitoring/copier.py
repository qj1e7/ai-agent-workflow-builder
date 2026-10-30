import asyncio
import logging
from contextlib import suppress

from platform_api.db import Database, UnitOfWork
from platform_api.monitoring.log import (
    CHANNEL,
    COPIED_CHANNEL,
    EventReplica,
    LoggedEvent,
    NotificationHub,
)
from platform_api.shared import RunId

logger = logging.getLogger(__name__)

_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('copy:' || %s, 0))"
_COPIED = "SELECT seq FROM monitoring.run_events_copied WHERE run_id = %s"
_ROWS_AFTER = """
    SELECT run_id, seq, ts, actor, kind, summary, data, dedupe_key FROM monitoring.run_events
    WHERE run_id = %(run_id)s AND seq > %(after)s ORDER BY seq LIMIT %(limit)s
"""
_RECORD = """
    INSERT INTO monitoring.run_events_copied (run_id, seq, copied_at)
    VALUES (%(run_id)s, %(seq)s, %(at)s)
    ON CONFLICT (run_id) DO UPDATE SET seq = EXCLUDED.seq, copied_at = EXCLUDED.copied_at
    WHERE monitoring.run_events_copied.seq < EXCLUDED.seq
"""
_RUNS_BEHIND = """
    SELECT logged.run_id FROM (
        SELECT run_id, max(seq) AS seq FROM monitoring.run_events GROUP BY run_id
    ) AS logged
    LEFT JOIN monitoring.run_events_copied AS copied USING (run_id)
    WHERE logged.seq > coalesce(copied.seq, 0)
"""


class Copier:
    """Copies each run's new events from monitoring.run_events to a replica, in seq order.

    A copy holds a per-run lock that appends never take, so a second copier on the same run
    waits and then finds nothing left. Each batch commits the highest seq it copied, even when
    a put fails halfway, and notifies COPIED_CHANNEL with it. PostgreSQL keeps every row."""

    def __init__(
        self,
        db: Database,
        replica: EventReplica,
        *,
        batch: int = 100,
        retry_delay: float = 1.0,
        reconnect_delay: float = 1.0,
    ) -> None:
        self._db = db
        self._replica = replica
        self._batch = batch
        self._retry_delay = retry_delay
        self._hub = NotificationHub(db, channel=CHANNEL, reconnect_delay=reconnect_delay)
        self._hub.watch(self._note)
        self._behind: set[RunId] = set()
        self._sweep = False
        self._work = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._copy_forever())
        await self._hub.start()

    async def stop(self) -> None:
        await self._hub.stop()
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def copy_run(self, run_id: RunId) -> int:
        while True:
            copied, full = await self._copy_batch(run_id)
            if not full:
                return copied

    async def runs_behind(self) -> list[RunId]:
        async with self._db.transaction("monitoring") as uow:
            rows = await (await uow.conn.execute(_RUNS_BEHIND)).fetchall()
        return [RunId(row["run_id"]) for row in rows]

    async def _copy_batch(self, run_id: RunId) -> tuple[int, bool]:
        failure: Exception | None = None
        async with self._db.transaction("monitoring") as uow:
            await uow.conn.execute(_LOCK, (run_id,))
            before = await self._copied(uow, run_id)
            rows = await (
                await uow.conn.execute(
                    _ROWS_AFTER, {"run_id": run_id, "after": before, "limit": self._batch}
                )
            ).fetchall()
            done = before
            for row in rows:
                try:
                    await self._replica.put(LoggedEvent(**row))
                except Exception as error:
                    failure = error
                    break
                done = row["seq"]
            if done > before:
                await uow.conn.execute(_RECORD, {"run_id": run_id, "seq": done, "at": uow.now})
                await uow.conn.execute(
                    "SELECT pg_notify(%s, %s)", (COPIED_CHANNEL, f"{run_id} {done}")
                )
        if failure is not None:
            raise failure
        return done, len(rows) == self._batch

    @staticmethod
    async def _copied(uow: UnitOfWork, run_id: RunId) -> int:
        row = await (await uow.conn.execute(_COPIED, (run_id,))).fetchone()
        return 0 if row is None else int(row["seq"])

    def _note(self, run_id: RunId | None) -> None:
        if run_id is None:
            self._sweep = True
        else:
            self._behind.add(run_id)
        self._work.set()

    async def _copy_forever(self) -> None:
        while True:
            await self._work.wait()
            self._work.clear()
            if not await self._copy_pending():
                await asyncio.sleep(self._retry_delay)
                self._work.set()

    async def _copy_pending(self) -> bool:
        if self._sweep:
            self._sweep = False
            try:
                self._behind.update(await self.runs_behind())
            except Exception as error:
                logger.warning("Could not list the runs left to copy: %s", error)
                self._sweep = True
                return False
        copied_all = True
        for run_id in sorted(self._behind):
            self._behind.discard(run_id)
            try:
                await self.copy_run(run_id)
            except Exception as error:
                logger.warning("Could not copy the events of %s: %r", run_id, error)
                self._behind.add(run_id)
                copied_all = False
        return copied_all
