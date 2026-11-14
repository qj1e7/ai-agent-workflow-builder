"""The chat-first sketch's flow on the new engine, each workflow its own n8n workflow (ENGINE-PLAN
E5): set up off, a test run that writes nothing, Turn it on, Run now, Bob's yes and one ticket, and
a retry after GitHub was down that picks up at Read. Then the safety tests of ENGINE-PLAN 4.1 that
need a running n8n."""

import os
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import psycopg
import pytest
from harness import (
    DATABASE_URL,
    Api,
    Json,
    MockGithub,
    approval_requested,
    bob_decides,
    fail,
    tickets_for,
)

N8N_URL = os.environ.get("N8N_BASE_URL", "http://n8n:5678")
LANGGRAPH = {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}
SINGAPORE = ZoneInfo("Asia/Singapore")
SCHEDULE_WAIT_SECONDS = 240


def set_up(api: Api, name: str, *, on: bool, at: str = "09:00") -> Json:
    body: Json = {
        "name": name,
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": "crd_version_checker", "values": LANGGRAPH}],
        "schedule": {"day": "every_day", "at": at},
        "on": on,
    }
    return api.post("carol", "/api/v1/agent-use-cases", body, expect=(201,)).json()


def owner() -> httpx.Client:
    """n8n as its owner signs in, the way the platform reads it."""
    login = {
        "emailOrLdapLoginId": os.environ["N8N_OWNER_EMAIL"],
        "password": os.environ["N8N_OWNER_PASSWORD"],
    }
    n8n = httpx.Client(base_url=N8N_URL, timeout=30)
    n8n.post("/rest/login", json=login).raise_for_status()
    return n8n


def in_n8n(workflow_id: str) -> Json:
    with owner() as n8n:
        answer = n8n.get(f"/rest/workflows/{workflow_id}")
        answer.raise_for_status()
        return answer.json()["data"]


def publication(workflow_id: str) -> Json:
    with owner() as n8n:
        answer = n8n.get(f"/rest/workflows/{workflow_id}/publication-status")
        answer.raise_for_status()
        return answer.json()["data"]


def linked_modes(events: list[Json]) -> list[str]:
    return [e["data"]["mode"] for e in events if e["kind"] == "execution_linked"]


def tidy(api: Api, use_case_id: str) -> None:
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))


@pytest.fixture
def langgraph(github: MockGithub) -> Iterator[MockGithub]:
    github.set_mode("ok")
    yield github
    github.set_mode("ok")


def test_the_sketch_flow_runs_on_the_workflow_s_own_n8n_workflow(api: Api, mock_model: None):
    created = set_up(api, "e2e engine sketch", on=False)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    runs = f"/api/v1/use-cases/{use_case_id}/runs"

    test_run = api.post(
        "carol",
        runs,
        {"test": True},
        expect=(201,),
        headers={"Idempotency-Key": f"e2e-test-{use_case_id}"},
    )
    test_id = test_run.json()["run_id"]
    events = api.stream_until("carol", test_id, {"run_succeeded"})
    kinds = [e["kind"] for e in events]
    assert linked_modes(events) == ["manual"], "the draft ran by hand in n8n"
    assert "write_action_proposed" in kinds and "approval_requested" not in kinds
    finished = api.wait_for_state("carol", test_id, {"succeeded"})
    assert (finished["outcome"], finished["written"]) == ("test_passed", [])
    assert tickets_for(api, test_id) == [], "a test run writes nothing"
    assert in_n8n(workflow_id)["activeVersionId"] is None, "a test run publishes nothing"

    turned_on = api.post("alice", f"/api/v1/use-cases/{use_case_id}/turn-on", expect=(200,))
    view = turned_on.json()
    status = publication(workflow_id)
    assert view["state"] == "on"
    assert status["status"] == "published", "On only once n8n has published it"
    assert status["triggers"] and all(t["status"] == "activated" for t in status["triggers"])
    assert status["liveVersionId"] == in_n8n(workflow_id)["activeVersionId"]
    at = datetime.fromisoformat(view["next_run_at"]).astimezone(SINGAPORE)
    assert (at.hour, at.minute) == (9, 0), "shown to the minute, as the sketch does"

    run_id, started = api.start_run("carol", use_case_id)
    assert started.status_code == 201
    events = api.stream_until("carol", run_id, {"approval_requested"})
    assert linked_modes(events) == ["webhook"], "Run now arrives through the signed trigger"
    approval_id = approval_requested(events)["approval_id"]
    approval = api.get("bob", f"/api/v1/approvals/{approval_id}")
    bob_decides(api, approval_id, "approve", approval["digest"])
    done = api.wait_for_state("carol", run_id, {"succeeded"})
    assert done["outcome"] == "written"
    assert len(tickets_for(api, run_id)) == 1, "exactly one ticket"
    tidy(api, use_case_id)


def test_a_retry_after_github_was_down_picks_up_at_read(
    api: Api, mock_model: None, langgraph: MockGithub
):
    created = set_up(api, "e2e engine retry", on=True)
    use_case_id = created["use_case_id"]
    langgraph.set_mode("unavailable")
    run_id, _ = api.start_run("carol", use_case_id)
    stopped = api.wait_for_state("carol", run_id, {"failed", "awaiting_approval"})
    assert stopped["state"] == "failed", "a check that read nothing never asks for a yes"
    assert (stopped["reason"], stopped["retryable"]) == ("WorkflowNodeError", True)
    assert '"Read release" failed in n8n' in stopped["message"]
    before = api.events_after("carol", run_id)

    langgraph.set_mode("ok")
    api.post("carol", f"/api/v1/runs/{run_id}/retry", expect=(202,))
    events = api.stream_until(
        "carol", run_id, {"approval_requested"}, last_event_id=before[-1]["seq"]
    )
    assert linked_modes(events) == ["retry"], "n8n's own retry carries the run on"
    approval_id = approval_requested(events)["approval_id"]
    approval = api.get("bob", f"/api/v1/approvals/{approval_id}")
    bob_decides(api, approval_id, "approve", approval["digest"])
    api.wait_for_state("carol", run_id, {"succeeded"})
    assert len(tickets_for(api, run_id)) == 1
    tidy(api, use_case_id)


def test_resume_url_alone_writes_nothing(api: Api, mock_model: None):
    """P6 case B made permanent: a wake that is not ours resumes nothing and writes nothing, and
    the real yes still lands once."""
    use_case_id = set_up(api, "e2e engine resume", on=True)["use_case_id"]
    run_id, _ = api.start_run("carol", use_case_id)
    events = api.stream_until("carol", run_id, {"approval_requested"})
    [execution] = [e["data"]["execution_id"] for e in events if e["kind"] == "execution_linked"]
    approval_id = approval_requested(events)["approval_id"]
    forged = {
        "execution_id": execution,
        "request_id": approval_id,
        "decision": "yes",
        "mac": "0" * 64,
    }
    with httpx.Client(base_url=N8N_URL, timeout=30) as n8n:
        answer = n8n.post(f"/webhook-waiting/{execution}", json=forged)
    assert answer.status_code in (401, 403), answer.text
    time.sleep(3)
    assert api.run_view("carol", run_id)["state"] == "awaiting_approval"
    assert tickets_for(api, run_id) == []

    approval = api.get("bob", f"/api/v1/approvals/{approval_id}")
    bob_decides(api, approval_id, "approve", approval["digest"])
    api.wait_for_state("carol", run_id, {"succeeded"})
    assert len(tickets_for(api, run_id)) == 1, "the real yes lands, once"
    tidy(api, use_case_id)


def test_gate_removed(api: Api, mock_model: None):
    """Someone deletes Ask for a yes in n8n and publishes. A run of that version writes nothing:
    our records never graded it, so it stops at its first call, and the gateway would refuse a
    write with no yes anyway (ENGINE-PLAN 2.3.11)."""
    created = set_up(api, "e2e engine gate removed", on=True)
    use_case_id, workflow_id = created["use_case_id"], created["n8n_workflow_id"]
    with owner() as n8n:
        held = n8n.get(f"/rest/workflows/{workflow_id}").json()["data"]
        nodes = [node for node in held["nodes"] if node["name"] != "Ask for a yes"]
        connections = {k: v for k, v in held["connections"].items() if k != "Ask for a yes"}
        connections["Newer?"]["main"][0] = [{"node": "Create ticket", "type": "main", "index": 0}]
        body = {"nodes": nodes, "connections": connections, "versionId": held["versionId"]}
        saved = n8n.patch(f"/rest/workflows/{workflow_id}", json=body)
        saved.raise_for_status()
        draft = saved.json()["data"]
        published = n8n.post(
            f"/rest/workflows/{workflow_id}/activate",
            json={"versionId": draft["versionId"], "expectedChecksum": draft["checksum"]},
        )
        published.raise_for_status()
    api.poll(
        "n8n to publish the version without the yes",
        lambda: publication(workflow_id)["status"] == "published",
    )

    run_id, _ = api.start_run("carol", use_case_id)
    stopped = api.wait_for_state("carol", run_id, {"failed", "succeeded"})
    assert (stopped["state"], stopped["reason"]) == ("failed", "SafetyDenied")
    assert tickets_for(api, run_id) == []
    tidy(api, use_case_id)


def test_publisher_cannot_approve(api: Api, mock_model: None):
    """Carol sets it up and Alice turns it on, so Alice published it. Its schedule fires in n8n,
    and the run is Alice's work: she can never approve it, and Bob can."""
    soon = (datetime.now(SINGAPORE) + timedelta(minutes=2)).strftime("%H:%M")
    created = set_up(api, "e2e engine publisher", on=False, at=soon)
    use_case_id = created["use_case_id"]
    api.post("alice", f"/api/v1/use-cases/{use_case_id}/turn-on", expect=(200,))

    deadline = time.monotonic() + SCHEDULE_WAIT_SECONDS
    run: Json | None = None
    while run is None and time.monotonic() < deadline:
        listed = api.get("alice", "/api/v1/runs")["runs"]
        ours = [r for r in listed if r["use_case_name"] == "e2e engine publisher"]
        run = ours[0] if ours else None
        time.sleep(2)
    if run is None:
        fail(f"n8n's Schedule Trigger did not fire at {soon} within {SCHEDULE_WAIT_SECONDS}s")
    run_id = run["run_id"]
    assert (run["started_by"], run["trigger"]) == ("alice", "schedule")
    events = api.stream_until("alice", run_id, {"approval_requested"})
    assert linked_modes(events) == ["trigger"]
    approval_id = approval_requested(events)["approval_id"]
    view = api.get("alice", f"/api/v1/approvals/{approval_id}")
    refused = api.post(
        "alice",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": view["digest"]},
        expect=(403,),
    ).json()
    assert refused["refusal"] == "own_work"
    bob_decides(api, approval_id, "decline", view["digest"])
    api.wait_for_state("alice", run_id, {"rejected"})
    assert tickets_for(api, run_id) == []
    tidy(api, use_case_id)


def test_expiry_wakes_no_answer(api: Api, mock_model: None):
    """ADR 0024: a request nobody answers expires and never approves itself. No API call can move
    a request's clock, so this brings its expiry forward in the database, as seed_tickets
    writes rows no API can."""
    if not DATABASE_URL:
        fail("E2E_DATABASE_URL is not set, so the request's clock cannot be moved.")
    use_case_id = set_up(api, "e2e engine expiry", on=True)["use_case_id"]
    run_id, _ = api.start_run("carol", use_case_id)
    events = api.stream_until("carol", run_id, {"approval_requested"})
    approval_id = approval_requested(events)["approval_id"]
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "UPDATE orchestration.approval_requests SET expires_at = now() - interval '1 second'"
            " WHERE approval_id = %s",
            (approval_id,),
        )
    expired = api.wait_for_state("carol", run_id, {"expired"})
    assert expired["state"] == "expired"
    wakes = api.poll(
        "the wake that tells n8n there was no answer",
        lambda: [e for e in api.events_after("carol", run_id) if e["kind"] == "run_expired"],
    )
    assert wakes
    assert tickets_for(api, run_id) == [], "No answer. Nothing was written."
    tidy(api, use_case_id)
