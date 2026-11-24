"""The Check card shows a simulation's results (ADR 0054, PR 7). Once the safety checker has
graded a drafted revision with nothing still needed, code runs it through its scenarios in the
background. The card leads with the result, code's grade comes first and the explainer's sentence
only helps. A failed case doesn't block Turn on, and a result belongs to its version's digest.
Where there is no simulation n8n the card says so, and it never shows running past the limit.
A revision that still needs a setting says it will be tried once every setting is filled."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.builder.drafted_settings import ANY_APPROVER, APPROVERS
from platform_api.builder.drafted_workflows import DraftedWorkflows
from platform_api.builder.simulations import SIMULATING, Simulations
from platform_api.db import Database
from platform_api.orchestration.people_store import People
from platform_api.orchestration.scenario_grades import WAIT_LIMIT_SECONDS
from platform_api.orchestration.setup_approvals import SetUpApprovals
from platform_api.orchestration.simulation_driver import (
    DIDNT_ANSWER,
    NotSimulated,
    Simulated,
)
from platform_api.orchestration.simulation_gateway import (
    CoverageOut,
    NotTriedOut,
    ResultOut,
    SimulationOut,
)
from platform_api.shared import TEAM_TIME_ZONE
from tests.conftest import PostgresUrls
from tests.support import LOCAL_ENV
from tests.test_drafted_layout import release_check
from tests.test_drafted_workflows import WORDS, Channels, Drafter, Facts, N8n, Staff, drafted
from tests.test_setup_approvals import Channel

pytestmark = pytest.mark.anyio

NOTE = '"Read releases" stopped the run with no reason people can act on.'
PINNED = NotTriedOut(block="Post the notice", why="No mock runs for it, so its output is pinned.")


def case(kind: str, verdict: str, happened: str = "It ran to the end.") -> ResultOut:
    return ResultOut(
        name=kind,
        kind=kind,  # type: ignore[arg-type]
        verdict=verdict,  # type: ignore[arg-type]
        expected=f"What code expects of {kind}.",
        happened=happened,
        ran=[] if verdict == "not_tried" else ["Every Monday", "Read releases"],
        not_tried=[PINNED] if verdict == "passed" else [],
        ending=None if verdict == "not_tried" else "finished",
        stopped_at=None,
        plays=[],
    )


def simulated(*cases: ResultOut, notes: Mapping[str, str] | None = None) -> Simulated:
    tried = [c for c in cases if c.verdict != "not_tried"]
    return Simulated(
        SimulationOut(
            tried=len(tried),
            passed=sum(c.verdict == "passed" for c in cases),
            results=list(cases),
            coverage=CoverageOut(not_reached=[], not_tried=[PINNED], kinds_without_a_scenario=[]),
            blocks=[],
            scenarios_from="templates",
            refused=[],
        ),
        dict(notes or {}),
    )


SIX_FIVE = simulated(
    case("happy_path", "passed"),
    case("nothing_new", "passed"),
    case("source_not_found", "failed", "It failed, and n8n names no block."),
    case("timeout", "passed"),
    case("approver_says_no", "passed"),
    case("odd_data", "passed"),
    notes={"source_not_found": NOTE},
)


@dataclass
class Driver:
    """The simulation, faked: what it was sent, and what it answers, once let go."""

    answers: list[Simulated | NotSimulated] = field(
        default_factory=lambda: [SIX_FIVE]  # pyright: ignore[reportUnknownLambdaType]
    )
    versions: list[Mapping[str, Any]] = field(default_factory=list[Mapping[str, Any]])
    hold: asyncio.Event | None = None
    stubborn: bool = False
    """Ignores being stopped at its limit, as a call stuck past its timeout would."""

    async def run(self, version: Mapping[str, Any]) -> Simulated | NotSimulated:
        self.versions.append(version)
        while self.hold is not None and not self.hold.is_set():
            try:
                await self.hold.wait()
            except asyncio.CancelledError:
                if not self.stubborn:
                    raise
        return self.answers.pop(0) if self.answers else SIX_FIVE


@dataclass
class Bench:
    db: Database
    drafted: DraftedWorkflows
    simulations: Simulations
    driver: Driver
    client: httpx.AsyncClient

    async def call(self, user: str, method: str, path: str, body: Any = None) -> httpx.Response:
        return await self.client.request(method, path, headers={"X-Dev-User": user}, json=body)

    async def start(self, user: str = "alice") -> dict[str, Any]:
        """A drafted release check with who says yes answered, so nothing is still needed."""
        r = await self.call(user, "POST", "/api/v1/drafted-workflows", {"words": WORDS})
        assert r.status_code == 202, r.text
        await self.drafted.settle()
        first = await self.read(r.json()["drafted_id"], user)
        waits = "waiting" if self.simulations.available else "unavailable"
        assert first["simulation"]["state"] == waits, "a revision still needing a setting waits"
        body = {"revision": first["revision"], "setting": APPROVERS, "choice": ANY_APPROVER}
        path = f"/api/v1/drafted-workflows/{first['drafted_id']}/answers"
        r = await self.call(user, "POST", path, body)
        assert r.status_code == 200, r.text
        return r.json()

    async def read(self, drafted_id: str, user: str = "bob") -> dict[str, Any]:
        r = await self.call(user, "GET", f"/api/v1/drafted-workflows/{drafted_id}")
        assert r.status_code == 200, r.text
        return r.json()

    async def again(self, drafted_id: str, revision: int, user: str = "alice") -> httpx.Response:
        return await self.call(
            user,
            "POST",
            f"/api/v1/drafted-workflows/{drafted_id}/simulation",
            {"revision": revision},
        )

    async def digests(self) -> list[str]:
        async with self.db.connection("builder") as conn:
            rows = await (
                await conn.execute("SELECT digest FROM builder.simulations ORDER BY started_at")
            ).fetchall()
        return [str(r["digest"]) for r in rows]


async def bench_of(
    db: Database, driver: Driver | None, limit: timedelta | None = None
) -> AsyncIterator[Bench]:
    people = People(db)
    assert await people.seed_dev(DEV_PEOPLE)
    approvals = SetUpApprovals(db, Channel(), people, "https://portal.example", TEAM_TIME_ZONE)
    simulations = Simulations(db, driver) if limit is None else Simulations(db, driver, limit=limit)
    drafted_workflows = DraftedWorkflows(
        db,
        Drafter(answers=[drafted(release_check()), drafted(release_check("friday 09:00"))]),
        approvals,
        Facts(),
        N8n(),
        "https://portal.example",
        TEAM_TIME_ZONE.key,
        Channels(),
        Staff(),
        "https://n8n.example",
        simulations=simulations,
    )
    approvals.serve(drafted_workflows)
    app = create_app(LOCAL_ENV)
    app.state.people = people
    app.state.drafted = drafted_workflows
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Bench(db, drafted_workflows, simulations, driver or Driver(), client)
    if driver is not None and driver.hold is not None:
        driver.hold.set()
    await drafted_workflows.settle()


@pytest.fixture
async def bench(postgres: PostgresUrls, db: Database) -> AsyncIterator[Bench]:
    async for made in bench_of(db, Driver()):
        yield made


async def test_once_a_graded_revision_needs_nothing_it_is_simulated_in_the_background(
    bench: Bench,
):
    view = await bench.start()
    await bench.drafted.settle()
    after = await bench.read(view["drafted_id"])

    [version] = bench.driver.versions
    assert set(version) == {"name", "nodes", "connections", "settings"}
    assert version["name"] == "Release check"
    sim = after["simulation"]
    assert (sim["state"], sim["tried"], sim["passed"]) == ("done", 6, 5)
    assert sim["case_seconds"] == WAIT_LIMIT_SECONDS
    assert [c["kind"] for c in sim["cases"]][:2] == ["happy_path", "nothing_new"]
    assert sim["said"] is None


WAITING = {
    "state": "waiting",
    "started_at": None,
    "case_seconds": WAIT_LIMIT_SECONDS,
    "tried": 0,
    "passed": 0,
    "cases": [],
    "not_tried": [],
    "said": None,
    "can_try_again": False,
}


async def test_a_revision_that_still_needs_a_setting_waits_and_is_tried_once_it_is_filled(
    bench: Bench,
):
    r = await bench.call("alice", "POST", "/api/v1/drafted-workflows", {"words": WORDS})
    assert r.status_code == 202, r.text
    await bench.drafted.settle()
    drafted_id = r.json()["drafted_id"]

    for user in ("alice", "bob"):
        first = await bench.read(drafted_id, user)
        assert first["needed"] == 1
        assert first["simulation"] == WAITING, "it waits: never not available, never running"
    assert (bench.driver.versions, await bench.digests()) == ([], [])
    refused = await bench.again(drafted_id, first["revision"])
    assert refused.status_code == 409

    body = {"revision": first["revision"], "setting": APPROVERS, "choice": ANY_APPROVER}
    bench.driver.hold = asyncio.Event()
    answered = await bench.call(
        "alice", "POST", f"/api/v1/drafted-workflows/{drafted_id}/answers", body
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["simulation"]["state"] == "running"
    bench.driver.hold.set()
    await bench.drafted.settle()

    assert (await bench.read(drafted_id))["simulation"]["state"] == "done"
    assert len(bench.driver.versions) == 1


async def test_where_there_is_no_simulation_n8n_a_revision_needing_a_setting_promises_no_try(
    postgres: PostgresUrls, db: Database
):
    async for bench in bench_of(db, None):
        r = await bench.call("alice", "POST", "/api/v1/drafted-workflows", {"words": WORDS})
        assert r.status_code == 202, r.text
        await bench.drafted.settle()

        sim = (await bench.read(r.json()["drafted_id"]))["simulation"]

        assert sim == {**WAITING, "state": "unavailable"}


async def test_a_failed_case_leads_with_code_s_grade_and_the_explainer_only_helps_and_turn_on_stays(
    bench: Bench,
):
    view = await bench.start()
    await bench.drafted.settle()
    after = await bench.read(view["drafted_id"], "alice")

    [failed] = [c for c in after["simulation"]["cases"] if c["verdict"] == "failed"]
    assert failed == {
        "kind": "source_not_found",
        "verdict": "failed",
        "expected": "What code expects of source_not_found.",
        "happened": "It failed, and n8n names no block.",
        "note": NOTE,
    }
    assert (after["can_send"], after["why_not_send"]) == (True, None)
    assert after["simulation"]["not_tried"] == [PINNED.model_dump()]


async def test_a_case_no_block_can_play_shows_as_not_tried_never_as_passed(
    postgres: PostgresUrls, db: Database
):
    driver = Driver(
        answers=[
            simulated(
                case("happy_path", "passed"),
                case(
                    "timeout", "not_tried", "No block here can play this case, so it was not tried."
                ),
            )
        ]
    )
    async for bench in bench_of(db, driver):
        view = await bench.start()
        await bench.drafted.settle()
        sim = (await bench.read(view["drafted_id"]))["simulation"]

        assert (sim["tried"], sim["passed"]) == (1, 1)
        assert [(c["kind"], c["verdict"]) for c in sim["cases"]] == [
            ("happy_path", "passed"),
            ("timeout", "not_tried"),
        ]


async def test_while_it_runs_the_card_says_so_with_each_case_s_limit(
    postgres: PostgresUrls, db: Database
):
    async for bench in bench_of(db, Driver(hold=asyncio.Event())):
        view = await bench.start()

        sim = view["simulation"]
        assert sim["state"] == "running"
        assert sim["started_at"] is not None
        assert sim["case_seconds"] == WAIT_LIMIT_SECONDS
        assert (sim["tried"], sim["passed"], sim["cases"]) == (0, 0, [])
        assert sim["can_try_again"] is False


async def test_a_simulation_past_its_limit_never_shows_running_and_can_be_tried_again(
    postgres: PostgresUrls, db: Database
):
    driver = Driver(hold=asyncio.Event())
    async for bench in bench_of(db, driver, limit=timedelta(0)):
        view = await bench.start()
        drafted_id = view["drafted_id"]

        alice = (await bench.read(drafted_id, "alice"))["simulation"]
        bob = (await bench.read(drafted_id, "bob"))["simulation"]

        assert (alice["state"], alice["can_try_again"]) == ("not_finished", True)
        assert (bob["state"], bob["can_try_again"]) == ("not_finished", False)
        assert alice["cases"] == []


async def test_results_belong_to_the_digest_so_a_new_revision_never_shows_an_old_result(
    bench: Bench,
):
    view = await bench.start()
    await bench.drafted.settle()
    drafted_id = view["drafted_id"]
    assert (await bench.read(drafted_id))["simulation"]["state"] == "done"
    bench.driver.hold = asyncio.Event()
    r = await bench.call(
        "alice",
        "POST",
        f"/api/v1/drafted-workflows/{drafted_id}/changes",
        {"words": "run it on Fridays instead", "revision": view["revision"]},
    )
    assert r.status_code == 202, r.text
    async with asyncio.timeout(5):
        while len(bench.driver.versions) < 2:
            await asyncio.sleep(0.01)
    newer = await bench.read(drafted_id)

    assert newer["revision"] == view["revision"] + 1
    assert newer["simulation"]["state"] == "running"
    assert newer["simulation"]["cases"] == []
    assert len(set(await bench.digests())) == 2
    bench.driver.hold.set()
    await bench.drafted.settle()
    assert (await bench.read(drafted_id))["simulation"]["state"] == "done"


async def test_where_there_is_no_simulation_n8n_the_card_says_so_and_claims_no_result(
    postgres: PostgresUrls, db: Database
):
    async for bench in bench_of(db, None):
        view = await bench.start()
        await bench.drafted.settle()
        sim = (await bench.read(view["drafted_id"], "alice"))["simulation"]

        assert sim == {
            "state": "unavailable",
            "started_at": None,
            "case_seconds": WAIT_LIMIT_SECONDS,
            "tried": 0,
            "passed": 0,
            "cases": [],
            "not_tried": [],
            "said": None,
            "can_try_again": False,
        }
        r = await bench.again(view["drafted_id"], view["revision"])
        assert r.status_code == 409
        assert await bench.digests() == []


async def test_practice_systems_that_didn_t_answer_say_so_and_an_operator_can_try_again(
    postgres: PostgresUrls, db: Database
):
    driver = Driver(answers=[NotSimulated(DIDNT_ANSWER, again=True), SIX_FIVE])
    async for bench in bench_of(db, driver):
        view = await bench.start()
        await bench.drafted.settle()
        drafted_id = view["drafted_id"]
        sim = (await bench.read(drafted_id, "alice"))["simulation"]
        assert (sim["state"], sim["said"], sim["can_try_again"]) == (
            "not_run",
            DIDNT_ANSWER,
            True,
        )
        assert (await bench.read(drafted_id, "bob"))["simulation"]["can_try_again"] is False

        assert (await bench.again(drafted_id, view["revision"], "bob")).status_code == 403
        assert (await bench.again(drafted_id, view["revision"] - 1)).status_code == 409
        driver.hold = asyncio.Event()
        r = await bench.again(drafted_id, view["revision"])
        assert r.status_code == 200, r.text
        assert r.json()["simulation"]["state"] == "running"
        driver.hold.set()
        await bench.drafted.settle()

        assert (await bench.read(drafted_id))["simulation"]["state"] == "done"
        assert len(driver.versions) == 2


async def test_a_simulation_already_running_is_not_started_twice(
    postgres: PostgresUrls, db: Database
):
    driver = Driver(hold=asyncio.Event())
    async for bench in bench_of(db, driver):
        view = await bench.start()

        r = await bench.again(view["drafted_id"], view["revision"])

        assert (r.status_code, r.json()["detail"]) == (409, SIMULATING)
        assert len(driver.versions) == 1


async def test_the_running_row_is_kept_with_the_revision_so_a_poll_never_sees_it_untried(
    postgres: PostgresUrls, db: Database, monkeypatch: pytest.MonkeyPatch
):
    """The row is written in the revision's own transaction. Here the process stops right after,
    before any simulation starts: a poll still reads running, never untried."""

    async def stopped(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(Simulations, "start", stopped)
    driver = Driver()
    async for bench in bench_of(db, driver):
        view = await bench.start()

        assert view["simulation"]["state"] == "running"
        assert (await bench.read(view["drafted_id"]))["simulation"]["state"] == "running"
        assert driver.versions == []


async def test_a_revision_never_tried_says_so_and_an_operator_can_try_it_now(
    postgres: PostgresUrls, db: Database
):
    async for bench in bench_of(db, Driver()):
        view = await bench.start()
        await bench.drafted.settle()
        drafted_id = view["drafted_id"]
        with psycopg.connect(postgres.owner, autocommit=True) as conn:
            conn.execute("DELETE FROM builder.simulations")

        alice = (await bench.read(drafted_id, "alice"))["simulation"]
        bob = (await bench.read(drafted_id, "bob"))["simulation"]

        assert (alice["state"], alice["said"], alice["can_try_again"]) == (
            "not_started",
            None,
            True,
        )
        assert (bob["state"], bob["can_try_again"]) == ("not_started", False)
        r = await bench.again(drafted_id, view["revision"])
        assert r.status_code == 200, r.text
        await bench.drafted.settle()
        assert (await bench.read(drafted_id))["simulation"]["state"] == "done"


async def test_once_shutdown_begins_no_new_simulation_starts(postgres: PostgresUrls, db: Database):
    driver = Driver()
    async for bench in bench_of(db, driver):
        bench.simulations.cancel()

        view = await bench.start()
        async with asyncio.timeout(5):
            await bench.drafted.settle()

        assert driver.versions == []
        assert (view["simulation"]["state"], view["simulation"]["can_try_again"]) == (
            "not_started",
            False,
        )
        assert (await bench.again(view["drafted_id"], view["revision"])).status_code == 409


async def test_a_try_past_its_limit_counts_as_ended_so_try_again_starts_anew(
    postgres: PostgresUrls, db: Database
):
    driver = Driver(hold=asyncio.Event(), stubborn=True)
    async for bench in bench_of(db, driver, limit=timedelta(seconds=0.2)):
        view = await bench.start()
        drafted_id = view["drafted_id"]
        await asyncio.sleep(0.3)
        assert (await bench.read(drafted_id, "alice"))["simulation"]["state"] == "not_finished"

        r = await bench.again(drafted_id, view["revision"])

        assert r.status_code == 200, r.text
        assert r.json()["simulation"]["state"] == "running"
        assert len(driver.versions) == 2


async def test_simulated_runs_never_show_as_runs_or_in_the_activity_log(bench: Bench):
    view = await bench.start()
    await bench.drafted.settle()
    assert (await bench.read(view["drafted_id"]))["simulation"]["state"] == "done"

    async with bench.db.connection("orchestration") as conn:
        runs = await (await conn.execute("SELECT count(*) AS n FROM orchestration.runs")).fetchone()
    async with bench.db.connection("monitoring") as conn:
        events = await (
            await conn.execute("SELECT count(*) AS n FROM monitoring.run_events")
        ).fetchone()
    async with bench.db.connection("builder") as conn:
        kept = await (
            await conn.execute(
                "SELECT digest FROM builder.drafted_revisions WHERE drafted_id = %s"
                " AND revision = %s",
                (view["drafted_id"], view["revision"]),
            )
        ).fetchone()
    assert runs is not None and events is not None and kept is not None
    assert (runs["n"], events["n"]) == (0, 0)
    assert await bench.digests() == [kept["digest"]]
