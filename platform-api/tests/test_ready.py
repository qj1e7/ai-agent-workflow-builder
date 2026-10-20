from fastapi.testclient import TestClient

from platform_api.app import create_app
from platform_api.bootstrap import LoadedWorkflow, previous_hashes, record_status
from tests.conftest import PostgresUrls, truncate_all
from tests.support import LOCAL_ENV


def env_for(postgres: PostgresUrls) -> dict[str, str]:
    return {
        **LOCAL_ENV,
        "DATABASE_URL_BUILDER": postgres.contexts.builder,
        "DATABASE_URL_ORCHESTRATION": postgres.contexts.orchestration,
        "DATABASE_URL_MONITORING": postgres.contexts.monitoring,
    }


def workflows_check(body: dict) -> dict:  # type: ignore[type-arg]
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
    loaded = [LoadedWorkflow("release_check", "W1", True, "abc")]
    record_status(postgres.owner, ready=True, detail="all workflows loaded", workflows=loaded)
    with TestClient(create_app(env_for(postgres))) as client:
        response = client.get("/healthz/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert [c["name"] for c in body["checks"] if c["ok"]] == ["activity_log", "workflows"]
    assert previous_hashes(postgres.owner) == {"release_check": "abc"}
