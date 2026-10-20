import asyncio
import logging
import secrets
from collections.abc import AsyncGenerator, AsyncIterator, Iterable
from contextlib import asynccontextmanager, suppress

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


class NotificationHub:
    """One LISTEN connection per process. Each subscriber gets a flag that is set on NOTIFY."""

    def __init__(self, db: Database, *, reconnect_delay: float = 1.0) -> None:
        self._db = db
        self._reconnect_delay = reconnect_delay
        self._subscribers: dict[RunId, set[asyncio.Event]] = {}
        self._listening = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def listening(self) -> bool:
        return self._listening.is_set()

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
    async def wakeups(self, run_id: RunId) -> AsyncGenerator[asyncio.Event]:
        flag = asyncio.Event()
        self._subscribers.setdefault(run_id, set()).add(flag)
        try:
            yield flag
        finally:
            flags = self._subscribers[run_id]
            flags.discard(flag)
            if not flags:
                del self._subscribers[run_id]

    async def _listen_forever(self) -> None:
        while True:
            try:
                await self._listen()
            except Exception:
                logger.warning("The run_events listener lost its connection.", exc_info=True)
            self._listening.clear()
            await asyncio.sleep(self._reconnect_delay)

    async def _listen(self) -> None:
        async with self._db.connection("monitoring") as conn:
            await conn.set_autocommit(True)
            try:
                await conn.execute(f"LISTEN {CHANNEL}")
                self._listening.set()
                # Anything committed while we were not listening is invisible to us, so
                # every subscriber re-reads once.
                for flags in self._subscribers.values():
                    self._wake(flags)
                async for notification in conn.notifies():
                    self._wake(self._subscribers.get(RunId(notification.payload), ()))
            finally:
                self._listening.clear()
                with suppress(Exception):
                    await conn.set_autocommit(False)

    @staticmethod
    def _wake(flags: Iterable[asyncio.Event]) -> None:
        for flag in flags:
            flag.set()


class ActivityLog:
    def __init__(self, db: Database, hub: NotificationHub | None = None) -> None:
        self._db = db
        self._hub = hub if hub is not None else NotificationHub(db)

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
        """Runs on the caller's transaction. Appends to one run serialize on an advisory lock,
        which the commit releases, so seq order is commit order and readers never see a gap."""
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

    async def read_after(
        self, run_id: RunId, after: int, *, uow: UnitOfWork | None = None
    ) -> list[ActivityEvent]:
        if uow is None:
            async with self._db.transaction("monitoring") as own:
                return await self.read_after(run_id, after, uow=own)
        rows = await (
            await uow.conn.execute(_READ_AFTER, {"run_id": run_id, "after": after})
        ).fetchall()
        return [activity_event_adapter.validate_python(row) for row in rows]

    async def subscribe(self, run_id: RunId, after: int) -> AsyncIterator[ActivityEvent]:
        """The backlog after `after`, then every new event in seq order, for as long as the
        caller iterates."""
        cursor = after
        async with self._hub.wakeups(run_id) as wakeup:
            while True:
                wakeup.clear()
                for event in await self.read_after(run_id, cursor):
                    cursor = event.seq
                    yield event
                await wakeup.wait()

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
