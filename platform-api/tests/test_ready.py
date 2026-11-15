import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.bootstrap import LoadedWorkflow, previous_hashes, record_status
from platform_api.monitoring import CosmosEvents, callback_for
from platform_api.monitoring.log import COPIED_CHANNEL, copied_notice
from platform_api.orchestration.self_test import SelfTestsSeen, ready_line
from platform_api.settings import CosmosSettings
from platform_api.shared import RunId, TaskId
from tests.conftest import PostgresUrls, cosmos_settings, truncate_all
from tests.support import FIXTURES, LOCAL_ENV


def env_for(postgres: PostgresUrls) -> dict[str, str]:
    return {
        **LOCAL_ENV,
        "DATABASE_URL_BUILDER": postgres.contexts.builder,
        "DATABASE_URL_ORCHESTRATION": postgres.contexts.orchestration,
        "DATABASE_URL_MONITORING": postgres.contexts.monitoring,
    }


def workflows_check(body: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in body["checks"] if c["name"] == "workflows")


def test_not_ready_before_bootstrap_has_run(postgres: PostgresUrls):
    truncate_all(postgres.owner)
    with TestClient(create_app(env_for(postgres))) as client:
        response = client.get("/healthz/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert workflows_check(body)["detail"] == "bootstrap has not run yet"


def test_not_ready_when_bootstrap_recorded_a_failure(postgres: PostgresUrls):
    truncate_all(postgres.owner)
    record_status(
        postgres.owner, ready=False, detail="the error workflow is inactive", workflows=[]
    )
    with TestClient(create_app(env_for(postgres))) as client:
        response = client.get("/healthz/ready")
    assert response.status_code == 503
    assert workflows_check(response.json())["detail"].startswith("the error workflow is inactive")


def test_ready_after_a_good_bootstrap(postgres: PostgresUrls):
    truncate_all(postgres.owner)
    loaded = [LoadedWorkflow("run", "W1", True, "abc")]
    record_status(postgres.owner, ready=True, detail="all workflows loaded", workflows=loaded)
    with TestClient(create_app(env_for(postgres))) as client:
        response = client.get("/healthz/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert [c["name"] for c in body["checks"] if c["ok"]] == ["activity_log", "workflows"]
    assert previous_hashes(postgres.owner) == {"run": "abc"}


def test_the_workflows_check_names_each_loaded_workflow_and_whether_it_is_active(
    postgres: PostgresUrls,
):
    truncate_all(postgres.owner)
    loaded = [
        LoadedWorkflow("run", "W1", True, "abc"),
        LoadedWorkflow("schedule_tick", "W2", True, "def"),
        LoadedWorkflow("run_failure_reporter", "W3", False, "ghi"),
    ]
    record_status(postgres.owner, ready=False, detail="inactive in n8n", workflows=loaded)
    with TestClient(create_app(env_for(postgres))) as client:
        detail = workflows_check(client.get("/healthz/ready").json())["detail"]
    assert detail.endswith(
        "; loaded: run active, schedule_tick active, run_failure_reporter inactive"
    )


def self_test_check(body: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in body["checks"] if c["name"] == "self_test")


def plant_self_test(owner_url: str, arrived_hours_ago: float | None, sent_hours_ago: float) -> None:
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.self_tests (execution_id, workflow_id, sent_at, arrived_at) "
            "VALUES (%s, 'wf_self_test', now() - make_interval(secs => %s), "
            "now() - make_interval(secs => %s))",
            (
                uuid.uuid4().hex,
                sent_hours_ago * 3600,
                None if arrived_hours_ago is None else arrived_hours_ago * 3600,
            ),
        )


@pytest.mark.parametrize(
    ("arrived_hours_ago", "ok", "says"),
    [
        (None, False, "no self-test has reached the platform yet"),
        (25, True, "the error workflow reported the daily self-test at "),
        (27, False, "no self-test has reached the platform since "),
    ],
    ids=["none-yet", "within-26-hours", "stale"],
)
def test_the_self_test_line_warns_and_never_holds_ready_back(
    postgres: PostgresUrls, arrived_hours_ago: float | None, ok: bool, says: str
):
    """Azure's probe and every stack's start wait for ready. A missed self-test is a warning
    about the error workflow, not a reason to take the platform out of traffic."""
    truncate_all(postgres.owner)
    record_status(postgres.owner, ready=True, detail="all workflows loaded", workflows=[])
    if arrived_hours_ago is not None:
        plant_self_test(postgres.owner, arrived_hours_ago, arrived_hours_ago)
    with TestClient(create_app(env_for(postgres))) as client:
        response = client.get("/healthz/ready")
    assert response.status_code == 200
    line = self_test_check(response.json())
    assert (line["ok"], line["counts_for_ready"]) == (ok, False)
    assert line["detail"].startswith(says), line["detail"]


NOON = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("seen", "ok", "says"),
    [
        (SelfTestsSeen(NOON - timedelta(hours=26), None), True, "the error workflow reported"),
        (SelfTestsSeen(NOON - timedelta(hours=26, seconds=1), None), False, "no self-test has"),
        (
            SelfTestsSeen(NOON - timedelta(hours=30), NOON - timedelta(hours=6)),
            False,
            "the error workflow did not report: the daily self-test failed on purpose at "
            "2026-11-16T06:00:00+00:00",
        ),
        (
            SelfTestsSeen(None, NOON - timedelta(hours=6)),
            False,
            "the error workflow did not report",
        ),
        (
            SelfTestsSeen(NOON - timedelta(hours=1), NOON - timedelta(hours=30)),
            True,
            "the error workflow reported",
        ),
    ],
    ids=["at-26-hours", "just-past-26-hours", "sent-not-reported", "never-reported", "older-miss"],
)
def test_the_self_test_line_says_what_broke(seen: SelfTestsSeen, ok: bool, says: str):
    line = ready_line(seen, NOON)
    assert line[0] is ok
    assert line[1].startswith(says), line[1]


async def read_from_cosmos(settings: CosmosSettings, run_id: RunId) -> list[int]:
    events = CosmosEvents.connect(settings)
    try:
        return [e.seq for e in await events.read_after(run_id, 0)]
    finally:
        await events.close()


@pytest.mark.cosmos
def test_with_activity_reader_cosmos_the_api_copies_each_event_and_reads_it_back(
    postgres: PostgresUrls,
):
    settings = cosmos_settings()
    truncate_all(postgres.owner)
    record_status(postgres.owner, ready=True, detail="all workflows loaded", workflows=[])
    env = {
        **env_for(postgres),
        "COSMOS_ENDPOINT": settings.endpoint,
        "COSMOS_KEY": settings.key,
        "ACTIVITY_READER": "cosmos",
    }
    run_id = RunId(f"run_ready{uuid.uuid4().hex[:12]}")
    task_id = TaskId(f"{run_id}/work/1/1")
    post = json.loads((FIXTURES / "agent" / "callback-event.json").read_text())
    post["task_id"] = task_id
    token = callback_for(
        LOCAL_ENV["CALLBACK_SIGNING_KEY"],
        LOCAL_ENV["PLATFORM_INTERNAL_URL"],
        run_id,
        task_id,
        datetime.now(UTC) + timedelta(hours=1),
    ).token

    with (
        psycopg.connect(postgres.contexts.monitoring, autocommit=True) as listener,
        TestClient(create_app(env)) as client,
    ):
        listener.execute(f"LISTEN {COPIED_CHANNEL}")
        ready = client.get("/healthz/ready")
        assert ready.status_code == 200
        assert {k: v for k, v in ready.json()["checks"][1].items() if k in ("name", "ok")} == {
            "name": "activity_copy",
            "ok": True,
        }
        posted = client.post(
            f"/internal/v1/runs/{run_id}/agent-events",
            params={"task": task_id},
            json=post,
            headers={"X-Callback-Token": token},
        )
        page = client.get(f"/api/v1/runs/{run_id}/events", headers={"X-Dev-User": "alice"})
        # Stopping the app cancels a copy still under way, so wait for the copier to announce it.
        copied = [n.payload for n in listener.notifies(timeout=30, stop_after=1)]

    assert posted.status_code == 202
    assert [e["kind"] for e in page.json()["events"]] == ["agent_joined"]
    assert copied == [copied_notice(run_id, 1)]
    assert asyncio.run(read_from_cosmos(settings, run_id)) == [1]
