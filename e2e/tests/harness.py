import json
import os
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import httpx
import pytest

type Json = dict[str, Any]

PLATFORM_API_URL = os.environ.get("PLATFORM_API_URL", "http://platform-api:8000")
MOCK_GITHUB_URL = os.environ.get("MOCK_GITHUB_URL", "http://mock-github:8200")
STEP_KEY = os.environ.get("STEP_KEY", "")
WAIT_SECONDS = float(os.environ.get("E2E_WAIT_SECONDS", "90"))
CONTRACTS_DIR = Path(os.environ.get("CONTRACTS_DIR", Path(__file__).parents[2] / "contracts"))

TERMINAL_STATES = frozenset({"succeeded", "rejected", "failed"})
TERMINAL_EVENTS = frozenset({"run_succeeded", "run_rejected", "run_failed"})

INSTRUCTION = "Check langchain-ai/langgraph for new releases and open a ticket for the team."
LAST_SEEN_TAG = "1.2.14"
EXPECTED_TITLE = "New LangGraph releases: 1.2.16, 1.2.15"
RELEASE_CHECK_PARAMS = {
    "repo": "langchain-ai/langgraph",
    "tag_pattern": r"^\d+\.\d+\.\d+$",
    "ticket_project": "MOCK",
    "last_seen_tag": LAST_SEEN_TAG,
}


def fail(message: str) -> NoReturn:
    pytest.fail(message, pytrace=False)


def fixture_kinds(name: str) -> list[str]:
    events: list[Json] = json.loads(
        (CONTRACTS_DIR / "fixtures" / "runs" / f"{name}.json").read_text()
    )
    return [event["kind"] for event in events]


@dataclass
class SseFrame:
    id: str = ""
    event: str = ""
    data: list[str] = field(default_factory=list[str])

    def activity(self, run_id: str) -> Json:
        event: Json = json.loads("\n".join(self.data))
        if self.event != "activity" or str(event["seq"]) != self.id:
            fail(f"SSE frame for {run_id} is malformed: id={self.id!r} event={self.event!r}")
        return event


def sse_frames(lines: Iterable[str], deadline: float) -> Iterator[SseFrame]:
    frame = SseFrame()
    for line in lines:
        if time.monotonic() > deadline:
            return
        if line == "":
            if frame.data:
                yield frame
            frame = SseFrame()
        elif line.startswith("id:"):
            frame.id = line[3:].strip()
        elif line.startswith("event:"):
            frame.event = line[6:].strip()
        elif line.startswith("data:"):
            frame.data.append(line[5:].strip())


class Api:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=15)

    def request(
        self,
        user: str | None,
        method: str,
        path: str,
        *,
        expect: Iterable[int],
        headers: dict[str, str] | None = None,
        json_body: Json | None = None,
    ) -> httpx.Response:
        sent = dict(headers or {})
        if user is not None:
            sent["X-Dev-User"] = user
        try:
            response = self.client.request(method, path, headers=sent, json=json_body)
        except httpx.HTTPError as error:
            fail(f"{method} {path} as {user}: no answer from {self.base_url} ({error!r})")
        allowed = tuple(expect)
        if response.status_code not in allowed:
            fail(
                f"{method} {path} as {user}: expected {' or '.join(map(str, allowed))}, "
                f"got {response.status_code}. Body: {response.text[:300]!r}"
            )
        return response

    def get(self, user: str | None, path: str, *, expect: Iterable[int] = (200,)) -> Json:
        return self.request(user, "GET", path, expect=expect).json()

    def post(
        self,
        user: str | None,
        path: str,
        body: Json | None = None,
        *,
        expect: Iterable[int],
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return self.request(user, "POST", path, expect=expect, headers=headers, json_body=body)

    def create_use_case(self, user: str, label: str) -> str:
        body = {
            "template": "release_check",
            "name": f"e2e {label} {uuid.uuid4().hex[:8]}",
            "instruction": INSTRUCTION,
            "params": RELEASE_CHECK_PARAMS,
        }
        created = self.post(user, "/api/v1/use-cases", body, expect=(201,)).json()
        if created.get("version") != 1 or not created.get("use_case_id"):
            fail(f"create use case: unexpected body {created!r}")
        return created["use_case_id"]

    def start_run(
        self, user: str, use_case_id: str, key: str | None = None
    ) -> tuple[str, httpx.Response]:
        response = self.post(
            user,
            f"/api/v1/use-cases/{use_case_id}/runs",
            expect=(200, 201),
            headers={"Idempotency-Key": key or str(uuid.uuid4())},
        )
        started = response.json()
        if not started.get("run_id"):
            fail(f"start run: no run_id in {started!r}")
        return started["run_id"], response

    def run_view(self, user: str, run_id: str) -> Json:
        return self.get(user, f"/api/v1/runs/{run_id}")

    def events_after(self, user: str, run_id: str, after: int = 0) -> list[Json]:
        return self.get(user, f"/api/v1/runs/{run_id}/events?after={after}")["events"]

    def delete(self, user: str, path: str, *, expect: Iterable[int]) -> httpx.Response:
        return self.request(user, "DELETE", path, expect=expect)

    def tickets(self, user: str = "alice") -> list[Json]:
        return self.get(user, "/api/v1/mock-jira/tickets")["tickets"]

    def mark_done(self, user: str, key: str, *, expect: Iterable[int] = (200,)) -> httpx.Response:
        return self.post(user, f"/api/v1/mock-jira/tickets/{key}/done", expect=expect)

    def tick(self, step_key: str, *, expect: Iterable[int] = (200,)) -> httpx.Response:
        """What the schedule_tick workflow asks every 5 minutes. It signs in with the step key."""
        return self.request(
            None,
            "POST",
            "/internal/v1/schedules/tick",
            expect=expect,
            headers={"X-Step-Key": step_key},
        )

    def watchlist(self, user: str = "alice") -> Json | None:
        return self.get(user, "/api/v1/watchlist")["watchlist"]

    def add_software(
        self,
        user: str,
        name: str,
        repo: str,
        our_version: str | None = None,
        *,
        expect: Iterable[int] = (201,),
    ) -> httpx.Response:
        body: Json = {"name": name, "repo": repo, "our_version": our_version}
        return self.post(user, "/api/v1/watchlist/software", body, expect=expect)

    def remove_software(
        self, user: str, software_id: str, *, expect: Iterable[int] = (200,)
    ) -> httpx.Response:
        return self.delete(user, f"/api/v1/watchlist/software/{software_id}", expect=expect)

    def clear_watchlist(self, user: str = "alice") -> None:
        """One watchlist per team, so a test on a stack that kept state starts from an empty one."""
        watchlist = self.watchlist(user)
        if watchlist is None:
            return
        for row in watchlist["software"]:
            self.remove_software(user, row["id"])

    def describe_run(self, user: str, run_id: str) -> str:
        try:
            view = self.run_view(user, run_id)
        except pytest.fail.Exception as error:
            return f"run state unknown ({error})"
        return (
            f"run {run_id} is in state {view.get('state')!r} with last_seq {view.get('last_seq')}"
        )

    def wait_for_state(self, user: str, run_id: str, states: set[str]) -> Json:
        deadline = time.monotonic() + WAIT_SECONDS
        view: Json = {}
        while time.monotonic() < deadline:
            view = self.run_view(user, run_id)
            if view["state"] in states:
                return view
            if view["state"] in TERMINAL_STATES:
                fail(f"run {run_id} ended in {view['state']!r}, wanted {sorted(states)}: {view}")
            time.sleep(0.5)
        fail(
            f"run {run_id} stuck in state {view.get('state')!r} for {WAIT_SECONDS:.0f}s, "
            f"wanted {sorted(states)}"
        )

    def stream_until(
        self,
        user: str,
        run_id: str,
        until: set[str],
        *,
        last_event_id: int | None = None,
    ) -> list[Json]:
        headers = {"Accept": "text/event-stream", "X-Dev-User": user}
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        deadline = time.monotonic() + WAIT_SECONDS
        events: list[Json] = []
        path = f"/api/v1/runs/{run_id}/events"
        timeout = httpx.Timeout(10, read=WAIT_SECONDS)
        try:
            with self.client.stream("GET", path, headers=headers, timeout=timeout) as response:
                if response.status_code != 200:
                    fail(f"SSE for {run_id}: expected 200, got {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    fail(f"SSE for {run_id}: content-type was {content_type!r}")
                for frame in sse_frames(response.iter_lines(), deadline):
                    event = frame.activity(run_id)
                    events.append(event)
                    if event["kind"] in until:
                        return events
                    if event["kind"] in TERMINAL_EVENTS:
                        fail(f"run {run_id} ended with {event['kind']} before {sorted(until)}")
        except httpx.TransportError as error:
            fail(f"SSE for {run_id} broke ({error!r}). {self.describe_run(user, run_id)}")
        seen = [e["kind"] for e in events][-3:]
        fail(
            f"no {sorted(until)} within {WAIT_SECONDS:.0f}s. "
            f"{self.describe_run(user, run_id)}; last events {seen}"
        )

    def poll(self, what: str, probe: Callable[[], Any]) -> Any:
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            found = probe()
            if found:
                return found
            time.sleep(0.5)
        fail(f"timed out after {WAIT_SECONDS:.0f}s waiting for {what}")


class MockGithub:
    def set_mode(self, mode: str) -> None:
        try:
            response = httpx.post(f"{MOCK_GITHUB_URL}/_admin/mode", json={"mode": mode}, timeout=5)
        except httpx.HTTPError as error:
            fail(f"mock-github at {MOCK_GITHUB_URL} is unreachable ({error!r})")
        if response.status_code != 200:
            fail(f"mock-github refused mode {mode!r}: {response.status_code} {response.text[:200]}")


def assert_gapless(events: list[Json], run_id: str, start: int = 1) -> None:
    seqs = [event["seq"] for event in events]
    assert seqs == list(range(start, start + len(events))), f"seq not gapless from {start}: {seqs}"
    assert {event["run_id"] for event in events} == {run_id}


def approval_requested(events: list[Json]) -> Json:
    return next(e["data"] for e in reversed(events) if e["kind"] == "approval_requested")


def tickets_for(api: Api, run_id: str) -> list[Json]:
    return [t for t in api.tickets() if t["run_id"] == run_id]


def bob_decides(api: Api, approval_id: str, verdict: str, digest: str) -> httpx.Response:
    return api.post(
        "bob",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": verdict, "digest": digest},
        expect=(201,),
    )
