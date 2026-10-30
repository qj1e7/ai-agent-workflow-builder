import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest

from platform_api.auth import DEV_PEOPLE
from platform_api.db import Database
from platform_api.orchestration import (
    NotOn,
    RunSpec,
    RunStarted,
    RunStarter,
    Schedule,
    ScheduleBook,
    ScheduleTicker,
)
from platform_api.orchestration.approvals import Refusal, Verdict
from platform_api.orchestration.http import run_view
from platform_api.orchestration.people import Person
from platform_api.orchestration.people_store import People, PersonRow
from platform_api.orchestration.runs import AwaitingApproval, StepName
from platform_api.orchestration.service import Decided, DecisionRefused
from platform_api.shared import N8nExecutionId, Principal, Role, UseCaseId
from tests.conftest import PostgresUrls
from tests.support import ALICE, BOB, CAROL, NOW, SPEC, WATCHLIST_SPEC
from tests.test_orchestrator import Harness, open_harness

pytestmark = pytest.mark.anyio

WATCHLIST = WATCHLIST_SPEC.use_case_id
OTHER = UseCaseId("uc_01OTHER")
MONDAY_9 = Schedule("monday", "09:00")
# NOW is Tuesday 3 Nov 2026, 10:14 in Singapore.
NEXT_MONDAY = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
SLOT = "2026-11-09T09:00:00+08:00"


@dataclass
class FakeSpecs:
    """The builder's side of the port: a spec for each watchlist, or nothing to check."""

    specs: dict[UseCaseId, RunSpec | NotOn | None] = field(
        default_factory=dict[UseCaseId, RunSpec | NotOn | None]
    )
    broken: set[UseCaseId] = field(default_factory=set[UseCaseId])
    asked: list[UseCaseId] = field(default_factory=list[UseCaseId])

    async def check_spec(self, use_case_id: UseCaseId) -> RunSpec | NotOn | None:
        self.asked.append(use_case_id)
        if use_case_id in self.broken:
            raise RuntimeError("the Jira refresh fell over")
        return self.specs[use_case_id]


@dataclass
class Recording:
    """The orchestrator, keeping the person each run was started as."""

    runs: RunStarter
    started_as: list[Principal] = field(default_factory=list[Principal])

    async def start_run(
        self, spec: RunSpec, principal: Principal, idempotency_key: str
    ) -> RunStarted:
        self.started_as.append(principal)
        return await self.runs.start_run(spec, principal, idempotency_key)


@dataclass
class Ticking:
    h: Harness
    book: ScheduleBook
    specs: FakeSpecs
    people: People
    runs: Recording
    ticker: ScheduleTicker

    def at(self, moment: datetime) -> None:
        self.h.clock["now"] = moment

    async def run_keys(self) -> list[tuple[str, str, str]]:
        async with self.h.db.connection("orchestration") as conn:
            rows = await (
                await conn.execute(
                    "SELECT use_case_id, idempotency_key, started_by FROM orchestration.runs "
                    "ORDER BY started_at, run_id"
                )
            ).fetchall()
        return [(r["use_case_id"], r["idempotency_key"], r["started_by"]) for r in rows]


@pytest.fixture
async def ticking(postgres: PostgresUrls) -> AsyncIterator[Ticking]:
    async with open_harness(postgres) as h:
        book = ScheduleBook(h.db)
        specs = FakeSpecs(
            {WATCHLIST: WATCHLIST_SPEC, OTHER: replace(WATCHLIST_SPEC, use_case_id=OTHER)}
        )
        people = People(h.db)
        assert await people.seed_dev(DEV_PEOPLE)
        runs = Recording(h.orchestrator)
        yield Ticking(h, book, specs, people, runs, ScheduleTicker(h.db, book, specs, runs))


async def test_nothing_is_due_before_the_slot(ticking: Ticking):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    ticking.at(NEXT_MONDAY - timedelta(minutes=5))
    assert await ticking.ticker.tick() == []
    assert ticking.specs.asked == []


async def test_a_due_schedule_starts_a_check_as_its_owner(ticking: Ticking):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    ticking.at(NEXT_MONDAY + timedelta(minutes=3))

    [run_id] = await ticking.ticker.tick()

    assert await ticking.run_keys() == [(WATCHLIST, f"schedule:{WATCHLIST}:{SLOT}", "carol")]
    detail = await ticking.h.orchestrator.get_run(run_id)
    assert detail is not None
    assert detail.record.started_by == "carol"
    assert detail.record.spec.trigger == "schedule"
    assert run_view(detail).trigger == "schedule"
    [created, *_] = await ticking.h.log.read_after(run_id, 0)
    assert created.kind == "run_created"
    assert created.summary == "Carol's schedule started a check of the Software watchlist."
    assert created.data.trigger == "schedule"  # type: ignore[union-attr]
    assert (created.actor.id, created.data.started_by) == ("carol", "carol")  # type: ignore[union-attr]


async def test_a_person_s_run_says_it_was_started_by_a_person(ticking: Ticking):
    started = await ticking.h.orchestrator.start_run(SPEC, ALICE, "by-hand")
    detail = await ticking.h.orchestrator.get_run(started.run_id)
    assert detail is not None and run_view(detail).trigger == "person"
    [created, *_] = await ticking.h.log.read_after(started.run_id, 0)
    assert created.summary == "Alice started a run of the Software watchlist."
    assert created.data.trigger == "person"  # type: ignore[union-attr]


async def test_a_repeated_tick_in_the_same_slot_starts_nothing(ticking: Ticking):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    ticking.at(NEXT_MONDAY + timedelta(minutes=1))
    assert len(await ticking.ticker.tick()) == 1
    ticking.at(NEXT_MONDAY + timedelta(minutes=6))
    assert await ticking.ticker.tick() == []
    ticking.at(NEXT_MONDAY + timedelta(hours=20))
    assert await ticking.ticker.tick() == []
    assert len(await ticking.run_keys()) == 1


async def test_a_tick_that_died_before_recording_the_slot_does_not_start_a_second_check(
    ticking: Ticking,
):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    ticking.at(NEXT_MONDAY)
    assert len(await ticking.ticker.tick()) == 1
    async with ticking.h.db.transaction("orchestration") as uow:
        await uow.conn.execute("UPDATE orchestration.schedules SET last_slot_started = NULL")

    assert await ticking.ticker.tick() == []

    assert len(await ticking.run_keys()) == 1
    [saved] = await ticking.book.all()
    assert saved.last_slot_started is not None


async def test_several_missed_slots_start_one_check_for_the_latest(ticking: Ticking):
    await ticking.book.save(WATCHLIST, Schedule("every_day", "09:00"), CAROL)
    ticking.at(NOW + timedelta(days=5, hours=1))  # Sunday 8 Nov, 11:14 in Singapore

    assert len(await ticking.ticker.tick()) == 1

    assert [key for _, key, _ in await ticking.run_keys()] == [
        f"schedule:{WATCHLIST}:2026-11-08T09:00:00+08:00"
    ]


async def test_a_schedule_saved_after_this_week_s_slot_waits_for_the_next(ticking: Ticking):
    ticking.at(NEXT_MONDAY + timedelta(hours=2))
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    ticking.at(NEXT_MONDAY + timedelta(days=3))
    assert await ticking.ticker.tick() == []
    ticking.at(NEXT_MONDAY + timedelta(days=7))
    assert len(await ticking.ticker.tick()) == 1


async def test_a_watchlist_with_no_software_records_the_slot_and_starts_nothing(
    ticking: Ticking,
):
    ticking.specs.specs[WATCHLIST] = None
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    ticking.at(NEXT_MONDAY)

    assert await ticking.ticker.tick() == []
    assert await ticking.ticker.tick() == []

    assert ticking.specs.asked == [WATCHLIST]
    [saved] = await ticking.book.all()
    assert saved.last_slot_started == NEXT_MONDAY
    assert await ticking.run_keys() == []


@pytest.mark.parametrize("state", ["paused", "deleted"])
async def test_a_paused_or_deleted_workflow_uses_its_slot_up_and_starts_nothing(
    ticking: Ticking, caplog: pytest.LogCaptureFixture, state: Literal["paused", "deleted"]
):
    ticking.specs.specs[WATCHLIST] = NotOn(state)
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    ticking.at(NEXT_MONDAY + timedelta(minutes=1))

    with caplog.at_level(logging.INFO, logger="platform_api.orchestration.schedule_store"):
        assert await ticking.ticker.tick() == []

    assert await ticking.run_keys() == []
    [saved] = await ticking.book.all()
    assert saved.last_slot_started == NEXT_MONDAY
    assert f"skipped the scheduled check of {WATCHLIST}, which is {state}" in caplog.text


async def test_a_workflow_resumed_after_its_slot_waits_for_the_next_one(ticking: Ticking):
    ticking.specs.specs[WATCHLIST] = NotOn("paused")
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    ticking.at(NEXT_MONDAY + timedelta(minutes=1))
    assert await ticking.ticker.tick() == []

    ticking.specs.specs[WATCHLIST] = WATCHLIST_SPEC
    ticking.at(NEXT_MONDAY + timedelta(hours=2))
    assert await ticking.ticker.tick() == []
    ticking.at(NEXT_MONDAY + timedelta(days=7, minutes=1))
    assert len(await ticking.ticker.tick()) == 1

    assert [key for _, key, _ in await ticking.run_keys()] == [
        f"schedule:{WATCHLIST}:2026-11-16T09:00:00+08:00"
    ]


async def test_a_scheduled_run_starts_as_its_owner_with_the_roles_they_hold_now(
    ticking: Ticking,
):
    await ticking.book.save(WATCHLIST, MONDAY_9, ALICE)  # Alice is an Operator and an Approver
    ticking.at(NEXT_MONDAY)

    assert len(await ticking.ticker.tick()) == 1

    assert ticking.runs.started_as == [ALICE]


SKIPPED = "skipped the scheduled check of {use_case}, because its owner {owner} {why}"


async def test_a_schedule_whose_owner_left_the_list_uses_its_slot_up_and_starts_nothing(
    ticking: Ticking, caplog: pytest.LogCaptureFixture
):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    assert isinstance(await ticking.people.remove(ALICE, "carol"), Person)
    ticking.at(NEXT_MONDAY + timedelta(minutes=1))

    with caplog.at_level(logging.INFO, logger="platform_api.orchestration.schedule_store"):
        assert await ticking.ticker.tick() == []
        ticking.at(NEXT_MONDAY + timedelta(minutes=6))
        assert await ticking.ticker.tick() == []

    assert await ticking.run_keys() == []
    assert ticking.specs.asked == [], "a held schedule does not build a check"
    [saved] = await ticking.book.all()
    assert saved.last_slot_started == NEXT_MONDAY
    skipped = SKIPPED.format(use_case=WATCHLIST, owner="carol", why="has left the People list")
    assert caplog.text.count(skipped) == 1, "the slot is used up, so the next tick is quiet"


async def test_a_schedule_whose_owner_is_now_only_an_approver_uses_its_slot_up_and_starts_nothing(
    ticking: Ticking, caplog: pytest.LogCaptureFixture
):
    await ticking.book.save(WATCHLIST, MONDAY_9, ALICE)
    changed = await ticking.people.set_operator(CAROL, "alice", False)
    assert isinstance(changed, Person) and changed.roles == {Role.APPROVER}
    ticking.at(NEXT_MONDAY + timedelta(minutes=1))

    with caplog.at_level(logging.INFO, logger="platform_api.orchestration.schedule_store"):
        assert await ticking.ticker.tick() == []

    assert await ticking.run_keys() == []
    [saved] = await ticking.book.all()
    assert saved.last_slot_started == NEXT_MONDAY
    skipped = SKIPPED.format(use_case=WATCHLIST, owner="alice", why="is no longer an Operator")
    assert skipped in caplog.text


async def test_an_operator_who_saves_a_held_schedule_again_takes_it_over(ticking: Ticking):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    assert isinstance(await ticking.people.remove(ALICE, "carol"), Person)
    ticking.at(NEXT_MONDAY + timedelta(minutes=1))
    assert await ticking.ticker.tick() == []

    ticking.at(NEXT_MONDAY + timedelta(hours=1))
    taken = await ticking.book.save(WATCHLIST, MONDAY_9, ALICE)
    assert taken.owner == "alice"
    ticking.at(NEXT_MONDAY + timedelta(days=7, minutes=1))
    assert len(await ticking.ticker.tick()) == 1

    assert [(key, by) for _, key, by in await ticking.run_keys()] == [
        (f"schedule:{WATCHLIST}:2026-11-16T09:00:00+08:00", "alice")
    ]
    assert ticking.runs.started_as == [ALICE]


async def test_a_held_schedule_starts_again_once_its_owner_is_an_operator_again(
    ticking: Ticking,
):
    await ticking.book.save(WATCHLIST, MONDAY_9, ALICE)
    assert isinstance(await ticking.people.set_operator(CAROL, "alice", False), Person)
    ticking.at(NEXT_MONDAY + timedelta(minutes=1))
    assert await ticking.ticker.tick() == []

    assert isinstance(await ticking.people.set_operator(CAROL, "alice", True), Person)
    ticking.at(NEXT_MONDAY + timedelta(hours=2))
    assert await ticking.ticker.tick() == [], "the slot it missed while held stays used up"
    ticking.at(NEXT_MONDAY + timedelta(days=7, minutes=1))
    assert len(await ticking.ticker.tick()) == 1

    assert [key for _, key, _ in await ticking.run_keys()] == [
        f"schedule:{WATCHLIST}:2026-11-16T09:00:00+08:00"
    ]


async def test_a_removed_owner_added_back_under_the_same_id_runs_the_next_slot_as_themselves(
    ticking: Ticking,
):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    assert isinstance(await ticking.people.remove(ALICE, "carol"), Person)
    ticking.at(NEXT_MONDAY + timedelta(minutes=1))
    assert await ticking.ticker.tick() == []

    back = await ticking.people.add(ALICE, "carol@example.test", "Carol", True, False)
    assert isinstance(back, PersonRow) and back.person.id == "carol"
    ticking.at(NEXT_MONDAY + timedelta(hours=2))
    assert await ticking.ticker.tick() == [], "the slot it missed while held stays used up"
    ticking.at(NEXT_MONDAY + timedelta(days=7, minutes=1))
    assert len(await ticking.ticker.tick()) == 1

    assert [(key, by) for _, key, by in await ticking.run_keys()] == [
        (f"schedule:{WATCHLIST}:2026-11-16T09:00:00+08:00", "carol")
    ]
    assert ticking.runs.started_as == [CAROL]


async def test_a_schedule_whose_spec_cannot_be_built_does_not_block_the_others(
    ticking: Ticking, caplog: pytest.LogCaptureFixture
):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    await ticking.book.save(OTHER, MONDAY_9, ALICE)
    ticking.specs.broken.add(WATCHLIST)
    ticking.at(NEXT_MONDAY)

    started = await ticking.ticker.tick()

    assert len(started) == 1
    assert [(use_case, by) for use_case, _, by in await ticking.run_keys()] == [(OTHER, "alice")]
    assert "could not start the scheduled check" in caplog.text
    ticking.specs.broken.clear()
    ticking.at(NEXT_MONDAY + timedelta(minutes=5))
    assert len(await ticking.ticker.tick()) == 1, (
        "the slot was not used up, so the next tick retries"
    )


async def test_a_schedule_turned_off_starts_nothing(ticking: Ticking):
    await ticking.book.save(WATCHLIST, MONDAY_9, CAROL)
    await ticking.book.delete(WATCHLIST)
    ticking.at(NEXT_MONDAY)
    assert await ticking.ticker.tick() == []
    assert await ticking.book.get(WATCHLIST) is None


async def test_the_schedule_owner_cannot_approve_the_scheduled_check_but_another_approver_can(
    ticking: Ticking,
):
    h = ticking.h
    ticking.specs.specs[WATCHLIST] = replace(SPEC, use_case_id=WATCHLIST)
    await ticking.book.save(WATCHLIST, MONDAY_9, ALICE)  # Alice is an Approver, and the owner
    ticking.at(NEXT_MONDAY)
    [run_id] = await ticking.ticker.tick()
    await h.orchestrator.tick()
    execution = N8nExecutionId("41")
    await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, execution)
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, execution)
    await h.orchestrator.tick()
    detail = await h.orchestrator.get_run(run_id)
    assert detail is not None and isinstance(detail.record.state, AwaitingApproval)
    approval_id = detail.record.state.approval_id

    own = await h.orchestrator.get_approval(approval_id, ALICE)
    assert own is not None and own.why_not is Refusal.OWN_WORK
    refused = await h.orchestrator.decide(
        approval_id, ALICE, 0, Verdict.APPROVE, own.request.digest
    )
    assert refused == DecisionRefused(Refusal.OWN_WORK)

    other = await h.orchestrator.get_approval(approval_id, BOB)
    assert other is not None and other.why_not is None
    decided = await h.orchestrator.decide(
        approval_id, BOB, 0, Verdict.APPROVE, other.request.digest
    )
    assert isinstance(decided, Decided)


async def test_the_book_saves_for_the_caller_and_a_new_save_takes_the_schedule_over(db: Database):
    book = ScheduleBook(db)
    first = await book.save(WATCHLIST, MONDAY_9, CAROL)
    assert (first.owner, first.owner_name, first.schedule) == ("carol", "Carol", MONDAY_9)
    assert first.schedule.time_zone == "Asia/Singapore"

    taken = await book.save(WATCHLIST, Schedule("friday", "17:30"), ALICE)
    assert (taken.owner, taken.owner_name) == ("alice", "Alice")
    assert taken.saved_at >= first.saved_at
    assert await book.get(WATCHLIST) == taken


async def test_the_default_schedule_is_monday_nine_and_never_replaces_a_saved_one(db: Database):
    book = ScheduleBook(db)
    await book.save_default(WATCHLIST, CAROL)
    saved = await book.get(WATCHLIST)
    assert saved is not None
    assert (saved.schedule, saved.owner) == (MONDAY_9, "carol")

    await book.save(WATCHLIST, Schedule("every_day", "06:00"), ALICE)
    await book.save_default(WATCHLIST, CAROL)
    again = await book.get(WATCHLIST)
    assert again is not None and (again.schedule.day, again.owner) == ("every_day", "alice")

    await book.delete(WATCHLIST)
    await book.delete(WATCHLIST)
    assert await book.get(WATCHLIST) is None


async def test_using_up_the_slots_until_a_moment_takes_the_latest_and_never_moves_back(
    db: Database,
):
    book = ScheduleBook(db)
    await book.use_up_slots_until(WATCHLIST, NEXT_MONDAY)
    assert await book.get(WATCHLIST) is None

    await book.save(WATCHLIST, MONDAY_9, CAROL)
    await book.use_up_slots_until(WATCHLIST, NEXT_MONDAY + timedelta(minutes=7))
    await book.use_up_slots_until(WATCHLIST, NEXT_MONDAY - timedelta(minutes=5))

    saved = await book.get(WATCHLIST)
    assert saved is not None and saved.last_slot_started == NEXT_MONDAY
