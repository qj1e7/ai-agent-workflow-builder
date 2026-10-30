import json
import random
from datetime import UTC, datetime, timedelta

import anyio
import pytest
from psycopg import AsyncConnection

from platform_api.db import Database
from platform_api.monitoring import (
    PLATFORM,
    ActivityEvent,
    ActivityLog,
    Copier,
    CosmosEvents,
    PendingEvent,
    RunRetriedData,
    activity_events_adapter,
)
from platform_api.monitoring.log import COPIED_CHANNEL, LoggedEvent
from platform_api.shared import RunId
from tests.conftest import CosmosUnderTest, PostgresUrls
from tests.support import FIXTURES

pytestmark = [pytest.mark.anyio, pytest.mark.cosmos]

RUN = RunId("run_01COSMOS")
OTHER = RunId("run_01OTHER")
START = datetime(2026, 11, 3, 2, 14, tzinfo=UTC)


def logged(seq: int, run_id: RunId = RUN) -> LoggedEvent:
    return LoggedEvent(
        run_id=run_id,
        seq=seq,
        ts=START + timedelta(seconds=seq, microseconds=390000),
        actor=PLATFORM.model_dump(mode="json"),
        kind="run_retried",
        summary=f"event {seq}",
        data={"leg": "work", "attempt": seq},
        dedupe_key=f"once:{seq}",
    )


def as_logged(event: ActivityEvent) -> LoggedEvent:
    return LoggedEvent(
        run_id=event.run_id,
        seq=event.seq,
        ts=event.ts,
        actor=event.actor.model_dump(mode="json"),
        kind=event.kind,
        summary=event.summary,
        data=event.data.model_dump(mode="json"),
        dedupe_key=f"story:{event.seq}",
    )


async def put(events: CosmosEvents, *seqs: int, run_id: RunId = RUN) -> None:
    for seq in seqs:
        await events.put(logged(seq, run_id))


async def test_a_read_returns_the_events_after_a_seq_in_order(cosmos: CosmosUnderTest):
    await put(cosmos.events, 1, 2, 3, 4, 5)

    read = await cosmos.events.read_after(RUN, 2)

    assert [(e.seq, e.summary, e.ts) for e in read] == [
        (seq, f"event {seq}", logged(seq).ts) for seq in (3, 4, 5)
    ]


async def test_reads_sort_on_the_number_seq_not_on_the_text_id(cosmos: CosmosUnderTest):
    order = list(range(1, 13))
    random.Random(4).shuffle(order)
    await put(cosmos.events, *order)

    assert [e.seq for e in await cosmos.events.read_after(RUN, 0)] == list(range(1, 13))
    assert [e.seq for e in await cosmos.events.read_after(RUN, 9)] == [10, 11, 12]


async def test_a_read_stops_before_a_gap(cosmos: CosmosUnderTest):
    await put(cosmos.events, 1, 2, 4, 5)

    assert [e.seq for e in await cosmos.events.read_after(RUN, 0)] == [1, 2]
    assert [e.seq for e in await cosmos.events.read_after(RUN, 3)] == [4, 5]


async def test_the_success_story_round_trips_through_cosmos_db(cosmos: CosmosUnderTest):
    story = activity_events_adapter.validate_python(
        json.loads((FIXTURES / "runs" / "success.json").read_text())
    )
    for event in story:
        await cosmos.events.put(as_logged(event))

    assert await cosmos.events.read_after(story[0].run_id, 0) == story


async def test_an_item_sits_in_its_runs_partition_with_every_column(cosmos: CosmosUnderTest):
    await put(cosmos.events, 7)

    item = await cosmos.container.read_item("7", partition_key=RUN)
    properties = await cosmos.container.read()

    assert properties["partitionKey"]["paths"] == ["/runId"]
    assert {k: v for k, v in item.items() if not k.startswith("_")} == {
        "id": "7",
        "runId": RUN,
        "seq": 7,
        "ts": "2026-11-03T02:14:07.390000+00:00",
        "actor": {"kind": "platform", "id": "platform", "display": "Platform"},
        "kind": "run_retried",
        "summary": "event 7",
        "data": {"leg": "work", "attempt": 7},
        "dedupeKey": "once:7",
    }


async def test_putting_an_event_twice_leaves_one_item(cosmos: CosmosUnderTest):
    await put(cosmos.events, 1, 1, 2, 2)

    assert await cosmos.seqs(RUN) == [1, 2]


async def test_a_run_reads_only_its_own_partition(cosmos: CosmosUnderTest):
    await put(cosmos.events, 1, 2)
    await put(cosmos.events, 1, 2, 3, run_id=OTHER)

    assert [(e.run_id, e.seq) for e in await cosmos.events.read_after(RUN, 0)] == [
        (RUN, 1),
        (RUN, 2),
    ]


async def test_ensure_is_safe_to_repeat(cosmos: CosmosUnderTest):
    await put(cosmos.events, 1)
    await cosmos.events.ensure()

    assert await cosmos.seqs(RUN) == [1]


def pending(n: int) -> PendingEvent:
    return PendingEvent(
        PLATFORM, "run_retried", f"event {n}", RunRetriedData(leg="work", attempt=n)
    )


class CountingReads:
    def __init__(self, inner: CosmosEvents) -> None:
        self.inner = inner
        self.reads: list[int] = []
        self.served: list[list[int]] = []

    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        self.reads.append(after)
        events = await self.inner.read_after(run_id, after)
        self.served.append([e.seq for e in events])
        return events


async def test_a_one_off_read_comes_from_cosmos_db_once_the_copy_reaches_postgresql(
    db: Database, cosmos: CosmosUnderTest
):
    reads = CountingReads(cosmos.events)
    log = ActivityLog(db, copy=reads, copy_wait=0.3)
    async with db.transaction("orchestration") as uow:
        stored = await log.append(uow, RUN, [pending(1), pending(2)])

    with anyio.fail_after(3):
        assert await log.read_after(RUN, 0) == stored
    assert reads.served == [[]]

    await Copier(db, cosmos.events).copy_run(RUN)

    assert await log.read_after(RUN, 0) == stored
    assert reads.served[-1] == [1, 2]


async def test_a_wake_up_that_names_a_copied_seq_at_or_below_the_cursor_reads_nothing(
    db: Database, cosmos: CosmosUnderTest, postgres: PostgresUrls
):
    reads = CountingReads(cosmos.events)
    log = ActivityLog(db, copy=reads)
    await log.start()
    await put(cosmos.events, 1)
    received: list[int] = []

    async def collect() -> None:
        async for event in log.subscribe(RUN, after=0):
            received.append(event.seq)
            if len(received) == 2:
                return

    async def notify(payload: str) -> None:
        async with await AsyncConnection.connect(postgres.contexts.monitoring) as conn:
            await conn.execute("SELECT pg_notify(%s, %s)", (COPIED_CHANNEL, payload))
            await conn.commit()

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(collect)
            with anyio.fail_after(5):
                while received != [1]:
                    await anyio.sleep(0.01)
            await notify(f"{RUN} 1")
            await notify(f"{OTHER} 9")
            await anyio.sleep(0.2)
            assert reads.reads == [0]
            await put(cosmos.events, 2)
            await notify(f"{RUN} 2")
            with anyio.fail_after(5):
                while len(received) < 2:
                    await anyio.sleep(0.01)
    finally:
        await log.stop()

    assert (received, reads.reads) == ([1, 2], [0, 1])
