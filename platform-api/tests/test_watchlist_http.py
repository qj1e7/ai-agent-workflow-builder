from collections.abc import AsyncIterator, Mapping
from datetime import timedelta

import httpx
import pytest

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.builder import Watchlist
from platform_api.builder.lifecycle import RESTORE_WINDOW
from platform_api.db import Database
from platform_api.orchestration import (
    Given,
    ScheduleBook,
    SoftwareFacts,
    Standing,
    WatchlistStanding,
)
from platform_api.orchestration.people_store import People
from platform_api.shared import RunId, SoftwareId, UseCaseId
from tests.conftest import PostgresUrls, truncate_all
from tests.support import LOCAL_ENV, MovingClock

pytestmark = pytest.mark.anyio

ALICE = {"X-Dev-User": "alice"}
BOB = {"X-Dev-User": "bob"}
CAROL = {"X-Dev-User": "carol"}
STEP_KEY = {"X-Step-Key": LOCAL_ENV["STEP_KEY"]}
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
REDIS = {"name": "Redis", "repo": "redis/redis"}


class NothingLearned:
    async def standings(
        self, use_case_id: UseCaseId, given: Mapping[SoftwareId, Given | None]
    ) -> WatchlistStanding:
        return WatchlistStanding(
            {
                software_id: Standing(SoftwareFacts(typed, None, None, None), "not_checked")
                for software_id, typed in given.items()
            },
            None,
        )


async def people_in(db: Database) -> People:
    """The People list in the database, as the platform runs it: sign-in reads it, and so does
    each schedule's view of its owner."""
    people = People(db)
    assert await people.seed_dev(DEV_PEOPLE)
    return people


class FakeTicker:
    async def tick(self) -> list[RunId]:
        return [RunId("run_01A"), RunId("run_01B")]


@pytest.fixture
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(LOCAL_ENV)
    app.state.people = await people_in(db)
    app.state.watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db))
    app.state.schedule_ticker = FakeTicker()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def clock() -> MovingClock:
    return MovingClock()


@pytest.fixture
async def timed_client(
    postgres: PostgresUrls, clock: MovingClock
) -> AsyncIterator[httpx.AsyncClient]:
    truncate_all(postgres.owner)
    database = Database(postgres.contexts, clock=clock)
    await database.open()
    app = create_app(LOCAL_ENV)
    app.state.people = await people_in(database)
    app.state.watchlist = Watchlist(database, NothingLearned(), ScheduleBook(database))
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await database.close()


async def test_the_watchlist_is_null_until_software_is_added_then_lists_it(
    client: httpx.AsyncClient,
):
    empty = await client.get("/api/v1/watchlist", headers=BOB)
    assert (empty.status_code, empty.json()) == (200, {"watchlist": None})

    added = await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    assert added.status_code == 201
    view = added.json()
    assert view["version"] == 1 and view["ticket_project"] == "MOCK"
    [row] = view["software"]
    assert (row["name"], row["our_version"], row["status"], row["added_by"]) == (
        "LangGraph",
        "1.2.14",
        "not_checked",
        "alice",
    )
    assert row["our_version_source"]["kind"] == "given"
    assert view["last_check"] is None
    assert (view["schedule"]["day"], view["schedule"]["at"], view["schedule"]["owner"]) == (
        "monday",
        "09:00",
        "alice",
    )

    again = await client.get("/api/v1/watchlist", headers=BOB)
    assert again.json() == {"watchlist": view}


async def test_a_repository_watched_twice_is_a_409(client: httpx.AsyncClient):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    r = await client.post(
        "/api/v1/watchlist/software", json={**LANGGRAPH, "name": "Again"}, headers=ALICE
    )
    assert r.status_code == 409
    assert r.json() == {"detail": "langchain-ai/langgraph is already watched"}


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({**LANGGRAPH, "name": "  "}, "name"),
        ({**LANGGRAPH, "name": "x" * 81}, "name"),
        ({**LANGGRAPH, "repo": "langgraph"}, "repo"),
        ({**LANGGRAPH, "repo": "owner/.."}, "repo"),
        ({**LANGGRAPH, "our_version": "v1.2.14"}, "our_version"),
        ({**LANGGRAPH, "our_version": "1.2"}, "our_version"),
        ({**LANGGRAPH, "colour": "red"}, "colour"),
        ({"repo": "redis/redis"}, "name"),
    ],
)
async def test_a_field_problem_is_a_422_naming_the_field(
    client: httpx.AsyncClient, body: dict[str, str], field: str
):
    r = await client.post("/api/v1/watchlist/software", json=body, headers=ALICE)
    assert r.status_code == 422
    assert [problem["loc"][-1] for problem in r.json()["detail"]] == [field]
    assert (await client.get("/api/v1/watchlist", headers=ALICE)).json() == {"watchlist": None}


async def test_removing_software_answers_the_list_that_is_left(client: httpx.AsyncClient):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    both = (await client.post("/api/v1/watchlist/software", json=REDIS, headers=ALICE)).json()
    langgraph = next(row["id"] for row in both["software"] if row["name"] == "LangGraph")
    left = await client.delete(f"/api/v1/watchlist/software/{langgraph}", headers=ALICE)
    assert left.status_code == 200
    assert left.json()["version"] == 3
    assert [row["name"] for row in left.json()["software"]] == ["Redis"]
    gone = await client.delete(f"/api/v1/watchlist/software/{langgraph}", headers=ALICE)
    assert (gone.status_code, gone.json()) == (404, {"detail": "No such watched software"})


async def test_restoring_puts_removed_software_back_with_the_same_id_once(
    client: httpx.AsyncClient,
):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    both = (await client.post("/api/v1/watchlist/software", json=REDIS, headers=ALICE)).json()
    langgraph = next(row for row in both["software"] if row["name"] == "LangGraph")
    await client.delete(f"/api/v1/watchlist/software/{langgraph['id']}", headers=ALICE)

    back = await client.post(f"/api/v1/watchlist/software/{langgraph['id']}/restore", headers=CAROL)
    assert back.status_code == 200
    assert back.json()["version"] == 4
    assert next(row for row in back.json()["software"] if row["id"] == langgraph["id"]) == langgraph
    again = await client.post(
        f"/api/v1/watchlist/software/{langgraph['id']}/restore", headers=ALICE
    )
    assert (again.status_code, again.json()) == (200, back.json())


async def test_restoring_is_allowed_for_a_day_after_the_removal_then_a_410_in_plain_words(
    timed_client: httpx.AsyncClient, clock: MovingClock
):
    first = await timed_client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    old = first.json()["software"][0]["id"]
    await timed_client.delete(f"/api/v1/watchlist/software/{old}", headers=ALICE)
    clock.now += RESTORE_WINDOW
    inside = await timed_client.post(f"/api/v1/watchlist/software/{old}/restore", headers=ALICE)
    assert inside.status_code == 200
    assert [row["id"] for row in inside.json()["software"]] == [old]

    await timed_client.delete(f"/api/v1/watchlist/software/{old}", headers=ALICE)
    clock.now += RESTORE_WINDOW + timedelta(seconds=1)
    late = await timed_client.post(f"/api/v1/watchlist/software/{old}/restore", headers=CAROL)
    assert (late.status_code, late.json()) == (
        410,
        {"detail": "This software was removed more than a day ago, so it can't be put back."},
    )
    view = (await timed_client.get("/api/v1/watchlist", headers=ALICE)).json()["watchlist"]
    assert view["software"] == []


async def test_restoring_unknown_software_is_a_404_and_a_repository_added_again_a_409(
    client: httpx.AsyncClient,
):
    never = await client.post("/api/v1/watchlist/software/sw_nope/restore", headers=ALICE)
    assert (never.status_code, never.json()) == (
        404,
        {"detail": "This software was never on the watchlist"},
    )
    first = (await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)).json()
    old = first["software"][0]["id"]
    await client.delete(f"/api/v1/watchlist/software/{old}", headers=ALICE)
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    clash = await client.post(f"/api/v1/watchlist/software/{old}/restore", headers=ALICE)
    assert clash.status_code == 409
    assert clash.json() == {
        "detail": "langchain-ai/langgraph was added again after it was removed, "
        "so the removed entry cannot come back"
    }


async def test_only_an_operator_changes_the_list_and_anyone_signed_in_reads_it(
    client: httpx.AsyncClient,
):
    assert (await client.get("/api/v1/watchlist")).status_code == 401
    refused = await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=BOB)
    assert refused.status_code == 403
    assert (await client.delete("/api/v1/watchlist/software/sw_x", headers=BOB)).status_code == 403
    restore = await client.post("/api/v1/watchlist/software/sw_x/restore", headers=BOB)
    assert restore.status_code == 403
    assert (await client.get("/api/v1/watchlist", headers=BOB)).json() == {"watchlist": None}


async def test_the_first_add_saves_the_default_schedule_for_the_person_who_added(
    client: httpx.AsyncClient,
):
    created = await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=CAROL)
    schedule = created.json()["schedule"]
    assert schedule["owner"] == "carol" and schedule["owner_name"] == "Carol"
    assert (schedule["day"], schedule["at"], schedule["time_zone"]) == (
        "monday",
        "09:00",
        "Asia/Singapore",
    )
    assert schedule["next_at"].endswith("+08:00")
    assert schedule["next_at"] > schedule["saved_at"]

    second = await client.post("/api/v1/watchlist/software", json=REDIS, headers=ALICE)
    assert second.json()["schedule"] == schedule, "a later add leaves the schedule and its owner"


async def test_saving_a_schedule_makes_the_caller_its_owner_and_answers_the_watchlist(
    client: httpx.AsyncClient,
):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=CAROL)
    saved = await client.put(
        "/api/v1/watchlist/schedule", json={"day": "every_day", "at": "06:30"}, headers=ALICE
    )
    assert saved.status_code == 200
    view = saved.json()
    assert [row["name"] for row in view["software"]] == ["LangGraph"]
    schedule = view["schedule"]
    assert (schedule["day"], schedule["at"], schedule["owner"]) == ("every_day", "06:30", "alice")
    assert schedule["next_at"].endswith("06:30:00+08:00")
    got = await client.get("/api/v1/watchlist", headers=BOB)
    assert got.json() == {"watchlist": view}


async def test_a_schedule_whose_owner_left_the_list_is_held_until_an_operator_saves_it_again(
    client: httpx.AsyncClient,
):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=CAROL)
    assert (await client.delete("/api/v1/people/carol", headers=ALICE)).status_code == 204

    held = (await client.get("/api/v1/watchlist", headers=BOB)).json()["watchlist"]["schedule"]

    assert (held["owner"], held.get("held"), held["next_at"]) == ("carol", "owner_removed", None)
    taken = await client.put(
        "/api/v1/watchlist/schedule", json={"day": "monday", "at": "09:00"}, headers=ALICE
    )
    assert taken.status_code == 200
    schedule = taken.json()["schedule"]
    assert (schedule["owner"], schedule["owner_name"], schedule["held"]) == ("alice", "Alice", None)
    assert schedule["next_at"].endswith("09:00:00+08:00")


async def test_a_schedule_whose_owner_is_now_only_an_approver_is_held_and_they_cannot_take_it_back(
    client: httpx.AsyncClient,
):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    lost = await client.put(
        "/api/v1/people/alice/operator", json={"operator": False}, headers=CAROL
    )
    assert lost.status_code == 200

    held = (await client.get("/api/v1/watchlist", headers=BOB)).json()["watchlist"]["schedule"]

    assert (held["owner"], held.get("held"), held["next_at"]) == (
        "alice",
        "owner_not_an_operator",
        None,
    )
    body = {"day": "friday", "at": "17:00"}
    assert (
        await client.put("/api/v1/watchlist/schedule", json=body, headers=ALICE)
    ).status_code == 403
    taken = (await client.put("/api/v1/watchlist/schedule", json=body, headers=CAROL)).json()
    assert (taken["schedule"]["owner"], taken["schedule"]["held"]) == ("carol", None)
    assert taken["schedule"]["next_at"].endswith("17:00:00+08:00")


async def test_turning_the_schedule_off_leaves_null_and_saving_again_turns_it_on(
    client: httpx.AsyncClient,
):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    off = await client.delete("/api/v1/watchlist/schedule", headers=CAROL)
    assert (off.status_code, off.json()["schedule"]) == (200, None)
    again = await client.delete("/api/v1/watchlist/schedule", headers=CAROL)
    assert (again.status_code, again.json()["schedule"]) == (200, None)
    await client.post("/api/v1/watchlist/software", json=REDIS, headers=ALICE)
    assert (await client.get("/api/v1/watchlist", headers=ALICE)).json()["watchlist"][
        "schedule"
    ] is None, "adding more software does not bring a turned off schedule back"
    on = await client.put(
        "/api/v1/watchlist/schedule", json={"day": "friday", "at": "17:00"}, headers=CAROL
    )
    assert on.json()["schedule"]["owner"] == "carol"


async def test_a_schedule_needs_a_watchlist_and_an_operator(client: httpx.AsyncClient):
    body = {"day": "monday", "at": "09:00"}
    assert (
        await client.put("/api/v1/watchlist/schedule", json=body, headers=ALICE)
    ).status_code == 404
    assert (await client.delete("/api/v1/watchlist/schedule", headers=ALICE)).status_code == 404
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    assert (
        await client.put("/api/v1/watchlist/schedule", json=body, headers=BOB)
    ).status_code == 403
    assert (await client.delete("/api/v1/watchlist/schedule", headers=BOB)).status_code == 403
    assert (await client.put("/api/v1/watchlist/schedule", json=body)).status_code == 401


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"day": "monday", "at": "09:03"}, "at"),
        ({"day": "monday", "at": "9:00"}, "at"),
        ({"day": "monday", "at": "24:00"}, "at"),
        ({"day": "monday", "at": "09:60"}, "at"),
        ({"day": "monday", "at": "09:00:00"}, "at"),
        ({"day": "someday", "at": "09:00"}, "day"),
        ({"day": "Monday", "at": "09:00"}, "day"),
        ({"at": "09:00"}, "day"),
        ({"day": "monday"}, "at"),
    ],
)
async def test_a_bad_day_or_time_is_a_422_naming_the_field(
    client: httpx.AsyncClient, body: dict[str, str], field: str
):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    r = await client.put("/api/v1/watchlist/schedule", json=body, headers=ALICE)
    assert r.status_code == 422
    assert [problem["loc"][-1] for problem in r.json()["detail"]] == [field]


async def test_the_tick_checks_the_step_key_and_answers_the_runs_it_started(
    client: httpx.AsyncClient,
):
    assert (await client.post("/internal/v1/schedules/tick")).status_code == 422
    wrong = await client.post("/internal/v1/schedules/tick", headers={"X-Step-Key": "wrong"})
    assert wrong.status_code == 401
    assert (await client.post("/internal/v1/schedules/tick", headers=ALICE)).status_code == 422
    ticked = await client.post("/internal/v1/schedules/tick", headers=STEP_KEY)
    assert (ticked.status_code, ticked.json()) == (200, {"started": ["run_01A", "run_01B"]})
