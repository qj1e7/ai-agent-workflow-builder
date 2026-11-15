"""A platform's database from before ENGINE-PLAN E10, when every workflow ran on the shared run
workflow, moves to the new engine as the platform starts, with its history intact.

The stack starts from e2e/old_engine/seed.json, loaded before bootstrap (scripts/e2e.sh with
E2E_SEED=old-engine). It holds two agent workflows on the shared run workflow: "Old release
check", whose one run Bob declined, and "Old waiting check", whose run waits for Bob's yes. From
E11 the shared run workflow's blocks are off, so the platform ends the waiting run as it starts,
says so, and refuses a late yes, and both workflows move."""

import pytest
from harness import Api, Json, approval_requested, assert_story, bob_decides, tickets_for

ENDED = (
    "This run started before the update and couldn't finish. Nothing was written. Start it again."
)

pytestmark = pytest.mark.old_engine

MOVED = "Old release check"
WAITING = "Old waiting check"


def workflow(api: Api, name: str) -> Json:
    listed = api.get("alice", "/api/v1/use-cases")["use_cases"]
    [found] = [w for w in listed if w["name"] == name]
    return found


def runs_of(api: Api, use_case_id: str) -> list[Json]:
    return [r for r in api.get("alice", "/api/v1/runs")["runs"] if r["use_case_id"] == use_case_id]


def versions(api: Api, use_case_id: str) -> list[Json]:
    return api.get("alice", f"/api/v1/use-cases/{use_case_id}/versions")["versions"]


def test_the_old_engine_database_moves_to_the_new_engine_with_its_history(
    api: Api, mock_model: None
):
    moved = workflow(api, MOVED)
    assert (moved["state"], moved["grade"], moved["moving_to_n8n"]) == ("on", "safe", False)
    assert moved["blocks"], "it is laid out in its own n8n workflow"
    assert moved["next_run_at"] is not None, "n8n's Schedule Trigger runs it"
    made = [(v["version"], v["made"]) for v in versions(api, moved["use_case_id"])]
    assert made == [(2, "moved_to_n8n"), (1, None)]
    assert [r["state"] for r in runs_of(api, moved["use_case_id"])] == ["rejected"]

    waiting = workflow(api, WAITING)
    assert (waiting["state"], waiting["grade"], waiting["moving_to_n8n"]) == ("on", "safe", False)
    assert waiting["blocks"], "its run ended as the platform started, so it moved"
    made = [(v["version"], v["made"]) for v in versions(api, waiting["use_case_id"])]
    assert made == [(2, "moved_to_n8n"), (1, None)]
    [ended] = runs_of(api, waiting["use_case_id"])
    assert (ended["state"], ended["reason"], ended["retryable"]) == (
        "failed",
        "StoppedByUpdate",
        False,
    )
    assert ended["message"] == ENDED
    events = api.events_after("alice", ended["run_id"])
    assert events[-1]["kind"] == "run_failed"
    approval_id = approval_requested(events)["approval_id"]
    approval = api.get("bob", f"/api/v1/approvals/{approval_id}")
    assert [step["status"] for step in approval["steps"]] == ["closed"]
    late = api.post(
        "bob",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": approval["digest"]},
        expect=(403,),
    )
    assert late.json()["refusal"] == "not_open", late.text
    assert tickets_for(api, ended["run_id"]) == [], "a late yes writes nothing"

    run_id, started = api.start_run("carol", moved["use_case_id"])
    assert started.status_code == 201
    events = api.stream_until("carol", run_id, {"approval_requested"})
    assert_story(events, ["run_created", "execution_linked", "approval_requested"])
    approval_id = approval_requested(events)["approval_id"]
    approval = api.get("bob", f"/api/v1/approvals/{approval_id}")
    bob_decides(api, approval_id, "approve", approval["digest"])
    assert api.wait_for_state("carol", run_id, {"succeeded"})["outcome"] == "written"
    assert len(tickets_for(api, run_id)) == 1
