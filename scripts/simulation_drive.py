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

Then it has the gateway make a version's copy (ADR 0054, PR 4): a version with n8n's own GitHub,
Jira, Slack and Teams blocks, each naming one of the platform's keys. The copy must name only the
mock keys, the GitHub block must read mock GitHub's releases, the Slack block must post to mock
Slack with the key its stack made up, and the Jira and Teams blocks, which have no mock here, must
run from their pins. A version with HTTP Request must be refused, with nothing made.

Last it has the gateway run whole simulations (ADR 0054, PR 5), with code's six templates and no
model: a release check of our blocks, and one that reads with n8n's own GitHub block, against mock
GitHub, and n8n's own Jira block, which is pinned. Each scenario must pass, the timeout must be
played by mock GitHub dropping the connection, the pinned Jira block must be named as not tried,
every copy must be deleted and mock GitHub set back. A scenario naming a block the version doesn't
have must be refused, with nothing made.

And it has the gateway serve what the scenario writer reads (ADR 0054, PR 6): a version's plan, with
each block's role and plays and the kinds that apply, and a simulation whose written scenario does
not fit, which runs code's templates in its place and says why.

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
SCOPES = ["workflow:create", "workflow:read", "workflow:list", "workflow:delete", "execution:read"]

failures: list[str] = []
cookie = ""
api_key = ""


def check(ok: bool, what: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {what}", flush=True)
    if not ok:
        failures.append(what)


def http(
    method: str,
    url: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60,
) -> tuple[int, Any, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
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
    method: str, path: str, value: Any = None, secret: str | None = None, timeout: float = 60
) -> tuple[int, Any]:
    body = b"" if value is None else as_json(value)
    key = os.environ["WAB_START_SECRET"] if secret is None else secret
    status, answer, _ = http(
        method, f"{GATEWAY}{path}", body or None, signed(method, path, body, key), timeout
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
    # n8n 2.42.6 refuses a label its user already holds, and an earlier drive's key is still
    # listed after it runs out, so each drive's label has an id of its own.
    label = f"simulation-drive {secrets.token_hex(4)}"
    key = {"label": label, "expiresAt": int(time.time()) + 3600, "scopes": SCOPES}
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
    status, made = public("POST", "/workflows", release_check())
    if status != 200:
        raise SystemExit(f"FAIL: the simulation n8n did not take the workflow ({status}): {made}")
    return str(made["id"])


def release_check(first: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A release check of our blocks with a Propose a change block: Read, Agent, Propose a change,
    Ask for approval, then Make the approved changes and Tell on Yes, and an end on each other exit.
    `first` stands in for Read. The Planner's own release check is tried in the simulation-link
    job (e2e/tests/test_practice_systems.py)."""
    read = {"source": "github_releases", "place": "langchain-ai/langgraph"}
    inputs = {"input": [{"name": "release", "value": "={{ $json.id }}"}]}
    propose = {
        "action": "jira.create_ticket",
        "place": "MOCK",
        "title": "Upgrade LangGraph",
        "body": "A new release is out.",
        "subject": "langgraph",
    }
    reads = first or [node("Read releases", "CUSTOM.wabRead", 1, read, **RETRY)]
    nodes = [
        node(START, "CUSTOM.wabStartFromPortal", 0, webhookId=str(uuid.uuid4())),
        *reads,
        node(
            "Compare", "CUSTOM.wabAgent", 2, {"agent": "release_checker", "inputs": inputs}, **RETRY
        ),
        node("Propose a change", "CUSTOM.wabProposeChange", 3, propose, **RETRY),
        node("Ask for approval", "CUSTOM.wabAskForYes", 4, webhookId=str(uuid.uuid4())),
        node("Make the approved changes", "CUSTOM.wabMakeApprovedChanges", 5, **RETRY),
        node("Tell", "CUSTOM.wabTell", 6, {"where": "channel", "what": "result"}, **RETRY),
        node("No answer", "n8n-nodes-base.noOp", 5),
        node("Declined", "n8n-nodes-base.noOp", 5),
        node("Nothing to change", "n8n-nodes-base.noOp", 5),
    ]
    exits = ["No answer", "Make the approved changes", "Declined", "Nothing to change"]
    line = [START, *[n["name"] for n in reads], "Compare"]
    edges = {
        **{a: to(b) for a, b in zip(line, line[1:], strict=False)},
        "Compare": to("Propose a change"),
        "Propose a change": to("Ask for approval"),
        "Ask for approval": {"main": [[{"node": e, "type": "main", "index": 0}] for e in exits]},
        "Make the approved changes": to("Tell"),
    }
    settings = {"saveManualExecutions": True, "saveExecutionProgress": True, "executionOrder": "v1"}
    return {
        "name": "Simulation gateway check",
        "nodes": nodes,
        "connections": edges,
        "settings": settings,
    }


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


def platform_key(kind: str, key: str) -> dict[str, Any]:
    """What a version names for one of the platform's own keys. Its copy must name none."""
    return {kind: {"id": key, "name": f"The platform's key {key}"}}


def version_with_systems() -> dict[str, Any]:
    """Start from the Portal, then n8n's own GitHub, Jira, Slack and Teams blocks."""
    github = {
        "resource": "release",
        "operation": "getAll",
        "owner": "langchain-ai",
        "repository": "langgraph",
        "returnAll": False,
        "limit": 3,
    }
    jira = {"jiraVersion": "server", "resource": "issue", "operation": "get", "issueKey": "MOCK-1"}
    slack = {
        "select": "channel",
        "channelId": {"__rl": True, "value": "C0SUPPORT", "mode": "id"},
        "text": "A new LangGraph release is out.",
        "otherOptions": {"includeLinkToWorkflow": False},
    }
    teams = {
        "resource": "channelMessage",
        "operation": "create",
        "teamId": {"__rl": True, "value": "team-1", "mode": "id"},
        "channelId": {"__rl": True, "value": "channel-1", "mode": "id"},
        "message": "A new LangGraph release is out.",
    }
    nodes = [
        node(START, "CUSTOM.wabStartFromPortal", 0, webhookId=str(uuid.uuid4())),
        node(
            "Read releases",
            "n8n-nodes-base.github",
            1,
            github,
            credentials=platform_key("githubApi", "wab-github-read"),
        ),
        node(
            "Read the issue",
            "n8n-nodes-base.jira",
            2,
            jira,
            executeOnce=True,
            credentials=platform_key("jiraSoftwareServerApi", "wab-jira-read"),
        ),
        node(
            "Post in Slack",
            "n8n-nodes-base.slack",
            3,
            slack,
            executeOnce=True,
            credentials=platform_key("slackApi", "wab-slack-send"),
        ),
        node(
            "Post in Teams",
            "n8n-nodes-base.microsoftTeams",
            4,
            teams,
            executeOnce=True,
            credentials=platform_key("microsoftOAuth2Api", "someones-teams-key"),
        ),
    ]
    nodes[2]["typeVersion"], nodes[3]["typeVersion"], nodes[4]["typeVersion"] = 1, 2.7, 2
    order = [n["name"] for n in nodes]
    return {
        "name": "Mock setup check",
        "nodes": nodes,
        "connections": {a: to(b) for a, b in zip(order, order[1:], strict=False)},
        "settings": {"executionOrder": "v1", "errorWorkflow": "the-platforms-error-workflow"},
    }


def run_copy(workflow: str) -> dict[str, Any]:
    """Runs the copy by hand, as a simulation runs it, and waits for it to end."""
    item = {"nonce": "mock-setup-check", "kind": "test", "workflow_id": workflow}
    run = {
        "triggerToStartFrom": {
            "name": START,
            "data": {
                "startTime": 0,
                "executionTime": 0,
                "source": [],
                "data": {"main": [[{"json": item}]]},
            },
        }
    }
    status, answer = rest("POST", f"/workflows/{workflow}/run", run)
    if status != 200:
        raise SystemExit(f"FAIL: n8n did not run the copy by hand ({status}): {answer}")
    execution = str(answer["data"]["executionId"])
    deadline = time.time() + 120
    while time.time() < deadline:
        status, record = public("GET", f"/executions/{execution}?includeData=true")
        if status == 200 and record.get("status") in ("success", "error", "crashed", "canceled"):
            return record
        time.sleep(0.5)
    raise SystemExit(f"FAIL: execution {execution} of the copy did not end in 120 s")


def output(record: dict[str, Any], block: str) -> list[dict[str, Any]]:
    runs = ((record.get("data") or {}).get("resultData") or {}).get("runData") or {}
    last = (runs.get(block) or [{}])[-1]
    main = ((last.get("data") or {}).get("main") or [[]])[0] or []
    return [item.get("json") or {} for item in main]


def check_mock_setup() -> None:
    status, _ = gateway("POST", "/simulation/v1/copies", {"version": version_with_systems()}, "x")
    check(
        status == 401, f"a copy asked for without the start secret is refused with 401 ({status})"
    )

    off = version_with_systems()
    off["nodes"].append(node("Call anything", "n8n-nodes-base.httpRequest", 5, {"url": "x"}))
    off["nodes"][-1]["typeVersion"] = 4.2
    _, before = public("GET", "/workflows")
    status, refused = gateway("POST", "/simulation/v1/copies", {"version": off})
    _, after = public("GET", "/workflows")
    named = [b["block"] for b in (refused or {}).get("blocks", [])]
    check(
        status == 422 and named == ["Call anything"],
        f"a version with HTTP Request is refused, naming it ({status}, {named})",
    )
    check(len(after["data"]) == len(before["data"]), "the refused version made nothing in the n8n")

    status, copied = gateway("POST", "/simulation/v1/copies", {"version": version_with_systems()})
    if status != 201:
        raise SystemExit(f"FAIL: the gateway did not make the copy ({status}): {copied}")
    modes = {b["block"]: (b["mode"], b["mock"]) for b in copied["blocks"]}
    check(
        modes
        == {
            START: ("ours", None),
            "Read releases": ("mock", "github"),
            "Read the issue": ("pinned", None),
            "Post in Slack": ("mock", "slack"),
            "Post in Teams": ("pinned", None),
        },
        f"each block got its mode from the class file ({modes})",
    )
    check(
        copied["not_tried"] == ["Read the issue", "Post in Teams"],
        f"the blocks with no mock are named as not tried ({copied['not_tried']})",
    )
    workflow = copied["workflow_id"]
    status, held = public("GET", f"/workflows/{workflow}")
    named_keys = sorted(
        key["id"] for n in held.get("nodes", []) for key in (n.get("credentials") or {}).values()
    )
    check(
        named_keys == ["sim-mock-github", "sim-mock-slack"],
        f"the copy names only the mock keys ({named_keys})",
    )
    check("wab-" not in json.dumps(held), "the copy names none of the platform's keys")
    pinned = sorted((held.get("pinData") or {}).keys())
    check(
        pinned == ["Post in Teams", "Read the issue"],
        f"only the blocks with no mock are pinned ({pinned})",
    )

    record = run_copy(workflow)
    check(record.get("status") == "success", f"the copy ran by hand ({record.get('status')})")
    tags = [item.get("tag_name") for item in output(record, "Read releases")]
    check(bool(tags) and all(tags), f"GitHub's block read mock GitHub's releases ({tags})")
    check(
        output(record, "Read the issue") == [{"pinned": copied["blocks"][2]["why"]}],
        "Jira's block, with no mock here, ran from its pin",
    )
    _, sent, _ = http("GET", "http://mock-slack:8500/_sent")
    posts = [m for m in (sent or {}).get("sent", []) if m.get("channel") == "C0SUPPORT"]
    check(
        len(posts) == 1 and posts[0]["token"] == os.environ["MOCK_SLACK_TOKEN"],
        f"Slack's block posted once to mock Slack, with its made-up key ({len(posts)})",
    )
    check(bool(output(record, "Post in Teams")), "Teams' block, with no mock, ran from its pin")
    public("DELETE", f"/workflows/{workflow}")


KINDS = ["happy_path", "nothing_new", "source_not_found", "timeout", "approver_says_no", "odd_data"]
AFTER_WRITE = "A simulation never writes, so a block after a write never runs."


def simulation(value: dict[str, Any]) -> tuple[int, Any]:
    return gateway("POST", "/simulation/v1/simulations", value, timeout=600)


def with_github() -> dict[str, Any]:
    """The release check, reading with n8n's own GitHub block, against mock GitHub, then n8n's
    own Jira block, which has no mock here, so it is pinned."""
    github = {
        "resource": "release",
        "operation": "getAll",
        "owner": "langchain-ai",
        "repository": "langgraph",
        "returnAll": False,
        "limit": 3,
    }
    jira = {"jiraVersion": "server", "resource": "issue", "operation": "get", "issueKey": "MOCK-1"}
    reads = [
        node(
            "GitHub releases",
            "n8n-nodes-base.github",
            1,
            github,
            credentials=platform_key("githubApi", "wab-github-read"),
        ),
        node(
            "Read the issue",
            "n8n-nodes-base.jira",
            1,
            jira,
            executeOnce=True,
            credentials=platform_key("jiraSoftwareServerApi", "wab-jira-read"),
        ),
    ]
    return release_check(reads)


def results_of(done: Any) -> dict[str, dict[str, Any]]:
    found = {r["kind"]: r for r in (done or {}).get("results", [])}
    for result in found.values():
        print(f"  {result['kind']}: {result['verdict']}. {result['happened']}", flush=True)
    return found


def check_simulations() -> None:
    _, before = public("GET", "/workflows")

    status, done = simulation({"version": release_check()})
    found = results_of(done)
    check(
        status == 200
        and {k: r["verdict"] for k, r in found.items()} == dict.fromkeys(KINDS, "passed"),
        f"our blocks: each of code's six scenarios passed ({status})",
    )
    check(
        (done or {}).get("coverage", {}).get("not_tried")
        == [{"block": "Tell", "why": AFTER_WRITE}],
        "our blocks: Tell, after the refused write, is named as not tried",
    )

    status, done = simulation({"version": with_github()})
    found = results_of(done)
    check(
        status == 200
        and {k: r["verdict"] for k, r in found.items()} == dict.fromkeys(KINDS, "passed"),
        f"n8n's GitHub block: each of code's six scenarios passed ({status})",
    )
    timeout = found.get("timeout", {}).get("happened", "")
    check(
        "GitHub closed the connection" in timeout,
        f"the timeout was played by mock GitHub dropping the connection ({timeout})",
    )
    pinned = [n["block"] for n in found.get("source_not_found", {}).get("not_tried", [])]
    check(
        pinned == ["Read the issue"], f"the pinned Jira block is not tried as not found ({pinned})"
    )

    scenario = {"kind": "happy_path", "reads": {"Nowhere": {"serve": "recorded"}}}
    status, refused = simulation({"version": release_check(), "scenarios": [scenario]})
    check(
        status == 422 and "Nowhere" in json.dumps(refused),
        f"a scenario naming a block the version doesn't have is refused ({status})",
    )

    status, plan = gateway("POST", "/simulation/v1/plans", {"version": with_github()})
    roles = {b["name"]: (b["role"], b["plays"]) for b in (plan or {}).get("blocks", [])}
    check(
        status == 200
        and (plan or {}).get("kinds") == KINDS
        and roles.get("Read the issue") == ("read", ["recorded", "varied", "empty"]),
        f"the gateway answers a version's plan for the scenario writer ({status}, {roles})",
    )
    status, done = simulation(
        {"version": release_check(), "scenarios": [scenario], "fall_back": True}
    )
    found = results_of(done)
    check(
        status == 200
        and (done or {}).get("scenarios_from") == "templates"
        and "Nowhere" in json.dumps((done or {}).get("refused"))
        and {k: r["verdict"] for k, r in found.items()} == dict.fromkeys(KINDS, "passed"),
        f"a written scenario that doesn't fit falls back to code's six templates ({status})",
    )

    _, after = public("GET", "/workflows")
    check(
        len(after["data"]) == len(before["data"]),
        f"every copy was deleted after grading ({len(before['data'])}, {len(after['data'])})",
    )
    _, mode, _ = http("GET", "http://mock-github:8200/_admin/mode")
    _, served, _ = http("GET", "http://mock-github:8200/repos/langchain-ai/langgraph/releases")
    check(
        mode == {"mode": "ok"} and served[0]["tag_name"] == "1.2.16",
        f"mock GitHub was set back to its own answers ({mode})",
    )


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
        f"yes: Ask for approval got yes and n8n woke ({kept['approver']}, {kept['woke']})",
    )
    written = [c["title"] for c in kept["proposed"][: kept["would_have_written"] or 0]]
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
    gone = "GitHub can't find langchain-ai/langgraph."
    check(
        record.get("status") == "error" and "Compare" not in ran(record),
        f"not found: Read failed and nothing after it ran ({error(record)})",
    )
    check(
        error(record) == gone,
        f"not found: n8n's record holds our words, as a real run's does ({error(record)})",
    )
    check(
        reads == [("refused", gone)] * RETRY["maxTries"],
        f"not found: the gateway refused each try in the same words ({reads})",
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

    check_mock_setup()
    check_simulations()
    if failures:
        print(f"FAIL: {len(failures)} check(s) of the simulation gateway failed.")
        return 1
    print("PASS: the simulation gateway answered our blocks as each scenario says.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
