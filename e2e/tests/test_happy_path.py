from harness import (
    EXPECTED_TITLE,
    Api,
    approval_requested,
    assert_gapless,
    bob_decides,
    fixture_kinds,
    tickets_for,
)


def test_a_watchlist_check_runs_through_approval_to_one_ticket(api: Api) -> None:
    use_case_id = api.watch_langgraph("alice")
    key = "e2e-happy-key-0001"
    run_id, first = api.start_run("alice", use_case_id, key)
    again_id, _ = api.start_run("alice", use_case_id, key)
    assert again_id == run_id, "the same Idempotency-Key must return the same run"
    assert first.json()["state"] == "pending"
    assert first.json()["events_url"] == f"/api/v1/runs/{run_id}/events"

    events = api.stream_until("alice", run_id, {"approval_requested"})
    assert_gapless(events, run_id)
    requested = approval_requested(events)
    approval_id = requested["approval_id"]

    message = api.poll(
        "the Teams stub message for this run",
        lambda: next(
            (
                m
                for m in api.get("alice", "/api/v1/teams-stub/messages")["messages"]
                if m["run_id"] == run_id
            ),
            None,
        ),
    )
    assert message["approval_id"] == approval_id
    assert approval_id in message["link"]
    assert EXPECTED_TITLE in message["text"]

    alice_view = api.get("alice", f"/api/v1/approvals/{approval_id}")
    assert alice_view["you_can_decide"] is False
    assert alice_view["why_not"] == "own_work"

    refused = api.post(
        "alice",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": alice_view["digest"]},
        expect=(403,),
    ).json()
    assert refused["refusal"] == "own_work"
    assert refused["message"]
    assert api.run_view("alice", run_id)["state"] == "awaiting_approval"

    bob_view = api.get("bob", f"/api/v1/approvals/{approval_id}")
    assert bob_view["you_can_decide"] is True
    assert bob_view["why_not"] is None
    assert bob_view["digest"] == alice_view["digest"]
    assert [(a["connector"], a["operation"]) for a in bob_view["actions"]] == [
        ("jira", "create_ticket")
    ]
    assert bob_view["actions"][0]["fields"]["title"] == EXPECTED_TITLE

    decided = bob_decides(api, approval_id, "approve", bob_view["digest"]).json()
    assert decided["status"] == "approved"
    assert decided["decision"]["by"] == "bob"
    repeat = api.post(
        "bob",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": bob_view["digest"]},
        expect=(200,),
    ).json()
    assert repeat == decided

    final = api.wait_for_state("alice", run_id, {"succeeded"})
    assert final["outcome"] == "written"
    assert [w["approved_by"] for w in final["written"]] == [["bob"]]

    tickets = tickets_for(api, run_id)
    assert [t["title"] for t in tickets] == [EXPECTED_TITLE]
    assert tickets[0]["project"] == "MOCK"
    assert final["written"][0]["external_reference"] == tickets[0]["key"]

    all_events = api.events_after("alice", run_id)
    assert_gapless(all_events, run_id)
    assert [e["kind"] for e in all_events] == fixture_kinds("success")

    cut = 10
    replayed = api.stream_until("alice", run_id, {"run_succeeded"}, last_event_id=cut)
    assert [e["seq"] for e in replayed] == [e["seq"] for e in all_events if e["seq"] > cut]
    assert [e["kind"] for e in replayed] == [e["kind"] for e in all_events if e["seq"] > cut]
