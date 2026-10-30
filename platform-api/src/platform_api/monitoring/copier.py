import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass

from platform_api.db import Database, UnitOfWork
from platform_api.monitoring.log import (
    CHANNEL,
    COPIED_CHANNEL,
    EventCopy,
    Generation,
    LoggedEvent,
    NotificationHub,
    copied_notice,
)
from platform_api.shared import RunId

logger = logging.getLogger(__name__)

_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('copy:' || %s, 0))"
_COPIED = """
    SELECT seq FROM monitoring.run_events_copied
    WHERE run_id = %(run_id)s AND generation = %(generation)s
"""
_ROWS_AFTER = """
    SELECT run_id, seq, ts, actor, kind, summary, data, dedupe_key FROM monitoring.run_events
    WHERE run_id = %(run_id)s AND seq > %(after)s ORDER BY seq LIMIT %(limit)s
"""
_RECORD = """
    INSERT INTO monitoring.run_events_copied (run_id, generation, seq, copied_at)
    VALUES (%(run_id)s, %(generation)s, %(seq)s, %(at)s)
    ON CONFLICT (run_id) DO UPDATE
    SET generation = EXCLUDED.generation, seq = EXCLUDED.seq, copied_at = EXCLUDED.copied_at
    WHERE monitoring.run_events_copied.generation <> EXCLUDED.generation
       OR monitoring.run_events_copied.seq < EXCLUDED.seq
"""
_RUNS_BEHIND = """
    SELECT logged.run_id FROM (
        SELECT run_id, max(seq) AS seq FROM monitoring.run_events GROUP BY run_id
    ) AS logged
    LEFT JOIN monitoring.run_events_copied AS copied
        ON copied.run_id = logged.run_id AND copied.generation = %(generation)s
    WHERE logged.seq > coalesce(copied.seq, 0)
"""


@dataclass(frozen=True)
class _Batch:
    done: int
    more: bool
    failure: Exception | None


@dataclass(frozen=True)
class _Retry:
    at: float
    failures: int


class Copier:
    def __init__(
        self,
        db: Database,
        copy: EventCopy,
        *,
        batch: int = 20,
        put_timeout: float = 10.0,
        retry_delay: float = 1.0,
        max_retry_delay: float = 5.0,
        reconnect_delay: float = 1.0,
    ) -> None:
        self._db = db
        self._copy = copy
        self._batch = batch
        self._put_timeout = put_timeout
        self._retry_delay = retry_delay
        self._max_retry_delay = max_retry_delay
        self._hub = NotificationHub(db, channel=CHANNEL, reconnect_delay=reconnect_delay)
        self._hub.watch(self._note_run, self._note_connect)
        self._generation_seen: Generation | None = None
        self._sweep_failed = False
        self._live: set[RunId] = set()
        self._behind: set[RunId] = set()
        self._retries: dict[RunId, _Retry] = {}
        self._sweep_at: float | None = None
        self._work = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def listening(self) -> bool:
        return self._hub.listening

    @property
    def behind(self) -> bool:
        return bool(self._retries) or self._sweep_failed

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
            batch = await self._copy_batch(run_id)
            if batch.failure is not None:
                raise batch.failure
            if not batch.more:
                return batch.done

    async def runs_behind(self) -> list[RunId]:
        generation = await self._follow_generation()
        async with self._db.transaction("monitoring") as uow:
            rows = await (
                await uow.conn.execute(_RUNS_BEHIND, {"generation": generation})
            ).fetchall()
        return [RunId(row["run_id"]) for row in rows]

    async def _follow_generation(self) -> Generation:
        async with asyncio.timeout(self._put_timeout):
            generation = await self._copy.ensure()
        if self._generation_seen not in (None, generation):
            self._catch_up_every_run()
        self._generation_seen = generation
        return generation

    def _catch_up_every_run(self) -> None:
        self._sweep_at = 0.0

    async def _copy_batch(self, run_id: RunId) -> _Batch:
        failure: Exception | None = None
        async with self._db.transaction("monitoring") as uow:
            await uow.conn.execute(_LOCK, (run_id,))
            generation = await self._follow_generation()
            before = await self._copied(uow, run_id, generation)
            rows = await (
                await uow.conn.execute(
                    _ROWS_AFTER, {"run_id": run_id, "after": before, "limit": self._batch}
                )
            ).fetchall()
            done = before
            for row in rows:
                try:
                    async with asyncio.timeout(self._put_timeout):
                        await self._copy.put(LoggedEvent(**row))
                except Exception as error:
                    failure = error
                    break
                done = row["seq"]
            if done > before:
                await uow.conn.execute(
                    _RECORD,
                    {"run_id": run_id, "generation": generation, "seq": done, "at": uow.now},
                )
                await uow.conn.execute(
                    "SELECT pg_notify(%s, %s)", (COPIED_CHANNEL, copied_notice(run_id, done))
                )
        return _Batch(done, len(rows) == self._batch, failure)

    @staticmethod
    async def _copied(uow: UnitOfWork, run_id: RunId, generation: Generation) -> int:
        row = await (
            await uow.conn.execute(_COPIED, {"run_id": run_id, "generation": generation})
        ).fetchone()
        return 0 if row is None else int(row["seq"])

    def _note_run(self, run_id: RunId) -> None:
        self._live.add(run_id)
        self._behind.add(run_id)
        self._work.set()

    def _note_connect(self) -> None:
        self._sweep_at = 0.0
        self._work.set()

    async def _copy_forever(self) -> None:
        while True:
            await self._next_work()
            now = time.monotonic()
            if self._sweep_at is not None and self._sweep_at <= now:
                await self._sweep(now)
            for run_id in sorted(self._behind, key=lambda r: (r not in self._live, r)):
                retry = self._retries.get(run_id)
                if retry is not None and retry.at > now:
                    continue
                self._behind.discard(run_id)
                self._live.discard(run_id)
                await self._copy_one_batch(run_id)
                if self._live:
                    break

    async def _next_work(self) -> None:
        due = [retry.at for retry in self._retries.values()]
        if self._sweep_at is not None:
            due.append(self._sweep_at)
        wait = max(0.0, min(due) - time.monotonic()) if due else None
        with suppress(TimeoutError):
            async with asyncio.timeout(wait):
                await self._work.wait()
        self._work.clear()
        now = time.monotonic()
        self._behind.update(run_id for run_id, retry in self._retries.items() if retry.at <= now)

    async def _sweep(self, now: float) -> None:
        try:
            self._behind.update(await self.runs_behind())
        except Exception as error:
            logger.warning("Could not catch up the copy: %r", error)
            self._sweep_at = now + self._retry_delay
            self._sweep_failed = True
            return
        self._sweep_at = None
        self._sweep_failed = False

    async def _copy_one_batch(self, run_id: RunId) -> None:
        try:
            batch = await self._copy_batch(run_id)
        except Exception as error:
            self._retry_later(run_id, error)
            return
        if batch.failure is not None:
            self._retry_later(run_id, batch.failure)
            return
        self._retries.pop(run_id, None)
        if batch.more:
            self._behind.add(run_id)
            self._work.set()

    def _retry_later(self, run_id: RunId, error: Exception) -> None:
        previous = self._retries.get(run_id)
        failures = 1 if previous is None else previous.failures + 1
        delay = min(self._retry_delay * 2 ** (failures - 1), self._max_retry_delay)
        self._retries[run_id] = _Retry(time.monotonic() + delay, failures)
        logger.warning(
            "Could not copy the events of %s (try %d, next in %.1f s): %r",
            run_id,
            failures,
            delay,
            error,
        )
