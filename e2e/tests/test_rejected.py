from harness import Api, approval_requested, assert_gapless, assert_story, bob_decides, tickets_for


def test_declined_run_ends_rejected_and_writes_nothing(api: Api) -> None:
    before = len(api.tickets())
    use_case_id = api.watch_langgraph("alice")
    run_id, _ = api.start_run("alice", use_case_id)
    events = api.stream_until("alice", run_id, {"approval_requested"})
    approval_id = approval_requested(events)["approval_id"]
    digest = api.get("bob", f"/api/v1/approvals/{approval_id}")["digest"]

    decided = bob_decides(api, approval_id, "decline", digest).json()
    assert decided["status"] == "declined"
    assert decided["decision"]["verdict"] == "decline"

    final = api.wait_for_state("alice", run_id, {"rejected"})
    assert final["state"] == "rejected"
    assert tickets_for(api, run_id) == []
    assert len(api.tickets()) == before, "a declined run must not create any ticket"

    all_events = api.events_after("alice", run_id)
    assert_gapless(all_events, run_id)
    assert_story(
        all_events,
        [
            "run_created",
            "execution_linked",
            "write_action_proposed",
            "approval_requested",
            "approval_decided",
            "run_rejected",
        ],
    )
