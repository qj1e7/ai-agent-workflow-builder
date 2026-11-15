"""n8n access per person on the real n8n (ENGINE-PLAN E7): an Operator gives Dana n8n access, the
platform makes her n8n account and shows her alone the link to set its password; Open in n8n moves
the workflow to her own space with its settings intact; she changes her n8n email and publishes,
and the sweep still names her, by the n8n user id the platform stored; once she is an Approver her
access ends, the workflow comes back, and she can never approve a run of the version she
published."""

import json
import secrets
import urllib.parse

from harness import N8N_OWNER, Api, Json, approval_requested, bob_decides, tickets_for
from test_n8n_engine import set_up
from test_n8n_versions import Member, settings_in_n8n, swept


def at_seven_thirty(nodes: list[Json], connections: Json) -> None:
    for node in nodes:
        if node["type"] == "n8n-nodes-base.scheduleTrigger":
            node["parameters"]["rule"]["interval"][0]["triggerAtMinute"] = 30
            node["parameters"]["rule"]["interval"][0]["triggerAtHour"] = 7


def sits_in(project: str, workflow_id: str) -> bool:
    """n8n's own list of the project's workflows, as its editor reads it. On the free edition a
    single workflow's read names no project."""
    wanted = urllib.parse.quote(json.dumps({"projectId": project}))
    listed: list[Json] = N8N_OWNER.call("GET", f"/workflows?filter={wanted}")
    return workflow_id in {str(workflow["id"]) for workflow in listed}


def becomes_approver(api: Api, person: str) -> None:
    asked = api.post("alice", f"/api/v1/people/{person}/approver", expect=(202,)).json()
    confirmation = asked["pending_approver"]["confirmation_id"]
    pending = api.get("bob", "/api/v1/confirmations")["confirmations"]
    [mine] = [c for c in pending if c["confirmation_id"] == confirmation]
    body = {"verdict": "confirm", "digest": mine["digest"]}
    api.post("bob", f"/api/v1/confirmations/{confirmation}/decisions", body, expect=(201,))


def test_n8n_access(api: Api, mock_model: None):
    email = f"dana-{secrets.token_hex(4)}@example.test"
    added = api.post(
        "alice",
        "/api/v1/people",
        {"email": email, "display": "Dana", "operator": True},
        expect=(201,),
    ).json()
    dana = added["id"]
    refused = api.request(
        "alice",
        "PUT",
        "/api/v1/people/bob/n8n-access",
        expect=(409,),
        json_body={"n8n_access": True},
    )
    assert refused.json()["refusal"] == "n8n_operators_only"
    created = set_up(api, "e2e n8n access", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    not_yet = api.post(dana, f"/api/v1/use-cases/{use_case_id}/open-in-n8n", expect=(403,))
    assert not_yet.json()["detail"].startswith("Only people with n8n access")

    api.request(
        "alice",
        "PUT",
        f"/api/v1/people/{dana}/n8n-access",
        expect=(200,),
        json_body={"n8n_access": True},
    )
    mine: Json = api.poll(
        "the platform to make Dana's n8n account",
        lambda: (m := api.get(dana, "/api/v1/me/n8n"))["set_password_url"] and m,
    )
    assert (mine["account"], mine["can_open"]) == ("invited", False)
    assert api.get("alice", "/api/v1/me/n8n")["set_password_url"] is None, "shown to Dana alone"
    member = Member("Dana", (email, mine["set_password_url"]))
    api.poll(
        "n8n to know Dana set her password", lambda: api.get(dana, "/api/v1/me/n8n")["can_open"]
    )
    assert api.get(dana, "/api/v1/me/n8n")["set_password_url"] is None, "used, so forgotten"

    laid_out = settings_in_n8n(workflow_id, "as the platform laid it out")
    platform = str(N8N_OWNER.call("GET", "/projects/personal")["id"])
    assert sits_in(platform, workflow_id)
    opened = api.post(dana, f"/api/v1/use-cases/{use_case_id}/open-in-n8n", expect=(200,)).json()
    assert opened["held_by"] == dana
    assert member.can_open(workflow_id), "Dana sees it, so it sits in her own n8n space"
    assert sits_in(member.project, workflow_id) and not sits_in(platform, workflow_id)
    assert settings_in_n8n(workflow_id, "once Dana holds it") == laid_out
    view = api.get(dana, f"/api/v1/use-cases/{use_case_id}/n8n")
    assert (view["holder"]["id"], view["can_open"]) == (dana, True)
    assert "Ask for a yes" in [node["name"] for node in view["nodes"]]
    schedule = {"day": "monday", "at": "07:30", "via": "page"}
    held = api.request(
        "alice",
        "PUT",
        f"/api/v1/use-cases/{use_case_id}/schedule",
        expect=(409,),
        json_body=schedule,
    )
    assert held.json()["detail"].startswith("Dana has it open in n8n since ")

    member.change_email(f"dana-elsewhere-{secrets.token_hex(4)}@example.test")
    member.publish(workflow_id, at_seven_thirty)
    swept_view = swept(api, use_case_id, 2)
    assert swept_view["grade"] == "safe", swept_view["findings"]
    newest = api.get("alice", f"/api/v1/use-cases/{use_case_id}/versions")["versions"][0]
    assert (newest["made"], newest["by"], newest["publisher_unknown"]) == (
        "published_in_n8n",
        dana,
        False,
    ), "matched by the n8n user id the platform stored, not by the email she changed"

    becomes_approver(api, dana)
    assert api.get(dana, "/api/v1/me")["n8n_access"] is False
    api.poll("the platform to take the workflow back", lambda: sits_in(platform, workflow_id))
    assert settings_in_n8n(workflow_id, "once taken back") == laid_out

    run_id, _ = api.start_run("carol", use_case_id)
    events = api.stream_until("carol", run_id, {"approval_requested"})
    approval_id = approval_requested(events)["approval_id"]
    approval = api.get("bob", f"/api/v1/approvals/{approval_id}")
    own = api.post(
        dana,
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": approval["digest"]},
        expect=(403,),
    ).json()
    assert own["refusal"] == "own_work", "Dana published the version this run uses"
    bob_decides(api, approval_id, "approve", approval["digest"])
    api.wait_for_state("carol", run_id, {"succeeded"})
    assert len(tickets_for(api, run_id)) == 1
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))
