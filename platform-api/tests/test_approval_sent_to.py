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
BOB_ = {"id": "bob", "display": "Bob"}
DAVE_ = {"id": "dave", "display": "Dave"}
ERIN_ = {"id": "erin", "display": "Erin"}


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
    assert (before["post"], before["sent_to"], before["sent_at"]) == ("waiting", [], None)

    await h.orchestrator.tick()

    event = await announced(lab, run_id)
    assert [[p.id for p in step] for step in event.data.sent_to] == [["bob", "dave", "erin"]]
    assert event.data.sent_at == event.ts
    [step] = await steps_of(lab, run_id)
    assert step["post"] == "sent"
    assert step["sent_to"] == [BOB_, DAVE_, ERIN_], "never Alice, who owns it"
    assert datetime.fromisoformat(step["sent_at"]) == event.ts


async def test_two_steps_each_name_their_own_approvers_in_turn(lab: Lab):
    started = await lab.h.orchestrator.start_run(
        replace(SPEC, approval_policy=TWO_STEPS), CAROL, "two-steps"
    )
    run_id = started.run_id
    await work(lab, run_id, cards=False)

    event = await announced(lab, run_id)
    assert [[p.id for p in step] for step in event.data.sent_to] == [["bob", "dave", "erin"]] * 2
    assert [s["sent_to"] for s in await steps_of(lab, run_id)] == [[BOB_, DAVE_, ERIN_]] * 2

    await decide_first_step(lab, "bob", run_id)

    first, second = await steps_of(lab, run_id)
    assert (first["status"], first["sent_to"]) == ("approved", [BOB_, DAVE_, ERIN_])
    assert (second["status"], second["sent_to"]) == ("open", [DAVE_, ERIN_]), "not Bob again"
