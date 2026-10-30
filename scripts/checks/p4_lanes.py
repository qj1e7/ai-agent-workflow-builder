"""Lanes for the P4 checker: the activity log's copy in Cosmos DB. Standard library only. Each
command saves what it saw in the folder it is given and prints PASS or FAIL.

usage: python3 -I scripts/checks/p4_lanes.py <command> <api-base-url> <out-dir> [arguments]

  lane1 <trunk-api> <out> <head-api>     a watchlist check streamed at trunk and at head
  lane2 <api> <out> <run-id>             the run's items in Cosmos DB
  lane3 <api> <out> <run-id>             the stream again with Last-Event-ID 3
  lane4 <api> <out>                      (own stack) the emulator stops during a run
  lane5 <api> <out> <signing-key> [n]    (own stack) platform-api is killed in the middle of a copy
  lane6 <api> <out>                      (own stack) a run fails on purpose; its troubleshooter
  lane7 <api> <out>                      bob approves a run; the decision's item in Cosmos DB
  lane8 <api> <out>                      (own stack, libfaketime) two days pass before the yes
  lane9 <api> <out> <second-api>         (own stack) two platform-api replicas stream one run
  lane10 <api> <out> <lane-1 json>       (own stack, ACTIVITY_READER=postgres) emulator stopped

P4_COMPOSE holds the lane stack's docker compose command, for example
    docker compose -p p4-check --env-file /tmp/swarm-p4/env/.env \\
        -f <src>/deploy/compose.yaml -f <src>/deploy/compose.e2e.yaml
The lanes read Cosmos DB through a short script in that stack's platform-api container, and
PostgreSQL through psql in its postgres container. Lanes 1 and 10 compare the kinds of events.
"""

import hashlib
import hmac
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

WAIT_SECONDS = 150
SETTLED = {"awaiting_approval", "succeeded", "failed", "rejected"}
DONE = {"succeeded", "failed", "rejected"}
MOCK_MODEL_URL = "http://mock-model:8300"
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
VALUES = {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}

COSMOS_ITEMS = """
import asyncio, json, os, sys
from azure.cosmos.aio import CosmosClient

async def main():
    async with CosmosClient(
        os.environ["COSMOS_ENDPOINT"],
        credential=os.environ["COSMOS_KEY"],
        enable_endpoint_discovery=False,
    ) as client:
        container = client.get_database_client("activity").get_container_client("run_events")
        properties = await container.read()
        query = container.query_items("SELECT * FROM c ORDER BY c.seq", partition_key=sys.argv[1])
        items = [item async for item in query]
    print(json.dumps({"partition_key": properties["partitionKey"], "items": items}))

asyncio.run(main())
"""


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.log: list[dict[str, Any]] = []

    def call(
        self,
        user: str | None,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        keep: bool = True,
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        sent = {"Accept": "application/json", "Content-Type": "application/json"}
        if user is not None:
            sent["X-Dev-User"] = user
        sent.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=sent)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        try:
            parsed: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw.decode(errors="replace")
        if keep:
            self.log.append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "user": user,
                    "method": method,
                    "path": path,
                    "status": status,
                    "response": parsed,
                }
            )
        return status, parsed

    def get(self, user: str, path: str) -> Any:
        status, parsed = self.call(user, "GET", path)
        if status != 200:
            raise SystemExit(f"GET {path} as {user}: HTTP {status} {parsed!r}"[:600])
        return parsed

    def start_run(self, user: str, use_case_id: str) -> str:
        status, started = self.call(
            user,
            "POST",
            f"/api/v1/use-cases/{use_case_id}/runs",
            headers={"Idempotency-Key": f"p4check-{uuid.uuid4()}"},
        )
        if status != 201:
            raise SystemExit(f"start a run of {use_case_id}: HTTP {status} {started!r}"[:600])
        return started["run_id"]

    def wait(self, run_id: str, states: set[str]) -> Any:
        deadline = time.monotonic() + WAIT_SECONDS
        run: Any = None
        while time.monotonic() < deadline:
            status, run = self.call("alice", "GET", f"/api/v1/runs/{run_id}", keep=False)
            if status == 200 and run["state"] in states:
                return self.get("alice", f"/api/v1/runs/{run_id}")
            time.sleep(0.5)
        raise SystemExit(f"run {run_id} never reached {sorted(states)}; last {run!r}"[:800])

    def events(self, run_id: str) -> list[Any]:
        return self.get("alice", f"/api/v1/runs/{run_id}/events?after=0")["events"]


class Stream:
    """One SSE connection, read on a thread. Keeps each raw frame and each event."""

    def __init__(self, base: str, run_id: str, last_event_id: int | None = None) -> None:
        headers = {"Accept": "text/event-stream", "X-Dev-User": "alice"}
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        request = urllib.request.Request(
            f"{base.rstrip('/')}/api/v1/runs/{run_id}/events", headers=headers
        )
        self.response = urllib.request.urlopen(request, timeout=WAIT_SECONDS)
        self.frames: list[str] = []
        self.events: list[dict[str, Any]] = []
        self.arrived = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        lines: list[str] = []
        try:
            for raw in self.response:
                line = raw.decode().rstrip("\r\n")
                if line:
                    lines.append(line)
                    continue
                if not lines:
                    continue
                with self.arrived:
                    self.frames.append("\n".join(lines))
                    data = [x[len("data: ") :] for x in lines if x.startswith("data: ")]
                    if data:
                        self.events.append(json.loads(data[0]))
                    self.arrived.notify_all()
                lines = []
        except OSError, ValueError:
            return

    def wait_for_seq(self, seq: int, timeout: float = 30) -> bool:
        deadline = time.monotonic() + timeout
        with self.arrived:
            while not any(e["seq"] >= seq for e in self.events):
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self.arrived.wait(left)
        return True

    def close(self) -> None:
        self.response.close()


class Stack:
    def __init__(self) -> None:
        command = os.environ.get("P4_COMPOSE")
        if not command:
            raise SystemExit("set P4_COMPOSE to the lane stack's docker compose command")
        self.compose = shlex.split(command)

    def run(self, *args: str, stdin: str | None = None, check: bool = True) -> str:
        done = subprocess.run(
            [*self.compose, *args], input=stdin, capture_output=True, text=True, check=False
        )
        if check and done.returncode != 0:
            raise SystemExit(f"{' '.join(args)}: {done.stderr.strip()}"[:800])
        return done.stdout

    def cosmos(self, run_id: str) -> dict[str, Any]:
        out = self.run("exec", "-T", "platform-api", "python", "-c", COSMOS_ITEMS, run_id)
        return json.loads(out.strip().splitlines()[-1])

    def sql(self, statement: str, run_id: str) -> Any:
        out = self.run(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "platform",
            "-tAq",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            f"run={run_id}",
            "-f",
            "-",
            stdin=statement,
        )
        return json.loads(out.strip() or "null")

    def rows(self, run_id: str) -> list[dict[str, Any]]:
        return self.sql(
            "SELECT coalesce(json_agg(json_build_object('seq', seq, 'kind', kind, 'ts', ts, "
            "'dedupe_key', dedupe_key) ORDER BY seq), '[]') "
            "FROM monitoring.run_events WHERE run_id = :'run';",
            run_id,
        )

    def mark(self, run_id: str) -> int:
        return self.sql(
            "SELECT coalesce((SELECT seq FROM monitoring.run_events_copied "
            "WHERE run_id = :'run'), 0);",
            run_id,
        )

    def health(self, service: str) -> str:
        container = self.run("ps", "-q", service).strip()
        if not container:
            return "absent"
        done = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container],
            capture_output=True,
            text=True,
            check=False,
        )
        return done.stdout.strip()

    def wait_healthy(self, service: str, timeout: float = 240) -> None:
        deadline = time.monotonic() + timeout
        while self.health(service) != "healthy":
            if time.monotonic() > deadline:
                raise SystemExit(f"{service} was not healthy after {timeout:.0f} s")
            time.sleep(1)


def save(out: Path, name: str, payload: Any) -> None:
    out.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    (out / name).write_text(text + "\n")


def verdict(lines: list[tuple[bool, str]]) -> bool:
    for ok, line in lines:
        print(("ok   " if ok else "FAIL ") + line)
    passed = all(ok for ok, _ in lines)
    print("PASS" if passed else "FAIL")
    return passed


def kinds(events: list[dict[str, Any]]) -> list[str]:
    return [e["kind"] for e in events]


def seqs_of(items: list[dict[str, Any]]) -> list[int]:
    return [item["seq"] for item in items]


def gapless(seqs: list[int]) -> bool:
    return seqs == list(range(1, len(seqs) + 1))


def ensure_watchlist(api: Api) -> str:
    status, added = api.call("alice", "POST", "/api/v1/watchlist/software", LANGGRAPH)
    if status not in (201, 409):
        raise SystemExit(f"add LangGraph: HTTP {status} {added!r}")
    return api.get("alice", "/api/v1/watchlist")["watchlist"]["use_case_id"]


def connect_model(api: Api) -> None:
    active = api.get("alice", "/api/v1/settings/model")["active"]
    if active is not None and active["base_url"] == MOCK_MODEL_URL:
        return
    status, saved = api.call(
        "alice",
        "PUT",
        "/api/v1/settings/model",
        {
            "style": "anthropic",
            "base_url": MOCK_MODEL_URL,
            "model": "mock-model",
            "api_key": "p4-mock-key-not-real",
        },
    )
    if status != 200:
        raise SystemExit(f"save the mock model: HTTP {status} {saved!r}")
    if saved["status"] == "awaiting_confirmation":
        pending = api.get("bob", "/api/v1/settings/model")["pending"]
        api.call(
            "bob",
            "POST",
            "/api/v1/settings/model/address-decision",
            {"verdict": "confirm", "digest": pending["digest"]},
        )
    if api.get("alice", "/api/v1/settings/model")["active"] is None:
        raise SystemExit("the mock model is not active")


def agent_workflow(api: Api, lane: str) -> str:
    body = {
        "name": f"p4 {lane} {uuid.uuid4().hex[:6]}",
        "instruction": "Check LangGraph for new releases and raise a ticket in MOCK.",
        "agents": [{"card_id": "crd_version_checker", "values": VALUES}],
    }
    status, created = api.call("alice", "POST", "/api/v1/agent-use-cases", body)
    if status != 201:
        raise SystemExit(f"create the workflow: HTTP {status} {created!r}")
    return created["use_case_id"]


def streamed_run(api: Api, use_case_id: str) -> tuple[str, list[dict[str, Any]], Any, bool]:
    run_id = api.start_run("alice", use_case_id)
    stream = Stream(api.base, run_id)
    run = api.wait(run_id, SETTLED)
    caught_up = stream.wait_for_seq(run["last_seq"])
    stream.close()
    return run_id, list(stream.events), run, caught_up


def approve_as_bob(api: Api, run: Any) -> tuple[int, Any, str]:
    approval_id = run["approval"]["approval_id"]
    view = api.get("bob", f"/api/v1/approvals/{approval_id}")
    status, decided = api.call(
        "bob",
        "POST",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": view["digest"]},
    )
    return status, decided, view["digest"]


def wait_for_copy(stack: Stack, run_id: str, last_seq: int, timeout: float = 90) -> Any:
    deadline = time.monotonic() + timeout
    found = stack.cosmos(run_id)
    while seqs_of(found["items"]) != list(range(1, last_seq + 1)):
        if time.monotonic() > deadline:
            break
        time.sleep(1)
        found = stack.cosmos(run_id)
    return found


def lane1(trunk: Api, out: Path, head: Api) -> bool:
    sides: dict[str, Any] = {}
    for name, api in (("trunk", trunk), ("head", head)):
        run_id, events, run, caught_up = streamed_run(api, ensure_watchlist(api))
        sides[name] = {
            "run_id": run_id,
            "state": run["state"],
            "last_seq": run["last_seq"],
            "caught_up": caught_up,
            "kinds": kinds(events),
            "seqs": [e["seq"] for e in events],
        }
    save(out, "p4-stream-trunk-head.json", sides)
    lines: list[tuple[bool, str]] = []
    for name, side in sides.items():
        lines.append(
            (
                side["caught_up"] and gapless(side["seqs"]),
                f"{name}: run {side['run_id']} is {side['state']}, the stream held "
                f"{len(side['seqs'])} of {side['last_seq']} events, gapless",
            )
        )
    lines.append(
        (
            sides["trunk"]["kinds"] == sides["head"]["kinds"],
            f"the same kinds in the same order: trunk {sides['trunk']['kinds']} "
            f"head {sides['head']['kinds']}",
        )
    )
    return verdict(lines)


def lane2(api: Api, out: Path, run_id: str) -> bool:
    stack = Stack()
    run = api.get("alice", f"/api/v1/runs/{run_id}")
    found = wait_for_copy(stack, run_id, run["last_seq"])
    items = found["items"]
    save(out, "p4-items.json", {"run": run, **found})
    return verdict(
        [
            (
                found["partition_key"]["paths"] == ["/runId"],
                f"partition key {found['partition_key']}",
            ),
            (
                bool(items) and all(item["runId"] == run_id for item in items),
                f"all {len(items)} items carry runId {run_id}",
            ),
            (
                gapless(seqs_of(items)) and len(items) == run["last_seq"],
                f"seqs {seqs_of(items)} run from 1 with no gap to last_seq {run['last_seq']}",
            ),
            (
                all(item["id"] == str(item["seq"]) for item in items),
                "each item's id is its seq as text",
            ),
        ]
    )


def lane3(api: Api, out: Path, run_id: str) -> bool:
    stream = Stream(api.base, run_id, last_event_id=3)
    stream.wait_for_seq(4, timeout=10)
    time.sleep(1)
    stream.close()
    save(out, "p4-resume.txt", "\n\n".join(stream.frames))
    first = stream.events[0]["seq"] if stream.events else None
    return verdict(
        [
            (first == 4, f"the first frame after Last-Event-ID 3 is event {first}"),
            (
                [e["seq"] for e in stream.events] == list(range(4, 4 + len(stream.events))),
                f"then {[e['seq'] for e in stream.events]} in order",
            ),
        ]
    )


def lane4(api: Api, out: Path) -> bool:
    stack = Stack()
    run_id = api.start_run("alice", ensure_watchlist(api))
    stack.run("stop", "-t", "1", "cosmos")
    stopped_at = datetime.now(UTC).isoformat()
    run = api.wait(run_id, SETTLED)
    copied_while_down = stack.mark(run_id)
    stack.run("start", "cosmos")
    stack.wait_healthy("cosmos")
    started_at = datetime.now(UTC).isoformat()
    found = wait_for_copy(stack, run_id, run["last_seq"])
    logs = stack.run("logs", "--no-color", "platform-api", check=False)
    warnings = [line for line in logs.splitlines() if "Could not copy" in line]
    save(
        out,
        "p4-emulator-down.json",
        {
            "run_id": run_id,
            "stopped_at": stopped_at,
            "started_at": started_at,
            "run": run,
            "mark_while_down": copied_while_down,
            "pg_rows": stack.rows(run_id),
            "cosmos": found,
            "copier_warnings": warnings[:20],
        },
    )
    seqs = seqs_of(found["items"])
    return verdict(
        [
            (run["state"] in SETTLED, f"the run reached {run['state']} in PostgreSQL"),
            (
                copied_while_down < run["last_seq"],
                f"while the emulator was down the mark stayed at {copied_while_down} "
                f"of {run['last_seq']}",
            ),
            (bool(warnings), f"the copier logged {len(warnings)} failed copies"),
            (
                seqs == list(range(1, run["last_seq"] + 1)),
                f"after the restart Cosmos DB holds {seqs} of {run['last_seq']}",
            ),
        ]
    )


def signed(key: str, run_id: str, task_id: str) -> str:
    expires = int(time.time()) + 3600
    message = f"{run_id}|{task_id}|{expires}".encode()
    return f"{expires}.{hmac.new(key.encode(), message, hashlib.sha256).hexdigest()}"


def post_agent_events(api: Api, run_id: str, key: str, count: int) -> int:
    task_id = f"{run_id}/work/1/1"
    token = signed(key, run_id, task_id)
    task = urllib.parse.quote(task_id, safe="")
    accepted = 0
    for n in range(1, count + 1):
        event = {
            "agent_seq": n,
            "ts": datetime.now(UTC).isoformat(),
            "agent": {"id": "p4_lane5", "display": "Lane 5"},
            "summary": f"Lane 5 event {n}.",
            "kind": "agent_step_started",
            "data": {"step": f"step {n}"},
        }
        status, _ = api.call(
            None,
            "POST",
            f"/internal/v1/runs/{run_id}/agent-events?task={task}",
            {"task_id": task_id, "event": event},
            headers={"X-Callback-Token": token},
            keep=False,
        )
        accepted += status == 202
    return accepted


def lane5(api: Api, out: Path, key: str, count: int) -> bool:
    stack = Stack()
    run_id = f"run_p4lane5{uuid.uuid4().hex[:12]}"
    stack.run("stop", "-t", "1", "cosmos")
    accepted = post_agent_events(api, run_id, key, count)
    stack.run("start", "cosmos")
    stack.wait_healthy("cosmos")
    deadline = time.monotonic() + 120
    mark = stack.mark(run_id)
    while mark == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
        mark = stack.mark(run_id)
    stack.run("kill", "-s", "SIGKILL", "platform-api")
    killed_at_mark = stack.mark(run_id)
    stack.run("start", "platform-api")
    stack.wait_healthy("platform-api")
    found = wait_for_copy(stack, run_id, count, timeout=180)
    seqs = seqs_of(found["items"])
    after = stack.mark(run_id)
    save(
        out,
        "p4-crash-copy.json",
        {
            "run_id": run_id,
            "posted": count,
            "accepted": accepted,
            "mark_seen_before_kill": mark,
            "mark_after_kill": killed_at_mark,
            "mark_after_restart": after,
            "cosmos_seqs": seqs,
            "item_ids": [item["id"] for item in found["items"]],
        },
    )
    return verdict(
        [
            (accepted == count, f"{accepted} of {count} events stored while the emulator was down"),
            (
                0 < killed_at_mark < count,
                f"platform-api was killed mid-copy, at mark {killed_at_mark} of {count}. "
                "Rerun with a larger count when this fails",
            ),
            (
                seqs == list(range(1, count + 1)),
                f"Cosmos DB holds {len(seqs)} items, seqs 1 to {count} each once",
            ),
            (
                len({item["id"] for item in found["items"]}) == len(found["items"]),
                "no item id repeats",
            ),
            (after == count, f"the copied mark ends at {after}"),
        ]
    )


SET_GITHUB = """
import json, sys, urllib.request
body = json.dumps({"mode": sys.argv[1]}).encode()
request = urllib.request.Request(
    "http://mock-github:8200/_admin/mode",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
urllib.request.urlopen(request, timeout=5).read()
"""


def set_github(stack: Stack, mode: str) -> None:
    stack.run("exec", "-T", "platform-api", "python", "-c", SET_GITHUB, mode)


def lane6(api: Api, out: Path) -> bool:
    stack = Stack()
    set_github(stack, "unavailable")
    try:
        run_id = api.start_run("alice", ensure_watchlist(api))
        run = api.wait(run_id, DONE | {"awaiting_approval"})
        status, answer = api.call("alice", "GET", f"/api/v1/runs/{run_id}/troubleshoot")
    finally:
        set_github(stack, "ok")
    found = wait_for_copy(stack, run_id, run["last_seq"])
    failed_items = [item for item in found["items"] if item["kind"] == "run_failed"]
    failed_item = failed_items[-1] if failed_items else None
    save(
        out,
        "p4-troubleshoot.json",
        {"run": run, "status": status, "answer": answer, "run_failed_item": failed_item},
    )
    failure = (answer or {}).get("failure") if isinstance(answer, dict) else None
    return verdict(
        [
            (run["state"] == "failed", f"the run is {run['state']}"),
            (status == 200, f"GET .../troubleshoot answered HTTP {status}"),
            (failed_item is not None, "Cosmos DB holds the run_failed item"),
            (
                failed_item is not None and failure == failed_item["data"],
                f"the answer's failure {failure} is the item's data "
                f"{failed_item and failed_item['data']}",
            ),
            (
                bool(failure) and bool(failure.get("stage")),
                f"the answer names the step that stopped: stage {failure and failure.get('stage')}",
            ),
        ]
    )


def lane7(api: Api, out: Path) -> bool:
    stack = Stack()
    connect_model(api)
    run_id = api.start_run("alice", agent_workflow(api, "lane7"))
    run = api.wait(run_id, SETTLED)
    if run["state"] != "awaiting_approval":
        raise SystemExit(f"run {run_id} is {run['state']}, not awaiting_approval")
    status, decided, digest = approve_as_bob(api, run)
    after = api.wait(run_id, DONE)
    found = wait_for_copy(stack, run_id, after["last_seq"])
    decisions = [item for item in found["items"] if item["kind"] == "approval_decided"]
    proposals = [item for item in found["items"] if item["kind"] == "write_action_proposed"]
    decision = decisions[-1] if decisions else None
    proposal = proposals[-1] if proposals else None
    save(
        out,
        "p4-decision-item.json",
        {
            "run_id": run_id,
            "decision_status": status,
            "decided": decided,
            "digest_bob_sent": digest,
            "decision_item": decision,
            "proposal_item": proposal,
            "note": "approval_decided has no digest field; the digest is on write_action_proposed",
        },
    )
    return verdict(
        [
            (status == 201, f"bob's decision answered HTTP {status}"),
            (
                decision is not None
                and decision["actor"]["id"] == "bob"
                and decision["data"]["by"] == "bob"
                and decision["data"]["verdict"] == "approve",
                f"the decision's item names bob: {decision and decision['data']}",
            ),
            (
                proposal is not None and proposal["data"]["digest"] == digest,
                f"the proposal's item holds the digest bob saw, {digest}",
            ),
        ]
    )


def server_time(api: Api) -> datetime:
    request = urllib.request.Request(f"{api.base}/healthz")
    with urllib.request.urlopen(request, timeout=10) as response:
        date = response.headers["date"]
    return datetime.strptime(date, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC)


def lane8(api: Api, out: Path) -> bool:
    stack = Stack()
    run_id = api.start_run("alice", ensure_watchlist(api))
    run = api.wait(run_id, SETTLED)
    if run["state"] != "awaiting_approval":
        raise SystemExit(f"run {run_id} is {run['state']}, not awaiting_approval")
    before_rows = stack.rows(run_id)
    before_items = wait_for_copy(stack, run_id, run["last_seq"])["items"]
    clock_before = server_time(api)
    stack.run("exec", "-T", "platform-api", "sh", "-c", "echo +2d > /tmp/faketime")
    clock_after = server_time(api)
    status, _, _ = approve_as_bob(api, run)
    after = api.wait(run_id, DONE)
    rows = stack.rows(run_id)
    items = wait_for_copy(stack, run_id, after["last_seq"])["items"]
    old = len(before_rows)
    new_rows = rows[old:]
    jumped = clock_after - clock_before
    save(
        out,
        "p4-long-run.json",
        {
            "run_id": run_id,
            "clock_before": clock_before,
            "clock_after": clock_after,
            "decision_status": status,
            "state": after["state"],
            "pg_rows_before": before_rows,
            "pg_rows_after": rows,
            "cosmos_seqs_before": seqs_of(before_items),
            "cosmos_seqs_after": seqs_of(items),
        },
    )
    first_new_ts = datetime.fromisoformat(new_rows[0]["ts"]) if new_rows else None
    last_old_ts = datetime.fromisoformat(before_rows[-1]["ts"]) if before_rows else None
    return verdict(
        [
            (jumped >= timedelta(hours=47), f"platform-api's clock moved {jumped}"),
            (
                status == 201 and after["state"] in DONE,
                f"bob approved; the run is {after['state']}",
            ),
            (
                bool(new_rows) and new_rows[0]["seq"] == old + 1,
                f"the new events number on from {old}: {[r['seq'] for r in new_rows]}",
            ),
            (
                first_new_ts is not None
                and last_old_ts is not None
                and first_new_ts - last_old_ts >= timedelta(hours=47),
                f"the first new event is stamped {first_new_ts}, the last old one {last_old_ts}",
            ),
            (gapless([r["seq"] for r in rows]), "PostgreSQL holds each seq once, with no gap"),
            (
                seqs_of(items) == [r["seq"] for r in rows],
                f"Cosmos DB holds the same seqs once: {seqs_of(items)}",
            ),
        ]
    )


def lane9(api: Api, out: Path, second: Api) -> bool:
    run_id = api.start_run("alice", ensure_watchlist(api))
    streams = {"api-1": Stream(api.base, run_id), "api-2": Stream(second.base, run_id)}
    run = api.wait(run_id, SETTLED)
    caught_up = {name: s.wait_for_seq(run["last_seq"]) for name, s in streams.items()}
    time.sleep(1)
    for stream in streams.values():
        stream.close()
    lines_out = [f"run {run_id} is {run['state']}, last_seq {run['last_seq']}"]
    for name, stream in streams.items():
        lines_out += [f"{name}: {e['seq']} {e['kind']}" for e in stream.events]
    save(out, "p4-two-replicas.txt", "\n".join(lines_out))
    expected = list(range(1, run["last_seq"] + 1))
    seen = {name: [e["seq"] for e in s.events] for name, s in streams.items()}
    return verdict(
        [
            *(
                (caught_up[name] and seen[name] == expected, f"{name} got {seen[name]}")
                for name in streams
            ),
            (
                kinds(streams["api-1"].events) == kinds(streams["api-2"].events),
                "both replicas streamed the same kinds in the same order",
            ),
        ]
    )


def lane10(api: Api, out: Path, lane1_json: str) -> bool:
    stack = Stack()
    stack.run("stop", "-t", "1", "cosmos")
    run_id, events, run, caught_up = streamed_run(api, ensure_watchlist(api))
    head = json.loads(Path(lane1_json).read_text())["head"]
    save(
        out,
        "p4-postgres-reader.json",
        {
            "run_id": run_id,
            "state": run["state"],
            "kinds": kinds(events),
            "seqs": [e["seq"] for e in events],
            "lane1_head_kinds": head["kinds"],
            "cosmos_health": stack.health("cosmos"),
        },
    )
    return verdict(
        [
            (stack.health("cosmos") != "healthy", "the emulator is stopped"),
            (caught_up and gapless([e["seq"] for e in events]), f"run {run_id}: {run['state']}"),
            (
                kinds(events) == head["kinds"],
                f"the stream holds lane 1's head kinds: {kinds(events)}",
            ),
        ]
    )


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    command, base, out = argv[0], argv[1], Path(argv[2])
    rest = argv[3:]
    api = Api(base)
    lanes: dict[str, Any] = {
        "lane1": lambda: lane1(api, out, Api(rest[0])),
        "lane2": lambda: lane2(api, out, rest[0]),
        "lane3": lambda: lane3(api, out, rest[0]),
        "lane4": lambda: lane4(api, out),
        "lane5": lambda: lane5(api, out, rest[0], int(rest[1]) if len(rest) > 1 else 600),
        "lane6": lambda: lane6(api, out),
        "lane7": lambda: lane7(api, out),
        "lane8": lambda: lane8(api, out),
        "lane9": lambda: lane9(api, out, Api(rest[0])),
        "lane10": lambda: lane10(api, out, rest[0]),
    }
    if command not in lanes:
        print(__doc__)
        return 2
    return 0 if lanes[command]() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
