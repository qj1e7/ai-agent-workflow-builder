import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app

LOCAL = {"AUTH_MODE": "dev", "PUBLIC_BASE_URL": "http://localhost:8000"}
ALICE = {"X-Dev-User": "alice"}

ROUTES = {
    ("GET", "/healthz"),
    ("GET", "/healthz/ready"),
    ("GET", "/api/v1/dev/users"),
    ("GET", "/api/v1/templates"),
    ("POST", "/api/v1/use-cases"),
    ("GET", "/api/v1/use-cases"),
    ("POST", "/api/v1/use-cases/suggest"),
    ("GET", "/api/v1/use-cases/{use_case_id}"),
    ("POST", "/api/v1/use-cases/{use_case_id}/runs"),
    ("GET", "/api/v1/runs"),
    ("GET", "/api/v1/runs/{run_id}"),
    ("POST", "/api/v1/runs/{run_id}/retry"),
    ("GET", "/api/v1/runs/{run_id}/events"),
    ("GET", "/api/v1/runs/{run_id}/troubleshoot"),
    ("GET", "/api/v1/approvals/{approval_id}"),
    ("POST", "/api/v1/approvals/{approval_id}/decisions"),
    ("GET", "/api/v1/teams-stub/messages"),
    ("GET", "/api/v1/mock-jira/tickets"),
    ("POST", "/internal/v1/runs/{run_id}/steps/{step}"),
    ("POST", "/internal/v1/runs/{run_id}/agent-events"),
    ("POST", "/internal/v1/workflow-failures"),
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(LOCAL))


def test_openapi_lists_every_route(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    listed = {(method.upper(), path) for path, ops in paths.items() for method in ops}
    assert listed == ROUTES


def test_healthz(client: TestClient):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_events_route_documents_both_content_types(client: TestClient):
    op = client.get("/openapi.json").json()["paths"]["/api/v1/runs/{run_id}/events"]["get"]
    assert set(op["responses"]["200"]["content"]) == {"application/json", "text/event-stream"}
    assert {p["name"] for p in op["parameters"]} >= {"after", "Last-Event-ID"}


def test_step_route_refuses_a_bad_step_name(client: TestClient):
    r = client.post(
        "/internal/v1/runs/run_1/steps/delete_everything",
        headers={"X-Step-Key": "k", "X-N8N-Execution": "1"},
    )
    assert r.status_code == 422


def test_unimplemented_routes_answer_501(client: TestClient):
    assert client.get("/api/v1/runs/run_1", headers=ALICE).status_code == 501
    assert client.get("/healthz/ready").status_code == 501
