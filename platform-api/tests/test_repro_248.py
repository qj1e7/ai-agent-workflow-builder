import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.bootstrap import record_status
from platform_api.monitoring import callback_for
from platform_api.monitoring.cosmos_log import DATABASE, cosmos_client
from platform_api.settings import CosmosSettings
from platform_api.shared import RunId, TaskId
from tests.conftest import PostgresUrls, cosmos_settings, truncate_all
from tests.support import FIXTURES, LOCAL_ENV
from tests.test_ready import env_for, read_from_cosmos

logger = logging.getLogger("platform_api.repro248")


async def drop_activity_database(settings: CosmosSettings) -> None:
    client = cosmos_client(settings)
    try:
        with suppress(CosmosResourceNotFoundError):
            await client.delete_database(DATABASE)
    finally:
        await client.close()


@pytest.mark.cosmos
@pytest.mark.parametrize(
    "cold",
    [pytest.param(i % 2 == 0, id=f"{i}-{'cold' if i % 2 == 0 else 'warm'}") for i in range(16)],
)
def test_repro_248(postgres: PostgresUrls, cold: bool):
    settings = cosmos_settings()
    if cold:
        asyncio.run(drop_activity_database(settings))
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

    logger.info("#248 test: cold=%s run=%s, app starts", cold, run_id)
    with TestClient(create_app(env)) as client:
        logger.info("#248 test: app started")
        ready = client.get("/healthz/ready")
        logger.info("#248 test: ready %s %s", ready.status_code, ready.json()["checks"][1])
        posted = client.post(
            f"/internal/v1/runs/{run_id}/agent-events",
            params={"task": task_id},
            json=post,
            headers={"X-Callback-Token": token},
        )
        logger.info("#248 test: posted %s", posted.status_code)
        page = client.get(f"/api/v1/runs/{run_id}/events", headers={"X-Dev-User": "alice"})
        logger.info("#248 test: page %s, app stops", [e["seq"] for e in page.json()["events"]])
    logger.info("#248 test: app stopped")
    with psycopg.connect(postgres.owner) as conn:
        copied = conn.execute(
            "SELECT generation, seq FROM monitoring.run_events_copied WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    first = asyncio.run(read_from_cosmos(settings, run_id))
    time.sleep(3)
    later = asyncio.run(read_from_cosmos(settings, run_id))
    logger.info("#248 test: copied row %s; cosmos now %s, 3 s later %s", copied, first, later)
    assert later == [1]
