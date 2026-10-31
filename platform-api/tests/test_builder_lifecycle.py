import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.builder import Builder, Watchlist
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.lifecycle import (
    RESTORE_WINDOW,
    AlreadyDeleted,
    Columns,
    Deleted,
    Lifecycle,
    On,
    Paused,
    TooLate,
    comes_on,
    delete,
    from_columns,
    is_on,
    pause,
    restore,
    resume,
    to_columns,
)
from platform_api.builder.watchlist import schedule_view
from platform_api.orchestration import (
    ChooseResult,
    DraftResult,
    LibraryCard,
    NoModel,
    NotOn,
    RuntimeDown,
    SavedSchedule,
    Schedule,
    ScheduleBook,
    ScheduleTicker,
    UnderstandResult,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.runs import AwaitingApproval, StepName
from platform_api.shared import N8nExecutionId, Role, RunId, UseCaseId, UserId
from tests.conftest import PostgresUrls
from tests.declared import declared_status
from tests.support import CAROL, LOCAL_ENV, NOW
from tests.test_builder_http import NothingLearned
from tests.test_card_runs import output, ticket
from tests.test_orchestrator import Harness, open_harness

pytestmark = pytest.mark.anyio

ALICE_ID = UserId("alice")
CAROL_ID = UserId("carol")
LATER = NOW + timedelta(minutes=5)
FIRST_MONDAY_SLOT = datetime(2026, 11, 9, 9, 0, tzinfo=ZoneInfo("Asia/Singapore"))
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
REDIS = {"name": "Redis", "repo": "redis/redis"}
VALUES = {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}
WORK = N8nExecutionId("41")
DRAFT = {"step": 2, "content": {"intent": "Nudge owners of stale tickets", "days": 14}}
DRAFT_PATH = "/api/v1/drafts/{draft_id}"
OPERATORS_ONLY = {"detail": "Only an Operator can change workflows."}


def test_pausing_keeps_who_paused_and_when_and_a_second_pause_changes_nothing():
    paused = Paused(NOW, ALICE_ID)
    assert pause(On(), NOW, ALICE_ID) == paused
    assert pause(paused, LATER, CAROL_ID) == paused


def test_resuming_turns_it_on_and_resuming_one_that_is_on_changes_nothing():
    assert resume(Paused(NOW, ALICE_ID)) == On()
    assert resume(On()) == On()


def test_a_deleted_use_case_cannot_be_paused_or_resumed():
    deleted = Deleted(NOW, ALICE_ID, On())
    assert pause(deleted, LATER, ALICE_ID) == AlreadyDeleted()
    assert resume(deleted) == AlreadyDeleted()


def test_deleting_twice_keeps_the_first_time():
    deleted = delete(On(), NOW, ALICE_ID)
    assert deleted == Deleted(NOW, ALICE_ID, On())
    assert delete(deleted, LATER, CAROL_ID) == deleted


def test_restoring_inside_the_day_puts_back_the_state_it_had():
    paused = Paused(NOW, CAROL_ID)
    deleted = delete(paused, LATER, ALICE_ID)
    assert restore(deleted, LATER + RESTORE_WINDOW) == paused
    assert restore(delete(On(), NOW, ALICE_ID), NOW + timedelta(hours=23)) == On()


def test_restoring_after_the_day_is_too_late():
    deleted = delete(On(), NOW, ALICE_ID)
    late = NOW + RESTORE_WINDOW + timedelta(seconds=1)
    assert restore(deleted, late) == TooLate(NOW + RESTORE_WINDOW)


def test_restoring_one_that_is_not_deleted_changes_nothing():
    assert restore(On(), NOW) == On()
    assert restore(Paused(NOW, ALICE_ID), LATER) == Paused(NOW, ALICE_ID)


@pytest.mark.parametrize(
    ("state", "running"),
    [(On(), True), (Paused(NOW, ALICE_ID), False), (Deleted(NOW, ALICE_ID, On()), False)],
)
def test_only_a_use_case_that_is_on_runs(state: Lifecycle, running: bool):
    assert is_on(state) is running


@pytest.mark.parametrize(
    ("before", "after", "back_on"),
    [
        (Paused(NOW, ALICE_ID), On(), True),
        (Deleted(NOW, ALICE_ID, On()), On(), True),
        (On(), On(), False),
        (Deleted(LATER, ALICE_ID, Paused(NOW, CAROL_ID)), Paused(NOW, CAROL_ID), False),
        (On(), Paused(NOW, ALICE_ID), False),
    ],
)
def test_a_move_comes_on_only_when_it_turns_a_paused_or_deleted_use_case_on(
    before: Lifecycle, after: Lifecycle, back_on: bool
):
    assert comes_on(before, after) is back_on


@pytest.mark.parametrize(
    "state",
    [
        On(),
        Paused(NOW, ALICE_ID),
        Deleted(LATER, CAROL_ID, On()),
        Deleted(LATER, CAROL_ID, Paused(NOW, ALICE_ID)),
    ],
)
def test_every_state_round_trips_through_its_columns(state: Lifecycle):
    assert from_columns(to_columns(state)) == state


def test_the_columns_of_a_deleted_paused_use_case_keep_both_times():
    assert to_columns(Deleted(LATER, CAROL_ID, Paused(NOW, ALICE_ID))) == Columns(
        NOW, ALICE_ID, LATER, CAROL_ID
    )


def test_a_paused_watchlist_s_schedule_shows_no_next_check():
    saved = SavedSchedule(
        UseCaseId("uc_w"),
        Schedule("monday", "09:00"),
        CAROL_ID,
        "Carol",
        NOW,
        None,
        frozenset({Role.OPERATOR}),
    )

    on = schedule_view(saved, NOW, on=True)
    paused = schedule_view(saved, NOW, on=False)

    assert on is not None and on.next_at == FIRST_MONDAY_SLOT
    assert paused == on.model_copy(update={"next_at": None})


class ModelConnected:
    async def has_model(self) -> bool:
        return True

    async def choose(
        self, task: str, library: Sequence[LibraryCard]
    ) -> ChooseResult | NoModel | RuntimeDown:
        raise AssertionError("not asked")

    async def draft(self, task: str) -> DraftResult | NoModel | RuntimeDown:
        raise AssertionError("not asked")

    async def understand(self, task: str) -> UnderstandResult | NoModel | RuntimeDown:
        raise AssertionError("not asked")


@dataclass
class Lab:
    h: Harness
    app: FastAPI
    client: httpx.AsyncClient
    builder: Builder

    async def call(
        self, user: str | None, method: str, path: str, body: Any = None, template: str = ""
    ) -> httpx.Response:
        headers = {} if user is None else {"X-Dev-User": user}
        if path.endswith("/runs") and method == "POST":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        response = await self.client.request(method, path, headers=headers, json=body)
        if template:
            declared_status(self.app, method, template, response)
        return response

    async def move(self, user: str, action: str, use_case_id: str) -> httpx.Response:
        if action == "delete":
            path, template, method = f"/api/v1/use-cases/{use_case_id}", "", "DELETE"
        else:
            path, template, method = f"/api/v1/use-cases/{use_case_id}/{action}", action, "POST"
        template = "/api/v1/use-cases/{use_case_id}" + (f"/{template}" if template else "")
        return await self.call(user, method, path, template=template)

    async def listed(self) -> list[dict[str, Any]]:
        return (await self.call("alice", "GET", "/api/v1/use-cases")).json()["use_cases"]

    async def runs(self) -> list[dict[str, Any]]:
        return (await self.call("alice", "GET", "/api/v1/runs")).json()["runs"]

    async def paused_columns(self, use_case_id: str) -> tuple[Any, ...]:
        async with self.h.db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT paused_at, paused_by, deleted_at, deleted_by FROM builder.use_cases"
                    " WHERE use_case_id = %s",
                    (use_case_id,),
                )
            ).fetchone()
        assert row is not None
        return (row["paused_at"], row["paused_by"], row["deleted_at"], row["deleted_by"])


@pytest.fixture
async def lab(postgres: PostgresUrls) -> AsyncIterator[Lab]:
    async with open_harness(postgres) as h:
        watchlist = Watchlist(h.db, NothingLearned(), ScheduleBook(h.db))
        app = create_app(LOCAL_ENV)
        builder = Builder(
            h.db, h.orchestrator, watchlist, "http://localhost:8000", ModelConnected()
        )
        people = People(h.db)
        assert await people.seed_dev(DEV_PEOPLE)
        app.state.people = people
        app.state.builder = builder
        app.state.watchlist = watchlist
        app.state.orchestrator = h.orchestrator
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Lab(h, app, client, builder)


async def watchlist_workflow(lab: Lab, by: str = "alice") -> str:
    """The watchlist, with its first schedule owned by whoever added the first software."""
    r = await lab.call(by, "POST", "/api/v1/watchlist/software", LANGGRAPH)
    assert r.status_code == 201
    return r.json()["use_case_id"]


async def agent_workflow(lab: Lab, name: str = "Watch LangGraph") -> str:
    body = {
        "name": name,
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
    }
    r = await lab.call("alice", "POST", "/api/v1/agent-use-cases", body)
    assert r.status_code == 201
    return r.json()["use_case_id"]


async def start_run(lab: Lab, use_case_id: str) -> RunId:
    r = await lab.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs")
    assert r.status_code == 201, r.text
    return RunId(r.json()["run_id"])


def at(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


async def test_alice_pauses_a_workflow_and_its_next_run_reads_paused(lab: Lab):
    use_case_id = await watchlist_workflow(lab)
    [before] = await lab.listed()
    assert (before["state"], at(before["next_run_at"])) == ("on", FIRST_MONDAY_SLOT)

    paused = await lab.move("alice", "pause", use_case_id)

    assert paused.status_code == 200
    assert (paused.json()["state"], paused.json()["next_run_at"]) == ("paused", None)
    [listed] = await lab.listed()
    assert (listed["state"], listed["next_run_at"]) == ("paused", None)
    assert await lab.paused_columns(use_case_id) == (NOW, "alice", None, None)


async def test_resuming_shows_the_next_run_again(lab: Lab):
    use_case_id = await watchlist_workflow(lab)
    await lab.move("alice", "pause", use_case_id)
    lab.h.advance(timedelta(days=7))

    resumed = await lab.move("carol", "resume", use_case_id)

    assert resumed.status_code == 200
    assert resumed.json()["state"] == "on"
    assert at(resumed.json()["next_run_at"]) == FIRST_MONDAY_SLOT + timedelta(days=7)
    assert await lab.paused_columns(use_case_id) == (None, None, None, None)
    again = await lab.move("carol", "resume", use_case_id)
    assert (again.status_code, again.json()) == (200, resumed.json())


async def test_a_held_schedule_names_no_next_run_until_an_operator_saves_it_again(lab: Lab):
    use_case_id = await watchlist_workflow(lab)  # Alice owns its schedule
    lost = await lab.call("carol", "PUT", "/api/v1/people/alice/operator", {"operator": False})
    assert lost.status_code == 200

    [listed] = await lab.listed()
    read = (await lab.call("bob", "GET", f"/api/v1/use-cases/{use_case_id}")).json()

    for view in (listed, read):
        assert (view["state"], view["next_run_at"]) == ("on", None)
        assert (view["schedule"]["held"], view["schedule"]["owner_name"]) == (
            "owner_not_an_operator",
            "Alice",
        )
    body = {"day": "monday", "at": "09:00"}
    assert (await lab.call("carol", "PUT", "/api/v1/watchlist/schedule", body)).status_code == 200
    [taken] = await lab.listed()
    assert at(taken["next_run_at"]) == FIRST_MONDAY_SLOT
    assert (taken["schedule"]["held"], taken["schedule"]["owner_name"]) == (None, "Carol")


async def test_a_schedule_whose_owner_left_the_list_names_no_next_run_until_it_is_taken_over(
    lab: Lab,
):
    use_case_id = await watchlist_workflow(lab, by="carol")
    assert (await lab.call("alice", "DELETE", "/api/v1/people/carol")).status_code == 204

    [listed] = await lab.listed()
    read = (await lab.call("bob", "GET", f"/api/v1/use-cases/{use_case_id}")).json()

    for view in (listed, read):
        assert (view["state"], view["next_run_at"]) == ("on", None)
        assert (view["schedule"]["held"], view["schedule"]["owner_name"]) == (
            "owner_removed",
            "Carol",
        )
    body = {"day": "monday", "at": "09:00"}
    assert (await lab.call("alice", "PUT", "/api/v1/watchlist/schedule", body)).status_code == 200
    taken = (await lab.call("bob", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
    assert at(taken["next_run_at"]) == FIRST_MONDAY_SLOT
    assert (taken["schedule"]["held"], taken["schedule"]["owner_name"]) == (None, "Alice")


@pytest.mark.parametrize(
    ("owner", "change", "held"),
    [
        pytest.param(
            "alice",
            ("carol", "PUT", "/api/v1/people/alice/operator", {"operator": False}),
            "owner_not_an_operator",
            id="not_an_operator",
        ),
        pytest.param(
            "carol",
            ("alice", "DELETE", "/api/v1/people/carol", None),
            "owner_removed",
            id="removed",
        ),
    ],
)
async def test_a_schedule_set_up_with_a_new_workflow_is_held_once_its_creator_cannot_run_it(
    lab: Lab, owner: str, change: tuple[str, str, str, Any], held: str
):
    body = {
        "name": "Watch LangGraph",
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
        "schedule": {"day": "monday", "at": "09:00"},
    }
    made = await lab.call(owner, "POST", "/api/v1/agent-use-cases", body)
    assert made.status_code == 201, made.text
    use_case_id = made.json()["use_case_id"]
    name = owner.capitalize()

    async def shown() -> list[tuple[datetime | None, str | None, str]]:
        [listed] = (await lab.call("bob", "GET", "/api/v1/use-cases")).json()["use_cases"]
        read = (await lab.call("bob", "GET", f"/api/v1/use-cases/{use_case_id}")).json()
        return [
            (at(v["next_run_at"]), v["schedule"]["held"], v["schedule"]["owner_name"])
            for v in (listed, read)
        ]

    assert await shown() == [(FIRST_MONDAY_SLOT, None, name)] * 2
    by, method, path, change_body = change
    assert (await lab.call(by, method, path, change_body)).status_code in (200, 204)
    assert await shown() == [(None, held, name)] * 2
    ticker = ScheduleTicker(lab.h.db, ScheduleBook(lab.h.db), lab.builder, lab.h.orchestrator)
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(minutes=1)
    assert await ticker.tick() == []
    assert (await lab.call("bob", "GET", "/api/v1/runs")).json()["runs"] == []


async def test_a_workflow_with_no_schedule_has_no_next_run(lab: Lab):
    use_case_id = await agent_workflow(lab)
    [listed] = await lab.listed()
    assert (listed["use_case_id"], listed["state"], listed["next_run_at"]) == (
        use_case_id,
        "on",
        None,
    )


MONDAYS_AT_NINE = {
    "day": "monday",
    "at": "09:00",
    "time_zone": "Asia/Singapore",
    "owner_name": "Alice",
    "held": None,
}


async def test_a_workflow_keeps_its_schedule_while_it_is_paused(lab: Lab):
    use_case_id = await watchlist_workflow(lab)
    [before] = await lab.listed()

    paused = await lab.move("alice", "pause", use_case_id)
    read = await lab.call(
        "alice",
        "GET",
        f"/api/v1/use-cases/{use_case_id}",
        template="/api/v1/use-cases/{use_case_id}",
    )

    assert before["schedule"] == MONDAYS_AT_NINE
    assert (paused.json()["schedule"], paused.json()["next_run_at"]) == (MONDAYS_AT_NINE, None)
    assert (read.json()["schedule"], read.json()["next_run_at"]) == (MONDAYS_AT_NINE, None)
    [listed] = await lab.listed()
    assert listed["schedule"] == MONDAYS_AT_NINE


async def test_a_workflow_with_no_schedule_says_so_while_on_and_while_paused(lab: Lab):
    use_case_id = await agent_workflow(lab)
    [on] = await lab.listed()
    paused = await lab.move("alice", "pause", use_case_id)
    assert (on["schedule"], paused.json()["schedule"]) == (None, None)


async def test_a_paused_workflow_cannot_be_started_by_hand(lab: Lab):
    use_case_id = await agent_workflow(lab)
    await lab.move("alice", "pause", use_case_id)

    r = await lab.call(
        "alice",
        "POST",
        f"/api/v1/use-cases/{use_case_id}/runs",
        template="/api/v1/use-cases/{use_case_id}/runs",
    )

    assert (r.status_code, r.json()) == (
        409,
        {"detail": "This workflow is paused. Resume it to start a run."},
    )
    assert await lab.runs() == []
    await lab.move("alice", "resume", use_case_id)
    await start_run(lab, use_case_id)


class HeldStart:
    """Starts the run for real, but only once the test lets it. The builder has read the
    workflow's state by then, so a pause can try to land before the run is inserted (#56)."""

    def __init__(self, runs: Any) -> None:
        self._runs = runs
        self.reached = asyncio.Event()
        self.go = asyncio.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runs, name)

    async def start_run(self, spec: Any, principal: Any, idempotency_key: str) -> Any:
        self.reached.set()
        await self.go.wait()
        return await self._runs.start_run(spec, principal, idempotency_key)


async def pause_waits_for(lab: Lab, held: HeldStart, starting: asyncio.Task[Any], uc: str) -> Any:
    await asyncio.wait_for(held.reached.wait(), 5)
    pausing = asyncio.create_task(lab.move("carol", "pause", uc))
    await asyncio.sleep(0.3)
    assert not pausing.done(), "the pause landed between the state read and the run insert"
    held.go.set()
    started = await asyncio.wait_for(starting, 5)
    paused = await asyncio.wait_for(pausing, 5)
    assert (paused.status_code, paused.json()["state"]) == (200, "paused")
    return started


async def test_a_pause_waits_for_a_start_that_has_read_the_state(lab: Lab):
    use_case_id = await agent_workflow(lab)
    held = HeldStart(lab.h.orchestrator)
    lab.app.state.builder = Builder(
        lab.h.db, held, lab.app.state.watchlist, "http://localhost:8000", ModelConnected()
    )
    starting = asyncio.create_task(
        lab.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs")
    )

    started = await pause_waits_for(lab, held, starting, use_case_id)

    assert started.status_code == 201, started.text
    [run] = await lab.runs()
    assert (run["run_id"], run["state"]) == (started.json()["run_id"], "pending")
    refused = await lab.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs")
    assert refused.status_code == 409


async def test_a_pause_waits_for_a_scheduled_start_that_has_read_the_state(lab: Lab):
    use_case_id = await watchlist_workflow(lab)
    held = HeldStart(lab.h.orchestrator)
    ticker = ScheduleTicker(lab.h.db, ScheduleBook(lab.h.db), lab.builder, held)
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(minutes=1)

    started = await pause_waits_for(lab, held, asyncio.create_task(ticker.tick()), use_case_id)

    [run] = await lab.runs()
    assert started == [RunId(run["run_id"])]


async def test_pausing_twice_keeps_the_first_pause(lab: Lab):
    use_case_id = await agent_workflow(lab)
    first = await lab.move("alice", "pause", use_case_id)
    lab.h.advance(timedelta(hours=1))

    second = await lab.move("carol", "pause", use_case_id)

    assert (second.status_code, second.json()) == (200, first.json())
    assert await lab.paused_columns(use_case_id) == (NOW, "alice", None, None)


async def test_two_pauses_at_the_same_moment_both_succeed_with_one_paused_state(lab: Lab):
    use_case_id = await agent_workflow(lab)

    one, two = await asyncio.gather(
        lab.move("alice", "pause", use_case_id), lab.move("carol", "pause", use_case_id)
    )

    assert (one.status_code, two.status_code) == (200, 200)
    assert one.json() == two.json()
    assert one.json()["state"] == "paused"
    paused_at, paused_by, deleted_at, _ = await lab.paused_columns(use_case_id)
    assert (paused_at, paused_by in {"alice", "carol"}, deleted_at) == (NOW, True, None)


async def test_delete_takes_a_workflow_out_of_the_list_and_keeps_its_past_runs(lab: Lab):
    use_case_id = await agent_workflow(lab)
    run_id = await start_run(lab, use_case_id)

    deleted = await lab.move("carol", "delete", use_case_id)

    assert deleted.status_code == 200
    assert deleted.json() == {
        "use_case_id": use_case_id,
        "deleted_at": NOW.isoformat().replace("+00:00", "Z"),
        "restore_until": (NOW + RESTORE_WINDOW).isoformat().replace("+00:00", "Z"),
    }
    assert await lab.listed() == []
    template = "/api/v1/use-cases/{use_case_id}"
    gone = await lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}", template=template)
    assert gone.status_code == 404
    started = await lab.call(
        "alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs", template=template + "/runs"
    )
    assert started.status_code == 404
    assert [r["run_id"] for r in await lab.runs()] == [run_id]
    run = await lab.call("alice", "GET", f"/api/v1/runs/{run_id}")
    assert (run.status_code, run.json()["use_case_id"]) == (200, use_case_id)
    for action in ("pause", "resume"):
        assert (await lab.move("alice", action, use_case_id)).status_code == 404
    lab.h.advance(timedelta(hours=1))
    again = await lab.move("alice", "delete", use_case_id)
    assert (again.status_code, again.json()) == (200, deleted.json())
    assert await lab.paused_columns(use_case_id) == (None, None, NOW, "carol")


async def test_restore_inside_the_day_brings_it_back_with_its_past_runs(lab: Lab):
    use_case_id = await agent_workflow(lab)
    run_id = await start_run(lab, use_case_id)
    await lab.move("alice", "delete", use_case_id)
    lab.h.advance(RESTORE_WINDOW)

    restored = await lab.move("alice", "restore", use_case_id)

    assert restored.status_code == 200
    assert (restored.json()["use_case_id"], restored.json()["state"]) == (use_case_id, "on")
    assert [u["use_case_id"] for u in await lab.listed()] == [use_case_id]
    assert [(r["run_id"], r["use_case_id"]) for r in await lab.runs()] == [(run_id, use_case_id)]
    assert await lab.paused_columns(use_case_id) == (None, None, None, None)
    await start_run(lab, use_case_id)


async def test_restore_brings_a_paused_workflow_back_paused(lab: Lab):
    use_case_id = await agent_workflow(lab)
    await lab.move("carol", "pause", use_case_id)
    await lab.move("alice", "delete", use_case_id)

    restored = await lab.move("alice", "restore", use_case_id)

    assert (restored.json()["state"], restored.json()["next_run_at"]) == ("paused", None)
    assert await lab.paused_columns(use_case_id) == (NOW, "carol", None, None)


async def test_restore_after_the_day_answers_410_and_it_stays_deleted(lab: Lab):
    use_case_id = await agent_workflow(lab)
    await lab.move("alice", "delete", use_case_id)
    lab.h.advance(RESTORE_WINDOW + timedelta(seconds=1))

    late = await lab.move("alice", "restore", use_case_id)

    assert (late.status_code, late.json()) == (
        410,
        {"detail": "This workflow was deleted more than a day ago, so it can't be put back."},
    )
    assert await lab.listed() == []
    assert await lab.paused_columns(use_case_id) == (None, None, NOW, "alice")


async def test_restoring_a_workflow_that_is_not_deleted_changes_nothing(lab: Lab):
    use_case_id = await agent_workflow(lab)
    [before] = await lab.listed()
    restored = await lab.move("alice", "restore", use_case_id)
    assert (restored.status_code, restored.json()) == (200, before)


async def test_the_software_watchlist_can_be_paused_and_resumed_but_not_deleted(lab: Lab):
    use_case_id = await watchlist_workflow(lab)

    refused = await lab.move("alice", "delete", use_case_id)

    assert (refused.status_code, refused.json()) == (
        409,
        {"detail": "The Software watchlist can't be deleted. Remove its software instead."},
    )
    assert [u["use_case_id"] for u in await lab.listed()] == [use_case_id]
    assert (await lab.move("alice", "pause", use_case_id)).json()["state"] == "paused"
    assert (await lab.move("alice", "delete", use_case_id)).status_code == 409
    assert (await lab.move("alice", "resume", use_case_id)).json()["state"] == "on"
    assert await lab.paused_columns(use_case_id) == (None, None, None, None)


async def work_to_approval(lab: Lab, run_id: RunId) -> str:
    h = lab.h
    h.agent.output = output(ticket(VERSION_CHECKER_ID))
    await h.orchestrator.tick()
    await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, WORK)
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, WORK)
    await h.orchestrator.tick()
    assert isinstance(await h.state(run_id), AwaitingApproval)
    run = (await lab.call("alice", "GET", f"/api/v1/runs/{run_id}")).json()
    return run["approval"]["approval_id"]


async def test_deleting_while_a_run_waits_for_a_yes_leaves_the_run_decidable(lab: Lab):
    use_case_id = await agent_workflow(lab)
    run_id = await start_run(lab, use_case_id)
    approval_id = await work_to_approval(lab, run_id)

    assert (await lab.move("alice", "delete", use_case_id)).status_code == 200

    seen = (await lab.call("bob", "GET", f"/api/v1/approvals/{approval_id}")).json()
    assert seen["you_can_decide"] is True
    decided = await lab.call(
        "bob",
        "POST",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": seen["digest"]},
    )
    assert (decided.status_code, decided.json()["status"]) == (201, "approved")
    started = await lab.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs")
    assert started.status_code == 404
    assert [r["run_id"] for r in await lab.runs()] == [run_id]


@pytest.mark.parametrize("action", ["pause", "resume", "delete", "restore"])
async def test_an_approver_only_caller_gets_403(lab: Lab, action: str):
    use_case_id = await agent_workflow(lab)
    r = await lab.move("bob", action, use_case_id)
    assert (r.status_code, r.json()) == (403, OPERATORS_ONLY)
    assert await lab.paused_columns(use_case_id) == (None, None, None, None)


@pytest.mark.parametrize("action", ["pause", "resume", "delete", "restore"])
async def test_an_unknown_workflow_is_404(lab: Lab, action: str):
    r = await lab.move("alice", action, "uc_nope")
    assert (r.status_code, r.json()) == (404, {"detail": "No such workflow"})


@pytest.mark.parametrize("action", ["pause", "resume", "delete", "restore"])
async def test_every_lifecycle_route_needs_a_signed_in_user(lab: Lab, action: str):
    use_case_id = await agent_workflow(lab)
    method = "DELETE" if action == "delete" else "POST"
    suffix = "" if action == "delete" else f"/{action}"
    r = await lab.call(
        None,
        method,
        f"/api/v1/use-cases/{use_case_id}{suffix}",
        template="/api/v1/use-cases/{use_case_id}" + suffix,
    )
    assert r.status_code == 401


async def test_a_tick_while_the_watchlist_is_paused_starts_no_run(lab: Lab):
    use_case_id = await watchlist_workflow(lab)
    ticker = ScheduleTicker(lab.h.db, ScheduleBook(lab.h.db), lab.builder, lab.h.orchestrator)
    await lab.move("alice", "pause", use_case_id)
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(minutes=1)

    assert await ticker.tick() == []

    assert await lab.runs() == []
    await lab.move("alice", "resume", use_case_id)
    assert await ticker.tick() == []
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(days=7, minutes=1)
    [run_id] = await ticker.tick()
    assert [(r["run_id"], r["trigger"]) for r in await lab.runs()] == [(run_id, "schedule")]


async def scheduled_agent_workflow(lab: Lab) -> str:
    use_case_id = await agent_workflow(lab)
    await ScheduleBook(lab.h.db).save(UseCaseId(use_case_id), Schedule("monday", "09:00"), CAROL)
    return use_case_id


@pytest.mark.parametrize(
    ("away", "back", "make"),
    [
        pytest.param("pause", "resume", watchlist_workflow, id="resume"),
        pytest.param("delete", "restore", scheduled_agent_workflow, id="restore"),
    ],
)
async def test_a_slot_that_falls_while_it_is_off_never_starts_even_with_no_tick_before_it_is_back(
    lab: Lab, away: str, back: str, make: Callable[[Lab], Awaitable[str]]
):
    use_case_id = await make(lab)
    ticker = ScheduleTicker(lab.h.db, ScheduleBook(lab.h.db), lab.builder, lab.h.orchestrator)
    lab.h.clock["now"] = FIRST_MONDAY_SLOT - timedelta(minutes=5)
    assert (await lab.move("alice", away, use_case_id)).status_code == 200
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(minutes=7)

    back_on = await lab.move("alice", back, use_case_id)

    assert back_on.json()["state"] == "on"
    assert at(back_on.json()["next_run_at"]) == FIRST_MONDAY_SLOT + timedelta(days=7)
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(minutes=12)
    assert await ticker.tick() == []
    assert await lab.runs() == []
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(days=7, minutes=1)
    [run_id] = await ticker.tick()
    assert [(r["run_id"], r["trigger"]) for r in await lab.runs()] == [(run_id, "schedule")]


async def test_while_the_watchlist_is_paused_its_view_reads_paused_with_no_next_check(lab: Lab):
    use_case_id = await watchlist_workflow(lab)
    await lab.move("alice", "pause", use_case_id)

    paused = (await lab.call("alice", "GET", "/api/v1/watchlist")).json()["watchlist"]

    assert (paused["state"], paused["schedule"]["next_at"]) == ("paused", None)
    added = (await lab.call("alice", "POST", "/api/v1/watchlist/software", REDIS)).json()
    assert (added["state"], added["schedule"]["next_at"]) == ("paused", None)
    await lab.move("alice", "resume", use_case_id)
    resumed = (await lab.call("alice", "GET", "/api/v1/watchlist")).json()["watchlist"]
    assert (resumed["state"], at(resumed["schedule"]["next_at"])) == ("on", FIRST_MONDAY_SLOT)


async def test_the_tick_is_told_a_paused_or_deleted_workflow_is_not_on(lab: Lab):
    use_case_id = await agent_workflow(lab)
    await lab.move("alice", "pause", use_case_id)
    assert await lab.builder.check_spec(UseCaseId(use_case_id)) == NotOn("paused")
    await lab.move("alice", "delete", use_case_id)
    assert await lab.builder.check_spec(UseCaseId(use_case_id)) == NotOn("deleted")
    assert await lab.builder.check_spec(UseCaseId("uc_nope")) is None


def stamp(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


async def save_draft(lab: Lab, user: str, draft_id: str, body: Any = DRAFT) -> httpx.Response:
    return await lab.call(user, "PUT", f"/api/v1/drafts/{draft_id}", body, template=DRAFT_PATH)


async def drafts_of(lab: Lab, user: str) -> list[dict[str, Any]]:
    r = await lab.call(user, "GET", "/api/v1/drafts", template="/api/v1/drafts")
    assert r.status_code == 200
    return r.json()["drafts"]


async def test_a_draft_is_saved_for_its_author_and_listed_only_for_them(lab: Lab):
    saved = await save_draft(lab, "alice", "d1")

    assert (saved.status_code, saved.json()) == (
        200,
        {"draft_id": "d1", **DRAFT, "created_at": stamp(NOW), "saved_at": stamp(NOW)},
    )
    assert await drafts_of(lab, "alice") == [saved.json()]
    assert await drafts_of(lab, "carol") == []


async def test_saving_again_replaces_the_draft_and_keeps_when_it_was_started(lab: Lab):
    await save_draft(lab, "alice", "d1")
    lab.h.advance(timedelta(minutes=3))

    again = await save_draft(lab, "alice", "d1", {"step": 3, "content": {"intent": "Changed"}})

    assert again.json() == {
        "draft_id": "d1",
        "step": 3,
        "content": {"intent": "Changed"},
        "created_at": stamp(NOW),
        "saved_at": stamp(NOW + timedelta(minutes=3)),
    }
    assert await drafts_of(lab, "alice") == [again.json()]


async def test_the_same_draft_id_is_separate_for_each_author(lab: Lab):
    await save_draft(lab, "alice", "d1")
    await save_draft(lab, "carol", "d1", {"step": 4, "content": {"intent": "Carol's"}})

    [alices] = await drafts_of(lab, "alice")
    [carols] = await drafts_of(lab, "carol")
    assert (alices["step"], alices["content"]) == (DRAFT["step"], DRAFT["content"])
    assert (carols["step"], carols["content"]) == (4, {"intent": "Carol's"})


async def test_deleting_someone_else_s_draft_is_404_and_leaves_it(lab: Lab):
    await save_draft(lab, "alice", "d1")

    theirs = await lab.call("carol", "DELETE", "/api/v1/drafts/d1", template=DRAFT_PATH)
    assert (theirs.status_code, theirs.json()) == (404, {"detail": "No such draft"})
    assert len(await drafts_of(lab, "alice")) == 1

    mine = await lab.call("alice", "DELETE", "/api/v1/drafts/d1")
    assert (mine.status_code, mine.content) == (204, b"")
    assert await drafts_of(lab, "alice") == []
    gone = await lab.call("alice", "DELETE", "/api/v1/drafts/d1", template=DRAFT_PATH)
    assert gone.status_code == 404


async def test_drafts_list_the_last_saved_first(lab: Lab):
    await save_draft(lab, "alice", "older")
    lab.h.advance(timedelta(minutes=1))
    await save_draft(lab, "alice", "newer")
    assert [d["draft_id"] for d in await drafts_of(lab, "alice")] == ["newer", "older"]
    lab.h.advance(timedelta(minutes=1))
    await save_draft(lab, "alice", "older")
    assert [d["draft_id"] for d in await drafts_of(lab, "alice")] == ["older", "newer"]


async def test_a_draft_over_32_kb_is_refused_and_nothing_is_saved(lab: Lab):
    big = {"step": 1, "content": {"intent": "a" * (32 * 1024)}}
    r = await save_draft(lab, "alice", "d1", big)
    [problem] = r.json()["detail"]
    assert (r.status_code, problem["loc"]) == (422, ["body", "content"])
    assert "under 32 KB" in problem["msg"]
    assert await drafts_of(lab, "alice") == []


@pytest.mark.parametrize(
    ("draft_id", "body", "where"),
    [
        ("d1", {"step": 0, "content": {}}, ["body", "step"]),
        ("d1", {"step": 5, "content": {}}, ["body", "step"]),
        ("d1", {"step": 1, "content": []}, ["body", "content"]),
        ("not ok", DRAFT, ["path", "draft_id"]),
        ("x" * 65, DRAFT, ["path", "draft_id"]),
    ],
)
async def test_a_bad_step_content_or_id_is_refused(
    lab: Lab, draft_id: str, body: Any, where: list[str]
):
    r = await save_draft(lab, "alice", draft_id, body)
    assert r.status_code == 422
    assert [p["loc"] for p in r.json()["detail"]] == [where]


async def test_an_operator_keeps_at_most_twenty_drafts(lab: Lab):
    for n in range(20):
        assert (await save_draft(lab, "alice", f"d{n}")).status_code == 200

    refused = await save_draft(lab, "alice", "d20")

    assert (refused.status_code, refused.json()) == (
        409,
        {"detail": "You have 20 drafts. Delete one before you save another."},
    )
    assert (await save_draft(lab, "alice", "d3")).status_code == 200
    assert (await save_draft(lab, "carol", "d20")).status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "template"),
    [
        ("PUT", "/api/v1/drafts/d1", DRAFT_PATH),
        ("GET", "/api/v1/drafts", "/api/v1/drafts"),
        ("DELETE", "/api/v1/drafts/d1", DRAFT_PATH),
    ],
)
async def test_drafts_are_for_operators_only(lab: Lab, method: str, path: str, template: str):
    body = DRAFT if method == "PUT" else None
    refused = await lab.call("bob", method, path, body, template=template)
    assert (refused.status_code, refused.json()) == (403, OPERATORS_ONLY)
    assert (await lab.call(None, method, path, body, template=template)).status_code == 401


SCHEDULE_PATH = "/api/v1/use-cases/{use_case_id}/schedule"
EVERY_MONDAY = {"day": "monday", "at": "09:00"}


async def save_schedule(
    lab: Lab, user: str | None, use_case_id: str, body: Any = None
) -> httpx.Response:
    return await lab.call(
        user,
        "PUT",
        f"/api/v1/use-cases/{use_case_id}/schedule",
        EVERY_MONDAY if body is None else body,
        template=SCHEDULE_PATH,
    )


async def scheduled_workflow(lab: Lab, owner: str) -> str:
    body = {
        "name": "Watch LangGraph",
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
        "schedule": EVERY_MONDAY,
    }
    made = await lab.call(owner, "POST", "/api/v1/agent-use-cases", body)
    assert made.status_code == 201, made.text
    return made.json()["use_case_id"]


async def test_an_operator_changes_a_workflows_schedule_and_becomes_its_owner(lab: Lab):
    use_case_id = await scheduled_workflow(lab, "alice")

    saved = await save_schedule(lab, "carol", use_case_id, {"day": "friday", "at": "17:30"})

    assert saved.status_code == 200, saved.text
    view = saved.json()
    assert view["use_case_id"] == use_case_id
    schedule = view["schedule"]
    assert (schedule["day"], schedule["at"], schedule["time_zone"]) == (
        "friday",
        "17:30",
        "Asia/Singapore",
    )
    assert (schedule["owner_name"], schedule["held"]) == ("Carol", None)
    assert at(view["next_run_at"]) == datetime(
        2026, 11, 6, 17, 30, tzinfo=ZoneInfo("Asia/Singapore")
    )
    [listed] = await lab.listed()
    assert listed["schedule"] == schedule
    assert await lab.runs() == [], "saving a schedule starts no run and asks for no approval"


async def test_saving_a_schedule_takes_over_a_held_workflow_whose_owner_left_the_list(lab: Lab):
    use_case_id = await scheduled_workflow(lab, "carol")
    assert (await lab.call("alice", "DELETE", "/api/v1/people/carol")).status_code == 204
    [held] = await lab.listed()
    assert (held["schedule"]["held"], held["next_run_at"]) == ("owner_removed", None)

    taken = await save_schedule(lab, "alice", use_case_id)

    assert taken.status_code == 200
    assert (taken.json()["schedule"]["held"], taken.json()["schedule"]["owner_name"]) == (
        None,
        "Alice",
    )
    assert at(taken.json()["next_run_at"]) == FIRST_MONDAY_SLOT


async def test_a_workflow_held_for_a_former_operator_is_taken_over_only_by_an_operator(lab: Lab):
    use_case_id = await scheduled_workflow(lab, "alice")
    lost = await lab.call("carol", "PUT", "/api/v1/people/alice/operator", {"operator": False})
    assert lost.status_code == 200
    [held] = await lab.listed()
    assert held["schedule"]["held"] == "owner_not_an_operator"

    for user in ("alice", "bob"):
        refused = await save_schedule(lab, user, use_case_id)
        assert (refused.status_code, refused.json()) == (403, OPERATORS_ONLY), user
    assert (await save_schedule(lab, None, use_case_id)).status_code == 401
    [still] = await lab.listed()
    assert still["schedule"]["held"] == "owner_not_an_operator", "a refused save changes nothing"

    taken = await save_schedule(lab, "carol", use_case_id)
    assert (taken.status_code, taken.json()["schedule"]["held"]) == (200, None)
    assert taken.json()["schedule"]["owner_name"] == "Carol"


async def test_a_workflow_with_no_schedule_gets_one_and_a_paused_one_stays_paused(lab: Lab):
    use_case_id = await agent_workflow(lab)
    [none] = await lab.listed()
    assert (none["schedule"], none["next_run_at"]) == (None, None)
    assert (await lab.move("alice", "pause", use_case_id)).status_code == 200

    saved = await save_schedule(lab, "alice", use_case_id)

    assert saved.status_code == 200
    view = saved.json()
    assert (view["state"], view["next_run_at"]) == ("paused", None)
    assert (view["schedule"]["day"], view["schedule"]["owner_name"]) == ("monday", "Alice")
    resumed = await lab.move("alice", "resume", use_case_id)
    assert at(resumed.json()["next_run_at"]) == FIRST_MONDAY_SLOT


async def test_a_schedule_cannot_be_saved_for_a_workflow_that_is_gone_or_the_watchlist(lab: Lab):
    assert (await save_schedule(lab, "alice", "uc_nope")).status_code == 404
    use_case_id = await agent_workflow(lab)
    assert (await lab.move("alice", "delete", use_case_id)).status_code == 200
    gone = await save_schedule(lab, "alice", use_case_id)
    assert (gone.status_code, gone.json()) == (404, {"detail": "No such workflow"})

    watchlist_id = await watchlist_workflow(lab)
    refused = await save_schedule(lab, "alice", watchlist_id)
    assert (refused.status_code, refused.json()) == (
        409,
        {"detail": "The Software watchlist's schedule is saved on the Software page."},
    )


@pytest.mark.parametrize(
    "body", [{"day": "monday"}, {"day": "someday", "at": "09:00"}, {"day": "monday", "at": "09:03"}]
)
async def test_a_schedule_must_be_a_day_and_a_five_minute_time_in_singapore(lab: Lab, body: Any):
    use_case_id = await agent_workflow(lab)
    refused = await save_schedule(lab, "alice", use_case_id, body)
    assert refused.status_code == 422
