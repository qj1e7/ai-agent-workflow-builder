"""Set up as a draft, try it with a test run that stops at the yes, then turn it on (ADR 0044)."""

from datetime import timedelta
from typing import Any

import httpx
import pytest

from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.lifecycle import (
    AlreadyDeleted,
    Deleted,
    Draft,
    Lifecycle,
    On,
    Paused,
    comes_on,
    delete,
    from_columns,
    is_on,
    pause,
    restore,
    resume,
    to_columns,
    turn_on,
)
from platform_api.monitoring.events import RunSucceeded, StepFinished, WriteActionProposed
from platform_api.orchestration import NotOn, ScheduleBook, ScheduleTicker
from platform_api.orchestration.runs import AwaitingApproval, Leg, Outcome, StepName, Succeeded
from platform_api.shared import N8nExecutionId, RunId, UseCaseId
from tests import test_builder_lifecycle
from tests.support import NOW
from tests.test_builder_lifecycle import (
    ALICE_ID,
    FIRST_MONDAY_SLOT,
    VALUES,
    WORK,
    Lab,
    at,
    changes,
    versions,
)
from tests.test_card_runs import output, ticket

pytestmark = pytest.mark.anyio

lab = test_builder_lifecycle.lab

TURN_ON_PATH = "/api/v1/use-cases/{use_case_id}/turn-on"
RUNS_PATH = "/api/v1/use-cases/{use_case_id}/runs"
EVERY_MONDAY = {"day": "monday", "at": "09:00"}
TEST_PASSED = "Test run passed up to the yes. Nothing was written."
NOT_ON_YET = {"detail": "This workflow isn't on yet. Do a test run, or turn it on to run it."}


def test_a_draft_is_not_on_and_turning_it_on_comes_on():
    assert is_on(Draft()) is False
    assert turn_on(Draft()) == On()
    assert comes_on(Draft(), On()) is True


def test_turning_on_changes_nothing_once_it_was_turned_on():
    paused = Paused(NOW, ALICE_ID)
    assert turn_on(On()) == On()
    assert turn_on(paused) == paused
    assert turn_on(Deleted(NOW, ALICE_ID, Draft())) == AlreadyDeleted()


def test_pausing_or_resuming_a_draft_leaves_it_a_draft():
    assert pause(Draft(), NOW, ALICE_ID) == Draft()
    assert resume(Draft()) == Draft()


def test_a_deleted_draft_is_restored_as_a_draft():
    assert restore(delete(Draft(), NOW, ALICE_ID), NOW + timedelta(hours=1)) == Draft()


@pytest.mark.parametrize("state", [Draft(), Deleted(NOW, ALICE_ID, Draft())])
def test_a_draft_round_trips_through_its_columns(state: Lifecycle):
    assert from_columns(to_columns(state)) == state


async def set_up(lab: Lab, body: dict[str, Any]) -> str:
    full = {
        "name": "LangGraph release check",
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
        **body,
    }
    r = await lab.call("alice", "POST", "/api/v1/agent-use-cases", full)
    assert r.status_code == 201, r.text
    return r.json()["use_case_id"]


async def draft(lab: Lab) -> str:
    return await set_up(lab, {"on": False, "schedule": EVERY_MONDAY})


async def use_case(lab: Lab, use_case_id: str) -> dict[str, Any]:
    r = await lab.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")
    assert r.status_code == 200, r.text
    return r.json()


async def turn_on_as(lab: Lab, user: str | None, use_case_id: str) -> httpx.Response:
    path = f"/api/v1/use-cases/{use_case_id}/turn-on"
    return await lab.call(user, "POST", path, template=TURN_ON_PATH)


async def try_it(lab: Lab, use_case_id: str) -> RunId:
    path = f"/api/v1/use-cases/{use_case_id}/runs"
    r = await lab.call("alice", "POST", path, {"test": True}, template=RUNS_PATH)
    assert r.status_code == 201, r.text
    return RunId(r.json()["run_id"])


async def work_leg(lab: Lab, run_id: RunId) -> None:
    """The work leg as n8n runs it: the agents propose a ticket, then the approval step."""
    h = lab.h
    h.agent.output = output(ticket(VERSION_CHECKER_ID))
    await h.orchestrator.tick()
    await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, WORK)
    reply = await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, WORK)
    assert reply.outcome in {"test_passed", "approval_opened"}
    await h.orchestrator.tick()


async def test_a_workflow_set_up_off_is_a_draft_with_its_schedule_and_no_next_run(lab: Lab):
    use_case_id = await draft(lab)

    view = await use_case(lab, use_case_id)

    assert (view["state"], view["version"], view["next_run_at"]) == ("draft", 1, None)
    assert (view["schedule"]["day"], view["schedule"]["at"]) == ("monday", "09:00")
    assert [u["state"] for u in await lab.listed()] == ["draft"]
    assert changes(await versions(lab, use_case_id)) == [], "nothing is published yet"


async def test_a_workflow_set_up_without_on_is_on_as_before(lab: Lab):
    use_case_id = await set_up(lab, {"schedule": EVERY_MONDAY})
    view = await use_case(lab, use_case_id)
    assert (view["state"], at(view["next_run_at"])) == ("on", FIRST_MONDAY_SLOT)


async def test_a_draft_never_runs_on_its_schedule(lab: Lab):
    use_case_id = await draft(lab)
    ticker = ScheduleTicker(lab.h.db, ScheduleBook(lab.h.db), lab.builder, lab.h.orchestrator)
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(minutes=1)

    assert await ticker.tick() == []

    assert await lab.runs() == []
    assert await lab.builder.check_spec(UseCaseId(use_case_id)) == NotOn("draft")


async def test_run_now_on_a_draft_is_refused_and_starts_nothing(lab: Lab):
    use_case_id = await draft(lab)
    path = f"/api/v1/use-cases/{use_case_id}/runs"

    refused = await lab.call("alice", "POST", path, template=RUNS_PATH)

    assert (refused.status_code, refused.json()) == (409, NOT_ON_YET)
    assert await lab.runs() == []


async def test_a_test_run_of_a_draft_stops_at_the_yes_and_writes_nothing(lab: Lab):
    use_case_id = await draft(lab)
    run_id = await try_it(lab, use_case_id)

    await work_leg(lab, run_id)

    state = await lab.h.state(run_id)
    assert isinstance(state, Succeeded) and state.outcome is Outcome.TEST_PASSED
    assert await lab.h.jira.tickets() == []
    assert await lab.h.teams.messages() == [], "nobody was asked for a yes in Teams"
    assert [leg for _, leg, rid in lab.h.engine.legs if rid == run_id] == [Leg.WORK]
    run = (await lab.call("bob", "GET", f"/api/v1/runs/{run_id}")).json()
    assert (run["state"], run["outcome"], run["written"], run["test"]) == (
        "succeeded",
        "test_passed",
        [],
        True,
    )
    assert "approval" not in run
    events = await lab.h.log.read_after(run_id, 0)
    kinds = [e.kind for e in events]
    assert "approval_requested" not in kinds
    [proposed] = [e for e in events if isinstance(e, WriteActionProposed)]
    assert [a.line for a in proposed.data.actions] == ["Create Jira ticket in MOCK: New release"]
    assert kinds[-3:] == ["step_started", "step_finished", "run_succeeded"]
    gate = [e for e in events if isinstance(e, StepFinished) and e.data.step == "ask_approval"]
    assert [e.data.outcome for e in gate] == ["test_passed"]
    [succeeded] = [e for e in events if isinstance(e, RunSucceeded)]
    assert (succeeded.summary, succeeded.data.outcome) == (TEST_PASSED, "test_passed")


async def test_the_safety_checker_refuses_a_write_for_a_test_run_of_a_draft(lab: Lab):
    use_case_id = await draft(lab)
    run_id = await try_it(lab, use_case_id)
    await work_leg(lab, run_id)

    stray = await lab.h.orchestrator.on_step(run_id, StepName.WRITE_ACTION, N8nExecutionId("77"))

    assert (stray.proceed, stray.outcome) == (False, "refused")
    assert await lab.h.jira.tickets() == []
    assert (await lab.h.kinds(run_id))[-2:] == ["write_action_denied", "step_finished"]
    again = await lab.h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, WORK)
    assert (again.proceed, again.outcome) == (False, "replayed")
    assert await lab.h.teams.messages() == []
    state = await lab.h.state(run_id)
    assert isinstance(state, Succeeded) and state.outcome is Outcome.TEST_PASSED


async def test_a_test_run_started_on_a_draft_stops_at_the_yes_after_it_is_turned_on(lab: Lab):
    use_case_id = await draft(lab)
    run_id = await try_it(lab, use_case_id)
    assert (await turn_on_as(lab, "alice", use_case_id)).json()["state"] == "on"

    await work_leg(lab, run_id)

    state = await lab.h.state(run_id)
    assert isinstance(state, Succeeded) and state.outcome is Outcome.TEST_PASSED
    assert await lab.h.teams.messages() == []


async def test_a_test_run_of_a_workflow_that_is_on_still_asks_for_a_yes(lab: Lab):
    use_case_id = await set_up(lab, {})
    run_id = await try_it(lab, use_case_id)

    await work_leg(lab, run_id)

    assert isinstance(await lab.h.state(run_id), AwaitingApproval)
    assert len(await lab.h.teams.messages()) == 1


async def test_turning_on_publishes_version_1_and_its_schedule_runs(lab: Lab):
    use_case_id = await draft(lab)
    lab.h.advance(timedelta(minutes=5))

    on = await turn_on_as(lab, "carol", use_case_id)

    assert on.status_code == 200, on.text
    assert (on.json()["state"], on.json()["version"]) == ("on", 1)
    assert at(on.json()["next_run_at"]) == FIRST_MONDAY_SLOT
    assert changes(await versions(lab, use_case_id)) == [(1, None, None, None, None, True)]
    ticker = ScheduleTicker(lab.h.db, ScheduleBook(lab.h.db), lab.builder, lab.h.orchestrator)
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(minutes=1)
    [run_id] = await ticker.tick()
    assert [(r["run_id"], r["trigger"]) for r in await lab.runs()] == [(run_id, "schedule")]


async def test_turning_on_twice_answers_the_same_and_publishes_nothing_more(lab: Lab):
    use_case_id = await draft(lab)
    first = await turn_on_as(lab, "alice", use_case_id)
    lab.h.advance(timedelta(minutes=5))

    second = await turn_on_as(lab, "alice", use_case_id)

    assert (second.status_code, second.json()) == (200, first.json())
    assert changes(await versions(lab, use_case_id)) == [(1, None, None, None, None, True)]


async def test_turning_on_a_paused_workflow_leaves_it_paused(lab: Lab):
    use_case_id = await draft(lab)
    await turn_on_as(lab, "alice", use_case_id)
    await lab.move("alice", "pause", use_case_id)

    again = await turn_on_as(lab, "alice", use_case_id)

    assert (again.json()["state"], again.json()["next_run_at"]) == ("paused", None)


async def test_a_slot_that_fell_while_it_was_a_draft_never_starts(lab: Lab):
    use_case_id = await draft(lab)
    ticker = ScheduleTicker(lab.h.db, ScheduleBook(lab.h.db), lab.builder, lab.h.orchestrator)
    lab.h.clock["now"] = FIRST_MONDAY_SLOT + timedelta(minutes=7)

    on = await turn_on_as(lab, "alice", use_case_id)

    assert at(on.json()["next_run_at"]) == FIRST_MONDAY_SLOT + timedelta(days=7)
    assert await ticker.tick() == []
    assert await lab.runs() == []


async def test_pause_and_resume_leave_a_draft_a_draft(lab: Lab):
    use_case_id = await draft(lab)
    assert (await lab.move("alice", "pause", use_case_id)).json()["state"] == "draft"
    assert (await lab.move("alice", "resume", use_case_id)).json()["state"] == "draft"
    assert await lab.paused_columns(use_case_id) == (None, None, None, None)


async def test_a_deleted_draft_comes_back_a_draft(lab: Lab):
    use_case_id = await draft(lab)
    assert (await lab.move("alice", "delete", use_case_id)).status_code == 200
    assert (await turn_on_as(lab, "alice", use_case_id)).status_code == 404
    assert (await lab.move("alice", "restore", use_case_id)).json()["state"] == "draft"


async def test_saving_a_draft_s_schedule_publishes_no_version_and_turn_on_uses_it(lab: Lab):
    use_case_id = await draft(lab)
    path = f"/api/v1/use-cases/{use_case_id}/schedule"

    saved = await lab.call("alice", "PUT", path, {"day": "friday", "at": "17:30"})

    assert saved.status_code == 200, saved.text
    assert (saved.json()["state"], saved.json()["version"]) == ("draft", 1)
    assert (saved.json()["schedule"]["day"], saved.json()["schedule"]["at"]) == ("friday", "17:30")
    assert changes(await versions(lab, use_case_id)) == []
    undo = await lab.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/versions/1/undo")
    assert (undo.status_code, undo.json()) == (404, {"detail": "No such version"})
    on = await turn_on_as(lab, "alice", use_case_id)
    assert (on.json()["version"], on.json()["schedule"]["day"]) == (1, "friday")


async def test_only_an_operator_turns_a_workflow_on(lab: Lab):
    use_case_id = await draft(lab)
    refused = await turn_on_as(lab, "bob", use_case_id)
    assert (refused.status_code, refused.json()) == (
        403,
        {"detail": "Only an Operator can change workflows."},
    )
    assert (await use_case(lab, use_case_id))["state"] == "draft"
    assert (await turn_on_as(lab, None, use_case_id)).status_code == 401


async def test_turning_on_an_unknown_workflow_is_404(lab: Lab):
    r = await turn_on_as(lab, "alice", "uc_nope")
    assert (r.status_code, r.json()) == (404, {"detail": "No such workflow"})
