"""n8n's error workflow reports through Report a failure, and a daily self-test proves it
(ENGINE-PLAN E3, the AGENTS.md rule "n8n error workflows must be active, or n8n skips them")."""

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import psycopg
import pytest
from harness import DATABASE_URL, N8N_OWNER, N8N_URL, Api, Json, MockGithub, fail
from test_n8n_engine import set_up, tidy

SELF_TEST_WAIT_SECONDS = 180
"""Every minute, at n8n's hidden second, and the time for the report to come back."""
EVERY_MINUTE = [{"field": "minutes", "minutesInterval": 1}]


def loaded_workflow(name: str) -> str:
    """The id bootstrap recorded for one of the platform's own workflows."""
    if not DATABASE_URL:
        fail("E2E_DATABASE_URL is not set, so the platform's own workflows cannot be found.")
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute(
            "SELECT workflows FROM orchestration.engine_status WHERE id = 1"
        ).fetchone()
    loaded = cast(list[Json], [] if row is None else row[0])
    found = next((str(w["id"]) for w in loaded if w["name"] == name), None)
    if found is None:
        fail(f"bootstrap did not load {name}: {loaded}")
    return found


KEY_LABEL = "e2e error workflow"


def remove_keys() -> None:
    for key in cast(list[Json], N8N_OWNER.call("GET", "/api-keys")["items"]):
        if key["label"] == KEY_LABEL:
            N8N_OWNER.call("DELETE", f"/api-keys/{key['id']}")


@pytest.fixture(scope="module")
def n8n_public() -> Iterator[httpx.Client]:
    """n8n's public API with a key of the test's own, to read executions with their data as
    the platform does. The key goes again after the module."""
    remove_keys()
    scopes = ["execution:list", "execution:read"]
    body = {"label": KEY_LABEL, "expiresAt": None, "scopes": scopes}
    created = N8N_OWNER.call("POST", "/api-keys", body)
    client = httpx.Client(
        base_url=f"{N8N_URL}/api/v1",
        headers={"X-N8N-API-KEY": str(created["rawApiKey"])},
        timeout=30,
    )
    try:
        yield client
    finally:
        client.close()
        remove_keys()


def reported(n8n_public: httpx.Client, reporter: str, execution: str) -> Json | None:
    """The error workflow's execution whose Error Trigger was handed this failed execution."""
    page = n8n_public.get("/executions", params={"workflowId": reporter, "includeData": "true"})
    page.raise_for_status()
    for item in cast(list[Json], page.json()["data"]):
        runs = cast(dict[str, Any], item.get("data") or {}).get("resultData", {}).get("runData", {})
        for run in runs.get("Error Trigger", []):
            handed = run["data"]["main"][0][0]["json"]
            if str(handed.get("execution", {}).get("id")) == execution:
                return item
    return None


def test_failure_reported(api: Api, mock_model: None, github: MockGithub, n8n_public: httpx.Client):
    """A Read that fails ends as a failed run with the block's words, and n8n's own record shows
    the error workflow handed that execution to Report a failure, which our API took. The sweep
    may settle the run first; the report must still reach our API."""
    reporter = loaded_workflow("run_failure_reporter")
    use_case_id = set_up(api, "e2e failure reported", on=True)["use_case_id"]
    github.set_mode("unavailable")
    run_id, _ = api.start_run("carol", use_case_id)
    stopped = api.wait_for_state("carol", run_id, {"failed", "awaiting_approval"})
    assert stopped["state"] == "failed", "a check that read nothing never asks for a yes"
    assert (stopped["reason"], stopped["retryable"]) == ("WorkflowNodeError", True)
    assert '"Read release" failed in n8n' in stopped["message"]
    [execution] = [
        e["data"]["execution_id"]
        for e in api.events_after("carol", run_id)
        if e["kind"] == "execution_linked"
    ]

    report = api.poll(
        f"the error workflow to report execution {execution}",
        lambda: reported(n8n_public, reporter, execution),
    )
    assert report["status"] == "success", "Report a failure got an answer from our API"
    github.set_mode("ok")
    tidy(api, use_case_id)


def self_tests_since(since: datetime) -> list[tuple[Any, Any]]:
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute(
            "SELECT sent_at, arrived_at FROM orchestration.self_tests "
            "WHERE arrived_at >= %s ORDER BY arrived_at",
            (since,),
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def set_rule(workflow_id: str, interval: list[Json]) -> None:
    """Changes the self-test's Schedule Trigger in n8n and publishes it, as the owner."""
    held = N8N_OWNER.call("GET", f"/workflows/{workflow_id}")
    nodes = cast(list[Json], held["nodes"])
    for node in nodes:
        if node["type"] == "n8n-nodes-base.scheduleTrigger":
            node["parameters"]["rule"]["interval"] = interval
    body = {"nodes": nodes, "connections": held["connections"], "versionId": held["versionId"]}
    draft = N8N_OWNER.call("PATCH", f"/workflows/{workflow_id}", body)
    activate = {"versionId": draft["versionId"], "expectedChecksum": draft["checksum"]}
    N8N_OWNER.call("POST", f"/workflows/{workflow_id}/activate", activate)


def schedule_rule(workflow_id: str) -> list[Json]:
    held = N8N_OWNER.call("GET", f"/workflows/{workflow_id}")
    [trigger] = [n for n in held["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"]
    return cast(list[Json], trigger["parameters"]["rule"]["interval"])


def test_self_test(api: Api):
    """The self-test fails on purpose in n8n, and its failure travels n8n's error workflow and
    Report a failure to our API, which keeps it as the self-test's arrival. It is no run: no run
    fails, no card goes to Teams, and /healthz/ready says the error workflow reports. n8n runs it
    once a day, so the test moves its schedule to every minute and back."""
    self_test = loaded_workflow("self_test_failure")
    daily = schedule_rule(self_test)
    runs_before = {r["run_id"] for r in api.get("alice", "/api/v1/runs")["runs"]}
    cards_before = len(api.get("alice", "/api/v1/teams-stub/messages")["messages"])
    since = datetime.now(UTC)

    set_rule(self_test, EVERY_MINUTE)
    try:
        deadline = time.monotonic() + SELF_TEST_WAIT_SECONDS
        arrivals = self_tests_since(since)
        while not arrivals and time.monotonic() < deadline:
            time.sleep(3)
            arrivals = self_tests_since(since)
    finally:
        set_rule(self_test, daily)
    if not arrivals:
        fail(f"no self-test reached the platform within {SELF_TEST_WAIT_SECONDS}s")

    sent, arrived = arrivals[0]
    assert sent is not None and sent <= arrived, "its Read reached our API, then the report came"
    ready = api.client.get("/healthz/ready")
    assert ready.status_code == 200
    [line] = [c for c in ready.json()["checks"] if c["name"] == "self_test"]
    assert line["ok"] is True and line["counts_for_ready"] is False
    assert line["detail"].startswith("the error workflow reported the daily self-test at ")
    runs_after = {r["run_id"] for r in api.get("alice", "/api/v1/runs")["runs"]}
    assert runs_after == runs_before, "a self-test is never a run"
    assert len(api.get("alice", "/api/v1/teams-stub/messages")["messages"]) == cards_before
    assert schedule_rule(self_test) == daily
