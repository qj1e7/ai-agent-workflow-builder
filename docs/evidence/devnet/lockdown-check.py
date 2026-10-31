"""Runs a Software watchlist check to Done on the locked stack, then tries to connect an AI model.

Runs inside platform-api, which reaches the API on localhost:
    docker compose ... exec -T platform-api python - < lockdown-check.py
"""

import json
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"


def call(user, method, path, body=None, headers=None):
    request = urllib.request.Request(
        BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"X-Dev-User": user, "Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read()
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def wait_for(run_id, states, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _, run = call("alice", "GET", f"/api/v1/runs/{run_id}")
        if run["state"] in states:
            return run
        time.sleep(1)
    raise SystemExit(f"the run did not reach {states} in {seconds} s; it is {run['state']}")


status, added = call(
    "alice", "POST", "/api/v1/watchlist/software",
    {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"},
)
print(f"alice adds LangGraph 1.2.14 to the Software watchlist -> {status}")
_, watchlist = call("alice", "GET", "/api/v1/watchlist")
use_case_id = watchlist["watchlist"]["use_case_id"]
status, _ = call("alice", "DELETE", "/api/v1/watchlist/schedule")
print(f"alice turns the schedule off, so only this check runs -> {status}")

status, started = call(
    "alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs",
    headers={"Idempotency-Key": str(uuid.uuid4())},
)
run_id = started["run_id"]
print(f"alice presses Check now -> {status}, run {run_id}")
began = time.monotonic()
run = wait_for(run_id, ("awaiting_approval", "succeeded", "failed"), 180)
print(f"the run is {run['state']} after {time.monotonic() - began:.0f} s")
if run["state"] != "awaiting_approval":
    raise SystemExit("the check did not reach the approval gate")

approval_id = run["approval"]["approval_id"]
_, approval = call("bob", "GET", f"/api/v1/approvals/{approval_id}")
for action in approval["actions"]:
    print(f"  proposed: {json.dumps(action)[:160]}")
status, decided = call(
    "bob", "POST", f"/api/v1/approvals/{approval_id}/decisions",
    {"step": 0, "verdict": "approve", "digest": approval["digest"]},
)
print(f"bob approves -> {status} {decided}")
run = wait_for(run_id, ("succeeded", "failed"), 120)
print(f"the run is {run['state']} after {time.monotonic() - began:.0f} s in all")

_, page = call("alice", "GET", f"/api/v1/runs/{run_id}/events?after=0", headers={"Accept": "application/json"})
print(f"its {len(page['events'])} activity events:")
for event in page["events"]:
    print(f"  {event['seq']:>2} {event['kind']}: {event['summary']}")
_, tickets = call("alice", "GET", "/api/v1/mock-jira/tickets")
for ticket in tickets["tickets"]:
    print(f"  practice Jira: {ticket['key']} {ticket['title']}")

status, connected = call(
    "alice", "POST", "/api/v1/settings/model/connect",
    {"provider_id": "aisg", "api_key": "lockdown-test-not-a-real-key"},
)
print(f"alice connects the AI Singapore gateway in Settings -> {status} {json.dumps(connected)[:400]}")
