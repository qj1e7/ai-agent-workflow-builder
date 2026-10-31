from collections.abc import Awaitable, Callable
from contextlib import suppress

import anyio
import psycopg
import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from psycopg import AsyncConnection

from platform_api.db import Database
from platform_api.monitoring import (
    PLATFORM,
    ActivityLog,
    Copier,
    CosmosEvents,
    PendingEvent,
    RunRetriedData,
)
from platform_api.monitoring.cosmos_log import CONTAINER, cosmos_client
from platform_api.monitoring.log import COPIED_CHANNEL, Generation, LoggedEvent
from platform_api.shared import RunId
from tests.conftest import (
    COSMOS_TEST_DATABASE,
    CosmosUnderTest,
    PostgresUrls,
    cosmos_settings,
)

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
        fails: Callable[[RunId, int], bool] = lambda run_id, seq: False,
        delay: float = 0.0,
    ) -> None:
        self.inner = inner
        self.name = name
        self.order = order if order is not None else []
        self.fails = fails
        self.delay = delay
        self.unreachable = False
        self.ensured = 0
        self.sample: Callable[[], bool] | None = None
        self.samples: list[bool] = []

    @property
    def puts(self) -> list[int]:
        return [seq for name, seq in self.order if name == self.name]

    async def ensure(self) -> Generation:
        if self.unreachable:
            raise CosmosDown("ensure")
        generation = await self.inner.ensure()
        self.ensured += 1
        return generation

    async def put(self, event: LoggedEvent) -> None:
        if self.fails(event.run_id, event.seq):
            raise CosmosDown(f"seq {event.seq}")
        if self.sample is not None:
            self.samples.append(self.sample())
        await anyio.sleep(self.delay)
        await self.inner.put(event)
        self.order.append((self.name, event.seq))


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
    watched = Watched(cosmos.events, fails=lambda run_id, seq: down and seq == 3)
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

    def fails(run_id: RunId, seq: int) -> bool:
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


async def test_a_run_that_keeps_failing_does_not_hold_up_another_run(
    db: Database, cosmos: CosmosUnderTest
):
    stuck, other = RunId("run_01STUCK"), RunId("run_01OTHER")
    watched = Watched(cosmos.events, fails=lambda run_id, seq: run_id == stuck)
    copier = Copier(db, watched, retry_delay=5, reconnect_delay=0.1)
    await copier.start()
    try:
        await append(db, 1, run_id=stuck)
        await anyio.sleep(0.2)
        await append(db, 1, 2, run_id=other)
        with anyio.fail_after(1.5):
            while await cosmos.seqs(other) != [1, 2]:
                await anyio.sleep(0.02)
    finally:
        await copier.stop()

    assert await cosmos.seqs(stuck) == []


async def test_a_copier_creates_its_container_before_its_first_copy(
    db: Database, cosmos: CosmosUnderTest
):
    await cosmos.database.delete_container(CONTAINER)
    fresh = CosmosEvents(cosmos_client(cosmos_settings()), database=COSMOS_TEST_DATABASE)
    copier = Copier(db, fresh, reconnect_delay=0.1)

    async def copied() -> list[int]:
        with suppress(CosmosResourceNotFoundError):
            return [e.seq for e in await fresh.read_after(RUN, 0)]
        return []

    await append(db, 1, 2)
    await copier.start()
    try:
        with anyio.fail_after(10):
            while await copied() != [1, 2]:
                await anyio.sleep(0.05)
    finally:
        await copier.stop()
        await fresh.close()


async def test_a_recreated_container_is_filled_again_from_postgresql(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2)
    assert await Copier(db, cosmos.events).copy_run(RUN) == 2
    await cosmos.database.delete_container(CONTAINER)
    fresh = CosmosEvents(cosmos_client(cosmos_settings()), database=COSMOS_TEST_DATABASE)
    try:
        again = Copier(db, fresh)
        assert await again.runs_behind() == [RUN]
        assert await again.copy_run(RUN) == 2
        assert [e.seq for e in await fresh.read_after(RUN, 0)] == [1, 2]
    finally:
        await fresh.close()


async def copied_seqs(cosmos: CosmosUnderTest, run_id: RunId = RUN) -> list[int]:
    with suppress(CosmosHttpResponseError):
        return await cosmos.seqs(run_id)
    return []


async def empty(cosmos: CosmosUnderTest) -> None:
    async for item in cosmos.container.query_items("SELECT c.id, c.runId FROM c"):
        await cosmos.container.delete_item(item["id"], partition_key=item["runId"])


async def test_a_container_deleted_while_the_copier_runs_is_made_again_and_filled(
    db: Database, cosmos: CosmosUnderTest
):
    copier = Copier(db, cosmos.events, retry_delay=0.05, reconnect_delay=0.1)
    await append(db, 1, 2)
    await copier.start()
    try:
        with anyio.fail_after(5):
            while await copied_seqs(cosmos) != [1, 2]:
                await anyio.sleep(0.02)
        await cosmos.database.delete_container(CONTAINER)
        await append(db, 3)
        with anyio.fail_after(15):
            while await copied_seqs(cosmos) != [1, 2, 3]:
                await anyio.sleep(0.05)
    finally:
        await copier.stop()


async def test_a_copier_that_starts_on_an_emptied_container_copies_every_run_again(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2)
    assert await Copier(db, cosmos.events).copy_run(RUN) == 2
    rid = (await cosmos.container.read())["_rid"]
    await empty(cosmos)
    assert (await cosmos.container.read())["_rid"] == rid

    again = Copier(db, cosmos.events)

    assert await again.runs_behind() == [RUN]
    assert await again.copy_run(RUN) == 2
    assert await cosmos.seqs(RUN) == [1, 2]


async def test_a_container_emptied_while_the_copier_runs_is_filled_again(
    db: Database, cosmos: CosmosUnderTest
):
    other = RunId("run_01FINISHED")
    copier = Copier(db, cosmos.events, retry_delay=0.05, reconnect_delay=0.1)
    await append(db, 1, run_id=other)
    await append(db, 1, 2)
    await copier.start()
    try:
        with anyio.fail_after(5):
            while (await copied_seqs(cosmos), await copied_seqs(cosmos, other)) != ([1, 2], [1]):
                await anyio.sleep(0.02)
        await empty(cosmos)
        await append(db, 3)
        with anyio.fail_after(10):
            while (await copied_seqs(cosmos), await copied_seqs(cosmos, other)) != ([1, 2, 3], [1]):
                await anyio.sleep(0.05)
    finally:
        await copier.stop()


async def test_a_second_copier_puts_nothing_again_once_the_first_filled_a_new_container(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2)
    first = Watched(cosmos.events, "first")
    second = Watched(cosmos.events, "second", order=first.order)
    assert await Copier(db, first).copy_run(RUN) == 2
    behind = Copier(db, second)
    assert await behind.runs_behind() == []
    await cosmos.database.delete_container(CONTAINER)

    assert await Copier(db, first).copy_run(RUN) == 2
    assert await behind.copy_run(RUN) == 2

    assert (first.puts, second.puts) == ([1, 2, 1, 2], [])
    assert await cosmos.seqs(RUN) == [1, 2]


async def test_a_copier_whose_copy_keeps_failing_is_behind_until_it_catches_up(
    db: Database, cosmos: CosmosUnderTest
):
    down = True
    watched = Watched(cosmos.events, fails=lambda run_id, seq: down)
    copier = Copier(db, watched, retry_delay=0.05, max_retry_delay=0.1, reconnect_delay=0.1)
    await copier.start()
    try:
        assert copier.behind is False
        await append(db, 1)
        with anyio.fail_after(5):
            while not copier.behind:
                await anyio.sleep(0.02)
        down = False
        with anyio.fail_after(5):
            while copier.behind or await cosmos.seqs(RUN) != [1]:
                await anyio.sleep(0.02)
    finally:
        await copier.stop()


async def generation(cosmos: CosmosUnderTest) -> str | None:
    with suppress(CosmosHttpResponseError):
        item = await cosmos.container.read_item("generation", partition_key="copier")
        return item["generation"]
    return None


async def until(condition: Callable[[], Awaitable[bool]], seconds: float) -> None:
    with anyio.fail_after(seconds):
        while not await condition():
            await anyio.sleep(0.02)


@pytest.mark.parametrize("what", ["container", "database"])
async def test_a_copy_deleted_while_nothing_is_logged_is_made_again_and_filled(
    db: Database, cosmos: CosmosUnderTest, what: str
):
    other = RunId("run_01FINISHED")
    await append(db, 1, run_id=other)
    await append(db, 1, 2)
    copier = Copier(db, cosmos.events, idle_check=0.1, retry_delay=0.05, reconnect_delay=0.1)

    async def both_copied() -> bool:
        return (await copied_seqs(cosmos), await copied_seqs(cosmos, other)) == ([1, 2], [1])

    await copier.start()
    try:
        await until(both_copied, 5)
        first = await generation(cosmos)
        await cosmos.delete(what)

        async def copied_again() -> bool:
            return await generation(cosmos) not in (None, first) and await both_copied()

        await until(copied_again, 5)
    finally:
        await copier.stop()


async def test_a_copier_is_behind_from_finding_its_copy_gone_until_it_is_filled_again(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2, 3)
    watched = Watched(cosmos.events, delay=0.05)
    copier = Copier(db, watched, batch=1, idle_check=0.1, reconnect_delay=0.1)
    watched.sample = lambda: copier.behind

    async def caught_up() -> bool:
        return not copier.behind and await copied_seqs(cosmos) == [1, 2, 3]

    async def behind() -> bool:
        return copier.behind

    await copier.start()
    try:
        await until(caught_up, 5)
        watched.samples.clear()
        await cosmos.delete("container")
        await until(behind, 5)
        await until(caught_up, 5)
    finally:
        await copier.stop()

    assert watched.samples == [True, True, True]


async def test_a_nudged_copier_checks_its_copy_at_once(db: Database, cosmos: CosmosUnderTest):
    await append(db, 1, 2)
    copier = Copier(db, cosmos.events, idle_check=60, reconnect_delay=0.1)

    async def copied() -> bool:
        return await copied_seqs(cosmos) == [1, 2]

    await copier.start()
    try:
        await until(copied, 5)
        first = await generation(cosmos)
        await cosmos.delete("container")
        copier.check_soon()

        async def copied_again() -> bool:
            return await generation(cosmos) not in (None, first) and await copied()

        await until(copied_again, 3)
    finally:
        await copier.stop()


async def test_a_copier_that_cannot_reach_cosmos_db_while_idle_is_behind_until_it_can(
    db: Database, cosmos: CosmosUnderTest
):
    watched = Watched(cosmos.events)
    copier = Copier(db, watched, idle_check=0.1, reconnect_delay=0.1)

    async def behind() -> bool:
        return copier.behind

    async def not_behind() -> bool:
        return not copier.behind

    async def swept_at_start() -> bool:
        return watched.ensured > 0 and not copier.behind

    await copier.start()
    try:
        await until(swept_at_start, 2)
        watched.unreachable = True
        await until(behind, 3)
        watched.unreachable = False
        await until(not_behind, 3)
    finally:
        await copier.stop()


async def test_a_stream_of_an_old_run_gets_every_event_while_its_copy_is_made_again(
    db: Database, cosmos: CosmosUnderTest
):
    await append(db, 1, 2, 3)
    copier = Copier(db, Watched(cosmos.events, delay=0.2), idle_check=60, reconnect_delay=0.1)
    log = ActivityLog(db, copy=cosmos.events, status=copier, read_retry=0.05, reconnect_delay=0.1)
    received: list[int] = []

    async def copied() -> bool:
        return await copied_seqs(cosmos) == [1, 2, 3]

    async def collect() -> None:
        async for event in log.subscribe(RUN, after=0):
            received.append(event.seq)
            if event.seq == 3:
                return

    await log.start()
    await copier.start()
    try:
        await until(copied, 5)
        await cosmos.delete("container")
        with anyio.fail_after(5):
            await collect()
    finally:
        await copier.stop()
        await log.stop()

    assert received == [1, 2, 3]
