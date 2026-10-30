"""API lanes for the P8 checker: pause, resume, delete with Undo, and drafts. Standard library
only. Each command saves what it saw as JSON in the folder it is given and prints PASS or FAIL.

usage: python3 -I scripts/checks/p8_lanes.py <command> <api-base-url> <out-dir> [arguments]

  lane1 <trunk-api> <out> <head-api>  alice starts a watchlist check at trunk and at head
  lane2 <api> <out>                   alice pauses the Software watchlist; no next run
  lane3 <api> <out> <step-key>        (own stack) a tick past the slot of a paused watchlist
  lane4 <api> <out>                   alice resumes the watchlist; its next run has a date again
  lane5 <api> <out>                   an agent workflow with a past run is deleted, then restored
  lane6 <api> <out>                   deleted while its run waits for a yes; bob still decides
  lane7 <api> <out>                   bob calls every lifecycle and draft route; 403 each
  lane8 <api> <out>                   alice saves a draft; carol's list does not hold it
  lane9 <api> <out>                   two pauses at the same moment; one paused state
  seed <api> <out> <count>            alice makes <count> agent workflows for the perf probe

Lane 3 cannot move the stack's clock, so it moves the schedule instead: it saves the watchlist's
schedule for the next 5-minute slot at least 90 seconds away, pauses the watchlist, waits until
the slot has passed and asks POST /internal/v1/schedules/tick with the step key. n8n's own
schedule_tick asks the same route every 5 minutes, so either may use the slot up. As a control it
then resumes the watchlist, saves the slot after that, waits again, and expects one scheduled run.
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SINGAPORE = timezone(timedelta(hours=8))
WAIT_SECONDS = 150
MOCK_MODEL_URL = "http://mock-model:8300"
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
VALUES = {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}
SETTLED = {"awaiting_approval", "succeeded", "failed", "rejected"}


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
            headers={"Idempotency-Key": f"p8check-{uuid.uuid4()}"},
        )

    def move(self, user: str, action: str, use_case_id: str) -> tuple[int, Any]:
        if action == "delete":
            return self.call(user, "DELETE", f"/api/v1/use-cases/{use_case_id}")
        return self.call(user, "POST", f"/api/v1/use-cases/{use_case_id}/{action}")

    def listed(self) -> list[Any]:
        return self.get("alice", "/api/v1/use-cases")["use_cases"]

    def row(self, use_case_id: str) -> Any:
        return next((u for u in self.listed() if u["use_case_id"] == use_case_id), None)

    def runs_of(self, use_case_id: str) -> list[Any]:
        runs = self.get("alice", "/api/v1/runs")["runs"]
        return [r for r in runs if r["use_case_id"] == use_case_id]

    def wait(self, run_id: str, states: set[str]) -> Any:
        deadline = time.monotonic() + WAIT_SECONDS
        run: Any = None
        while time.monotonic() < deadline:
            status, run = self.call("alice", "GET", f"/api/v1/runs/{run_id}", keep=False)
            if status == 200 and run["state"] in states:
                return self.get("alice", f"/api/v1/runs/{run_id}")
            time.sleep(1)
        raise SystemExit(f"run {run_id} never reached {sorted(states)}; last {run!r}"[:800])


def save(out: Path, name: str, payload: Any) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(payload, indent=2, default=str) + "\n")


def verdict(lines: list[tuple[bool, str]]) -> bool:
    for ok, line in lines:
        print(("ok   " if ok else "FAIL ") + line)
    passed = all(ok for ok, _ in lines)
    print("PASS" if passed else "FAIL")
    return passed


def ensure_watchlist(api: Api) -> Any:
    status, added = api.call("alice", "POST", "/api/v1/watchlist/software", LANGGRAPH)
    if status not in (201, 409):
        raise SystemExit(f"add LangGraph: HTTP {status} {added!r}")
    found = api.get("alice", "/api/v1/watchlist")["watchlist"]
    if found["schedule"] is None:
        api.call("alice", "PUT", "/api/v1/watchlist/schedule", {"day": "monday", "at": "09:00"})
        found = api.get("alice", "/api/v1/watchlist")["watchlist"]
    return found


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
            "api_key": "p8-mock-key-not-real",
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
        "name": f"p8 {lane} {uuid.uuid4().hex[:6]}",
        "instruction": "Check LangGraph for new releases and raise a ticket in MOCK.",
        "agents": [{"card_id": "crd_version_checker", "values": VALUES}],
    }
    status, created = api.call("alice", "POST", "/api/v1/agent-use-cases", body)
    if status != 201:
        raise SystemExit(f"create the workflow: HTTP {status} {created!r}")
    return created["use_case_id"]


def started_run(api: Api, use_case_id: str) -> str:
    status, started = api.start_run("alice", use_case_id)
    if status != 201:
        raise SystemExit(f"start a run: HTTP {status} {started!r}")
    return started["run_id"]


def check_once(api: Api) -> dict[str, Any]:
    found = ensure_watchlist(api)
    before = api.runs_of(found["use_case_id"])
    status, started = api.start_run("alice", found["use_case_id"])
    run = api.wait(started["run_id"], SETTLED) if status == 201 else None
    after = api.runs_of(found["use_case_id"])
    return {
        "use_case_id": found["use_case_id"],
        "start_status": status,
        "started": started,
        "run": run,
        "runs_before": len(before),
        "runs_after": len(after),
    }


def lane1(trunk: Api, out: Path, head: Api) -> bool:
    at_trunk = check_once(trunk)
    pause_status, pause = trunk.call(
        "alice", "POST", f"/api/v1/use-cases/{at_trunk['use_case_id']}/pause"
    )
    at_head = check_once(head)
    save(
        out,
        "p8-run-trunk-head.json",
        {
            "trunk": {**at_trunk, "pause_status": pause_status, "pause": pause},
            "head": at_head,
            "trunk_calls": trunk.log,
            "head_calls": head.log,
        },
    )
    lines: list[tuple[bool, str]] = []
    for name, side in (("trunk", at_trunk), ("head", at_head)):
        run = side["run"] or {}
        lines.append(
            (
                side["start_status"] == 201 and side["runs_after"] == side["runs_before"] + 1,
                f"{name}: HTTP {side['start_status']}, runs {side['runs_before']} -> "
                f"{side['runs_after']}, run {run.get('run_id')} is {run.get('state')}",
            )
        )
    lines.append(
        (
            pause_status in (404, 405),
            f"trunk has no pause route: POST .../pause answered HTTP {pause_status} (recorded)",
        )
    )
    lines.append(
        (
            (at_trunk["run"] or {}).get("state") == (at_head["run"] or {}).get("state"),
            "the run reaches the same state at trunk and head",
        )
    )
    return verdict(lines)


def lane2(api: Api, out: Path) -> bool:
    found = ensure_watchlist(api)
    use_case_id = found["use_case_id"]
    resumed_first = None
    if (api.row(use_case_id) or {}).get("state") == "paused":
        resumed_first = api.move("alice", "resume", use_case_id)
    before = api.row(use_case_id)
    status, paused = api.move("alice", "pause", use_case_id)
    after = api.row(use_case_id)
    save(
        out,
        "p8-paused.json",
        {
            "resumed_first": resumed_first,
            "before": before,
            "status": status,
            "paused": paused,
            "listed_after": after,
            "calls": api.log,
        },
    )
    return verdict(
        [
            (
                before is not None and before["next_run_at"] is not None,
                f"before: {(before or {}).get('state')}, "
                f"next run {(before or {}).get('next_run_at')}",
            ),
            (status == 200, f"alice's pause answered HTTP {status}"),
            (
                paused["state"] == "paused" and paused["next_run_at"] is None,
                f"the answer reads {paused.get('state')}, next run {paused.get('next_run_at')}",
            ),
            (
                after is not None and after["state"] == "paused" and after["next_run_at"] is None,
                f"GET /api/v1/use-cases reads {after and after['state']}, "
                f"next run {after and after['next_run_at']}",
            ),
        ]
    )


def next_slot(now: datetime, ahead: timedelta = timedelta(seconds=90)) -> datetime:
    local = (now + ahead).astimezone(SINGAPORE)
    slot = local.replace(second=0, microsecond=0)
    slot += timedelta(minutes=(5 - slot.minute % 5) % 5)
    return slot if slot >= local else slot + timedelta(minutes=5)


def wait_past(slot: datetime) -> None:
    pause = (slot - datetime.now(UTC)).total_seconds() + 20
    print(f"waiting {pause:.0f} s for the slot {slot.isoformat()} to pass")
    time.sleep(max(0.0, pause))


def schedule_for(api: Api, slot: datetime) -> tuple[int, Any]:
    body = {"day": "every_day", "at": slot.strftime("%H:%M")}
    return api.call("carol", "PUT", "/api/v1/watchlist/schedule", body)


def tick(api: Api, step_key: str) -> tuple[int, Any]:
    return api.call(None, "POST", "/internal/v1/schedules/tick", headers={"X-Step-Key": step_key})


def lane3(api: Api, out: Path, step_key: str) -> bool:
    found = ensure_watchlist(api)
    use_case_id = found["use_case_id"]
    slot = next_slot(datetime.now(UTC))
    saved_status, saved = schedule_for(api, slot)
    on = api.row(use_case_id)
    pause_status, paused = api.move("alice", "pause", use_case_id)
    runs_before = api.runs_of(use_case_id)
    wait_past(slot)
    tick_status, ticked = tick(api, step_key)
    runs_after = api.runs_of(use_case_id)

    api.move("alice", "resume", use_case_id)
    control_slot = next_slot(datetime.now(UTC))
    schedule_for(api, control_slot)
    wait_past(control_slot)
    control_status, control_tick = tick(api, step_key)
    deadline = time.monotonic() + 30
    control_runs = api.runs_of(use_case_id)
    while len(control_runs) == len(runs_after) and time.monotonic() < deadline:
        time.sleep(2)
        control_runs = api.runs_of(use_case_id)
    new_control = [r for r in control_runs if r["run_id"] not in {x["run_id"] for x in runs_after}]
    save(
        out,
        "p8-no-tick.json",
        {
            "slot": slot.isoformat(),
            "schedule_status": saved_status,
            "schedule": saved,
            "listed_while_on": on,
            "pause_status": pause_status,
            "paused": paused,
            "runs_before": runs_before,
            "tick_status": tick_status,
            "tick": ticked,
            "runs_after": runs_after,
            "control_slot": control_slot.isoformat(),
            "control_tick_status": control_status,
            "control_tick": control_tick,
            "control_new_runs": new_control,
            "calls": api.log,
        },
    )
    expected = slot.astimezone(UTC)
    listed_next = (on or {}).get("next_run_at")
    return verdict(
        [
            (saved_status == 200, f"carol saved the schedule for {slot.strftime('%H:%M')} SGT"),
            (
                listed_next is not None and datetime.fromisoformat(listed_next) == expected,
                f"while on, the next run reads {listed_next}",
            ),
            (pause_status == 200 and paused["next_run_at"] is None, "alice paused it"),
            (tick_status == 200, f"the tick after the slot answered HTTP {tick_status}: {ticked}"),
            (
                len(runs_after) == len(runs_before),
                f"no run started: runs {len(runs_before)} -> {len(runs_after)}",
            ),
            (
                len(new_control) == 1 and new_control[0]["trigger"] == "schedule",
                f"control: resumed, the next slot started {len(new_control)} scheduled run(s)",
            ),
        ]
    )


def lane4(api: Api, out: Path) -> bool:
    found = ensure_watchlist(api)
    use_case_id = found["use_case_id"]
    before = api.row(use_case_id)
    status, resumed = api.move("alice", "resume", use_case_id)
    after = api.row(use_case_id)
    save(
        out,
        "p8-resumed.json",
        {"before": before, "status": status, "resumed": resumed, "listed_after": after},
    )
    return verdict(
        [
            (before is not None and before["state"] == "paused", "it was paused before"),
            (status == 200, f"alice's resume answered HTTP {status}"),
            (
                resumed["state"] == "on" and resumed["next_run_at"] is not None,
                f"the answer reads {resumed.get('state')}, next run {resumed.get('next_run_at')}",
            ),
            (
                after is not None and after["next_run_at"] is not None,
                f"GET /api/v1/use-cases shows the next run {after and after['next_run_at']}",
            ),
        ]
    )


def lane5(api: Api, out: Path) -> bool:
    connect_model(api)
    use_case_id = agent_workflow(api, "lane 5")
    run_id = started_run(api, use_case_id)
    run = api.wait(run_id, SETTLED)
    del_status, deleted = api.move("alice", "delete", use_case_id)
    listed_deleted = api.row(use_case_id)
    get_status, _ = api.call("alice", "GET", f"/api/v1/use-cases/{use_case_id}")
    runs_deleted = api.runs_of(use_case_id)
    res_status, restored = api.move("alice", "restore", use_case_id)
    listed_restored = api.row(use_case_id)
    runs_restored = api.runs_of(use_case_id)
    save(
        out,
        "p8-restored.json",
        {
            "use_case_id": use_case_id,
            "run": run,
            "delete_status": del_status,
            "deleted": deleted,
            "listed_while_deleted": listed_deleted,
            "get_while_deleted": get_status,
            "runs_while_deleted": runs_deleted,
            "restore_status": res_status,
            "restored": restored,
            "listed_after_restore": listed_restored,
            "runs_after_restore": runs_restored,
            "calls": api.log,
        },
    )
    return verdict(
        [
            (del_status == 200, f"delete answered HTTP {del_status}: {deleted}"),
            (
                listed_deleted is None and get_status == 404,
                f"while deleted: not listed, GET answers {get_status}",
            ),
            (
                [r["run_id"] for r in runs_deleted] == [run_id],
                f"its run {run_id} stays readable while deleted",
            ),
            (
                res_status == 200 and restored["state"] == "on",
                f"restore answered HTTP {res_status}",
            ),
            (
                listed_restored is not None and [r["run_id"] for r in runs_restored] == [run_id],
                "it is listed again, with its past run",
            ),
        ]
    )


def lane6(api: Api, out: Path) -> bool:
    connect_model(api)
    use_case_id = agent_workflow(api, "lane 6")
    run_id = started_run(api, use_case_id)
    waiting = api.wait(run_id, SETTLED)
    if waiting["state"] != "awaiting_approval":
        save(out, "p8-delete-waiting.json", {"waiting_run": waiting, "calls": api.log})
        return verdict([(False, f"the run never waited for a yes: it is {waiting['state']}")])
    del_status, deleted = api.move("alice", "delete", use_case_id)
    approval = api.get("bob", f"/api/v1/approvals/{waiting['approval']['approval_id']}")
    dec_status, decided = api.call(
        "bob",
        "POST",
        f"/api/v1/approvals/{approval['approval_id']}/decisions",
        {"step": 0, "verdict": "approve", "digest": approval["digest"]},
    )
    final = api.wait(run_id, {"succeeded", "failed", "rejected"})
    start_status, start = api.start_run("alice", use_case_id)
    runs = api.runs_of(use_case_id)
    save(
        out,
        "p8-delete-waiting.json",
        {
            "use_case_id": use_case_id,
            "waiting_run": waiting,
            "delete_status": del_status,
            "deleted": deleted,
            "approval_as_bob": approval,
            "decision_status": dec_status,
            "decision": decided,
            "final_run": final,
            "start_after_delete_status": start_status,
            "start_after_delete": start,
            "runs": runs,
            "calls": api.log,
        },
    )
    return verdict(
        [
            (waiting["state"] == "awaiting_approval", f"the run was {waiting['state']}"),
            (del_status == 200, f"delete answered HTTP {del_status}"),
            (approval["you_can_decide"] is True, "bob can still decide the waiting run"),
            (dec_status == 201, f"bob's yes answered HTTP {dec_status}"),
            (final["state"] == "succeeded", f"the run ended {final['state']}"),
            (start_status == 404, f"a new start answered HTTP {start_status}"),
            ([r["run_id"] for r in runs] == [run_id], f"the workflow has {len(runs)} run(s)"),
        ]
    )


def lane7(api: Api, out: Path) -> bool:
    use_case_id = agent_workflow(api, "lane 7")
    before = api.row(use_case_id)
    answers: dict[str, int] = {}
    for action in ("pause", "resume", "delete", "restore"):
        answers[action], _ = api.move("bob", action, use_case_id)
    answers["PUT draft"], _ = api.call(
        "bob", "PUT", "/api/v1/drafts/p8-lane7", {"step": 1, "content": {}}
    )
    answers["GET drafts"], _ = api.call("bob", "GET", "/api/v1/drafts")
    answers["DELETE draft"], _ = api.call("bob", "DELETE", "/api/v1/drafts/p8-lane7")
    after = api.row(use_case_id)
    save(
        out,
        "p8-approver.json",
        {"before": before, "answers": answers, "after": after, "calls": api.log},
    )
    lines = [(status == 403, f"bob {name}: HTTP {status}") for name, status in answers.items()]
    lines.append((after == before, "the workflow is unchanged"))
    return verdict(lines)


def lane8(api: Api, out: Path) -> bool:
    draft_id = f"p8-lane8-{uuid.uuid4().hex[:8]}"
    body = {"step": 2, "content": {"intent": "Nudge owners of stale MOCK tickets", "days": 14}}
    save_status, saved = api.call("alice", "PUT", f"/api/v1/drafts/{draft_id}", body)
    carols = api.get("carol", "/api/v1/drafts")["drafts"]
    del_status, refused = api.call("carol", "DELETE", f"/api/v1/drafts/{draft_id}")
    alices = api.get("alice", "/api/v1/drafts")["drafts"]
    save(
        out,
        "p8-drafts.json",
        {
            "draft_id": draft_id,
            "save_status": save_status,
            "saved": saved,
            "carols_list": carols,
            "carol_delete_status": del_status,
            "carol_delete": refused,
            "alices_list": alices,
            "calls": api.log,
        },
    )
    return verdict(
        [
            (save_status == 200, f"alice saved {draft_id}: HTTP {save_status}"),
            (
                all(d["draft_id"] != draft_id for d in carols),
                f"carol's list holds {len(carols)} draft(s), none of them alice's",
            ),
            (del_status == 404, f"carol deleting it answered HTTP {del_status}"),
            (
                any(d["draft_id"] == draft_id and d["content"] == body["content"] for d in alices),
                "alice still has it, unchanged",
            ),
        ]
    )


def lane9(api: Api, out: Path) -> bool:
    use_case_id = agent_workflow(api, "lane 9")
    barrier = threading.Barrier(2)
    answers: dict[str, tuple[int, Any, str]] = {}

    def pause_as(user: str) -> None:
        mine = Api(api.base)
        barrier.wait()
        status, body = mine.move(user, "pause", use_case_id)
        answers[user] = (status, body, datetime.now(UTC).isoformat())

    threads = [threading.Thread(target=pause_as, args=(u,)) for u in ("alice", "carol")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    after = api.row(use_case_id)
    third_status, third = api.move("alice", "pause", use_case_id)
    save(
        out,
        "p8-pause-twice.json",
        {"answers": answers, "listed_after": after, "third": [third_status, third]},
    )
    (s1, b1, _), (s2, b2, _) = answers["alice"], answers["carol"]
    return verdict(
        [
            ((s1, s2) == (200, 200), f"both pauses answered success: {s1}, {s2}"),
            (b1 == b2 and b1["state"] == "paused", "both answers read the same paused state"),
            (after is not None and after["state"] == "paused", "the list reads one paused state"),
            (third_status == 200 and third == b1, "a third pause answers the same"),
        ]
    )


def seed(api: Api, out: Path, count: int) -> bool:
    made = [agent_workflow(api, f"perf {n}") for n in range(count)]
    listed = api.listed()
    save(out, "p8-seed.json", {"made": made, "listed": len(listed)})
    return verdict([(len(listed) >= count, f"{len(listed)} workflows listed")])


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    command, base, out = argv[0], argv[1], Path(argv[2])
    rest = argv[3:]
    api = Api(base)
    lanes: dict[str, Any] = {
        "lane1": lambda: lane1(api, out, Api(rest[0])),
        "lane2": lambda: lane2(api, out),
        "lane3": lambda: lane3(api, out, rest[0]),
        "lane4": lambda: lane4(api, out),
        "lane5": lambda: lane5(api, out),
        "lane6": lambda: lane6(api, out),
        "lane7": lambda: lane7(api, out),
        "lane8": lambda: lane8(api, out),
        "lane9": lambda: lane9(api, out),
        "seed": lambda: seed(api, out, int(rest[0])),
    }
    if command not in lanes:
        print(__doc__)
        return 2
    return 0 if lanes[command]() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
