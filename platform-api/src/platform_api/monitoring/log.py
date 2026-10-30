import asyncio
import logging
import secrets
from collections.abc import AsyncGenerator, Callable, Collection, Iterable
from contextlib import aclosing, asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from psycopg import sql

from platform_api.db import Database, UnitOfWork, json
from platform_api.monitoring.agent_events import AgentEvent
from platform_api.monitoring.events import (
    ActivityEvent,
    PendingEvent,
    activity_event_adapter,
    agent_actor,
)
from platform_api.shared import RunId, TaskId

CHANNEL = "run_events"
COPIED_CHANNEL = "run_events_copied"
logger = logging.getLogger(__name__)

_COLUMNS = "run_id, seq, ts, actor, kind, summary, data"
_INSERT = f"""
    INSERT INTO monitoring.run_events (run_id, seq, ts, actor, kind, summary, data, dedupe_key)
    VALUES (%(run_id)s, %(seq)s, %(ts)s, %(actor)s, %(kind)s, %(summary)s, %(data)s, %(dedupe_key)s)
    ON CONFLICT (run_id, dedupe_key) DO NOTHING
    RETURNING {_COLUMNS}
"""
_READ_AFTER = f"""
    SELECT {_COLUMNS} FROM monitoring.run_events
    WHERE run_id = %(run_id)s AND seq > %(after)s ORDER BY seq
"""


@dataclass(frozen=True)
class LoggedEvent:
    run_id: RunId
    seq: int
    ts: datetime
    actor: dict[str, object]
    kind: str
    summary: str
    data: dict[str, object]
    dedupe_key: str


class EventReader(Protocol):
    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]: ...


class EventReplica(EventReader, Protocol):
    async def put(self, event: LoggedEvent) -> None: ...


class Wakeup:
    """Set by each notification for one run. It keeps the highest seq those notifications named,
    and has no bound when one of them named none."""

    def __init__(self) -> None:
        self._flag = asyncio.Event()
        self._unbounded = True
        self._upto = 0

    def wake(self, upto: int | None) -> None:
        if upto is None:
            self._unbounded = True
        else:
            self._upto = max(self._upto, upto)
        self._flag.set()

    def take(self) -> int | None:
        self._flag.clear()
        upto = None if self._unbounded else self._upto
        self._unbounded = False
        return upto

    async def wait(self) -> None:
        await self._flag.wait()


type Watcher = Callable[[RunId | None], None]


class NotificationHub:
    """One LISTEN connection per process. A payload is a run id, optionally followed by a space
    and the highest seq copied. Watchers hear of every run, and of None after each connect."""

    def __init__(
        self, db: Database, *, channel: str = CHANNEL, reconnect_delay: float = 1.0
    ) -> None:
        self._db = db
        self._channel = channel
        self._reconnect_delay = reconnect_delay
        self._subscribers: dict[RunId, set[Wakeup]] = {}
        self._watchers: list[Watcher] = []
        self._listening = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def listening(self) -> bool:
        return self._listening.is_set()

    def watch(self, watcher: Watcher) -> None:
        self._watchers.append(watcher)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen_forever())
        await self._listening.wait()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    @asynccontextmanager
    async def wakeups(self, run_id: RunId) -> AsyncGenerator[Wakeup]:
        wakeup = Wakeup()
        self._subscribers.setdefault(run_id, set()).add(wakeup)
        try:
            yield wakeup
        finally:
            wakeups = self._subscribers[run_id]
            wakeups.discard(wakeup)
            if not wakeups:
                del self._subscribers[run_id]

    async def _listen_forever(self) -> None:
        while True:
            try:
                await self._listen()
            except Exception:
                logger.warning("The %s listener lost its connection.", self._channel, exc_info=True)
            self._listening.clear()
            await asyncio.sleep(self._reconnect_delay)

    async def _listen(self) -> None:
        async with self._db.connection("monitoring") as conn:
            await conn.set_autocommit(True)
            try:
                await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(self._channel)))
                self._listening.set()
                # Anything committed while we were not listening is invisible to us, so
                # every subscriber re-reads once.
                for wakeups in self._subscribers.values():
                    self._wake(wakeups, None)
                self._tell_watchers(None)
                async for notification in conn.notifies():
                    run_text, _, seq = notification.payload.partition(" ")
                    run_id = RunId(run_text)
                    self._wake(self._subscribers.get(run_id, ()), int(seq) if seq else None)
                    self._tell_watchers(run_id)
            finally:
                self._listening.clear()
                with suppress(Exception):
                    await conn.set_autocommit(False)

    @staticmethod
    def _wake(wakeups: Iterable[Wakeup], upto: int | None) -> None:
        for wakeup in wakeups:
            wakeup.wake(upto)

    def _tell_watchers(self, run_id: RunId | None) -> None:
        for watcher in self._watchers:
            watcher(run_id)


class ActivityLog:
    """Writes always go to PostgreSQL. Reads go to PostgreSQL, or to a replica that a Copier
    fills (ADR 0031), woken by the copier's notifications."""

    def __init__(
        self,
        db: Database,
        *,
        replica: EventReader | None = None,
        reconnect_delay: float = 1.0,
        read_wait: float = 2.0,
    ) -> None:
        self._db = db
        self._replica = replica
        self._read_wait = read_wait
        channel = CHANNEL if replica is None else COPIED_CHANNEL
        self._hub = NotificationHub(db, channel=channel, reconnect_delay=reconnect_delay)

    @property
    def database(self) -> Database:
        return self._db

    @property
    def listening(self) -> bool:
        return self._hub.listening

    async def start(self) -> None:
        await self._hub.start()

    async def stop(self) -> None:
        await self._hub.stop()

    async def append(
        self, uow: UnitOfWork, run_id: RunId, events: Iterable[PendingEvent]
    ) -> list[ActivityEvent]:
        """Appends to one run serialize on an advisory lock, which the commit releases, so seq
        order is commit order and readers never see a gap."""
        await uow.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (run_id,))
        seq = await self.last_seq(uow, run_id)
        stored: list[ActivityEvent] = []
        for event in events:
            row = await (
                await uow.conn.execute(
                    _INSERT,
                    {
                        "run_id": run_id,
                        "seq": seq + 1,
                        "ts": event.ts or uow.now,
                        "actor": json(event.actor.model_dump(mode="json")),
                        "kind": event.kind,
                        "summary": event.summary,
                        "data": json(event.data.model_dump(mode="json")),
                        "dedupe_key": event.dedupe_key or f"once:{secrets.token_hex(16)}",
                    },
                )
            ).fetchone()
            if row is None:
                continue
            seq += 1
            stored.append(activity_event_adapter.validate_python(row))
        await uow.conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, run_id))
        return stored

    async def last_seq(self, uow: UnitOfWork, run_id: RunId) -> int:
        row = await (
            await uow.conn.execute(
                "SELECT coalesce(max(seq), 0) AS seq FROM monitoring.run_events WHERE run_id = %s",
                (run_id,),
            )
        ).fetchone()
        assert row is not None
        return int(row["seq"])

    async def last_seqs(self, uow: UnitOfWork, run_ids: Collection[RunId]) -> dict[RunId, int]:
        if not run_ids:
            return {}
        rows = await (
            await uow.conn.execute(
                "SELECT run_id, max(seq) AS seq FROM monitoring.run_events "
                "WHERE run_id = ANY(%s) GROUP BY run_id",
                (list(run_ids),),
            )
        ).fetchall()
        found = {RunId(row["run_id"]): int(row["seq"]) for row in rows}
        return {run_id: found.get(run_id, 0) for run_id in run_ids}

    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        """From a replica, this waits at most read_wait for the copy to reach what PostgreSQL
        held when the read began. A client that just saw a run's state then reads the event
        that set it."""
        if self._replica is None:
            return await self._read_postgres(run_id, after)
        async with self._db.transaction("monitoring") as uow:
            logged = await self.last_seq(uow, run_id)
        if logged <= after:
            return []
        events: list[ActivityEvent] = []
        with suppress(TimeoutError):
            async with (
                asyncio.timeout(self._read_wait),
                aclosing(self.subscribe(run_id, after)) as stream,
            ):
                async for event in stream:
                    events.append(event)
                    if event.seq >= logged:
                        break
        return events

    async def subscribe(self, run_id: RunId, after: int) -> AsyncGenerator[ActivityEvent]:
        cursor = after
        async with self._hub.wakeups(run_id) as wakeup:
            while True:
                upto = wakeup.take()
                if upto is None or upto > cursor:
                    for event in await self._read(run_id, cursor):
                        cursor = event.seq
                        yield event
                await wakeup.wait()

    async def _read(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        if self._replica is None:
            return await self._read_postgres(run_id, after)
        return await self._replica.read_after(run_id, after)

    async def _read_postgres(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        async with self._db.transaction("monitoring") as uow:
            rows = await (
                await uow.conn.execute(_READ_AFTER, {"run_id": run_id, "after": after})
            ).fetchall()
        return [activity_event_adapter.validate_python(row) for row in rows]

    async def ingest_agent_events(
        self, uow: UnitOfWork, run_id: RunId, task_id: TaskId, events: Iterable[AgentEvent]
    ) -> list[ActivityEvent]:
        pending = [
            PendingEvent(
                agent_actor(event.agent.id, event.agent.display),
                event.kind,
                event.summary,
                event.data,
                dedupe_key=f"agent:{task_id}:{event.agent_seq}",
                ts=event.ts,
            )
            for event in events
        ]
        return await self.append(uow, run_id, pending)
