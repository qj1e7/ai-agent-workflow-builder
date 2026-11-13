"""Set up off, a new workflow is saved in n8n as a draft of its own, and the safety checker graded
it safe with the yes in front of the write (ENGINE-PLAN 2.5, E4)."""

import os

import httpx
from harness import Api, Json

N8N_URL = os.environ.get("N8N_BASE_URL", "http://n8n:5678")
PLANTED = {"GitHub repository": "acme/planted", "Jira project": "MOCK"}
SKETCH_LOG = [
    "Adding blocks in n8n…",
    "The blocks fit together.",
    "Safety checker is checking the write…",
    "Added a yes before the ticket.",
    "Every write waits for a yes.",
    "Saved as a draft in n8n.",
]


def held_in_n8n(workflow_id: str) -> Json:
    """The draft as n8n holds it, read as its owner, the way the platform reads it."""
    login = {
        "emailOrLdapLoginId": os.environ["N8N_OWNER_EMAIL"],
        "password": os.environ["N8N_OWNER_PASSWORD"],
    }
    with httpx.Client(base_url=N8N_URL, timeout=30) as n8n:
        n8n.post("/rest/login", json=login).raise_for_status()
        answer = n8n.get(f"/rest/workflows/{workflow_id}")
        answer.raise_for_status()
        return answer.json()["data"]


def into(document: Json, target: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    connections: dict[str, Json] = document["connections"]
    for source, outputs in connections.items():
        exits: list[list[Json] | None] = outputs["main"]
        for index, targets in enumerate(exits):
            found.extend((source, index) for edge in targets or [] if edge["node"] == target)
    return found


def test_set_up_off_saves_a_draft_in_n8n_that_the_safety_checker_graded_safe(api: Api) -> None:
    body: Json = {
        "name": "e2e release check in n8n",
        "instruction": "Check acme/planted for new releases.",
        "agents": [{"card_id": "crd_version_checker", "values": PLANTED}],
        "schedule": {"day": "every_day", "at": "08:00"},
        "on": False,
    }
    created = api.post("alice", "/api/v1/agent-use-cases", body, expect=(201,)).json()
    assert created["grade"] == "safe"
    assert [line["text"] for line in created["build_log"]] == SKETCH_LOG

    held = held_in_n8n(created["n8n_workflow_id"])
    assert held["activeVersionId"] is None, "the draft is saved, not published"
    types = {node["name"]: node["type"] for node in held["nodes"]}
    assert types["Ask for a yes"] == "CUSTOM.wabAskForYes"
    assert types["Create ticket"] == "CUSTOM.wabMakeApprovedChanges"
    assert into(held, "Create ticket") == [("Ask for a yes", 1)], "only the Yes exit writes"
    assert held["settings"]["timezone"] == "Asia/Singapore"
    assert held["settings"]["saveExecutionProgress"] is True

    view = api.get("alice", f"/api/v1/use-cases/{created['use_case_id']}")
    assert view["state"] == "draft"
    assert [b["name"] for b in view["blocks"]] == [b["name"] for b in created["blocks"]]
    api.delete("alice", f"/api/v1/use-cases/{created['use_case_id']}", expect=(200,))
