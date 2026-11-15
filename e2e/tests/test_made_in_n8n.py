"""A workflow made in n8n and set up from Workflows, on the real n8n (ENGINE-PLAN E15): Erin, an
Operator with n8n access, builds a workflow from our blocks in her own n8n space and publishes it;
it waits on Workflows with her as its maker, graded safe, for her and nobody without n8n access;
she sets it up, so it moves to the platform's project and is on; Run now reads and asks, Erin,
an Approver by then, can never approve it, and Bob's yes makes one ticket."""

import copy
import uuid

from harness import N8N_OWNER, Api, Json, approval_requested, bob_decides, tickets_for
from test_n8n_access import becomes_approver, sits_in
from test_n8n_engine import set_up
from test_n8n_versions import Member, staff_member


def built_from_our_blocks(member: Member, source_id: str, name: str) -> str:
    """Erin draws a workflow in her own space from the blocks the Planner lays out, each a new
    block with the new ids n8n's editor gives one, then saves and publishes it."""
    laid = N8N_OWNER.call("GET", f"/workflows/{source_id}")
    nodes: list[Json] = copy.deepcopy(laid["nodes"])
    for node in nodes:
        node["id"] = str(uuid.uuid4())
        if "webhookId" in node:
            node["webhookId"] = str(uuid.uuid4())
    body = {
        "name": name,
        "nodes": nodes,
        "connections": laid["connections"],
        "settings": laid["settings"],
    }
    saved = member.call("POST", "/workflows", body)
    workflow_id = str(saved["id"])
    held = member.call("GET", f"/workflows/{workflow_id}")
    publish = {"versionId": held["versionId"], "expectedChecksum": held["checksum"]}
    member.call("POST", f"/workflows/{workflow_id}/activate", publish)
    assert N8N_OWNER.call("GET", f"/workflows/{workflow_id}")["activeVersionId"]
    return workflow_id


def test_a_workflow_made_in_n8n_is_set_up_runs_and_bob_approves(api: Api, mock_model: None):
    source = set_up(api, "e2e made in n8n, the blocks it copies", on=False)
    erin = staff_member(api, "Erin")
    name = f"e2e made in n8n {uuid.uuid4().hex[:6]}"
    workflow_id = built_from_our_blocks(erin.member, source["n8n_workflow_id"], name)
    assert sits_in(erin.member.project, workflow_id)

    refused = api.request("bob", "GET", "/api/v1/n8n/workflows", expect=(403,))
    assert refused.json()["detail"].startswith("Only an Operator with n8n access")
    waiting = {
        w["workflow_id"]: w for w in api.get(erin.person, "/api/v1/n8n/workflows")["workflows"]
    }
    found = waiting[workflow_id]
    assert (found["name"], found["made_by"], found["published"]) == (name, erin.person, True)
    assert (found["grade"], found["findings"], found["can_set_up"]) == ("safe", [], True)
    assert source["n8n_workflow_id"] not in waiting, "a workflow the platform runs never waits"

    created = api.post(
        erin.person, "/api/v1/use-cases/from-n8n", {"workflow_id": workflow_id}, expect=(201,)
    ).json()
    use_case_id = created["use_case_id"]
    assert (created["n8n_workflow_id"], created["grade"]) == (workflow_id, "safe")
    platform = str(N8N_OWNER.call("GET", "/projects/personal")["id"])
    assert sits_in(platform, workflow_id) and not erin.member.can_open(workflow_id)
    view = api.get("alice", f"/api/v1/use-cases/{use_case_id}")
    assert (view["state"], view["made_in_n8n_by"], view["grade"]) == ("on", erin.person, "safe")
    in_n8n = api.get(erin.person, f"/api/v1/use-cases/{use_case_id}/n8n")
    assert (in_n8n["published_by"], in_n8n["published_in"]) == (erin.person, "n8n")
    still = api.get(erin.person, "/api/v1/n8n/workflows")["workflows"]
    assert workflow_id not in {w["workflow_id"] for w in still}, "set up, so no longer waiting"

    becomes_approver(api, erin.person)
    run_id, _ = api.start_run("carol", use_case_id)
    events = api.stream_until("carol", run_id, {"approval_requested"})
    approval_id = approval_requested(events)["approval_id"]
    approval = api.get("bob", f"/api/v1/approvals/{approval_id}")
    own = api.post(
        erin.person,
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": approval["digest"]},
        expect=(403,),
    ).json()
    assert own["refusal"] == "own_work", "Erin made the workflow in n8n"
    bob_decides(api, approval_id, "approve", approval["digest"])
    done = api.wait_for_state("carol", run_id, {"succeeded"})
    assert done["outcome"] == "written"
    assert len(tickets_for(api, run_id)) == 1, "exactly one ticket"
    for made in (use_case_id, source["use_case_id"]):
        api.delete("alice", f"/api/v1/use-cases/{made}", expect=(200,))
