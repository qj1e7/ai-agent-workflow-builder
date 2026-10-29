"""API lanes for the P2 checker. Standard library only. Each command saves its responses as JSON
in the folder it is given and prints PASS or FAIL lines.

usage: python3 -I scripts/checks/p2_lanes.py <command> <api-base-url> <out-dir> [arguments]

  check <api> <out> <file> <name> <repo> <ours>   alice watches one software and presses Check now
  lane2 <api> <out>                                LangGraph check; the events name the Planner and the Version checker
  lane4 <api> <out> <run_id>                       bob approves; one new practice Jira ticket, the run ends succeeded
  lane5 <api> <out> <run_id>                       alice approves her own run; 403, nothing written
  lane6 <api> <out> <run_id>                       bob replays a decision with a changed digest; refused, nothing written
  lane7 <api> <out>                                POST /api/v1/use-cases with template release_check; 422 naming it
  release-check <api> <out>                        (trunk only) create and run an old release-check use case
  wait <api> <out> <run_id> <states,...> <file>    poll a run until one of the states
  retry <api> <out> <run_id>                       alice retries a failed run and waits for the approval request
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

RETIRED = re.compile(r"room[ _-]?lead|roomlead|release[ _-]?checker|release_check", re.IGNORECASE)
STALE_DIGEST = "sha256:" + "0" * 64
WAIT_SECONDS = 120


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
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        all_headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if user is not None:
            all_headers["X-Dev-User"] = user
        all_headers.update(headers or {})
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers=all_headers
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        try:
            parsed: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw.decode(errors="replace")
        self.log.append(
            {
                "user": user,
                "method": method,
                "path": path,
                "body": body,
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

    def start_run(self, user: str, use_case_id: str) -> tuple[int, Any]:
        return self.call(
            user,
            "POST",
            f"/api/v1/use-cases/{use_case_id}/runs",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )

    def wait(self, user: str, run_id: str, states: set[str]) -> Any:
        deadline = time.monotonic() + WAIT_SECONDS
        run = None
        while time.monotonic() < deadline:
            status, run = self.call(user, "GET", f"/api/v1/runs/{run_id}")
            self.log.pop()  # keep the log to the calls that matter
            if status == 200 and run["state"] in states:
                self.call(user, "GET", f"/api/v1/runs/{run_id}")
                return run
            time.sleep(1)
        raise SystemExit(f"run {run_id} never reached {sorted(states)}; last {run!r}"[:800])

    def events(self, user: str, run_id: str) -> list[Any]:
        return self.get(user, f"/api/v1/runs/{run_id}/events?after=0")["events"]

    def tickets(self) -> list[Any]:
        return self.get("alice", "/api/v1/mock-jira/tickets")["tickets"]


def save(out: Path, name: str, payload: Any) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(payload, indent=2, default=str) + "\n")


def verdict(lines: list[tuple[bool, str]]) -> bool:
    for ok, line in lines:
        print(("ok   " if ok else "FAIL ") + line)
    passed = all(ok for ok, _ in lines)
    print("PASS" if passed else "FAIL")
    return passed


def check(api: Api, name: str, repo: str, ours: str) -> dict[str, Any]:
    before = api.get("alice", "/api/v1/watchlist")
    status, added = api.call(
        "alice",
        "POST",
        "/api/v1/watchlist/software",
        {"name": name, "repo": repo, "our_version": ours},
    )
    if status not in (201, 409):
        raise SystemExit(f"add software: HTTP {status} {added!r}")
    watchlist = api.get("alice", "/api/v1/watchlist")["watchlist"]
    status, started = api.start_run("alice", watchlist["use_case_id"])
    if status not in (200, 201, 202):
        raise SystemExit(f"start run: HTTP {status} {started!r}")
    run_id = started["run_id"]
    run = api.wait("alice", run_id, {"awaiting_approval", "succeeded", "failed", "rejected"})
    return {
        "watchlist_before": before,
        "added": added,
        "started": started,
        "run": run,
        "events": api.events("alice", run_id),
    }


def actors(events: list[Any]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for event in events:
        actor = event.get("actor") or {}
        if actor.get("kind") == "agent":
            found.add((str(actor.get("id")), str(actor.get("display"))))
    return found


def lane2(api: Api, out: Path) -> bool:
    result = check(api, "LangGraph", "langchain-ai/langgraph", "1.2.14")
    run, events = result["run"], result["events"]
    seen = actors(events)
    text = json.dumps({"run": run, "events": events})
    retired = sorted({m.group(0) for m in RETIRED.finditer(text)})
    result["agent_actors"] = sorted(seen)
    result["retired_names_found"] = retired
    save(out, "p2-check.json", {**result, "calls": api.log})
    return verdict(
        [
            (run["state"] == "awaiting_approval", f"run {run['run_id']} is {run['state']}"),
            (
                ("planner", "Planner") in seen,
                f"an event is by the Planner; agent actors {sorted(seen)}",
            ),
            (("version_checker", "Version checker") in seen, "an event is by the Version checker"),
            (not retired, f"no retired name in the run or its {len(events)} events: {retired}"),
        ]
    )


def approval_of(api: Api, user: str, run_id: str) -> tuple[Any, Any]:
    run = api.get(user, f"/api/v1/runs/{run_id}")
    approval_id = run["approval"]["approval_id"]
    return run, api.get(user, f"/api/v1/approvals/{approval_id}")


def lane4(api: Api, out: Path, run_id: str) -> bool:
    tickets_before = api.tickets()
    _, approval = approval_of(api, "bob", run_id)
    status, decided = api.call(
        "bob",
        "POST",
        f"/api/v1/approvals/{approval['approval_id']}/decisions",
        {"step": 0, "verdict": "approve", "digest": approval["digest"]},
    )
    run = api.wait("alice", run_id, {"succeeded", "failed", "rejected"})
    tickets_after = api.tickets()
    new = [t for t in tickets_after if t not in tickets_before]
    events = api.events("alice", run_id)
    save(
        out,
        "p2-approved.json",
        {
            "approval": approval,
            "decision_status": status,
            "decision": decided,
            "run": run,
            "tickets_before": tickets_before,
            "tickets_after": tickets_after,
            "new_tickets": new,
            "events": events,
            "calls": api.log,
        },
    )
    return verdict(
        [
            (status == 201, f"bob's approval answered HTTP {status}"),
            (
                run["state"] == "succeeded",
                f"run ends {run['state']} (outcome {run.get('outcome')})",
            ),
            (
                len(new) == 1 and new[0].get("run_id") == run_id,
                f"{len(new)} new practice Jira ticket(s): {[t.get('key') + ' ' + t.get('title', '') for t in new]}",
            ),
            (
                len(tickets_after) == len(tickets_before) + 1,
                f"ticket count {len(tickets_before)} -> {len(tickets_after)}",
            ),
        ]
    )


def refusal_lane(
    api: Api, out: Path, run_id: str, user: str, digest_of: Any, file: str, want: set[int]
) -> bool:
    tickets_before = api.tickets()
    run_before, approval = approval_of(api, "bob", run_id)
    events_before = api.events("alice", run_id)
    digest = digest_of(approval)
    status, refused = api.call(
        user,
        "POST",
        f"/api/v1/approvals/{approval['approval_id']}/decisions",
        {"step": 0, "verdict": "approve", "digest": digest},
    )
    time.sleep(3)
    run_after, approval_after = approval_of(api, "bob", run_id)
    tickets_after = api.tickets()
    events_after = api.events("alice", run_id)
    save(
        out,
        file,
        {
            "run_id": run_id,
            "sent_digest": digest,
            "real_digest": approval["digest"],
            "status": status,
            "response": refused,
            "approval_before": approval,
            "approval_after": approval_after,
            "run_before": run_before,
            "run_after": run_after,
            "tickets_before": tickets_before,
            "tickets_after": tickets_after,
            "events_before": len(events_before),
            "events_after": len(events_after),
            "new_events": events_after[len(events_before) :],
            "calls": api.log,
        },
    )
    return verdict(
        [
            (status in want, f"{user}'s decision answered HTTP {status}: {refused}"),
            (isinstance(refused, dict) and "decision" not in refused, "no decision in the answer"),
            (
                approval_after["steps"][0]["status"] == "open",
                f"step 0 is {approval_after['steps'][0]['status']}",
            ),
            (run_after["state"] == "awaiting_approval", f"run is still {run_after['state']}"),
            (
                tickets_after == tickets_before,
                f"tickets {len(tickets_before)} -> {len(tickets_after)}",
            ),
            (
                len(events_after) == len(events_before),
                f"events {len(events_before)} -> {len(events_after)}",
            ),
        ]
    )


def lane7(api: Api, out: Path) -> bool:
    body = {
        "template": "release_check",
        "name": "p2 lane 7 release check",
        "instruction": "Tell me when LangGraph has a new release.",
        "params": {
            "repo": "langchain-ai/langgraph",
            "tag_pattern": r"^\d+\.\d+\.\d+$",
            "ticket_project": "MOCK",
            "last_seen_tag": "1.2.14",
        },
    }
    use_cases_before = api.get("alice", "/api/v1/use-cases")
    status, answer = api.call("alice", "POST", "/api/v1/use-cases", body)
    templates = api.get("alice", "/api/v1/templates")
    use_cases_after = api.get("alice", "/api/v1/use-cases")
    save(
        out,
        "p2-no-template.json",
        {
            "status": status,
            "response": answer,
            "templates": templates,
            "use_cases_before": use_cases_before,
            "use_cases_after": use_cases_after,
            "calls": api.log,
        },
    )
    text = json.dumps(answer)
    keys = [t.get("key") for t in templates.get("templates", [])]
    return verdict(
        [
            (status == 422, f"POST /api/v1/use-cases answered HTTP {status}"),
            (
                "release_check" in text and "nknown template" in text,
                f"the answer names it: {text[:300]}",
            ),
            ("release_check" not in keys, f"GET /api/v1/templates lists {keys}"),
            (use_cases_after == use_cases_before, "the use-case list did not change"),
        ]
    )


def release_check(api: Api, out: Path) -> bool:
    body = {
        "template": "release_check",
        "name": "p2 lane 3b old release check",
        "instruction": "Tell me when LangGraph has a new release.",
        "params": {
            "repo": "langchain-ai/langgraph",
            "tag_pattern": r"^\d+\.\d+\.\d+$",
            "ticket_project": "MOCK",
            "last_seen_tag": "1.2.14",
        },
    }
    status, created = api.call("alice", "POST", "/api/v1/use-cases", body)
    if status != 201:
        raise SystemExit(f"create release check: HTTP {status} {created!r}")
    status, started = api.start_run("alice", created["use_case_id"])
    run = api.wait(
        "alice", started["run_id"], {"awaiting_approval", "succeeded", "failed", "rejected"}
    )
    save(
        out,
        "trunk-release-check.json",
        {
            "created": created,
            "started": started,
            "run": run,
            "events": api.events("alice", run["run_id"]),
            "calls": api.log,
        },
    )
    return verdict(
        [
            (
                status in (200, 201, 202),
                f"use case {created['use_case_id']} run {run['run_id']} is {run['state']}",
            )
        ]
    )


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    command, base, out = argv[0], argv[1], Path(argv[2])
    rest = argv[3:]
    api = Api(base)
    if command == "check":
        result = check(api, rest[1], rest[2], rest[3])
        save(out, rest[0], {**result, "calls": api.log})
        print(json.dumps({"run_id": result["run"]["run_id"], "state": result["run"]["state"]}))
        return 0
    if command == "lane2":
        return 0 if lane2(api, out) else 1
    if command == "lane4":
        return 0 if lane4(api, out, rest[0]) else 1
    if command == "lane5":
        return (
            0
            if refusal_lane(
                api, out, rest[0], "alice", lambda a: a["digest"], "p2-own-run.json", {403}
            )
            else 1
        )
    if command == "lane6":
        return (
            0
            if refusal_lane(
                api,
                out,
                rest[0],
                "bob",
                lambda a: STALE_DIGEST,
                "p2-stale-digest.json",
                {403, 409, 422},
            )
            else 1
        )
    if command == "lane7":
        return 0 if lane7(api, out) else 1
    if command == "release-check":
        return 0 if release_check(api, out) else 1
    if command == "wait":
        run = api.wait("alice", rest[0], set(rest[1].split(",")))
        save(out, rest[2], {"run": run, "events": api.events("alice", rest[0]), "calls": api.log})
        print(
            json.dumps(
                {"run_id": run["run_id"], "state": run["state"], "reason": run.get("reason")}
            )
        )
        return 0
    if command == "retry":
        status, retried = api.call("alice", "POST", f"/api/v1/runs/{rest[0]}/retry")
        print(json.dumps({"status": status, "response": retried}))
        save(
            out,
            rest[1] if len(rest) > 1 else "retry.json",
            {"status": status, "response": retried, "calls": api.log},
        )
        return 0 if status == 202 else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
