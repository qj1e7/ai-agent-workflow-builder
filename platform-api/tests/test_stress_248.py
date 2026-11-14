import asyncio
import json
import logging
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
from platform_api.monitoring.log import COPIED_CHANNEL, copied_notice
from platform_api.settings import CosmosSettings
from platform_api.shared import RunId, TaskId
from tests.conftest import PostgresUrls, cosmos_settings, truncate_all
from tests.support import FIXTURES, LOCAL_ENV
from tests.test_ready import env_for, read_from_cosmos

logger = logging.getLogger("platform_api.stress248")


async def drop_activity_database(settings: CosmosSettings) -> None:
    client = cosmos_client(settings)
    try:
        with suppress(CosmosResourceNotFoundError):
            await client.delete_database(DATABASE)
    finally:
        await client.close()


@pytest.mark.cosmos
@pytest.mark.parametrize("i", range(24))
def test_stress_248(postgres: PostgresUrls, i: int):
    settings = cosmos_settings()
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
    with (
        psycopg.connect(postgres.contexts.monitoring, autocommit=True) as listener,
        TestClient(create_app(env)) as client,
    ):
        listener.execute(f"LISTEN {COPIED_CHANNEL}")
        client.get("/healthz/ready")
        client.post(
            f"/internal/v1/runs/{run_id}/agent-events",
            params={"task": task_id},
            json=post,
            headers={"X-Callback-Token": token},
        )
        client.get(f"/api/v1/runs/{run_id}/events", headers={"X-Dev-User": "alice"})
        with psycopg.connect(postgres.owner) as conn:
            recorded = conn.execute(
                "SELECT seq FROM monitoring.run_events_copied WHERE run_id = %s", (run_id,)
            ).fetchone()
        copied = [n.payload for n in listener.notifies(timeout=30, stop_after=1)]
    logger.warning("#248 stress %d: in flight after the page: %s", i, recorded is None)
    assert copied == [copied_notice(run_id, 1)]
    assert asyncio.run(read_from_cosmos(settings, run_id)) == [1]
