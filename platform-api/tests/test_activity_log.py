import json
import logging
from datetime import UTC, datetime

import anyio
import pytest
from psycopg import AsyncConnection

from platform_api.db import Database
from platform_api.monitoring import (
    PLATFORM,
    ActivityEvent,
    ActivityLog,
    AgentEventPost,
    PendingEvent,
    RunRetriedData,
    activity_events_adapter,
    agent_event_adapter,
)
from platform_api.monitoring.log import COPIED_CHANNEL, PostgresEvents, copied_notice
from platform_api.settings import Context
from platform_api.shared import RunId, TaskId
from tests.conftest import PostgresUrls
from tests.support import FIXTURES

pytestmark = pytest.mark.anyio

RUN = RunId("run_01TEST")


def pending(n: int, ts: datetime | None = None, dedupe_key: str | None = None) -> PendingEvent:
    return PendingEvent(
        PLATFORM,
        "run_retried",
        f"event {n}",
        RunRetriedData(leg="work", attempt=n),
        dedupe_key=dedupe_key,
        ts=ts,
    )


@pytest.fixture
def log(activity_log: ActivityLog) -> ActivityLog:
    return activity_log


async def append(log: ActivityLog, context: Context, *events: PendingEvent) -> list[ActivityEvent]:
    async with log.database.transaction(context) as uow:
        return await log.append(uow, RUN, events)


async def test_append_assigns_seq_in_order_and_ts_from_the_transaction(log: ActivityLog):
    carried = datetime(2026, 11, 3, 2, 14, 2, 390000, tzinfo=UTC)
    async with log.database.transaction("monitoring") as uow:
        stored = await log.append(uow, RUN, [pending(1), pending(2, ts=carried), pending(3)])
        started = uow.now

    assert [(e.seq, e.summary) for e in stored] == [(1, "event 1"), (2, "event 2"), (3, "event 3")]
    assert [e.ts for e in stored] == [started, carried, started]
    assert all(e.run_id == RUN for e in stored)
    assert await log.read_after(RUN, 0) == stored
    assert await log.read_after(RUN, 2) == stored[2:]


async def test_last_seq_is_zero_for_an_unknown_run(log: ActivityLog):
    async with log.database.transaction("monitoring") as uow:
        assert await log.last_seq(uow, RUN) == 0
    await append(log, "monitoring", pending(1), pending(2))
    async with log.database.transaction("monitoring") as uow:
        assert await log.last_seq(uow, RUN) == 2


async def test_last_seqs_reads_many_runs_at_once_and_gives_zero_for_unknown_ones(log: ActivityLog):
    other, unknown = RunId("run_01OTHER"), RunId("run_01UNKNOWN")
    await append(log, "monitoring", pending(1), pending(2), pending(3))
    async with log.database.transaction("orchestration") as uow:
        await log.append(uow, other, [pending(1)])
    async with log.database.transaction("orchestration") as uow:
        assert await log.last_seqs(uow, [RUN, other, unknown]) == {RUN: 3, other: 1, unknown: 0}
        assert await log.last_seqs(uow, []) == {}


async def test_concurrent_appends_from_both_roles_leave_no_gap(log: ActivityLog):
    async def worker(i: int) -> None:
        context: Context = "orchestration" if i % 2 else "monitoring"
        await append(log, context, *(pending(i * 10 + k) for k in range(5)))

    async with anyio.create_task_group() as tg:
        for i in range(20):
            tg.start_soon(worker, i)

    stored = await log.read_after(RUN, 0)
    assert [e.seq for e in stored] == list(range(1, 101))
    assert len({e.summary for e in stored}) == 100


async def test_a_repeated_dedupe_key_stores_once_and_consumes_no_seq(log: ActivityLog):
    first = await append(log, "monitoring", pending(1, dedupe_key="k1"))
    second = await append(log, "monitoring", pending(1, dedupe_key="k1"), pending(2))

    assert [e.seq for e in first] == [1]
    assert [(e.seq, e.summary) for e in second] == [(2, "event 2")]
    assert [e.seq for e in await log.read_after(RUN, 0)] == [1, 2]


async def test_agent_events_are_stored_once_with_their_own_ts(log: ActivityLog):
    post = AgentEventPost.model_validate(
        json.loads((FIXTURES / "agent" / "callback-event.json").read_text())
    )
    finished = json.loads((FIXTURES / "agent" / "task-finished.json").read_text())
    events = [agent_event_adapter.validate_python(e) for e in finished["events"]]
    run_id = RunId(finished["task_id"].split("/")[0])
    task_id = TaskId(finished["task_id"])

    async with log.database.transaction("monitoring") as uow:
        live = await log.ingest_agent_events(uow, run_id, task_id, [post.event])
    async with log.database.transaction("orchestration") as uow:
        backfilled = await log.ingest_agent_events(uow, run_id, task_id, events)

    assert [e.seq for e in live] == [1]
    assert [e.seq for e in backfilled] == list(range(2, len(events) + 1))
    stored = await log.read_after(run_id, 0)
    assert [(e.kind, e.ts, e.summary) for e in stored] == [
        (e.kind, e.ts, e.summary) for e in events
    ]
    assert [(e.actor.kind, e.actor.id, e.actor.display) for e in stored] == [
        ("agent", e.agent.id, e.agent.display) for e in events
    ]
    assert [e.data.model_dump() for e in stored] == [e.data.model_dump() for e in events]


async def test_the_success_story_replays_through_the_log(log: ActivityLog):
    story = json.loads((FIXTURES / "runs" / "success.json").read_text())
    expected = activity_events_adapter.validate_python(story)
    run_id = expected[0].run_id
    async with log.database.transaction("orchestration") as uow:
        for e in expected:
            await log.append(
                uow, run_id, [PendingEvent(e.actor, e.kind, e.summary, e.data, ts=e.ts)]
            )

    assert await log.read_after(run_id, 0) == expected


async def test_orchestrations_rollback_stores_nothing(log: ActivityLog):
    class Abort(Exception):
        pass

    with pytest.raises(Abort):
        async with log.database.transaction("orchestration") as uow:
            await log.append(uow, RUN, [pending(1)])
            raise Abort

    assert await log.read_after(RUN, 0) == []


async def test_subscribe_resumes_after_a_seq_and_follows_new_appends(
    log: ActivityLog, postgres: PostgresUrls
):
    await append(log, "monitoring", pending(1), pending(2), pending(3))
    received: list[int] = []

    async def collect() -> None:
        async for event in log.subscribe(RUN, after=2):
            received.append(event.seq)
            if len(received) == 3:
                return

    async with anyio.create_task_group() as tg:
        tg.start_soon(collect)
        with anyio.fail_after(5):
            while received != [3]:
                await anyio.sleep(0.01)
        async with (
            await AsyncConnection.connect(postgres.contexts.orchestration) as conn,
            conn.transaction(),
        ):
            now = datetime.now(UTC)
            await conn.execute(
                "INSERT INTO monitoring.run_events "
                "(run_id, seq, ts, actor, kind, summary, data, dedupe_key) VALUES "
                "(%(run)s, 4, %(ts)s, %(actor)s, 'run_retried', 'event 4', %(d4)s, 'x4'), "
                "(%(run)s, 5, %(ts)s, %(actor)s, 'run_retried', 'event 5', %(d5)s, 'x5')",
                {
                    "run": RUN,
                    "ts": now,
                    "actor": PLATFORM.model_dump_json(),
                    "d4": '{"leg": "work", "attempt": 4}',
                    "d5": '{"leg": "work", "attempt": 5}',
                },
            )
            await conn.execute("SELECT pg_notify('run_events', %s)", (RUN,))
        with anyio.fail_after(5):
            while len(received) < 3:
                await anyio.sleep(0.01)

    assert received == [3, 4, 5]


async def test_subscribers_wake_after_the_listener_reconnects(log: ActivityLog):
    received: list[int] = []

    async def collect() -> None:
        async for event in log.subscribe(RUN, after=0):
            received.append(event.seq)
            return

    async with anyio.create_task_group() as tg:
        tg.start_soon(collect)
        await anyio.sleep(0.05)
        async with log.database.connection("monitoring") as conn:
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE pid <> pg_backend_pid() AND query LIKE 'LISTEN %'"
            )
        with anyio.fail_after(5):
            while log.listening:
                await anyio.sleep(0.01)
            while not log.listening:
                await anyio.sleep(0.01)
            await append(log, "monitoring", pending(1))
            while not received:
                await anyio.sleep(0.01)

    assert received == [1]


class ShortOnce:
    def __init__(self, db: Database) -> None:
        self.inner = PostgresEvents(db)
        self.short = False
        self.reads = 0

    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        self.reads += 1
        events = await self.inner.read_after(run_id, after)
        if self.short:
            self.short = False
            return events[:1]
        return events


class Failing:
    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        raise RuntimeError("the replica is down")


class FailsFirst(ShortOnce):
    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        if self.reads == 0:
            self.reads += 1
            raise RuntimeError("the replica is down")
        return await super().read_after(run_id, after)


class Lagging:
    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        return []


async def notify_copied(db: Database, run_id: RunId, seq: int) -> None:
    async with db.connection("monitoring") as conn, conn.transaction():
        await conn.execute("SELECT pg_notify(%s, %s)", (COPIED_CHANNEL, copied_notice(run_id, seq)))


async def appended(db: Database, *numbers: int) -> list[ActivityEvent]:
    async with db.transaction("orchestration") as uow:
        return await ActivityLog(db).append(uow, RUN, [pending(n) for n in numbers])


async def test_a_stream_reads_again_when_a_read_comes_back_short_of_the_named_seq(db: Database):
    replica = ShortOnce(db)
    log = ActivityLog(db, replica=replica, short_read_recheck=0.05)
    await log.start()
    received: list[int] = []

    async def collect() -> None:
        async for event in log.subscribe(RUN, after=0):
            received.append(event.seq)
            if len(received) == 3:
                return

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(collect)
            await anyio.sleep(0.05)
            await appended(db, 1, 2, 3)
            replica.short = True
            await notify_copied(db, RUN, 3)
            with anyio.fail_after(2):
                while len(received) < 3:
                    await anyio.sleep(0.01)
    finally:
        await log.stop()

    assert received == [1, 2, 3]


async def test_a_stream_reads_again_after_a_failed_read(db: Database):
    log = ActivityLog(db, replica=FailsFirst(db), read_retry=0.05)
    await log.start()
    await appended(db, 1)
    received: list[int] = []

    async def collect() -> None:
        async for event in log.subscribe(RUN, after=0):
            received.append(event.seq)
            return

    try:
        with anyio.fail_after(2):
            await collect()
    finally:
        await log.stop()

    assert received == [1]


@pytest.mark.parametrize("replica", [Lagging(), Failing()], ids=["lagging", "failing"])
async def test_a_one_off_read_falls_back_to_postgresql_when_the_copy_cannot_answer(
    db: Database, replica: Lagging | Failing, caplog: pytest.LogCaptureFixture
):
    log = ActivityLog(db, replica=replica, copy_wait=0.2, read_retry=0.05)
    stored = await appended(db, 1, 2)

    with caplog.at_level(logging.WARNING), anyio.fail_after(2):
        assert await log.read_after(RUN, 0) == stored

    assert f"Read {RUN} from PostgreSQL" in caplog.text


async def test_a_malformed_notice_is_skipped_and_the_listener_stays_up(
    db: Database, caplog: pytest.LogCaptureFixture
):
    log = ActivityLog(db, replica=PostgresEvents(db), reconnect_delay=5)
    await log.start()
    received: list[int] = []

    async def collect() -> None:
        async for event in log.subscribe(RUN, after=0):
            received.append(event.seq)
            return

    try:
        with caplog.at_level(logging.WARNING):
            async with anyio.create_task_group() as tg:
                tg.start_soon(collect)
                await anyio.sleep(0.05)
                async with db.connection("monitoring") as conn, conn.transaction():
                    await conn.execute(
                        "SELECT pg_notify(%s, %s)", (COPIED_CHANNEL, f"{RUN} not-a-seq")
                    )
                await appended(db, 1)
                await notify_copied(db, RUN, 1)
                with anyio.fail_after(2):
                    while not received:
                        await anyio.sleep(0.01)
    finally:
        await log.stop()

    assert received == [1]
    assert "Skipped a run_events_copied notice" in caplog.text
    assert "lost its connection" not in caplog.text
