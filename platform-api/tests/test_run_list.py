from datetime import timedelta
from typing import Any

import pytest

from platform_api.builder import Builder
from platform_api.shared import RunId
from tests import test_home
from tests.declared import declared_status
from tests.test_builder_lifecycle import ModelConnected
from tests.test_home import Lab, start, stopped_run, waiting_run, work, workflow

pytestmark = pytest.mark.anyio

lab = test_home.lab


async def runs_as(lab: Lab, user: str) -> list[dict[str, Any]]:
    response = await lab.call(user, "GET", "/api/v1/runs")
    assert response.status_code == 200, response.text
    declared_status(lab.app, "GET", "/api/v1/runs", response)
    return response.json()["runs"]


async def decidable(lab: Lab, user: str) -> dict[str, bool]:
    runs = await runs_as(lab, user)
    return {r["run_id"]: r["you_can_decide"] for r in runs if r["state"] == "awaiting_approval"}


async def nine_retried_ahead_of_one_to_decide(lab: Lab) -> tuple[RunId, list[RunId]]:
    """The issue's steps: carol owns the workflow and starts every run. One waits for alice.
    Nine newer ones fail, and alice retries them, so each is their own work."""
    use_case_id = await workflow(lab, owner="carol")
    theirs = await waiting_run(lab, use_case_id, by="carol")
    retried: list[RunId] = []
    for _ in range(9):
        lab.h.advance(timedelta(seconds=1))
        retried.append(await stopped_run(lab, use_case_id, by="carol"))
    for run_id in retried:
        response = await lab.call("alice", "POST", f"/api/v1/runs/{run_id}/retry")
        assert response.status_code == 202, response.text
    lab.h.advance(timedelta(seconds=5))
    for run_id in retried:
        await work(lab, run_id)
    return theirs, retried


async def test_the_list_says_which_waiting_runs_the_person_can_decide(lab: Lab):
    theirs, retried = await nine_retried_ahead_of_one_to_decide(lab)

    runs = await runs_as(lab, "alice")

    assert [r["run_id"] for r in runs] == [*retried[::-1], theirs]
    assert [r["you_can_decide"] for r in runs] == [False] * 9 + [True]
    assert await decidable(lab, "bob") == dict.fromkeys([*retried, theirs], True)
    assert await decidable(lab, "carol") == dict.fromkeys([*retried, theirs], False)


async def test_each_waiting_run_says_what_its_approval_says_for_the_same_person(lab: Lab):
    await nine_retried_ahead_of_one_to_decide(lab)

    for user in ("alice", "bob", "carol", "dave"):
        for run in await runs_as(lab, user):
            approval_id = run["approval"]["approval_id"]
            approval = (await lab.call(user, "GET", f"/api/v1/approvals/{approval_id}")).json()
            assert run["you_can_decide"] is approval["you_can_decide"], (user, run["run_id"])


async def test_one_run_says_it_too_and_a_run_that_waits_for_no_one_does_not(lab: Lab):
    use_case_id = await workflow(lab, owner="carol")
    waiting = await waiting_run(lab, use_case_id, by="carol")
    stopped = await stopped_run(lab, await workflow(lab, owner="carol", name="Another"), "carol")

    one = (await lab.call("alice", "GET", f"/api/v1/runs/{waiting}")).json()
    failed = (await lab.call("alice", "GET", f"/api/v1/runs/{stopped}")).json()

    assert (one["state"], one["you_can_decide"]) == ("awaiting_approval", True)
    assert failed["state"] == "failed"
    assert "you_can_decide" not in failed


async def test_a_stop_reads_the_same_from_the_run_the_list_the_workflow_and_needs_you(lab: Lab):
    """One stop, one sentence: the troubleshooter's. The workflow's row gives the time it stopped,
    the time Needs you gives, not the time it started."""
    lab.app.state.builder = Builder(
        lab.h.db,
        lab.h.orchestrator,
        lab.app.state.watchlist,
        "http://localhost:8000",
        ModelConnected(),
        history=lab.h.orchestrator,
    )
    use_case_id = await workflow(lab, owner="carol")
    run_id = await start(lab, use_case_id, "carol")
    lab.h.advance(timedelta(minutes=3))
    await work(lab, run_id, fail=True)

    one = (await lab.call("carol", "GET", f"/api/v1/runs/{run_id}")).json()
    (listed,) = [r for r in await runs_as(lab, "carol") if r["run_id"] == run_id]
    rows = (await lab.call("carol", "GET", "/api/v1/use-cases")).json()["use_cases"]
    (last,) = [row["last_run"] for row in rows if row["use_case_id"] == use_case_id]
    (needs,) = (await lab.home("carol"))["stopped"]

    said = "GitHub didn't answer."
    assert (one["what_happened"], listed["what_happened"], needs["what_happened"]) == (
        said,
        said,
        said,
    )
    assert last["stop"] == {"at": needs["stopped_at"], "what_happened": said}
    assert last["stop"]["at"] != last["at"], "it stopped three minutes after it started"
