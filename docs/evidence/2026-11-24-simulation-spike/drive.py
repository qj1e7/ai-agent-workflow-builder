"""Drives the simulation spike from inside the simspike network (ADR 0054, S1 to S5 and S7).

It signs in to the simulation n8n as the owner bootstrap made, makes an API key for itself and
for the gateway stand-in, makes only mock credentials, lays out small workflows, runs them by hand
or from a signed start, and writes what it saw to /out/results.json. It prints no key and writes
none: the keys are made at run time by run.sh and stay in the containers' environment.
"""

import datetime
import hashlib
import hmac
import json
import os
import secrets
import time
import traceback
import urllib.error
import urllib.request
import uuid
from typing import Any

N8N = "http://n8n:5678"
GATEWAY = "http://gateway:8600"
UPSTREAM = "http://gateway:8700"
MOCK_GITHUB = "http://mock-github:8200"
MOCK_SLACK = "http://mock-slack:8500"
OWNER = "owner@sim.example"
START = "Start from the Portal"
ONLY = {s for s in os.environ.get("SIM_ONLY", "").split(",") if s}
SCOPES = [
    "workflow:create", "workflow:read", "workflow:update", "workflow:delete", "workflow:list",
    "workflow:activate", "workflow:deactivate", "execution:read", "execution:list",
    "credential:create", "credential:list", "credential:read", "credential:delete",
]  # fmt: skip
SETTINGS = {"saveManualExecutions": True, "saveExecutionProgress": True, "executionOrder": "v1"}
RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}
RELEASE = {"tag_name": "1.2.16", "name": "1.2.16", "published_at": "2026-10-28T09:00:00Z"}

results: dict[str, Any] = {"ran_at": datetime.datetime.now(datetime.UTC).isoformat()}
cookie = ""
api_key = ""


def say(message: str) -> None:
    print(f"drive: {message}", flush=True)


def http(method: str, url: str, body: Any = None, headers: dict[str, str] | None = None, timeout: float = 60):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            raw = answer.read()
            status, got = answer.status, answer.headers
    except urllib.error.HTTPError as error:
        raw, status, got = error.read(), error.code, error.headers
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = raw.decode(errors="replace")[:300]
    return status, parsed, got


def rest(method: str, path: str, body: Any = None):
    return http(method, f"{N8N}/rest{path}", body, {"Cookie": cookie})


def public(method: str, path: str, body: Any = None):
    return http(method, f"{N8N}/api/v1{path}", body, {"X-N8N-API-KEY": api_key})


def wait_for(what: str, check, timeout: float = 120, every: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = check()
        if got:
            return got
        time.sleep(every)
    raise TimeoutError(f"waited {timeout:g} s for {what}")


def sign_in() -> None:
    global cookie, api_key
    status, _, headers = http("POST", f"{N8N}/rest/login", {"emailOrLdapLoginId": OWNER, "password": os.environ["SIM_OWNER_LOGIN"]})
    assert status == 200, f"sign-in answered {status}"
    cookie = headers.get("Set-Cookie", "").split(";")[0]
    status, made, _ = rest("POST", "/api-keys", {"label": "simspike-driver", "expiresAt": None, "scopes": SCOPES})
    assert status == 200, f"api key answered {status}: {made}"
    api_key = made["data"]["rawApiKey"]
    http("POST", f"{GATEWAY}/_admin/n8n-key", {"key": api_key})


# ---- Layout helpers ----------------------------------------------------------------------------


def node(name: str, kind: str, params: dict[str, Any] | None = None, version: float = 1, x: int = 0, **extra: Any) -> dict[str, Any]:
    made = {"id": str(uuid.uuid4()), "name": name, "type": kind, "typeVersion": version, "position": [x * 220, 0], "parameters": params or {}}
    made.update(extra)
    return made


def start_node() -> dict[str, Any]:
    return node(START, "CUSTOM.wabStartFromPortal", webhookId=str(uuid.uuid4()))


def to(*targets: str) -> dict[str, Any]:
    return {"main": [[{"node": t, "type": "main", "index": 0} for t in targets]]}


def exits(no_answer: str | None, yes: str | None, no: str | None, nothing: str | None) -> dict[str, Any]:
    """Ask for a yes's four exits, in its order: No answer, Yes, No, Nothing to change."""
    return {"main": [[] if t is None else [{"node": t, "type": "main", "index": 0}] for t in (no_answer, yes, no, nothing)]}


def github(name: str, credential: dict[str, str], x: int, **extra: Any) -> dict[str, Any]:
    params = {"resource": "release", "operation": "getAll", "owner": "langchain-ai", "repository": "langgraph", "returnAll": False, "limit": 3}
    return node(name, "n8n-nodes-base.github", params, 1, x, credentials={"githubApi": credential}, **extra)


def our_chain(x0: int = 1) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read, Agent, Propose a change, Ask for a yes, then each exit, as a release check lays them."""
    nodes = [
        node("Read", "CUSTOM.wabRead", {"source": "github_releases", "place": "langchain-ai/langgraph"}, x=x0, **RETRY),
        node("Agent", "CUSTOM.wabAgent", {"agent": "release_checker", "inputs": {"input": [{"name": "release", "value": "={{ $json.tag_name }}"}]}}, x=x0 + 1, **RETRY),
        node("Propose a change", "CUSTOM.wabProposeChange", {"action": "create_ticket", "place": "MOCK", "title": "Upgrade", "body": "New release", "subject": "langgraph"}, x=x0 + 2, **RETRY),
        node("Ask for a yes", "CUSTOM.wabAskForYes", x=x0 + 3, webhookId=str(uuid.uuid4())),
        node("Make the approved changes", "CUSTOM.wabMakeApprovedChanges", x=x0 + 4, **RETRY),
        node("Tell", "CUSTOM.wabTell", {"where": "channel", "what": "result"}, x=x0 + 5, **RETRY),
        node("Declined", "n8n-nodes-base.noOp", x=x0 + 4),
        node("No answer", "n8n-nodes-base.noOp", x=x0 + 4),
        node("Nothing to change", "n8n-nodes-base.noOp", x=x0 + 4),
    ]
    edges = {
        "Read": to("Agent"),
        "Agent": to("Propose a change"),
        "Propose a change": to("Ask for a yes"),
        "Ask for a yes": exits("No answer", "Make the approved changes", "Declined", "Nothing to change"),
        "Make the approved changes": to("Tell"),
    }
    return nodes, edges


def create(name: str, nodes: list[dict[str, Any]], edges: dict[str, Any], pins: dict[str, Any] | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    document: dict[str, Any] = {"name": f"simspike {name}", "nodes": nodes, "connections": edges, "settings": {**SETTINGS, **(settings or {})}}
    if pins:
        document["pinData"] = pins
    status, made, _ = public("POST", "/workflows", document)
    assert status == 200, f"create {name} answered {status}: {made}"
    status, held, _ = public("GET", f"/workflows/{made['id']}")
    if pins:
        assert held.get("pinData") == pins, f"n8n did not keep the pins of {name}: {held.get('pinData')}"
    return held


# ---- Runs --------------------------------------------------------------------------------------


def run_by_hand(workflow: dict[str, Any], kind: str = "test") -> tuple[str, str]:
    """As platform-api's run_draft: n8n runs the draft from Start from the Portal with this item."""
    nonce = f"simnonce-{secrets.token_hex(6)}"
    item = {"nonce": nonce, "kind": kind, "workflow_id": workflow["id"]}
    body = {"triggerToStartFrom": {"name": START, "data": {"startTime": 0, "executionTime": 0, "source": [], "data": {"main": [[{"json": item}]]}}}}
    status, answer, _ = rest("POST", f"/workflows/{workflow['id']}/run", body)
    assert status == 200, f"run by hand answered {status}: {answer}"
    return str(answer["data"]["executionId"]), nonce


def activate(workflow: dict[str, Any]) -> dict[str, Any]:
    """Turns the workflow on, then waits until n8n reads it published with its triggers moved, as
    platform-api's wait_published does (P7 Q19)."""
    status, _, _ = public("POST", f"/workflows/{workflow['id']}/activate")
    began = time.time()

    def published():
        _, answer, _ = rest("GET", f"/workflows/{workflow['id']}/publication-status")
        data = (answer or {}).get("data") or {}
        return data if data.get("status") == "published" else None

    try:
        data = wait_for("n8n to publish", published, 30, 0.5)
    except TimeoutError:
        data = rest("GET", f"/workflows/{workflow['id']}/publication-status")[1]
    return {"activate_answered": status, "publication": data, "seconds_to_publish": round(time.time() - began, 1)}


def signed_start(workflow: dict[str, Any], secret: str) -> tuple[int, Any, str]:
    trigger = next(n for n in workflow["nodes"] if n["name"] == START)
    nonce = f"simnonce-{secrets.token_hex(6)}"
    expires = int(time.time()) + 240
    message = "\n".join((workflow["id"], trigger["webhookId"], nonce, "run_now", str(expires)))
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    # n8n may answer 404 for a moment after it reads published, so a 404 is asked again briefly.
    for _ in range(20):
        status, answer, _ = http("POST", f"{N8N}/webhook/{trigger['webhookId']}/start", {"nonce": nonce, "kind": "run_now", "expires": expires}, {"X-Wab-Signature": signature})
        if status != 404:
            break
        time.sleep(0.5)
    return status, answer, nonce


def newest_execution(workflow_id: str, after: set[str]) -> str:
    def found():
        status, page, _ = public("GET", f"/executions?workflowId={workflow_id}&limit=10")
        fresh = [str(e["id"]) for e in (page or {}).get("data", []) if str(e["id"]) not in after]
        return fresh[0] if fresh else None

    return wait_for("the new execution", found, 30, 0.5)


def executions_of(workflow_id: str) -> set[str]:
    status, page, _ = public("GET", f"/executions?workflowId={workflow_id}&limit=50")
    return {str(e["id"]) for e in (page or {}).get("data", [])}


def finished(execution_id: str, timeout: float = 180) -> dict[str, Any]:
    def ended():
        status, record, _ = public("GET", f"/executions/{execution_id}?includeData=true")
        if status == 200 and record.get("status") in ("success", "error", "crashed", "canceled"):
            return record
        return None

    return wait_for(f"execution {execution_id} to end", ended, timeout)


def seconds(record: dict[str, Any]) -> float | None:
    def when(text: str | None):
        return None if not text else datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))

    start, stop = when(record.get("startedAt")), when(record.get("stoppedAt"))
    return None if not start or not stop else round((stop - start).total_seconds(), 2)


def shown(record: dict[str, Any]) -> dict[str, Any]:
    """What code would read from n8n's execution data to grade a scenario and find coverage gaps."""
    result = record["data"]["resultData"]
    run_data = result.get("runData") or {}
    blocks = [n["name"] for n in record["workflowData"]["nodes"]]
    ran = {}
    for name, tries in run_data.items():
        last = tries[-1]
        outputs = (last.get("data") or {}).get("main") or []
        ran[name] = {
            "status": last.get("executionStatus"),
            "runs": len(tries),
            "items_per_exit": [len(o or []) for o in outputs],
            "error": (last.get("error") or {}).get("message"),
        }
    return {
        "execution": str(record["id"]),
        "status": record.get("status"),
        "mode": record.get("mode"),
        "seconds": seconds(record),
        "error": (result.get("error") or {}).get("message"),
        "last_block": result.get("lastNodeExecuted"),
        "ran": ran,
        "not_ran": [b for b in blocks if b not in run_data],
        "pinned_in_execution": sorted((result.get("pinData") or {}).keys()),
    }


def gateway_calls(execution_id: str | None = None) -> list[dict[str, Any]]:
    _, answer, _ = http("GET", f"{GATEWAY}/_admin/calls")
    calls = answer["calls"]
    if execution_id is not None:
        calls = [c for c in calls if c["execution_id"] == execution_id]
    return [{k: c[k] for k in ("kind", "node", "mode", "link")} for c in calls]


def gateway_wakes(execution_id: str) -> list[dict[str, Any]]:
    _, answer, _ = http("GET", f"{GATEWAY}/_admin/calls")
    return [w for w in answer["wakes"] if w["execution_id"] == execution_id]


def scenario(read: str = "ok", ask: str = "no") -> None:
    http("POST", f"{GATEWAY}/_admin/scenario", {"read": read, "ask": ask})


def upstream(mode: str, hold: int = 60) -> None:
    http("POST", f"{UPSTREAM}/_admin/mode", {"mode": mode, "hold_seconds": hold})


def upstream_seen() -> list[dict[str, Any]]:
    _, answer, _ = http("GET", f"{UPSTREAM}/_admin/seen")
    return [{k: s[k] for k in ("path", "auth")} for s in answer["seen"]]


def credential(name: str, kind: str, data: dict[str, str]) -> dict[str, str]:
    status, made, _ = public("POST", "/credentials", {"name": name, "type": kind, "data": data})
    assert status == 200, f"credential {kind} answered {status}: {made}"
    return {"id": str(made["id"]), "name": name}


def made_up() -> str:
    return f"sim-{secrets.token_hex(8)}"


# ---- Spike items ----------------------------------------------------------------------------------


def s1(out: dict[str, Any]) -> dict[str, Any]:
    status, types, _ = http("GET", f"{N8N}/types/nodes.json", headers={"Cookie": cookie})
    names = sorted({t["name"] for t in types})
    with open("/out/served-types.json", "w") as f:
        json.dump(types, f)
    ours = [n for n in names if n.startswith("CUSTOM.wab")]
    out["our_blocks_loaded"] = ours
    out["types_served"] = len(names)
    out["left_out_still_loaded"] = [n for n in names if n in ("n8n-nodes-base.executeCommand", "n8n-nodes-base.localFileTrigger", "n8n-nodes-base.function", "n8n-nodes-base.functionItem", "@n8n/n8n-nodes-langchain.code", "n8n-nodes-base.git", "n8n-nodes-base.gitTool")]
    status, listed, _ = public("GET", "/workflows")
    out["workflows_bootstrap_loaded"] = sorted((w["name"], w["active"]) for w in listed["data"])
    status, settings, _ = rest("GET", "/settings")
    out["n8n_version"] = settings["data"].get("versionCli")
    out["outside_reach_from_driver"] = {}
    for url in ("https://api.github.com/", "https://slack.com/api/api.test", "http://platform-api:8000/healthz", "http://wab-platform-api-1:8000/healthz"):
        try:
            status, _, _ = http("GET", url, timeout=5)
            out["outside_reach_from_driver"][url] = f"answered {status}"
        except Exception as error:  # noqa: BLE001
            out["outside_reach_from_driver"][url] = f"{type(error).__name__}: {str(error)[:80]}"
    return out


def s2(out: dict[str, Any]) -> dict[str, Any]:
    gh = credential("sim GitHub (mock)", "githubApi", {"server": MOCK_GITHUB, "user": "sim", "accessToken": made_up()})
    pat = credential("sim Jira PAT (stand-in)", "jiraSoftwareServerPatApi", {"domain": UPSTREAM, "personalAccessToken": made_up()})
    cloud = credential("sim Jira Cloud (stand-in)", "jiraSoftwareCloudApi", {"domain": UPSTREAM, "email": "sim@sim.example", "apiToken": made_up()})
    # mock Slack's own published test token (e2e/mock_slack/server.py), not a secret.
    slack = credential("sim Slack (mock)", "slackApi", {"accessToken": "mock-slack-token"})
    nodes = [
        start_node(),
        github("GitHub releases", gh, 1),
        node("Jira (server)", "n8n-nodes-base.jira", {"jiraVersion": "serverPat", "resource": "issue", "operation": "get", "issueKey": "MOCK-1", "additionalFields": {}}, 1, 2, executeOnce=True, credentials={"jiraSoftwareServerPatApi": pat}),
        node("Jira (cloud)", "n8n-nodes-base.jira", {"jiraVersion": "cloud", "resource": "issue", "operation": "get", "issueKey": "MOCK-1", "additionalFields": {}}, 1, 3, executeOnce=True, credentials={"jiraSoftwareCloudApi": cloud}),
        node("Slack post", "n8n-nodes-base.slack", {"select": "channel", "channelId": {"__rl": True, "value": "C0SUPPORT", "mode": "id"}, "text": "simspike S2", "otherOptions": {"includeLinkToWorkflow": False}}, 2.7, 4, executeOnce=True, credentials={"slackApi": slack}),
    ]
    edges = {START: to("GitHub releases"), "GitHub releases": to("Jira (server)"), "Jira (server)": to("Jira (cloud)"), "Jira (cloud)": to("Slack post")}
    workflow = create("S2 systems", nodes, edges)
    upstream("ok")
    execution, _ = run_by_hand(workflow)
    record = finished(execution)
    run_data = record["data"]["resultData"]["runData"]
    tags = [i["json"].get("tag_name") for i in run_data.get("GitHub releases", [{}])[-1].get("data", {}).get("main", [[]])[0]]
    _, sent, _ = http("GET", f"{MOCK_SLACK}/_sent")
    out.update({
        "run": shown(record),
        "github_tags_from_mock": tags,
        "jira_requests_at_stand_in": upstream_seen(),
        "slack_posts_at_mock": [{k: m.get(k) for k in ("method", "channel", "text")} for m in sent.get("sent", [])],
        "credentials_in_sim_n8n": sorted((c["name"], c["type"]) for c in public("GET", "/credentials")[1]["data"]),
    })
    return out


def s3(out: dict[str, Any]) -> dict[str, Any]:
    _, listed, _ = public("GET", "/workflows")
    reporter = next(w["id"] for w in listed["data"] if w["name"] == "run_failure_reporter")
    nodes, edges = our_chain()
    workflow = create("S3 our blocks", [start_node(), *nodes], {START: to("Read"), **edges}, settings={"errorWorkflow": reporter})
    out["activated"] = activate(workflow)

    # a. A start signed with the simulation's own secret, and the Approver says no.
    scenario(ask="no")
    before = executions_of(workflow["id"])
    status, answer, nonce = signed_start(workflow, os.environ["SIM_START_SECRET"])
    out["a_signed_with_sim_secret"] = {"start_answered": status, "answer": answer, "nonce_sent": nonce}
    execution = newest_execution(workflow["id"], before)
    record = finished(execution)
    out["a_signed_with_sim_secret"].update({"run": shown(record), "gateway_calls": gateway_calls(execution), "wakes": gateway_wakes(execution)})

    # b. A start signed with another secret, as the platform's would be.
    before = executions_of(workflow["id"])
    status, answer, _ = signed_start(workflow, secrets.token_hex(32))
    time.sleep(3)
    out["b_signed_with_other_secret"] = {"start_answered": status, "answer": answer, "new_executions": sorted(executions_of(workflow["id"]) - before)}

    # c. By hand, as a simulation runs: the Approver says yes, and the write is refused.
    scenario(ask="yes")
    execution, nonce = run_by_hand(workflow)
    record = finished(execution)
    out["c_by_hand_yes_then_write"] = {"nonce_sent": nonce, "run": shown(record), "gateway_calls": gateway_calls(execution)}

    # d. From a signed start: the refused write fails the run, and the error workflow reports it.
    before = executions_of(workflow["id"])
    status, answer, nonce = signed_start(workflow, os.environ["SIM_START_SECRET"])
    out["d_signed_yes_then_write"] = {"start_answered": status, "answer": answer}
    execution = newest_execution(workflow["id"], before)
    record = finished(execution)
    time.sleep(4)
    failures = [c for c in http("GET", f"{GATEWAY}/_admin/calls")[1]["calls"] if c["kind"] == "failures"]
    out["d_signed_yes_then_write"].update({"nonce_sent": nonce, "run": shown(record), "gateway_calls": gateway_calls(execution), "failure_reports_at_gateway": [{k: c[k] for k in ("node", "mode", "failed")} for c in failures], "by_hand_execution_c": out["c_by_hand_yes_then_write"]["run"]["execution"]})

    # e. Read answers "not found" and "timeout" at once, as data, with Read's own retries.
    for read in ("not_found", "timeout", "empty"):
        scenario(read=read, ask="no")
        execution, _ = run_by_hand(workflow)
        record = finished(execution)
        out[f"e_read_{read}"] = {"run": shown(record), "gateway_calls": [c["kind"] for c in gateway_calls(execution)]}
    public("POST", f"/workflows/{workflow['id']}/deactivate")
    return out


def s4(out: dict[str, Any]) -> dict[str, Any]:
    gh = credential("sim GitHub (stand-in)", "githubApi", {"server": UPSTREAM, "user": "sim", "accessToken": made_up()})
    nodes, edges = our_chain(2)
    pins = {"GitHub releases": [{"json": RELEASE}], "Read": [{"json": RELEASE}]}
    workflow = create("S4 pins", [start_node(), github("GitHub releases", gh, 1, **RETRY), *nodes], {START: to("GitHub releases"), "GitHub releases": to("Read"), **edges}, pins=pins)
    scenario(ask="no")
    upstream("ok")
    execution, nonce = run_by_hand(workflow)
    record = finished(execution)
    calls = gateway_calls(execution)
    out["by_hand"] = {
        "nonce_sent": nonce,
        "run": shown(record),
        "requests_at_github_stand_in": upstream_seen(),
        "gateway_calls": calls,
        "first_call_linked_by_nonce": bool(calls) and calls[0]["link"]["nonce"] == nonce and calls[0]["link"]["linked"],
    }
    # The same workflow from a signed start, which n8n runs as a webhook: pins must not apply.
    out["activated"] = activate(workflow)
    upstream("ok")
    before = executions_of(workflow["id"])
    status, answer, nonce = signed_start(workflow, os.environ["SIM_START_SECRET"])
    out["from_signed_start"] = {"start_answered": status, "answer": answer}
    execution = newest_execution(workflow["id"], before)
    record = finished(execution)
    out["from_signed_start"].update({"run": shown(record), "requests_at_github_stand_in": upstream_seen(), "gateway_calls": [c["kind"] for c in gateway_calls(execution)]})
    public("POST", f"/workflows/{workflow['id']}/deactivate")
    return out


def s5(out: dict[str, Any]) -> dict[str, Any]:
    gh = credential("sim GitHub (timeouts)", "githubApi", {"server": UPSTREAM, "user": "sim", "accessToken": made_up()})
    pat = credential("sim Jira (timeouts)", "jiraSoftwareServerPatApi", {"domain": UPSTREAM, "personalAccessToken": made_up()})
    tries = {"retryOnFail": True, "maxTries": 2, "waitBetweenTries": 1000}

    def flow(name: str, block: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
        return create(name, [start_node(), block, node("Done", "n8n-nodes-base.noOp", x=2)], {START: to(block["name"]), block["name"]: to("Done")}, settings=settings)

    plain = flow("S5 GitHub", github("GitHub releases", gh, 1, **tries))
    once = flow("S5 GitHub, one try", github("GitHub releases", gh, 1))
    capped = flow("S5 GitHub capped", github("GitHub releases", gh, 1, **tries), {"executionTimeout": 10})
    jira = flow("S5 Jira", node("Jira", "n8n-nodes-base.jira", {"jiraVersion": "serverPat", "resource": "issue", "operation": "get", "issueKey": "MOCK-1", "additionalFields": {}}, 1, 1, credentials={"jiraSoftwareServerPatApi": pat}, **tries))

    def attempt(label: str, workflow: dict[str, Any], mode: str, hold: int = 60, timeout: float = 240) -> None:
        upstream(mode, hold)
        began = time.time()
        execution, _ = run_by_hand(workflow)
        out[label] = {"execution": execution, "hold_seconds": hold if mode == "hold" else None}
        try:
            record = finished(execution, timeout)
            out[label]["run"] = shown(record)
        except TimeoutError as error:
            out[label]["run"] = {"status": f"still not ended: {error}"}
        _, seen, _ = http("GET", f"{UPSTREAM}/_admin/seen")
        out[label]["wall_seconds"] = round(time.time() - began, 1)
        out[label]["requests_at_stand_in_after_s"] = [round(s["at"] - began, 1) for s in seen["seen"]]
        say(f"S5 {label}: {out[label]['run']['status']} in {out[label]['wall_seconds']} s, requests at {out[label]['requests_at_stand_in_after_s']}")

    attempt("github_drop", plain, "drop")
    attempt("jira_drop", jira, "drop")
    attempt("github_not_found", plain, "not_found")
    attempt("github_hold_120s_cap_10s", capped, "hold", 120, 400)
    attempt("github_hold_90s", plain, "hold", 90, 300)
    attempt("github_hold_400s_one_try", once, "hold", 400, 700)
    upstream("ok")
    return out


def s7(collected: dict[str, Any]) -> dict[str, Any]:
    """Which blocks ran in each scenario, read back from n8n's execution data above."""
    rows: dict[str, Any] = {}
    s3 = collected.get("S3") or {}
    every: set[str] = set()
    for key in ("a_signed_with_sim_secret", "c_by_hand_yes_then_write", "e_read_not_found", "e_read_timeout", "e_read_empty"):
        run = (s3.get(key) or {}).get("run")
        if run:
            ask = run["ran"].get("Ask for a yes")
            rows[f"S3 {key}"] = {"status": run["status"], "not_ran": run["not_ran"], "ask_exit_items": None if ask is None else ask["items_per_exit"]}
            every |= set(run["ran"])
    nodes, _ = our_chain()
    rows["S3 blocks no scenario reached"] = sorted({n["name"] for n in nodes} - every)
    run = ((collected.get("S4") or {}).get("by_hand") or {}).get("run")
    if run:
        rows["S4 by_hand"] = {"ran": sorted(run["ran"]), "pinned_in_execution_record": run["pinned_in_execution"]}
    run = ((collected.get("S5") or {}).get("github_hold_120s_cap_10s") or {}).get("run")
    if run:
        rows["S5 cut by the time limit"] = {k: run[k] for k in ("status", "error", "last_block", "not_ran")}
    return rows


def main() -> None:
    wait_for("n8n", lambda: http("GET", f"{N8N}/healthz/readiness", timeout=3)[0] == 200, 120, 2)
    sign_in()
    say("signed in")
    for name, step in (("S1", s1), ("S2", s2), ("S3", s3), ("S4", s4), ("S5", s5)):
        if ONLY and name not in ONLY:
            continue
        say(f"{name} ...")
        out: dict[str, Any] = {}
        results[name] = out
        try:
            step(out)
        except Exception as error:  # noqa: BLE001
            out["error"] = f"{type(error).__name__}: {error}"
            out["trace"] = traceback.format_exc()[-1500:]
        http("POST", f"{GATEWAY}/_admin/reset")
        say(f"{name} done")
        with open("/out/results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
    if not ONLY or "S7" in ONLY:
        results["S7"] = s7(results)
    with open("/out/results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    say("wrote /out/results.json")


if __name__ == "__main__":
    main()
