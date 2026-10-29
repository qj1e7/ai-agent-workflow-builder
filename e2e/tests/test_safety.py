from harness import Api, approval_requested, bob_decides, tickets_for

STALE_DIGEST = "sha256:" + "0" * 64


def test_unknown_dev_user_gets_401(api: Api) -> None:
    api.request("mallory", "GET", "/api/v1/use-cases", expect=(401,))


def test_missing_dev_user_gets_401(api: Api) -> None:
    api.request(None, "GET", "/api/v1/use-cases", expect=(401,))


def test_stale_digest_is_refused_and_the_step_stays_open(api: Api) -> None:
    use_case_id = api.watch_langgraph("alice")
    run_id, _ = api.start_run("alice", use_case_id)
    events = api.stream_until("alice", run_id, {"approval_requested"})
    approval_id = approval_requested(events)["approval_id"]
    view = api.get("bob", f"/api/v1/approvals/{approval_id}")

    stale = api.post(
        "bob",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": STALE_DIGEST},
        expect=(403, 409, 422),
    )
    assert "decision" not in stale.json()

    after = api.get("bob", f"/api/v1/approvals/{approval_id}")
    assert after["steps"][0]["status"] == "open"
    assert api.run_view("alice", run_id)["state"] == "awaiting_approval"
    assert tickets_for(api, run_id) == []

    bob_decides(api, approval_id, "approve", view["digest"])
    api.wait_for_state("alice", run_id, {"succeeded"})
    assert len(tickets_for(api, run_id)) == 1
