from collections.abc import Callable

import anyio
import psycopg
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
)
from platform_api.monitoring.log import COPIED_CHANNEL, LoggedEvent
from platform_api.shared import RunId
from tests.conftest import CosmosUnderTest, PostgresUrls

pytestmark = [pytest.mark.anyio, pytest.mark.cosmos]

RUN = RunId("run_01COPY")


class CosmosDown(Exception):
    pass


class Watched:
    def __init__(
        self,
        inner: CosmosEvents,
        name: str = "copier",
        *,
        order: list[tuple[str, int]] | None = None,
        fails: Callable[[int], bool] = lambda seq: False,
        delay: float = 0.0,
    ) -> None:
        self.inner = inner
        self.name = name
        self.order = order if order is not None else []
        self.fails = fails
        self.delay = delay

    @property
    def puts(self) -> list[int]:
        return [seq for name, seq in self.order if name == self.name]

    async def put(self, event: LoggedEvent) -> None:
        if self.fails(event.seq):
            raise CosmosDown(f"seq {event.seq}")
        await anyio.sleep(self.delay)
        await self.inner.put(event)
        self.order.append((self.name, event.seq))

    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]:
        return await self.inner.read_after(run_id, after)


def pending(n: int) -> PendingEvent:
    return PendingEvent(
        PLATFORM, "run_retried", f"event {n}", RunRetriedData(leg="work", attempt=n)
    )


async def append(db: Database, *numbers: int, run_id: RunId = RUN) -> None:
    async with db.transaction("orchestration") as uow:
        await ActivityLog(db).append(uow, run_id, [pending(n) for n in numbers])


async def mark(db: Database, run_id: RunId = RUN) -> int | None:
    async with db.transaction("monitoring") as uow:
        row = await (
            await uow.conn.execute(
                "SELECT seq FROM monitoring.run_events_copied WHERE run_id = %s", (run_id,)
            )
        ).fetchone()
    return None if row is None else int(row["seq"])


async def test_a_copy_puts_each_new_event_in_order_and_records_the_highest(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2, 3)
    watched = Watched(cosmos.events)

    assert await Copier(db, watched).copy_run(RUN) == 3

    assert watched.puts == [1, 2, 3]
    assert await cosmos.seqs(RUN) == [1, 2, 3]
    assert await mark(db) == 3


async def test_a_copy_that_runs_twice_puts_nothing_the_second_time(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2, 3)
    watched = Watched(cosmos.events)
    copier = Copier(db, watched)

    await copier.copy_run(RUN)
    assert await copier.copy_run(RUN) == 3

    assert watched.puts == [1, 2, 3]
    assert await cosmos.seqs(RUN) == [1, 2, 3]


async def test_a_copy_repeated_after_a_crash_before_the_mark_leaves_each_event_once(
    db: Database, cosmos: CosmosUnderTest, postgres: PostgresUrls
):
    await append(db, 1, 2, 3)
    watched = Watched(cosmos.events)
    copier = Copier(db, watched)
    await copier.copy_run(RUN)
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("DELETE FROM monitoring.run_events_copied")

    assert await copier.copy_run(RUN) == 3

    assert watched.puts == [1, 2, 3, 1, 2, 3]
    assert await cosmos.seqs(RUN) == [1, 2, 3]


async def test_a_copy_that_fails_halfway_keeps_its_progress_and_the_next_one_finishes(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2, 3, 4, 5)
    down = True
    watched = Watched(cosmos.events, fails=lambda seq: down and seq == 3)
    copier = Copier(db, watched, batch=2)

    with pytest.raises(CosmosDown):
        await copier.copy_run(RUN)
    assert (await mark(db), await cosmos.seqs(RUN)) == (2, [1, 2])

    down = False
    assert await copier.copy_run(RUN) == 5

    assert watched.puts == [1, 2, 3, 4, 5]
    assert await cosmos.seqs(RUN) == [1, 2, 3, 4, 5]


async def test_two_copiers_on_one_run_take_turns_and_put_each_event_once_in_order(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2, 3, 4, 5, 6)
    order: list[tuple[str, int]] = []
    first = Copier(db, Watched(cosmos.events, "first", order=order, delay=0.02), batch=2)
    second = Copier(db, Watched(cosmos.events, "second", order=order, delay=0.02), batch=2)
    finished: list[int] = []

    async def copy(copier: Copier) -> None:
        finished.append(await copier.copy_run(RUN))

    async with anyio.create_task_group() as tg:
        tg.start_soon(copy, first)
        tg.start_soon(copy, second)

    assert [seq for _, seq in order] == [1, 2, 3, 4, 5, 6]
    assert finished == [6, 6]
    assert await cosmos.seqs(RUN) == [1, 2, 3, 4, 5, 6]
    assert await mark(db) == 6


async def test_an_event_added_after_the_first_copy_is_copied_by_the_next(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2)
    watched = Watched(cosmos.events)
    copier = Copier(db, watched)
    assert await copier.copy_run(RUN) == 2

    await append(db, 3)

    assert await copier.copy_run(RUN) == 3
    assert watched.puts == [1, 2, 3]
    assert await cosmos.seqs(RUN) == [1, 2, 3]


async def test_runs_behind_names_each_run_with_events_not_yet_copied(
    db: Database, cosmos: CosmosUnderTest
):
    done, partly, never = RunId("run_01DONE"), RunId("run_01PARTLY"), RunId("run_01NEVER")
    copier = Copier(db, cosmos.events)
    await append(db, 1, 2, run_id=done)
    await append(db, 1, run_id=partly)
    await copier.copy_run(done)
    await copier.copy_run(partly)
    await append(db, 2, run_id=partly)
    await append(db, 1, run_id=never)

    assert sorted(await copier.runs_behind()) == [never, partly]


async def test_a_running_copier_catches_up_at_start_then_follows_and_names_what_it_copied(
    db: Database, cosmos: CosmosUnderTest, postgres: PostgresUrls
):
    await append(db, 1, 2)
    copier = Copier(db, cosmos.events, reconnect_delay=0.1)
    async with await AsyncConnection.connect(postgres.contexts.monitoring, autocommit=True) as conn:
        await conn.execute(f"LISTEN {COPIED_CHANNEL}")
        await copier.start()
        try:
            with anyio.fail_after(5):
                while await cosmos.seqs(RUN) != [1, 2]:
                    await anyio.sleep(0.02)
            await append(db, 3)
            with anyio.fail_after(5):
                while await cosmos.seqs(RUN) != [1, 2, 3]:
                    await anyio.sleep(0.02)
        finally:
            await copier.stop()
        payloads = [n.payload async for n in conn.notifies(timeout=1, stop_after=2)]

    assert payloads == [f"{RUN} 2", f"{RUN} 3"]


async def test_a_running_copier_retries_a_failed_copy_after_a_short_delay(
    db: Database, cosmos: CosmosUnderTest
):
    attempts: list[int] = []

    def fails(seq: int) -> bool:
        attempts.append(seq)
        return len(attempts) <= 2

    watched = Watched(cosmos.events, fails=fails)
    copier = Copier(db, watched, retry_delay=0.05, reconnect_delay=0.1)
    await copier.start()
    try:
        await append(db, 1, 2)
        with anyio.fail_after(5):
            while await cosmos.seqs(RUN) != [1, 2]:
                await anyio.sleep(0.02)
    finally:
        await copier.stop()

    assert attempts[:2] == [1, 1]
    assert watched.puts == [1, 2]
