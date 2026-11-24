"""Drives the simulation gateway through the simulation n8n (ADR 0054, PR 3), as a simulation will.

scripts/simulation.sh drive runs it inside the gateway's own container, which holds the
simulation's made-up keys, so no key leaves the stack and none is printed. Python's standard
library only.

It lays out one workflow of our blocks in the simulation n8n, then runs it by hand once for each
of four scenarios, with the start item the gateway issued. For each it checks n8n's own record of
the execution and the gateway's record of the simulated run:

- the Approver says yes: the write is refused with "A simulation never writes.", and the gateway
  kept the change it would have made;
- the Approver says no: the run leaves by No, and nothing would have been written;
- the source is not found: Read fails after its tries, and the gateway kept why;
- nothing is new: the run ends at Read.

It also checks that a start signed with another secret, a record read without a signature and a
node call without the node key are each refused with 401.

usage: docker exec -i <gateway container> python -I - < scripts/simulation_drive.py
Exits 0 when every check passes, and 1 when one fails.
"""

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

N8N = os.environ.get("N8N_BASE_URL", "http://n8n:5678").rstrip("/")
GATEWAY = "http://127.0.0.1:8600"
START = "Start from the Portal"
RETRY = {"retryOnFail": True, "maxTries": 2, "waitBetweenTries": 1000}
RELEASE = {"kind": "release", "id": "1.2.16", "name": "1.2.16", "published_at": "2026-10-28"}
REPLY = {"serve": "recorded", "items": [{"summary": "1.2.16 is new."}]}
SCOPES = ["workflow:create", "workflow:read", "workflow:delete", "execution:read"]

failures: list[str] = []
cookie = ""
api_key = ""


def check(ok: bool, what: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {what}", flush=True)
    if not ok:
        failures.append(what)


def http(
    method: str, url: str, body: bytes | None = None, headers: dict[str, str] | None = None
) -> tuple[int, Any, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            raw, status, got = answer.read(), answer.status, answer.headers
    except urllib.error.HTTPError as error:
        raw, status, got = error.read(), error.code, error.headers
    try:
        return status, json.loads(raw) if raw else None, got
    except ValueError:
        return status, raw.decode(errors="replace")[:200], got


def as_json(value: Any) -> bytes:
    return json.dumps(value).encode()


def signed(method: str, path: str, body: bytes, secret: str) -> dict[str, str]:
    """As platform_api.orchestration.simulation_gateway.control_signature."""
    expires = int(time.time()) + 120
    message = f"{method}\n{path}\n{expires}\n".encode() + body
    mac = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {"X-Wab-Expires": str(expires), "X-Wab-Signature": mac}


def gateway(
    method: str, path: str, value: Any = None, secret: str | None = None
) -> tuple[int, Any]:
    body = b"" if value is None else as_json(value)
    key = os.environ["WAB_START_SECRET"] if secret is None else secret
    status, answer, _ = http(
        method, f"{GATEWAY}{path}", body or None, signed(method, path, body, key)
    )
    return status, answer


def rest(method: str, path: str, value: Any = None) -> tuple[int, Any]:
    body = None if value is None else as_json(value)
    status, answer, _ = http(method, f"{N8N}/rest{path}", body, {"Cookie": cookie})
    return status, answer


def public(method: str, path: str, value: Any = None) -> tuple[int, Any]:
    body = None if value is None else as_json(value)
    status, answer, _ = http(method, f"{N8N}/api/v1{path}", body, {"X-N8N-API-KEY": api_key})
    return status, answer


def sign_in() -> None:
    global cookie, api_key
    login = {
        "emailOrLdapLoginId": os.environ["N8N_OWNER_EMAIL"],
        "password": os.environ["N8N_OWNER_PASSWORD"],
    }
    status, _, headers = http("POST", f"{N8N}/rest/login", as_json(login))
    if status != 200:
        raise SystemExit(f"FAIL: the simulation n8n's owner could not sign in ({status})")
    cookie = headers.get("Set-Cookie", "").split(";")[0]
    key = {"label": "simulation-drive", "expiresAt": int(time.time()) + 3600, "scopes": SCOPES}
    status, made = rest("POST", "/api-keys", key)
    if status != 200:
        raise SystemExit(f"FAIL: the simulation n8n made no API key ({status})")
    api_key = made["data"]["rawApiKey"]


def node(name: str, kind: str, x: int, params: dict[str, Any] | None = None, **extra: Any) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": kind,
        "typeVersion": 1,
        "position": [x * 220, 0],
        "parameters": params or {},
        **extra,
    }


def to(target: str) -> dict[str, Any]:
    return {"main": [[{"node": target, "type": "main", "index": 0}]]}


def lay_out() -> str:
    """A release check as the Planner lays one out: Read, Agent, Propose a change, Ask for a yes,
    then Make the approved changes and Tell on Yes, and an end on each other exit."""
    read = {"source": "github_releases", "place": "langchain-ai/langgraph"}
    inputs = {"input": [{"name": "release", "value": "={{ $json.id }}"}]}
    propose = {
        "action": "jira.create_ticket",
        "place": "MOCK",
        "title": "Upgrade LangGraph",
        "body": "A new release is out.",
        "subject": "langgraph",
    }
    nodes = [
        node(START, "CUSTOM.wabStartFromPortal", 0, webhookId=str(uuid.uuid4())),
        node("Read releases", "CUSTOM.wabRead", 1, read, **RETRY),
        node(
            "Compare", "CUSTOM.wabAgent", 2, {"agent": "release_checker", "inputs": inputs}, **RETRY
        ),
        node("Propose a change", "CUSTOM.wabProposeChange", 3, propose, **RETRY),
        node("Ask for a yes", "CUSTOM.wabAskForYes", 4, webhookId=str(uuid.uuid4())),
        node("Make the approved changes", "CUSTOM.wabMakeApprovedChanges", 5, **RETRY),
        node("Tell", "CUSTOM.wabTell", 6, {"where": "channel", "what": "result"}, **RETRY),
        node("No answer", "n8n-nodes-base.noOp", 5),
        node("Declined", "n8n-nodes-base.noOp", 5),
        node("Nothing to change", "n8n-nodes-base.noOp", 5),
    ]
    exits = ["No answer", "Make the approved changes", "Declined", "Nothing to change"]
    edges = {
        START: to("Read releases"),
        "Read releases": to("Compare"),
        "Compare": to("Propose a change"),
        "Propose a change": to("Ask for a yes"),
        "Ask for a yes": {"main": [[{"node": e, "type": "main", "index": 0}] for e in exits]},
        "Make the approved changes": to("Tell"),
    }
    settings = {"saveManualExecutions": True, "saveExecutionProgress": True, "executionOrder": "v1"}
    document = {
        "name": "Simulation gateway check",
        "nodes": nodes,
        "connections": edges,
        "settings": settings,
    }
    status, made = public("POST", "/workflows", document)
    if status != 200:
        raise SystemExit(f"FAIL: the simulation n8n did not take the workflow ({status}): {made}")
    return str(made["id"])


def simulate(workflow: str, scenario: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """One scenario, as a simulation runs it: a start from the gateway, then n8n's run by hand."""
    status, started = gateway(
        "POST", "/simulation/v1/starts", {"workflow_id": workflow, "scenario": scenario}
    )
    if status != 201:
        raise SystemExit(f"FAIL: the gateway did not take a signed start ({status}): {started}")
    run = {
        "triggerToStartFrom": {
            "name": START,
            "data": {
                "startTime": 0,
                "executionTime": 0,
                "source": [],
                "data": {"main": [[{"json": started["item"]}]]},
            },
        }
    }
    status, answer = rest("POST", f"/workflows/{workflow}/run", run)
    if status != 200:
        raise SystemExit(f"FAIL: n8n did not run the workflow by hand ({status}): {answer}")
    execution = str(answer["data"]["executionId"])
    deadline = time.time() + 120
    record: dict[str, Any] = {}
    while time.time() < deadline:
        status, record = public("GET", f"/executions/{execution}?includeData=true")
        if status == 200 and record.get("status") in ("success", "error", "crashed", "canceled"):
            break
        time.sleep(0.5)
    else:
        raise SystemExit(f"FAIL: execution {execution} did not end in 120 s")
    status, kept = gateway("GET", f"/simulation/v1/runs/{started['nonce']}")
    if status != 200:
        raise SystemExit(f"FAIL: the gateway did not show the simulated run ({status})")
    return record, kept


def ran(record: dict[str, Any]) -> set[str]:
    return set(((record.get("data") or {}).get("resultData") or {}).get("runData") or {})


def error(record: dict[str, Any]) -> str:
    found = ((record.get("data") or {}).get("resultData") or {}).get("error") or {}
    return str(found.get("message") or "")


def first_calls(kept: dict[str, Any]) -> list[dict[str, Any]]:
    return [call for call in kept["calls"] if not call["replayed"]]


def main() -> int:
    other = secrets.token_hex(24)
    status, _ = gateway(
        "POST", "/simulation/v1/starts", {"workflow_id": "x", "scenario": {"name": "x"}}, other
    )
    check(status == 401, f"a start signed with another secret is refused with 401 ({status})")
    status, _, _ = http("GET", f"{GATEWAY}/simulation/v1/runs/sim_x")
    check(status == 401, f"a record read without a signature is refused with 401 ({status})")
    status, _, _ = http("POST", f"{GATEWAY}/internal/v1/n8n/calls/read", b"{}")
    check(status == 401, f"a node call without the node key is refused with 401 ({status})")

    sign_in()
    workflow = lay_out()

    record, kept = simulate(
        workflow,
        {
            "name": "approver_says_yes",
            "blocks": {"Read releases": {"serve": "mock"}, "Compare": REPLY},
            "approver": "yes",
        },
    )
    calls = first_calls(kept)
    check(
        record.get("status") == "error" and "A simulation never writes." in error(record),
        f"yes: the write is refused in the gateway's words ({error(record)})",
    )
    check(
        kept["execution_id"] == str(record["id"]) and kept["mode"] == "manual",
        f"yes: every call links to the run by hand ({kept['execution_id']}, {kept['mode']})",
    )
    check(
        [c["kind"] for c in calls] == ["read", "agent", "propose", "ask", "write"],
        f"yes: the gateway kept each block's call in order ({[c['kind'] for c in calls]})",
    )
    check(
        (calls[0]["items"] or 0) >= 1, f"yes: Read got mock GitHub's releases ({calls[0]['items']})"
    )
    check(
        kept["approver"] == "yes" and kept["woke"] == "delivered",
        f"yes: Ask for a yes got yes and n8n woke ({kept['approver']}, {kept['woke']})",
    )
    written = [c["title"] for c in kept["would_have_written"] or []]
    check(
        written == ["Upgrade LangGraph"],
        f"yes: the gateway kept what it would have written ({written})",
    )
    check("Tell" not in ran(record), "yes: nothing after the refused write ran")

    one = {"serve": "recorded", "items": [RELEASE]}
    record, kept = simulate(
        workflow,
        {
            "name": "approver_says_no",
            "blocks": {"Read releases": one, "Compare": REPLY},
            "approver": "no",
        },
    )
    check(
        record.get("status") == "success" and "Declined" in ran(record),
        f"no: the run left by No ({record.get('status')}, {sorted(ran(record))})",
    )
    check("Make the approved changes" not in ran(record), "no: the write never ran")
    check(
        kept["approver"] == "no"
        and kept["woke"] == "delivered"
        and kept["would_have_written"] is None,
        f"no: the gateway kept the no and nothing written ({kept['approver']}, {kept['woke']})",
    )

    record, kept = simulate(
        workflow, {"name": "source_not_found", "blocks": {"Read releases": {"serve": "not_found"}}}
    )
    reads = [(c["outcome"], c["detail"]) for c in kept["calls"]]
    check(
        record.get("status") == "error" and "Compare" not in ran(record),
        f"not found: Read failed and nothing after it ran ({error(record)})",
    )
    check(
        reads == [("try_again", "The place was not found at the source.")] * RETRY["maxTries"],
        f"not found: the gateway kept each try and why ({reads})",
    )

    empty = {"serve": "recorded", "items": []}
    record, kept = simulate(workflow, {"name": "nothing_new", "blocks": {"Read releases": empty}})
    check(
        record.get("status") == "success" and "Compare" not in ran(record),
        f"nothing new: the run ended at Read ({record.get('status')}, {sorted(ran(record))})",
    )
    check(
        [(c["kind"], c["items"]) for c in kept["calls"]] == [("read", 0)],
        "nothing new: the gateway kept one Read with nothing in it",
    )

    public("DELETE", f"/workflows/{workflow}")
    if failures:
        print(f"FAIL: {len(failures)} check(s) of the simulation gateway failed.")
        return 1
    print("PASS: the simulation gateway answered our blocks as each scenario says.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
