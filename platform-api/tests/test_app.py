import pytest
from fastapi.testclient import TestClient

from platform_api.app import create_app, readiness_of
from platform_api.db import Database
from platform_api.orchestration.approvals import Refusal
from platform_api.orchestration.service import DecisionRefused, RetryLater
from tests.support import LOCAL_ENV as LOCAL

ROUTES = {
    ("GET", "/healthz"),
    ("GET", "/healthz/ready"),
    ("GET", "/api/v1/dev/users"),
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/templates"),
    ("POST", "/api/v1/use-cases"),
    ("GET", "/api/v1/use-cases"),
    ("POST", "/api/v1/use-cases/suggest"),
    ("GET", "/api/v1/use-cases/{use_case_id}"),
    ("POST", "/api/v1/use-cases/{use_case_id}/runs"),
    ("POST", "/api/v1/use-cases/{use_case_id}/pause"),
    ("POST", "/api/v1/use-cases/{use_case_id}/resume"),
    ("DELETE", "/api/v1/use-cases/{use_case_id}"),
    ("POST", "/api/v1/use-cases/{use_case_id}/restore"),
    ("PUT", "/api/v1/drafts/{draft_id}"),
    ("GET", "/api/v1/drafts"),
    ("DELETE", "/api/v1/drafts/{draft_id}"),
    ("GET", "/api/v1/tools"),
    ("GET", "/api/v1/agent-cards"),
    ("POST", "/api/v1/agent-cards"),
    ("POST", "/api/v1/agent-cards/check"),
    ("GET", "/api/v1/agent-cards/{card_id}"),
    ("PUT", "/api/v1/agent-cards/{card_id}"),
    ("POST", "/api/v1/builder/plan"),
    ("POST", "/api/v1/builder/understand"),
    ("POST", "/api/v1/agent-use-cases"),
    ("GET", "/api/v1/watchlist"),
    ("POST", "/api/v1/watchlist/software"),
    ("PUT", "/api/v1/watchlist/schedule"),
    ("DELETE", "/api/v1/watchlist/schedule"),
    ("DELETE", "/api/v1/watchlist/software/{software_id}"),
    ("GET", "/api/v1/runs"),
    ("GET", "/api/v1/runs/{run_id}"),
    ("POST", "/api/v1/runs/{run_id}/retry"),
    ("GET", "/api/v1/runs/{run_id}/events"),
    ("GET", "/api/v1/runs/{run_id}/troubleshoot"),
    ("GET", "/api/v1/approvals/{approval_id}"),
    ("POST", "/api/v1/approvals/{approval_id}/decisions"),
    ("GET", "/api/v1/teams-stub/messages"),
    ("GET", "/api/v1/mock-jira/tickets"),
    ("POST", "/api/v1/mock-jira/tickets/{key}/done"),
    ("POST", "/internal/v1/runs/{run_id}/steps/{step}"),
    ("POST", "/internal/v1/runs/{run_id}/agent-events"),
    ("GET", "/internal/v1/runs/{run_id}/practice-jira/tickets"),
    ("GET", "/internal/v1/runs/{run_id}/practice-jira/tickets/{key}"),
    ("POST", "/internal/v1/schedules/tick"),
    ("POST", "/internal/v1/workflow-failures"),
    ("GET", "/api/v1/settings/model"),
    ("PUT", "/api/v1/settings/model"),
    ("DELETE", "/api/v1/settings/model"),
    ("POST", "/api/v1/settings/model/connect"),
    ("POST", "/api/v1/settings/model/address-decision"),
    ("GET", "/api/v1/settings/history"),
    ("GET", "/api/v1/people"),
    ("POST", "/api/v1/people"),
    ("PUT", "/api/v1/people/{person_id}/operator"),
    ("POST", "/api/v1/people/{person_id}/approver"),
    ("DELETE", "/api/v1/people/{person_id}/approver"),
    ("DELETE", "/api/v1/people/{person_id}"),
    ("GET", "/api/v1/confirmations"),
    ("POST", "/api/v1/confirmations/{confirmation_id}/decisions"),
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(LOCAL))


def test_openapi_lists_every_route(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    listed = {(method.upper(), path) for path, ops in paths.items() for method in ops}
    assert listed == ROUTES


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [
        ("/healthz", {}, 200),
        ("/api/v1/dev/users", {}, 200),
        ("/api/v1/runs", {}, 401),
        ("/no/such/route", {}, 404),
        ("/openapi.json", {}, 200),
    ],
)
def test_every_response_forbids_content_sniffing(
    client: TestClient, path: str, headers: dict[str, str], status: int
):
    response = client.get(path, headers=headers)
    assert response.status_code == status
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_trailing_slash_is_not_found_and_never_redirects(client: TestClient):
    response = client.get("/api/v1/runs/", headers={"X-Dev-User": "alice"}, follow_redirects=False)
    assert response.status_code == 404
    assert "location" not in response.headers


def test_healthz(client: TestClient):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_events_route_documents_both_content_types(client: TestClient):
    op = client.get("/openapi.json").json()["paths"]["/api/v1/runs/{run_id}/events"]["get"]
    assert set(op["responses"]["200"]["content"]) == {"application/json", "text/event-stream"}
    assert {p["name"] for p in op["parameters"]} >= {"after", "Last-Event-ID"}


def test_step_route_refuses_a_bad_step_name():
    app = create_app(LOCAL)
    app.state.orchestrator = None
    client = TestClient(app)
    r = client.post(
        "/internal/v1/runs/run_1/steps/delete_everything",
        headers={"X-Step-Key": LOCAL["STEP_KEY"], "X-N8N-Execution": "1"},
    )
    assert r.status_code == 422


@pytest.mark.anyio
async def test_readiness_is_not_ready_before_bootstrap(db: Database):
    readiness = await readiness_of(db, True)
    assert readiness.ready is False
    assert [(c.name, c.ok) for c in readiness.checks] == [
        ("activity_log", True),
        ("workflows", False),
    ]


class RefusingOrchestrator:
    async def decide(self, *args: object) -> DecisionRefused:
        return DecisionRefused(Refusal.OWN_WORK)

    async def on_step(self, *args: object) -> None:
        raise RetryLater("n8n is still starting")


@pytest.fixture
def refusing_client() -> TestClient:
    app = create_app(LOCAL)
    app.state.orchestrator = RefusingOrchestrator()
    return TestClient(app)


def test_a_refused_decision_answers_the_documented_refusal_body(refusing_client: TestClient):
    r = refusing_client.post(
        "/api/v1/approvals/apr_1/decisions",
        headers={"X-Dev-User": "alice"},
        json={"step": 0, "verdict": "approve", "digest": "sha256:" + "0" * 64},
    )
    assert r.status_code == 403
    assert r.json() == {
        "refusal": "own_work",
        "message": "You started this run, so another Approver must decide.",
    }


def test_a_step_told_to_retry_answers_the_documented_retry_body(refusing_client: TestClient):
    r = refusing_client.post(
        "/internal/v1/runs/run_1/steps/run_agents",
        headers={"X-Step-Key": LOCAL["STEP_KEY"], "X-N8N-Execution": "1"},
    )
    assert r.status_code == 503
    assert r.json() == {"detail": "n8n is still starting", "retryable": True}
