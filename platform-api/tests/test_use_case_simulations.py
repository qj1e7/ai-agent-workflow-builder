"""A workflow the Planner builds from our blocks is tried on practice systems too (ADR 0054,
section 1). Each version is tried once, by its digest, the first time its Check is read, and its
Check shows the same result a drafted workflow's card shows. A simulation is not a run, a pass
turns nothing on, and only an Operator can try it again."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from platform_api.builder.simulations import NO_SIMULATION, SIMULATING, Simulations
from platform_api.builder.use_case_simulations import UseCaseSimulations
from platform_api.orchestration.scenario_grades import WAIT_LIMIT_SECONDS
from platform_api.orchestration.simulation_driver import DIDNT_ANSWER, NotSimulated
from platform_api.orchestration.version_digest import workflow_digest
from tests.fake_n8n import FakeN8n
from tests.test_builder_lifecycle import Lab
from tests.test_drafted_simulations import SIX_FIVE, Driver
from tests.test_n8n_builder import BODY, N8nLab, lab, with_n8n
from tests.test_n8n_lifecycle import Workflows, made, version_row

pytestmark = pytest.mark.anyio

__all__ = ["lab"]

PATH = "/api/v1/use-cases/{use_case_id}/simulation"
CHANGED = "It changed since you opened it. Open it again."


@dataclass
class Tried:
    own: N8nLab
    simulations: Simulations
    driver: Driver

    async def check(self, use_case_id: str, user: str = "alice") -> dict[str, Any]:
        r = await self.own.lab.call(
            user, "GET", f"/api/v1/use-cases/{use_case_id}/simulation", template=PATH
        )
        assert r.status_code == 200, r.text
        return r.json()

    async def again(self, use_case_id: str, version: int, user: str = "alice") -> httpx.Response:
        return await self.own.lab.call(
            user,
            "POST",
            f"/api/v1/use-cases/{use_case_id}/simulation",
            {"version": version},
            template=PATH,
        )

    async def digests(self) -> list[str]:
        async with self.own.lab.h.db.connection("builder") as conn:
            rows = await (
                await conn.execute("SELECT digest FROM builder.simulations ORDER BY started_at")
            ).fetchall()
        return [str(r["digest"]) for r in rows]


async def tried_of(lab: Lab, driver: Driver | None) -> AsyncIterator[Tried]:
    n8n = FakeN8n()
    with_n8n(lab, Workflows(n8n, lab.h.db))
    simulations = Simulations(lab.h.db, driver)
    lab.app.state.use_case_simulations = UseCaseSimulations(lab.h.db, simulations)
    yield Tried(N8nLab(lab, n8n), simulations, driver or Driver())
    if driver is not None and driver.hold is not None:
        driver.hold.set()
    await simulations.settle()


@pytest.fixture
async def tried(lab: Lab) -> AsyncIterator[Tried]:
    async for made_ in tried_of(lab, Driver()):
        yield made_


async def test_a_planner_built_version_is_tried_the_first_time_its_check_is_read(tried: Tried):
    use_case_id, _ = await made(tried.own)
    tried.driver.hold = asyncio.Event()

    first = await tried.check(use_case_id)

    assert (first["use_case_id"], first["version"]) == (use_case_id, 1)
    sim = first["simulation"]
    assert (sim["state"], sim["case_seconds"], sim["cases"]) == ("running", WAIT_LIMIT_SECONDS, [])
    assert sim["can_try_again"] is False
    tried.driver.hold.set()
    await tried.simulations.settle()

    done = (await tried.check(use_case_id))["simulation"]
    assert (done["state"], done["tried"], done["passed"]) == ("done", 6, 5)
    [version] = tried.driver.versions
    assert set(version) == {"name", "nodes", "connections", "settings"}
    assert version["name"] == BODY["name"]
    document = (await version_row(tried.own, use_case_id, 1))["document"]
    assert await tried.digests() == [workflow_digest(document)]


async def test_reading_it_again_or_as_someone_else_starts_no_second_try(tried: Tried):
    use_case_id, _ = await made(tried.own)
    tried.driver.hold = asyncio.Event()

    alice = (await tried.check(use_case_id, "alice"))["simulation"]
    bob = (await tried.check(use_case_id, "bob"))["simulation"]

    assert (alice["state"], bob["state"]) == ("running", "running")
    assert len(tried.driver.versions) == 1
    assert len(await tried.digests()) == 1


async def test_a_new_schedule_changes_the_digest_so_the_check_never_shows_the_older_result(
    tried: Tried,
):
    use_case_id, _ = await made(tried.own)
    await tried.check(use_case_id)
    await tried.simulations.settle()
    assert (await tried.check(use_case_id))["simulation"]["state"] == "done"
    tried.driver.hold = asyncio.Event()

    saved = await tried.own.lab.call(
        "alice",
        "PUT",
        f"/api/v1/use-cases/{use_case_id}/schedule",
        {"day": "friday", "at": "17:30", "expected_version": 1},
    )
    assert saved.status_code == 200, saved.text
    newer = (await tried.check(use_case_id))["simulation"]

    assert (newer["state"], newer["cases"]) == ("running", [])
    assert len(set(await tried.digests())) == 2
    assert len(tried.driver.versions) == 2


async def test_a_pass_turns_nothing_on_and_is_never_a_run_or_in_the_activity_log(tried: Tried):
    use_case_id, _ = await made(tried.own)
    await tried.check(use_case_id)
    await tried.simulations.settle()
    assert (await tried.check(use_case_id))["simulation"]["state"] == "done"

    view = await tried.own.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")
    assert view.json()["state"] == "draft", "a pass never turns it on"
    db = tried.own.lab.h.db
    async with db.connection("orchestration") as conn:
        runs = await (await conn.execute("SELECT count(*) AS n FROM orchestration.runs")).fetchone()
    async with db.connection("monitoring") as conn:
        events = await (
            await conn.execute("SELECT count(*) AS n FROM monitoring.run_events")
        ).fetchone()
    assert runs is not None and events is not None
    assert (runs["n"], events["n"]) == (0, 0)


async def test_only_an_operator_can_try_it_again_once_practice_systems_didn_t_answer(lab: Lab):
    driver = Driver(answers=[NotSimulated(DIDNT_ANSWER, again=True), SIX_FIVE])
    async for tried in tried_of(lab, driver):
        use_case_id, _ = await made(tried.own)
        await tried.check(use_case_id)
        await tried.simulations.settle()

        alice = (await tried.check(use_case_id, "alice"))["simulation"]
        bob = (await tried.check(use_case_id, "bob"))["simulation"]
        assert (alice["state"], alice["said"], alice["can_try_again"]) == (
            "not_run",
            DIDNT_ANSWER,
            True,
        )
        assert bob["can_try_again"] is False

        assert (await tried.again(use_case_id, 1, "bob")).status_code == 403
        stale = await tried.again(use_case_id, 2)
        assert (stale.status_code, stale.json()["detail"]) == (409, CHANGED)
        driver.hold = asyncio.Event()
        r = await tried.again(use_case_id, 1)
        assert r.status_code == 200, r.text
        assert r.json()["simulation"]["state"] == "running"
        running = await tried.again(use_case_id, 1)
        assert (running.status_code, running.json()["detail"]) == (409, SIMULATING)
        driver.hold.set()
        await tried.simulations.settle()

        assert (await tried.check(use_case_id))["simulation"]["state"] == "done"
        assert len(driver.versions) == 2


async def test_where_there_is_no_simulation_n8n_the_check_says_so_and_claims_no_result(lab: Lab):
    async for tried in tried_of(lab, None):
        use_case_id, _ = await made(tried.own)

        sim = (await tried.check(use_case_id))["simulation"]

        assert (sim["state"], sim["started_at"], sim["can_try_again"]) == (
            "unavailable",
            None,
            False,
        )
        refused = await tried.again(use_case_id, 1)
        assert (refused.status_code, refused.json()["detail"]) == (409, NO_SIMULATION)
        assert await tried.digests() == []


async def test_once_shutdown_begins_no_new_try_starts(tried: Tried):
    use_case_id, _ = await made(tried.own)
    tried.simulations.cancel()

    sim = (await tried.check(use_case_id))["simulation"]

    assert (sim["state"], sim["can_try_again"]) == ("not_started", False)
    assert tried.driver.versions == []


async def test_a_workflow_with_no_n8n_workflow_of_its_own_has_nothing_to_try(lab: Lab):
    driver = Driver()
    simulations = Simulations(lab.h.db, driver)
    lab.app.state.use_case_simulations = UseCaseSimulations(lab.h.db, simulations)
    created = await lab.call("alice", "POST", "/api/v1/agent-use-cases", BODY)
    assert created.status_code == 201, created.text
    use_case_id = created.json()["use_case_id"]

    r = await lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/simulation")

    assert r.status_code == 200, r.text
    assert r.json()["simulation"] is None
    assert driver.versions == []
    nothing = await lab.call(
        "alice", "POST", f"/api/v1/use-cases/{use_case_id}/simulation", {"version": 1}
    )
    assert nothing.status_code == 409


async def test_an_unknown_or_deleted_workflow_has_no_check(tried: Tried):
    unknown = await tried.own.lab.call("alice", "GET", "/api/v1/use-cases/uc_nope/simulation")
    assert unknown.status_code == 404
    use_case_id, _ = await made(tried.own)
    assert (await tried.own.lab.move("alice", "delete", use_case_id)).status_code == 200

    gone = await tried.own.lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}/simulation")

    assert gone.status_code == 404
    assert tried.driver.versions == []
