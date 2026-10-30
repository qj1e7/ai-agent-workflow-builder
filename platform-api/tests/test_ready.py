import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.bootstrap import LoadedWorkflow, previous_hashes, record_status
from platform_api.monitoring import CosmosEvents, callback_for
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

    with TestClient(create_app(env)) as client:
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

    assert posted.status_code == 202
    assert [e["kind"] for e in page.json()["events"]] == ["agent_joined"]
    assert asyncio.run(read_from_cosmos(settings, run_id)) == [1]
