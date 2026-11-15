"""n8n's allow list on the real n8n (ENGINE-PLAN E11, ADR 0045). n8n itself refuses a type
node_classes.json turns off: a workflow with an HTTP Request node can neither be published nor
run by hand, and nothing is sent (P6 Q5, kept as a test). A block n8n loads, set to do what the
file turns off, is published by a member and graded Needs a fix by the platform, so its run stops
at the first block and writes nothing."""

from harness import N8N_OWNER, Api, Json
from test_n8n_engine import set_up, ticket_count
from test_n8n_versions import Member, held_by, swept

OFF = ("n8n-nodes-base.httpRequest", "n8n-nodes-base.code", "n8n-nodes-base.webhook")

SENDS_IT_OUT: Json = {
    "name": "e2e allow list: sends data out",
    "nodes": [
        {
            "id": "allow-list-by-hand",
            "name": "Run by hand",
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [0, 0],
            "parameters": {},
        },
        {
            "id": "allow-list-out",
            "name": "Send it out",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [220, 0],
            "parameters": {"url": "http://mock-github:8200/allow-list-leak", "options": {}},
        },
    ],
    "connections": {
        "Run by hand": {"main": [[{"node": "Send it out", "type": "main", "index": 0}]]}
    },
    "settings": {"executionOrder": "v1"},
}


def by_sql(nodes: list[Json], connections: Json) -> None:
    """A Merge block, which n8n loads, set to its SQL mode, which the class file turns off."""
    nodes.append(
        {
            "id": "allow-list-merge",
            "name": "Join by SQL",
            "type": "n8n-nodes-base.merge",
            "typeVersion": 3.2,
            "position": [440, 600],
            "parameters": {"mode": "combineBySql"},
        }
    )


def test_allow_list(api: Api, mock_model: None):
    served = N8N_OWNER.send("GET", "/types/nodes.json")
    loaded = {t["name"] for t in served.raise_for_status().json()}
    assert "CUSTOM.wabAskForYes" in loaded and "n8n-nodes-base.merge" in loaded
    assert not set(OFF) & loaded, "n8n loads none of the types the class file turns off"

    saved = N8N_OWNER.call("POST", "/workflows", SENDS_IT_OUT)
    publish = N8N_OWNER.send(
        "POST", f"/rest/workflows/{saved['id']}/activate", {"versionId": saved["versionId"]}
    )
    assert publish.status_code == 400, publish.text
    assert "Unrecognized node type: n8n-nodes-base.httpRequest" in publish.text
    by_hand = N8N_OWNER.send(
        "POST",
        f"/rest/workflows/{saved['id']}/run",
        {"destinationNode": {"nodeName": "Send it out", "mode": "inclusive"}},
    )
    assert by_hand.status_code == 400, by_hand.text
    assert "Unrecognized node type: n8n-nodes-base.httpRequest" in by_hand.text
    assert N8N_OWNER.call("GET", f"/workflows/{saved['id']}").get("activeVersionId") is None

    created = set_up(api, "e2e allow list", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    member = Member("erin")
    held_by(api, member, workflow_id)
    member.publish(workflow_id, by_sql)
    view = swept(api, use_case_id, 2)
    assert view["grade"] == "needs_a_fix"
    assert view["findings"] == ['"Join by SQL" does something that is off: combineBySql.']

    tickets = ticket_count(api)
    run_id, started = api.start_run("carol", use_case_id)
    assert started.status_code == 201, started.text
    stopped = api.wait_for_state("carol", run_id, {"failed", "awaiting_approval", "succeeded"})
    assert stopped["state"] == "failed", stopped
    assert ticket_count(api) == tickets, "a version that fails the check writes nothing"
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))
