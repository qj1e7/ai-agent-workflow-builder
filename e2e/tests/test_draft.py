"""A draft's test run goes through the real n8n run workflow, stops at the approval step and
writes nothing, then Turn it on publishes version 1 (ADR 0044)."""

import uuid

from harness import Api, Json, assert_gapless, tickets_for

PLANTED = {"GitHub repository": "acme/planted", "Jira project": "MOCK"}


def test_a_draft_s_test_run_stops_at_the_yes_and_turn_it_on_publishes_version_1(
    api: Api, mock_model: None
) -> None:
    body: Json = {
        "name": "e2e draft",
        "instruction": "Run the agent.",
        "agents": [{"card_id": "crd_version_checker", "values": PLANTED}],
        "schedule": {"day": "monday", "at": "09:00"},
        "on": False,
    }
    use_case_id = api.post("alice", "/api/v1/agent-use-cases", body, expect=(201,)).json()[
        "use_case_id"
    ]
    draft = api.get("alice", f"/api/v1/use-cases/{use_case_id}")
    assert (draft["state"], draft["next_run_at"]) == ("draft", None)
    runs = f"/api/v1/use-cases/{use_case_id}/runs"
    api.post("alice", runs, expect=(409,), headers={"Idempotency-Key": str(uuid.uuid4())})

    started = api.post(
        "alice", runs, {"test": True}, expect=(201,), headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    run_id = started.json()["run_id"]
    events = api.stream_until("alice", run_id, {"run_succeeded"})

    assert_gapless(events, run_id)
    kinds = [e["kind"] for e in events]
    assert "write_action_proposed" in kinds, "the agents found something to write"
    assert "approval_requested" not in kinds
    gate = [
        e["data"]["outcome"]
        for e in events
        if e["kind"] == "step_finished" and e["data"]["step"] == "ask_approval"
    ]
    assert gate == ["test_passed"], "n8n reached the approval step and it stopped there"
    final = api.wait_for_state("alice", run_id, {"succeeded"})
    assert (final["outcome"], final["written"]) == ("test_passed", [])
    assert tickets_for(api, run_id) == []

    turned_on = api.post("alice", f"/api/v1/use-cases/{use_case_id}/turn-on", expect=(200,))
    assert (turned_on.json()["state"], turned_on.json()["version"]) == ("on", 1)
    assert turned_on.json()["next_run_at"] is not None
    again = api.post("alice", f"/api/v1/use-cases/{use_case_id}/turn-on", expect=(200,))
    assert again.json() == turned_on.json()
    versions = api.get("bob", f"/api/v1/use-cases/{use_case_id}/versions")["versions"]
    assert [(v["version"], v["running"]) for v in versions] == [(1, True)]
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))
