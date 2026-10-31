"""Lanes for the P4 checker: the activity log's copy in Cosmos DB. Standard library only. Each
command saves what it saw in the folder it is given and prints PASS or FAIL.

usage: python3 -I scripts/checks/p4_lanes.py <command> <api-base-url> <out-dir> [arguments]

  lane1 <trunk-api> <out> <head-api>     a watchlist check streamed at trunk and at head
  lane2 <api> <out> <run-id>             the run's items, then every item against PostgreSQL
  lane3 <api> <out> <run-id>             the stream again with Last-Event-ID 3
  lane4 <api> <out>                      (own stack) the emulator is down for a whole run
  lane5 <api> <out> <signing-key> [n]    (own stack) platform-api is killed in the middle of a copy
  lane6 <api> <out>                      (own stack) a run fails on purpose; its troubleshooter
  lane7 <api> <out>                      bob approves a run; the decision's item in Cosmos DB
  lane8 <api> <out>                      (own stack, libfaketime) two days pass before the yes
  lane9 <api> <out> <second-api> <key>   (own stack) two platform-api replicas stream one run
  lane10 <api> <out> <lane-1 json>       (own stack, ACTIVITY_READER=postgres) emulator stopped
  lane11 <api> <out> <signing-key> [n]   (own stack) n agent events [4000], then the emulator is
                                         made again while the API runs and nothing is logged;
                                         then a new run
  lane12 <api> <out>                     (own stack) down without -v, then up; every old run

P4_COMPOSE holds the lane stack's docker compose command, for example
    docker compose -p p4-check --env-file /tmp/swarm-p4/env/.env \\
        -f <src>/deploy/compose.yaml -f <src>/deploy/compose.e2e.yaml
Lane 12 runs `up` itself, so it also needs the stack's WAB_IMAGE_TAG and host ports in its
environment; p4.sh passes them. The lanes read Cosmos DB through a short script in that stack's
platform-api container, and PostgreSQL through psql in its postgres container. Lanes 1, 9 and 10
compare the kinds of events.
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
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

WAIT_SECONDS = 150
SETTLED = {"awaiting_approval", "succeeded", "failed", "rejected"}
DONE = {"succeeded", "failed", "rejected"}
MOCK_MODEL_URL = "http://mock-model:8300"
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
VALUES = {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}
MARKER = "P4-MARKER: this text exists only in the Cosmos DB item"
COSMOS_ADDRESS = "cosmos:8081"
LANE9_EVENTS = 1000

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
        if len(sys.argv) > 1:
            query = container.query_items("SELECT * FROM c", partition_key=sys.argv[1])
        else:
            query = container.query_items("SELECT * FROM c")
        found = [item async for item in query]
    events = sorted((i for i in found if "seq" in i), key=lambda i: (i["runId"], i["seq"]))
    print(json.dumps({
        "partition_key": properties["partitionKey"],
        "rid": properties["_rid"],
        "generation": [i.get("generation") for i in found if "seq" not in i],
        "items": events,
    }))

asyncio.run(main())
"""

PATCH_ITEM = """
import asyncio, json, os, sys
from azure.cosmos.aio import CosmosClient

async def main(run_id, seq, field, value):
    async with CosmosClient(
        os.environ["COSMOS_ENDPOINT"],
        credential=os.environ["COSMOS_KEY"],
        enable_endpoint_discovery=False,
    ) as client:
        container = client.get_database_client("activity").get_container_client("run_events")
        item = await container.read_item(str(seq), partition_key=run_id)
        *path, last = field.split(".")
        target = item
        for key in path:
            target = target[key]
        old = target[last]
        target[last] = value
        await container.upsert_item({k: v for k, v in item.items() if not k.startswith("_")})
    print(json.dumps({"old": old, "new": value}))

asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]))
"""

LAST_SEQS = (
    "SELECT coalesce(json_object_agg(run_id, seq), '{}') FROM "
    "(SELECT run_id, max(seq) AS seq FROM monitoring.run_events GROUP BY run_id) AS runs;"
)

ALL_ROWS = (
    "SELECT coalesce(json_agg(json_build_object('run_id', run_id, 'seq', seq, 'ts', ts, "
    "'actor', actor, 'kind', kind, 'summary', summary, 'data', data, "
    "'dedupe_key', dedupe_key) ORDER BY run_id, seq), '[]') FROM monitoring.run_events;"
)

GRANTS = """
SELECT json_object_agg(t.name || ' ' || r.rolname, concat_ws(',',
    CASE WHEN has_table_privilege(r.rolname, t.name, 'SELECT') THEN 'select' END,
    CASE WHEN has_table_privilege(r.rolname, t.name, 'INSERT') THEN 'insert' END,
    CASE WHEN has_table_privilege(r.rolname, t.name, 'UPDATE') THEN 'update' END,
    CASE WHEN has_table_privilege(r.rolname, t.name, 'DELETE') THEN 'delete' END,
    CASE WHEN has_table_privilege(r.rolname, t.name, 'TRUNCATE') THEN 'truncate' END)
    ORDER BY t.name, r.rolname)
FROM pg_roles AS r
CROSS JOIN (VALUES ('monitoring.run_events'), ('monitoring.run_events_copied')) AS t(name)
WHERE r.rolname IN ('n8n', 'wab_builder', 'wab_monitoring', 'wab_orchestration');
"""
TODAYS_GRANTS = {
    "monitoring.run_events n8n": "",
    "monitoring.run_events wab_builder": "",
    "monitoring.run_events wab_monitoring": "select,insert",
    "monitoring.run_events wab_orchestration": "select,insert",
    "monitoring.run_events_copied n8n": "",
    "monitoring.run_events_copied wab_builder": "",
    "monitoring.run_events_copied wab_monitoring": "select,insert,update",
    "monitoring.run_events_copied wab_orchestration": "",
}


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

    def ready(self) -> dict[str, Any]:
        status, body = self.call(None, "GET", "/healthz/ready")
        checks = body.get("checks", []) if isinstance(body, dict) else []
        copy = next((c for c in checks if c["name"] == "activity_copy"), None)
        return {"status": status, "body": body, "copy": copy}


def copy_behind(ready: dict[str, Any]) -> bool:
    return ready["copy"] is not None and "behind" in ready["copy"]["detail"]


def ready_without_cosmos(ready: dict[str, Any]) -> bool:
    copy = ready["copy"]
    return (
        ready["status"] == 200
        and copy is not None
        and copy["ok"]
        and COSMOS_ADDRESS not in json.dumps(ready["body"])
    )


def wait_behind(api: Api, timeout: float = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    ready = api.ready()
    while not copy_behind(ready) and time.monotonic() < deadline:
        time.sleep(0.5)
        ready = api.ready()
    return ready


def wait_caught_up(api: Api, timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    ready = api.ready()
    while copy_behind(ready) and time.monotonic() < deadline:
        time.sleep(0.5)
        ready = api.ready()
    return ready


class Stream:
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
        self.error: str | None = None
        self.arrived = threading.Condition()
        self.closed = threading.Event()
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
        except Exception as error:
            if not self.closed.is_set():
                self.error = repr(error)

    def wait_for_seq(self, seq: int, timeout: float = 30) -> bool:
        deadline = time.monotonic() + timeout
        with self.arrived:
            while not any(e["seq"] >= seq for e in self.events):
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self.arrived.wait(left)
        return True

    def seqs(self) -> list[int]:
        return [e["seq"] for e in self.events]

    def close(self) -> None:
        self.closed.set()
        self.response.close()


class Stack:
    def __init__(self) -> None:
        command = os.environ.get("P4_COMPOSE")
        if not command:
            raise SystemExit("set P4_COMPOSE to the lane stack's docker compose command")
        self.compose = shlex.split(command)

    def attempt(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.compose, *args], input=stdin, capture_output=True, text=True, check=False
        )

    def run(self, *args: str, stdin: str | None = None, check: bool = True) -> str:
        done = self.attempt(*args, stdin=stdin)
        if check and done.returncode != 0:
            raise SystemExit(f"{' '.join(args)}: {done.stderr.strip()}"[:800])
        return done.stdout

    def cosmos(self, run_id: str | None = None) -> dict[str, Any]:
        args = [run_id] if run_id is not None else []
        done = self.attempt("exec", "-T", "platform-api", "python", "-c", COSMOS_ITEMS, *args)
        if done.returncode != 0:
            error = (done.stderr.strip().splitlines() or ["no output"])[-1]
            return {
                "partition_key": None,
                "rid": None,
                "generation": [],
                "items": [],
                "error": error,
            }
        return json.loads(done.stdout.strip().splitlines()[-1])

    def patch(self, run_id: str, seq: int, field: str, value: str) -> Any:
        out = self.run(
            "exec", "-T", "platform-api", "python", "-c", PATCH_ITEM, run_id, str(seq), field, value
        )
        return json.loads(out.strip().splitlines()[-1])

    def sql(self, statement: str, run_id: str = "") -> Any:
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

    def last_seqs(self) -> dict[str, int]:
        return self.sql(LAST_SEQS)

    def mark(self, run_id: str) -> int:
        return self.sql(
            "SELECT coalesce((SELECT seq FROM monitoring.run_events_copied "
            "WHERE run_id = :'run'), 0);",
            run_id,
        )

    def container(self, service: str) -> str:
        return self.run("ps", "-q", service).strip()

    def inspect(self, service: str, template: str) -> str:
        container = self.container(service)
        if not container:
            return "absent"
        done = subprocess.run(
            ["docker", "inspect", "--format", template, container],
            capture_output=True,
            text=True,
            check=False,
        )
        return done.stdout.strip()

    def health(self, service: str) -> str:
        return self.inspect(service, "{{.State.Health.Status}}")

    def started_at(self, service: str) -> str:
        return self.inspect(service, "{{.Id}} {{.State.StartedAt}}")

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


def verdict(lines: list[tuple[bool, str]], notes: list[str] | None = None) -> bool:
    for note in notes or []:
        print("note " + note)
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


def same(row: dict[str, Any], item: dict[str, Any]) -> bool:
    return (
        item["id"] == str(row["seq"])
        and item["kind"] == row["kind"]
        and item["summary"] == row["summary"]
        and item["data"] == row["data"]
        and item["actor"] == row["actor"]
        and item["dedupeKey"] == row["dedupe_key"]
        and datetime.fromisoformat(item["ts"]) == datetime.fromisoformat(row["ts"])
    )


def compare(stack: Stack) -> dict[str, Any]:
    found = stack.cosmos()
    rows = stack.sql(ALL_ROWS)
    by_row = {(r["run_id"], r["seq"]): r for r in rows}
    by_item: dict[tuple[str, int], dict[str, Any]] = {}
    repeated: list[tuple[str, int]] = []
    for item in found["items"]:
        key = (item["runId"], item["seq"])
        if key in by_item:
            repeated.append(key)
        by_item[key] = item
    missing = sorted(by_row.keys() - by_item.keys())
    extra = sorted(by_item.keys() - by_row.keys())
    differ = [k for k in sorted(by_row.keys() & by_item.keys()) if not same(by_row[k], by_item[k])]
    runs = sorted({run for run, _ in by_row})
    pg_gapless = all(gapless(sorted(s for r, s in by_row if r == run)) for run in runs)
    return {
        "ok": not (missing or extra or repeated or differ) and pg_gapless and "error" not in found,
        "pg_rows": len(rows),
        "cosmos_items": len(found["items"]),
        "runs": len(runs),
        "missing": len(missing),
        "extra": len(extra),
        "repeated": len(repeated),
        "differ": len(differ),
        "pg_gapless_per_run": pg_gapless,
        "error": found.get("error"),
        "first_missing": missing[:10],
        "first_extra": extra[:10],
        "first_differ": [{"pg": by_row[k], "cosmos": by_item[k]} for k in differ[:3]],
    }


def settled_compare(stack: Stack, timeout: float = 90) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    compared = compare(stack)
    while not compared["ok"] and time.monotonic() < deadline:
        time.sleep(2)
        compared = compare(stack)
    return compared


def compared_line(compared: dict[str, Any]) -> str:
    counts = {k: compared[k] for k in ("pg_rows", "cosmos_items", "runs", "missing", "extra")}
    counts |= {k: compared[k] for k in ("repeated", "differ")}
    return f"every PostgreSQL row has one equal item in Cosmos DB, and nothing else: {counts}"


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


def replay(api: Api, run_id: str, last_seq: int, timeout: float = 30) -> list[int]:
    stream = Stream(api.base, run_id)
    stream.wait_for_seq(last_seq, timeout=timeout)
    time.sleep(1)
    stream.close()
    return stream.seqs()


def timed_page(api: Api, run_id: str) -> dict[str, Any]:
    started = time.monotonic()
    events = api.events(run_id)
    return {"seqs": [e["seq"] for e in events], "seconds": round(time.monotonic() - started, 2)}


def patch_copy_then_read_page(api: Api, stack: Stack, run_id: str) -> tuple[bool, float, Any]:
    patched = stack.patch(run_id, 1, "summary", MARKER)
    started = time.monotonic()
    events = api.events(run_id)
    took = time.monotonic() - started
    return bool(events) and events[0]["summary"] == MARKER, took, patched


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
    compared = settled_compare(stack)
    grants = stack.sql(GRANTS)
    save(out, "p4-items.json", {"run": run, **found})
    save(out, "p4-compare.json", compared)
    save(out, "p4-grants.json", grants)
    return verdict(
        [
            (
                found["partition_key"] is not None
                and found["partition_key"]["paths"] == ["/runId"],
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
            (compared["ok"], compared_line(compared)),
            (grants == TODAYS_GRANTS, f"the activity log keeps today's grants: {grants}"),
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
                stream.seqs() == list(range(4, 4 + len(stream.events))),
                f"then {stream.seqs()} in order",
            ),
        ]
    )


def lane4(api: Api, out: Path) -> bool:
    stack = Stack()
    connect_model(api)
    use_case = agent_workflow(api, "lane4")
    stack.run("stop", "-t", "1", "cosmos")
    stopped_at = datetime.now(UTC).isoformat()
    run_id = api.start_run("alice", use_case)
    stream = Stream(api.base, run_id)
    run = api.wait(run_id, SETTLED)
    approved = None
    if run["state"] == "awaiting_approval":
        approved, _, _ = approve_as_bob(api, run)
    done = api.wait(run_id, DONE)
    copied_while_down = stack.mark(run_id)
    ready_down = wait_behind(api)
    stream.wait_for_seq(done["last_seq"], timeout=15)
    streamed_while_down = stream.seqs()
    stack.run("start", "cosmos")
    stack.wait_healthy("cosmos")
    started_at = datetime.now(UTC).isoformat()
    found = wait_for_copy(stack, run_id, done["last_seq"])
    stream.wait_for_seq(done["last_seq"], timeout=60)
    time.sleep(1)
    stream.close()
    ready_after = wait_caught_up(api)
    compared = settled_compare(stack)
    logs = stack.run("logs", "--no-color", "platform-api", check=False)
    warnings = [line for line in logs.splitlines() if "Could not copy" in line]
    expected = list(range(1, done["last_seq"] + 1))
    save(
        out,
        "p4-emulator-down.json",
        {
            "run_id": run_id,
            "stopped_at": stopped_at,
            "started_at": started_at,
            "state_at_the_gate": run["state"],
            "approve_status": approved,
            "run": done,
            "mark_while_down": copied_while_down,
            "streamed_while_down": streamed_while_down,
            "ready_while_down": ready_down,
            "ready_after": ready_after,
            "pg_rows": stack.rows(run_id),
            "cosmos": found,
            "streamed_across_the_outage": stream.seqs(),
            "copier_warnings": warnings[:20],
            "compare": compared,
        },
    )
    return verdict(
        [
            (
                run["state"] == "awaiting_approval" and approved == 201,
                f"bob approved while the emulator was down: HTTP {approved}",
            ),
            (
                done["state"] == "succeeded",
                f"the run finished in PostgreSQL with the emulator down: {done['state']}, "
                f"last_seq {done['last_seq']}",
            ),
            (
                copied_while_down < done["last_seq"],
                f"while the emulator was down the mark stayed at {copied_while_down} "
                f"of {done['last_seq']}",
            ),
            (bool(warnings), f"the copier logged {len(warnings)} failed copies"),
            (
                ready_without_cosmos(ready_down) and copy_behind(ready_down),
                f"readiness while down: HTTP {ready_down['status']}, {ready_down['copy']}",
            ),
            (
                streamed_while_down == expected,
                f"while the emulator was down the open stream got {streamed_while_down} "
                "from PostgreSQL",
            ),
            (
                seqs_of(found["items"]) == expected,
                f"after the restart Cosmos DB holds {len(found['items'])} of {done['last_seq']}",
            ),
            (
                stream.seqs() == expected,
                f"a stream held open across the outage got {stream.seqs()}, each once, in order",
            ),
            (
                ready_after["status"] == 200 and not copy_behind(ready_after),
                f"readiness once caught up: {ready_after['copy']}",
            ),
            (compared["ok"], compared_line(compared)),
        ]
    )


def signed(key: str, run_id: str, task_id: str) -> str:
    expires = int(time.time()) + 3600
    message = f"{run_id}|{task_id}|{expires}".encode()
    return f"{expires}.{hmac.new(key.encode(), message, hashlib.sha256).hexdigest()}"


def post_agent_events(apis: list[Api], run_id: str, key: str, count: int, agent: str) -> int:
    task_id = f"{run_id}/work/1/1"
    token = signed(key, run_id, task_id)
    task = urllib.parse.quote(task_id, safe="")
    accepted = 0
    for n in range(1, count + 1):
        event = {
            "agent_seq": n,
            "ts": datetime.now(UTC).isoformat(),
            "agent": {"id": agent, "display": agent},
            "summary": f"{agent} event {n}.",
            "kind": "agent_step_started",
            "data": {"step": f"step {n}"},
        }
        status, _ = apis[n % len(apis)].call(
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
    accepted = post_agent_events([api], run_id, key, count, "p4_lane5")
    stack.run("start", "cosmos")
    deadline = time.monotonic() + 240
    mark = stack.mark(run_id)
    while mark == 0 and time.monotonic() < deadline:
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
                "Rerun with a larger LANE5_EVENTS when this fails",
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
    finally:
        set_github(stack, "ok")
    found = wait_for_copy(stack, run_id, run["last_seq"])
    status, answer = api.call("alice", "GET", f"/api/v1/runs/{run_id}/troubleshoot")
    failed_items = [item for item in found["items"] if item["kind"] == "run_failed"]
    failed_item = failed_items[-1] if failed_items else None
    patched = marked_status = marked = None
    if failed_item is not None:
        patched = stack.patch(run_id, failed_item["seq"], "data.message", MARKER)
        marked_status, marked = api.call("alice", "GET", f"/api/v1/runs/{run_id}/troubleshoot")
    save(
        out,
        "p4-troubleshoot.json",
        {
            "run": run,
            "status": status,
            "answer": answer,
            "run_failed_item": failed_item,
            "patched_in_cosmos_only": patched,
            "status_after_patch": marked_status,
            "answer_after_patch": marked,
        },
    )
    failure = (answer or {}).get("failure") if isinstance(answer, dict) else None
    marked_failure = (marked or {}).get("failure") if isinstance(marked, dict) else None
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
            (
                marked_status == 200
                and bool(marked_failure)
                and marked_failure.get("message") == MARKER,
                "after the item's message changed in Cosmos DB only, the answer carries it: "
                f"{marked_failure and marked_failure.get('message')}",
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
        },
    )
    decided_digest = decision and decision["data"].get("digest")
    proposed_digest = proposal and proposal["data"]["digest"]
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
                decided_digest == digest,
                f"the decision's item holds the digest bob sent, {decided_digest} vs {digest}",
            ),
            (
                decided_digest == proposed_digest,
                f"it is the digest write_action_proposed showed, {proposed_digest}",
            ),
        ]
    )


def server_time(api: Api) -> datetime:
    request = urllib.request.Request(f"{api.base}/healthz")
    with urllib.request.urlopen(request, timeout=10) as response:
        date = response.headers["date"]
    return datetime.strptime(date, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC)


def server_time_after_the_jump(api: Api, before: datetime, timeout: float = 5) -> datetime:
    """uvicorn makes its Date header once a second, so the new clock shows after a second."""
    deadline = time.monotonic() + timeout
    after = server_time(api)
    while after - before < timedelta(hours=47) and time.monotonic() < deadline:
        time.sleep(0.5)
        after = server_time(api)
    return after


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
    clock_after = server_time_after_the_jump(api, clock_before)
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
            "clock_moved": "platform-api only",
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
            (
                jumped >= timedelta(hours=47),
                f"platform-api's clock moved {jumped}. Only platform-api's clock moves; "
                "it stamps the run's events and the decision",
            ),
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


def lane9(api: Api, out: Path, second: Api, key: str) -> bool:
    stack = Stack()
    run_id = api.start_run("alice", ensure_watchlist(api))
    streams = {"api-1": Stream(api.base, run_id), "api-2": Stream(second.base, run_id)}
    run = api.wait(run_id, SETTLED)
    caught_up = {name: s.wait_for_seq(run["last_seq"]) for name, s in streams.items()}
    time.sleep(1)
    for stream in streams.values():
        stream.close()
    many = f"run_p4lane9{uuid.uuid4().hex[:12]}"
    busy = {"api-1": Stream(api.base, many), "api-2": Stream(second.base, many)}
    time.sleep(0.5)
    accepted = post_agent_events([api, second], many, key, LANE9_EVENTS, "p4_lane9")
    busy_caught_up = {name: s.wait_for_seq(LANE9_EVENTS, 60) for name, s in busy.items()}
    time.sleep(1)
    for stream in busy.values():
        stream.close()
    compared = settled_compare(stack)
    lines_out = [f"run {run_id} is {run['state']}, last_seq {run['last_seq']}"]
    for name, stream in streams.items():
        lines_out += [f"{name}: {e['seq']} {e['kind']}" for e in stream.events]
    for name, stream in busy.items():
        lines_out.append(f"{name}: run {many} got {len(stream.events)} events")
    save(out, "p4-two-replicas.txt", "\n".join(lines_out))
    save(
        out,
        "p4-two-replicas-1000.json",
        {
            "run_id": many,
            "accepted": accepted,
            **{name: s.seqs() for name, s in busy.items()},
            "compare": compared,
        },
    )
    expected = list(range(1, run["last_seq"] + 1))
    many_expected = list(range(1, LANE9_EVENTS + 1))
    return verdict(
        [
            *(
                (caught_up[name] and s.seqs() == expected, f"{name} got {s.seqs()}")
                for name, s in streams.items()
            ),
            (
                kinds(streams["api-1"].events) == kinds(streams["api-2"].events),
                "both replicas streamed the same kinds in the same order",
            ),
            (
                accepted == LANE9_EVENTS,
                f"{accepted} of {LANE9_EVENTS} events posted, alternating between the replicas",
            ),
            *(
                (
                    busy_caught_up[name] and s.seqs() == many_expected,
                    f"{name} streamed {len(s.events)} of {LANE9_EVENTS} events, each once, "
                    "in order",
                )
                for name, s in busy.items()
            ),
            (compared["ok"], compared_line(compared)),
        ]
    )


def lane10(api: Api, out: Path, lane1_json: str) -> bool:
    stack = Stack()
    stack.run("stop", "-t", "1", "cosmos")
    run_id, events, run, caught_up = streamed_run(api, ensure_watchlist(api))
    head = json.loads(Path(lane1_json).read_text())["head"]
    ready = wait_behind(api)
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
            "ready": ready,
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
            (
                ready_without_cosmos(ready) and copy_behind(ready),
                f"readiness: HTTP {ready['status']}, {ready['copy']}, and it never names "
                f"{COSMOS_ADDRESS}",
            ),
        ]
    )


def old_runs(api: Api, stack: Stack, count: int = 2) -> dict[str, int]:
    use_case = ensure_watchlist(api)
    for _ in range(count):
        streamed_run(api, use_case)
    runs = stack.last_seqs()
    for run_id, last_seq in runs.items():
        wait_for_copy(stack, run_id, last_seq)
    return runs


def backlog(api: Api, stack: Stack, key: str, count: int) -> dict[str, Any]:
    """Agent events on a run of their own, all copied before the emulator goes, so that making
    the copy again takes long enough to watch."""
    run_id = f"run_p4lane11{uuid.uuid4().hex[:12]}"
    accepted = post_agent_events([api], run_id, key, count, "p4_lane11")
    found = wait_for_copy(stack, run_id, count, timeout=180)
    return {"run_id": run_id, "posted": count, "accepted": accepted, "copied": len(found["items"])}


def watch_the_refill(
    api: Api, stack: Stack, stop: threading.Event, timeout: float = 420
) -> list[dict[str, Any]]:
    """Readiness, then the copy, then readiness again, from before the emulator is made again
    until the copy is full. The copy only grows, so a sample that says caught up while its copy
    is short is a real miss. Readiness read again right after a short copy ("behind_after") shows
    the refill was seen while it ran."""
    started = time.monotonic()
    deadline = started + timeout
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline and not stop.is_set():
        ready = api.ready()
        found = stack.cosmos()
        then = api.ready()
        samples.append(
            {
                "t": round(time.monotonic() - started, 2),
                "at": datetime.now(UTC).isoformat(),
                "behind": copy_behind(ready),
                "detail": ready["copy"]["detail"] if ready["copy"] else None,
                "items": len(found["items"]),
                "error": found.get("error"),
                "behind_after": copy_behind(then),
            }
        )
        if not samples[-1]["behind"] and "error" not in found and samples[-1]["items"] > 0:
            break
        time.sleep(0.5)
    return samples


def refill_lines(
    samples: list[dict[str, Any]], rows: int, refill_seconds: float | None
) -> list[tuple[bool, str]]:
    said_caught_up_short = [
        x for x in samples if not x["behind"] and (x["error"] or x["items"] < rows)
    ]
    # The emulator answered, its copy was short, and readiness said behind right after.
    seen_behind = [x for x in samples if not x["error"] and x["items"] < rows and x["behind_after"]]
    last = samples[-1] if samples else {"behind": True, "items": 0, "detail": None}
    behind_samples = sum(x["behind"] for x in samples)
    return [
        (
            bool(samples) and not last["behind"] and last["items"] == rows,
            f"with nothing logged, the copy was full again {refill_seconds} s after the "
            f"emulator first answered, and readiness then said {last['detail']!r}",
        ),
        (
            bool(seen_behind),
            f"readiness said behind right after the emulator answered with a short copy, in "
            f"{len(seen_behind)} of {len(samples)} samples, so the next line can fail. Rerun "
            "with a larger LANE11_EVENTS when this is 0",
        ),
        (
            not said_caught_up_short,
            f"readiness said behind until the refill ended ({behind_samples} of "
            f"{len(samples)} samples); it never said caught up while the copy was short: "
            f"{said_caught_up_short}",
        ),
    ]


def lane11(api: Api, out: Path, key: str, count: int) -> bool:
    stack = Stack()
    runs = old_runs(api, stack)
    queued = backlog(api, stack, key, count)
    rows = sum(stack.last_seqs().values())
    before = stack.cosmos()
    api_before = stack.started_at("platform-api")
    stack.run("rm", "-sf", "cosmos")
    removed_at = datetime.now(UTC).isoformat()
    ready_gone = wait_behind(api)
    streams_gone = {run_id: replay(api, run_id, last_seq) for run_id, last_seq in runs.items()}
    pages_gone = {run_id: timed_page(api, run_id) for run_id in runs}
    # Sampling starts before `up`: the copy can be full again before `up --wait` returns.
    stop = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        watching = pool.submit(watch_the_refill, api, stack, stop)
        try:
            stack.run("up", "-d", "--no-deps", "--wait", "cosmos")
        except BaseException:
            stop.set()
            raise
        made_again_at = datetime.now(UTC).isoformat()
        samples = watching.result()
    answered = next((x for x in samples if not x["error"]), None)
    refill_seconds = round(samples[-1]["t"] - answered["t"], 2) if answered else None
    logged_meanwhile = sum(stack.last_seqs().values()) - rows
    after = stack.cosmos()
    compared = settled_compare(stack)
    streams_after = {run_id: replay(api, run_id, last_seq) for run_id, last_seq in runs.items()}
    first = next(iter(runs))
    from_cosmos, took, patched = patch_copy_then_read_page(api, stack, first)
    use_case = ensure_watchlist(api)
    new_id = api.start_run("alice", use_case)
    stream = Stream(api.base, new_id)
    new_run = api.wait(new_id, SETTLED)
    new_found = wait_for_copy(stack, new_id, new_run["last_seq"], timeout=60)
    stream.wait_for_seq(new_run["last_seq"], timeout=60)
    time.sleep(1)
    stream.close()
    ready = wait_caught_up(api)
    api_after = stack.started_at("platform-api")
    expected = {run_id: list(range(1, last_seq + 1)) for run_id, last_seq in runs.items()}
    save(
        out,
        "p4-emulator-made-again.json",
        {
            "old_runs": runs,
            "backlog": queued,
            "rows": rows,
            "removed_at": removed_at,
            "made_again_at": made_again_at,
            "platform_api_before": api_before,
            "platform_api_after": api_after,
            "rid_before": before["rid"],
            "rid_after": after["rid"],
            "generation_before": before["generation"],
            "generation_after": after["generation"],
            "ready_while_gone": ready_gone,
            "streams_while_gone": streams_gone,
            "pages_while_gone": pages_gone,
            "refill_samples": samples,
            "refill_seconds": refill_seconds,
            "logged_meanwhile": logged_meanwhile,
            "streams_after": streams_after,
            "compare": compared,
            "page_read_seconds": took,
            "patched_in_cosmos_only": patched,
            "new_run": {"run_id": new_id, "last_seq": new_run["last_seq"], **new_found},
            "new_run_streamed": stream.seqs(),
            "ready": ready,
        },
    )
    return verdict(
        [
            (api_before == api_after, f"platform-api ran throughout: {api_after}"),
            (
                queued["accepted"] == count and queued["copied"] == count,
                f"a backlog of {queued['accepted']} of {count} agent events on "
                f"{queued['run_id']}, {queued['copied']} copied before the emulator went",
            ),
            (
                len(runs) >= 2 and before["generation"] != after["generation"],
                f"{len(runs)} old runs; the new container has a new generation: "
                f"{before['generation']} then {after['generation']}",
            ),
            (
                ready_without_cosmos(ready_gone) and copy_behind(ready_gone),
                f"readiness with the emulator gone: HTTP {ready_gone['status']}, "
                f"{ready_gone['copy']}",
            ),
            (
                streams_gone == expected,
                f"with the emulator gone every old run's stream replayed in full: {streams_gone}",
            ),
            (
                all(page["seqs"] == expected[r] for r, page in pages_gone.items()),
                f"with the emulator gone every old run's page read: {pages_gone}",
            ),
            (
                logged_meanwhile == 0,
                f"nothing was logged while the copy was made again ({logged_meanwhile} new events)",
            ),
            *refill_lines(samples, rows, refill_seconds),
            (compared["ok"], compared_line(compared)),
            (
                streams_after == expected,
                f"after the refill every old run's stream replayed in full: {streams_after}",
            ),
            (from_cosmos, f"an old run's page came from Cosmos DB, in {took:.2f} s"),
            (
                seqs_of(new_found["items"]) == list(range(1, new_run["last_seq"] + 1)),
                f"run {new_id}, started after, reached Cosmos DB: {seqs_of(new_found['items'])}",
            ),
            (
                stream.seqs() == list(range(1, new_run["last_seq"] + 1)),
                f"its stream got {stream.seqs()}, each once, in order",
            ),
            (
                ready["status"] == 200 and not copy_behind(ready),
                f"readiness at the end: {ready['copy']}",
            ),
        ],
        [f"the container's _rid was {before['rid']} and is {after['rid']}"],
    )


def lane12(api: Api, out: Path) -> bool:
    stack = Stack()
    runs = old_runs(api, stack)
    before = stack.cosmos()
    stack.run("down")
    stack.run("up", "--no-build", "--wait", "--wait-timeout", "420")
    kept = {run_id: api.get("alice", f"/api/v1/runs/{run_id}")["last_seq"] for run_id in runs}
    compared = settled_compare(stack, timeout=120)
    after = stack.cosmos()
    replays = {run_id: replay(api, run_id, last_seq) for run_id, last_seq in runs.items()}
    pages = {run_id: patch_copy_then_read_page(api, stack, run_id) for run_id in runs}
    ready = wait_caught_up(api)
    expected = {run_id: list(range(1, last_seq + 1)) for run_id, last_seq in runs.items()}
    save(
        out,
        "p4-down-up.json",
        {
            "old_runs": runs,
            "kept_in_postgresql": kept,
            "rid_before": before["rid"],
            "rid_after": after["rid"],
            "generation_before": before["generation"],
            "generation_after": after["generation"],
            "compare": compared,
            "replayed": replays,
            "pages": {
                run_id: {"from_cosmos": ok, "seconds": took, "patched": patched}
                for run_id, (ok, took, patched) in pages.items()
            },
            "ready": ready,
        },
    )
    return verdict(
        [
            (
                len(runs) >= 2 and kept == runs,
                f"PostgreSQL kept every old run with its last_seq: {kept}",
            ),
            (
                before["generation"] != after["generation"] and bool(after["generation"]),
                f"the new emulator's container has a new generation: {before['generation']} "
                f"then {after['generation']}",
            ),
            (compared["ok"], compared_line(compared)),
            (
                replays == expected,
                f"every old run's stream replayed in full, each once, in order: {replays}",
            ),
            (
                all(ok for ok, _, _ in pages.values()),
                "every old run's page came from Cosmos DB: "
                + ", ".join(f"{r} {took:.2f} s" for r, (_, took, _) in pages.items()),
            ),
            (
                ready["status"] == 200 and not copy_behind(ready),
                f"readiness at the end: {ready['copy']}",
            ),
        ],
        [f"the container's _rid was {before['rid']} and is {after['rid']}"],
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
        "lane5": lambda: lane5(api, out, rest[0], int(rest[1]) if len(rest) > 1 else 4000),
        "lane6": lambda: lane6(api, out),
        "lane7": lambda: lane7(api, out),
        "lane8": lambda: lane8(api, out),
        "lane9": lambda: lane9(api, out, Api(rest[0]), rest[1]),
        "lane10": lambda: lane10(api, out, rest[0]),
        "lane11": lambda: lane11(api, out, rest[0], int(rest[1]) if len(rest) > 1 else 4000),
        "lane12": lambda: lane12(api, out),
    }
    if command not in lanes:
        print(__doc__)
        return 2
    return 0 if lanes[command]() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
