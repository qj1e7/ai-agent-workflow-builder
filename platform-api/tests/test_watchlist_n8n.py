"""The Software watchlist moves to its own n8n workflow (ENGINE-PLAN 2.6), with its schedule in
the Schedule Trigger, and changes its schedule there under the version compare (2.5). The real
drafts store runs on a fake n8n."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, LiteralString

import pytest

from platform_api.auth import DEV_PEOPLE
from platform_api.builder import Builder, Watchlist
from platform_api.builder.models import AddSoftware, ScheduleIn, WatchlistView
from platform_api.builder.watchlist import (
    AlreadyOnN8n,
    Move,
    MovedToN8n,
    OnN8n,
    WaitsForRun,
)
from platform_api.db import Database
from platform_api.orchestration import (
    ChangedInN8n,
    NothingToRun,
    RunSpec,
    RunStarted,
    ScheduleBook,
    ScheduleTicker,
)
from platform_api.orchestration.people_store import People
from platform_api.shared import Principal, RunId, UseCaseId
from tests.conftest import PostgresUrls, truncate_all
from tests.fake_n8n import FakeN8n
from tests.support import ALICE, CAROL, MovingClock
from tests.test_n8n_builder import Drafts
from tests.test_watchlist_builder import FakeFacts

pytestmark = pytest.mark.anyio

SOFTWARE_PAGE = "http://portal.example/software"
SCHEDULE_TRIGGER = "n8n-nodes-base.scheduleTrigger"


@dataclass
class OpenRuns:
    open: RunId | None = None

    async def open_run(self, use_case_id: UseCaseId) -> RunId | None:
        return self.open


@dataclass
class World:
    db: Database
    n8n: FakeN8n
    runs: OpenRuns
    on_n8n: Watchlist
    shared: Watchlist
    """The same watchlist as a platform before the move sees it, with no n8n."""

    async def rows(self, sql: LiteralString, *args: object) -> list[dict[str, Any]]:
        async with self.db.connection("builder") as conn:
            return [dict(r) for r in await (await conn.execute(sql, args)).fetchall()]

    async def use_case(self) -> dict[str, Any]:
        [row] = await self.rows(
            "SELECT use_case_id, engine, n8n_workflow_id FROM builder.use_cases"
        )
        return row

    async def version(self, version: int) -> dict[str, Any]:
        [row] = await self.rows(
            "SELECT n8n_version_id, document, grade, published_by, published_in"
            " FROM builder.use_case_versions WHERE version = %s",
            version,
        )
        return row

    async def view(self) -> WatchlistView:
        found = await self.on_n8n.view()
        assert found is not None
        return found

    def rule(self, workflow_id: str) -> dict[str, Any] | None:
        nodes = self.n8n.workflows[workflow_id]["nodes"]
        return next((n["parameters"] for n in nodes if n["type"] == SCHEDULE_TRIGGER), None)


@pytest.fixture
def world(db: Database) -> World:
    return world_on(db)


def world_on(db: Database) -> World:
    n8n, runs, facts, schedules = FakeN8n(), OpenRuns(), FakeFacts(), ScheduleBook(db)
    on = OnN8n(Drafts(n8n, db), runs, SOFTWARE_PAGE)
    return World(
        db,
        n8n,
        runs,
        Watchlist(db, facts, schedules, n8n=on),
        Watchlist(db, facts, schedules),
    )


def langgraph() -> AddSoftware:
    return AddSoftware(name="LangGraph", repo="langchain-ai/langgraph", our_version="1.2.14")


async def watchlist_before_the_move(world: World) -> None:
    """Made before the move, with Carol's Tuesday 07:30 schedule."""
    await world.shared.add(ALICE, langgraph())
    await world.shared.save_schedule(CAROL, ScheduleIn(day="tuesday", at="07:30"))


async def test_the_move_copies_the_schedule_into_the_trigger_and_puts_it_live(world: World):
    await watchlist_before_the_move(world)
    before = await world.view()

    moved = await world.on_n8n.move_to_n8n()

    assert isinstance(moved, MovedToN8n) and moved.version == 2
    assert world.rule(moved.workflow_id) == {
        "rule": {
            "interval": [
                {"field": "weeks", "triggerAtDay": [2], "triggerAtHour": 7, "triggerAtMinute": 30}
            ]
        }
    }
    use_case = await world.use_case()
    assert (use_case["engine"], use_case["n8n_workflow_id"]) == ("own", moved.workflow_id)
    stored = await world.version(2)
    assert stored["document"]["nodes"] == world.n8n.workflows[moved.workflow_id]["nodes"]
    assert world.n8n.workflows[moved.workflow_id]["activeVersionId"] == stored["n8n_version_id"]
    assert (stored["grade"], stored["published_by"], stored["published_in"]) == (
        "safe",
        CAROL.user_id,
        "portal",
    ), "the schedule owner, who could not approve its scheduled checks, still cannot"
    after = await world.view()
    assert after.version == 2
    assert after.software == before.software, "the Software page's rows are unchanged"
    assert after.schedule is not None and before.schedule is not None
    assert (after.schedule.day, after.schedule.at, after.schedule.owner) == (
        "tuesday",
        "07:30",
        "carol",
    )
    assert after.schedule.next_at is not None


async def test_a_second_move_changes_nothing(world: World):
    await watchlist_before_the_move(world)
    await world.on_n8n.move_to_n8n()

    assert await world.on_n8n.move_to_n8n() == AlreadyOnN8n()
    assert len(world.n8n.workflows) == 1
    assert len(await world.rows("SELECT 1 FROM builder.use_case_versions")) == 2


async def test_a_watchlist_with_a_check_not_ended_stays_until_it_ends(world: World):
    """The team lead's watchlist waits for Bob's yes: it is not touched, and it says so."""
    await watchlist_before_the_move(world)
    world.runs.open = RunId("run_waiting")

    assert await world.on_n8n.move_to_n8n() == WaitsForRun(RunId("run_waiting"))
    assert (await world.use_case())["engine"] == "shared_run"
    assert world.n8n.workflows == {}
    assert (await world.view()).moving_to_n8n is True

    world.runs.open = None
    assert isinstance(await world.on_n8n.move_to_n8n(), MovedToN8n)
    assert (await world.view()).moving_to_n8n is False


async def test_a_new_watchlist_is_born_on_its_own_workflow(world: World):
    added = await world.on_n8n.add(ALICE, langgraph())
    assert isinstance(added, WatchlistView)

    use_case = await world.use_case()
    assert use_case["engine"] == "own"
    assert world.rule(use_case["n8n_workflow_id"]) == {
        "rule": {
            "interval": [
                {"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 9, "triggerAtMinute": 0}
            ]
        }
    }
    assert added.version == 2
    assert [row.name for row in added.software] == ["LangGraph"]


async def test_when_n8n_does_not_keep_the_workflow_the_watchlist_runs_as_before(world: World):
    await watchlist_before_the_move(world)
    world.n8n.keeps = lambda document: {**document, "name": "Something else"}

    moved = await world.on_n8n.move_to_n8n()

    assert "n8n" in getattr(moved, "detail", "")
    assert (await world.use_case())["engine"] == "shared_run"
    assert world.n8n.workflows == {}
    assert len(await world.rows("SELECT 1 FROM builder.use_case_versions")) == 1


async def test_a_list_change_keeps_running_the_same_workflow(world: World):
    await watchlist_before_the_move(world)
    moved = await world.on_n8n.move_to_n8n()
    assert isinstance(moved, MovedToN8n)

    await world.on_n8n.add(
        ALICE, AddSoftware(name="Redis", repo="redis/redis", our_version="8.2.1")
    )

    assert await world.version(3) == await world.version(2)


async def test_a_new_schedule_changes_the_trigger_in_n8n_first(world: World):
    await watchlist_before_the_move(world)
    moved = await world.on_n8n.move_to_n8n()
    assert isinstance(moved, MovedToN8n)

    saved = await world.on_n8n.save_schedule(ALICE, ScheduleIn(day="friday", at="08:00"))

    assert isinstance(saved, WatchlistView) and saved.version == 3
    assert world.rule(moved.workflow_id) == {
        "rule": {
            "interval": [
                {"field": "weeks", "triggerAtDay": [5], "triggerAtHour": 8, "triggerAtMinute": 0}
            ]
        }
    }
    stored = await world.version(3)
    assert world.n8n.workflows[moved.workflow_id]["activeVersionId"] == stored["n8n_version_id"]
    assert stored["published_by"] == ALICE.user_id
    assert saved.schedule is not None and saved.schedule.owner == "alice"

    off = await world.on_n8n.turn_off_schedule(ALICE)
    assert isinstance(off, WatchlistView) and off.schedule is None
    assert world.rule(moved.workflow_id) is None, "nothing in n8n starts it on a schedule"


async def test_a_schedule_change_over_an_edit_in_n8n_saves_nothing(world: World):
    await watchlist_before_the_move(world)
    moved = await world.on_n8n.move_to_n8n()
    assert isinstance(moved, MovedToN8n)
    world.n8n.edit(moved.workflow_id)

    refused = await world.on_n8n.save_schedule(ALICE, ScheduleIn(day="friday", at="08:00"))

    assert isinstance(refused, ChangedInN8n)
    view = await world.view()
    assert view.version == 2
    assert view.schedule is not None and (view.schedule.day, view.schedule.owner) == (
        "tuesday",
        "carol",
    )


@dataclass
class Starts:
    specs: list[RunSpec] = field(default_factory=list[RunSpec])

    async def start_run(self, spec: RunSpec, principal: Principal, idempotency_key: str):
        self.specs.append(spec)
        return RunStarted(RunId(f"run_{len(self.specs)}"), created=True)


async def test_the_schedule_tick_leaves_a_moved_watchlist_to_its_schedule_trigger(
    postgres: PostgresUrls,
):
    truncate_all(postgres.owner)
    clock = MovingClock()
    db = Database(postgres.contexts, clock=clock)
    await db.open()
    try:
        assert await People(db).seed_dev(DEV_PEOPLE), "Carol, the schedule's owner, is an Operator"
        world = world_on(db)
        await watchlist_before_the_move(world)
        starts = Starts()
        ticker = ScheduleTicker(db, ScheduleBook(db), Builder(db, starts, world.on_n8n, ""), starts)
        clock.now += timedelta(days=7)
        assert len(await ticker.tick()) == 1, "before the move, the tick starts its check"

        assert isinstance(await world.on_n8n.move_to_n8n(), MovedToN8n)
        clock.now += timedelta(days=7)
        assert await ticker.tick() == []
        assert len(starts.specs) == 1, "after it, n8n's Schedule Trigger starts it, not the tick"
    finally:
        await db.close()


async def test_an_empty_watchlist_has_nothing_on_the_list_to_check(world: World):
    added = await world.on_n8n.add(ALICE, langgraph())
    assert isinstance(added, WatchlistView)
    await world.on_n8n.remove(added.software[0].id)
    facts = Builder(world.db, Starts(), world.on_n8n, "").facts

    workflow_id = (await world.use_case())["n8n_workflow_id"]

    assert await facts.workflow(workflow_id) == NothingToRun("Nothing on the list to check.")


async def test_the_builder_knows_the_watchlist_s_own_workflow(world: World):
    await world.on_n8n.add(ALICE, langgraph())
    facts = Builder(world.db, Starts(), world.on_n8n, "").facts

    workflow_id = (await world.use_case())["n8n_workflow_id"]

    assert await facts.watchlist(workflow_id) is True
    assert await facts.watchlist("wf-someone-else") is False


class Crash(BaseException):
    """The process stops here, so no handler runs."""


class CrashesOnceLive(Drafts):
    async def go_live(self, workflow_id: str, version_id: str) -> None:
        await super().go_live(workflow_id, version_id)
        raise Crash


async def test_a_move_cut_off_once_its_workflow_is_live_is_finished_by_the_next(world: World):
    await watchlist_before_the_move(world)
    on = OnN8n(CrashesOnceLive(world.n8n, world.db), world.runs, SOFTWARE_PAGE)
    with pytest.raises(Crash):
        await Watchlist(world.db, FakeFacts(), ScheduleBook(world.db), n8n=on).move_to_n8n()
    assert len(world.n8n.workflows) == 1
    assert (await world.use_case())["engine"] == "shared_run"

    moved = await world.on_n8n.move_to_n8n()

    assert isinstance(moved, MovedToN8n)
    assert list(world.n8n.workflows) == [moved.workflow_id], "nothing of the cut-off move is left"
    assert (await world.use_case())["n8n_workflow_id"] == moved.workflow_id


class MovedMeanwhile(Watchlist):
    """Another start moved the watchlist between Check now's first read and its own move."""

    def __init__(self, world: World) -> None:
        super().__init__(world.db, FakeFacts(), ScheduleBook(world.db))
        self.world = world

    async def move_to_n8n(self) -> Move:
        await self.world.on_n8n.move_to_n8n()
        return AlreadyOnN8n()


async def test_check_now_runs_the_version_that_is_current_after_the_move(world: World):
    await watchlist_before_the_move(world)
    starts = Starts()
    builder = Builder(world.db, starts, MovedMeanwhile(world), "")
    [use_case_id] = [
        row["use_case_id"] for row in await world.rows("SELECT use_case_id FROM builder.use_cases")
    ]

    await builder.start_run(UseCaseId(use_case_id), ALICE, "check-now-1")

    [spec] = starts.specs
    assert (spec.use_case_version, spec.n8n is not None) == (2, True)
