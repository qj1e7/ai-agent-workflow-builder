from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from platform_api.monitoring.events import ApprovalAnnounced
from platform_api.orchestration.runs import AwaitingApproval, StepName
from platform_api.shared import RunId
from tests.support import CAROL, SPEC
from tests.test_home import TWO_STEPS, Lab, decide_first_step, execution_of, lab, work

__all__ = ["lab"]

pytestmark = pytest.mark.anyio

# The lab's People list: Alice, Bob, Dave and Erin hold the Approver role, Carol does not.


async def steps_of(lab: Lab, run_id: RunId) -> list[dict[str, Any]]:
    """The request's steps, as its own view and its run's view both give them."""
    run = (await lab.call("bob", "GET", f"/api/v1/runs/{run_id}")).json()
    approval_id = run["approval"]["approval_id"]
    view = (await lab.call("bob", "GET", f"/api/v1/approvals/{approval_id}")).json()
    assert view["steps"] == run["approval"]["steps"], "the run and its request say the same"
    return view["steps"]


async def announced(lab: Lab, run_id: RunId) -> ApprovalAnnounced:
    [event] = [e for e in await lab.h.log.read_after(run_id, 0) if e.kind == "approval_announced"]
    assert isinstance(event, ApprovalAnnounced)
    return event


async def test_one_step_names_every_approver_but_the_runs_parties_once_it_is_in_teams(lab: Lab):
    h = lab.h
    run_id = (await h.orchestrator.start_run(SPEC, CAROL, "one-step")).run_id
    await h.orchestrator.tick()
    execution = execution_of(h, run_id)
    await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, execution)
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, execution)
    assert isinstance(await h.state(run_id), AwaitingApproval)
    [before] = await steps_of(lab, run_id)
    assert (before["sent_to"], before["sent_at"]) == ([], None), "nothing is sent before Teams"

    await h.orchestrator.tick()

    event = await announced(lab, run_id)
    assert event.data.sent_to == [["Bob", "Dave", "Erin"]], "never Alice, who owns it"
    assert event.data.sent_at == event.ts
    [step] = await steps_of(lab, run_id)
    assert step["sent_to"] == ["Bob", "Dave", "Erin"]
    assert datetime.fromisoformat(step["sent_at"]) == event.ts


async def test_two_steps_each_name_their_own_approvers_in_turn(lab: Lab):
    started = await lab.h.orchestrator.start_run(
        replace(SPEC, approval_policy=TWO_STEPS), CAROL, "two-steps"
    )
    run_id = started.run_id
    await work(lab, run_id, cards=False)

    assert (await announced(lab, run_id)).data.sent_to == [["Bob", "Dave", "Erin"]] * 2
    assert [s["sent_to"] for s in await steps_of(lab, run_id)] == [["Bob", "Dave", "Erin"]] * 2

    await decide_first_step(lab, "bob", run_id)

    first, second = await steps_of(lab, run_id)
    assert (first["status"], first["sent_to"]) == ("approved", ["Bob", "Dave", "Erin"])
    assert (second["status"], second["sent_to"]) == ("open", ["Dave", "Erin"]), "not Bob again"
