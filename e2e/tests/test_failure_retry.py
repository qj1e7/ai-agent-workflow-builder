from harness import (
    EXPECTED_TITLE,
    Api,
    MockGithub,
    approval_requested,
    assert_gapless,
    bob_decides,
    tickets_for,
)


def test_github_outage_fails_the_run_and_a_retry_after_recovery_succeeds(
    api: Api, github: MockGithub
) -> None:
    github.set_mode("unavailable")
    use_case_id = api.create_use_case("alice", "failure")
    run_id, _ = api.start_run("alice", use_case_id)

    failed = api.wait_for_state("alice", run_id, {"failed"})
    assert failed["reason"] == "AgentError"
    assert failed["retryable"] is True
    assert failed["stage"] == "working"
    assert tickets_for(api, run_id) == []

    advice = api.get("alice", f"/api/v1/runs/{run_id}/troubleshoot")
    assert advice["run_id"] == run_id
    assert advice["failure"]["reason"] == "AgentError"
    assert advice["advice"]["suggested_action"] == "retry"
    assert advice["advice"]["suggestion"]

    failed_events = api.events_after("alice", run_id)
    assert_gapless(failed_events, run_id)
    kinds = [e["kind"] for e in failed_events]
    assert "agent_failed" in kinds
    assert kinds[-1] == "run_failed"
    last_seq = failed_events[-1]["seq"]

    github.set_mode("ok")
    retried = api.post("alice", f"/api/v1/runs/{run_id}/retry", expect=(202,)).json()
    assert retried["state"] == "pending"

    events = api.stream_until("alice", run_id, {"approval_requested"}, last_event_id=last_seq)
    assert events[0]["seq"] == last_seq + 1
    assert events[0]["kind"] == "run_retried"
    approval_id = approval_requested(events)["approval_id"]
    digest = api.get("bob", f"/api/v1/approvals/{approval_id}")["digest"]
    bob_decides(api, approval_id, "approve", digest)

    final = api.wait_for_state("alice", run_id, {"succeeded"})
    assert final["outcome"] == "written"
    tickets = tickets_for(api, run_id)
    assert [t["title"] for t in tickets] == [EXPECTED_TITLE]
    assert_gapless(api.events_after("alice", run_id), run_id)
