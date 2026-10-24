import pytest
from fastapi.testclient import TestClient

from platform_api.orchestration.approvals import Refusal
from platform_api.orchestration.service import (
    DecisionRace,
    DecisionRefused,
    NotFound,
    NotRetryable,
)
from tests.declared import ALICE, BOB, FakeOrchestrator, app_with, declared_status

DIGEST = "sha256:" + "0" * 64
DECISION = {"step": 0, "verdict": "approve", "digest": DIGEST}

CASES = [
    pytest.param("GET", "/api/v1/runs", {}, None, FakeOrchestrator(), 401, id="runs-401"),
    pytest.param("GET", "/api/v1/runs/{run_id}", {}, None, FakeOrchestrator(), 401, id="run-401"),
    pytest.param(
        "GET", "/api/v1/runs/{run_id}", ALICE, None, FakeOrchestrator(), 404, id="run-404"
    ),
    pytest.param(
        "POST", "/api/v1/runs/{run_id}/retry", {}, None, FakeOrchestrator(), 401, id="retry-401"
    ),
    pytest.param(
        "POST", "/api/v1/runs/{run_id}/retry", BOB, None, FakeOrchestrator(), 403, id="retry-403"
    ),
    pytest.param(
        "POST",
        "/api/v1/runs/{run_id}/retry",
        ALICE,
        None,
        FakeOrchestrator(retry=NotFound()),
        404,
        id="retry-404",
    ),
    pytest.param(
        "POST",
        "/api/v1/runs/{run_id}/retry",
        ALICE,
        None,
        FakeOrchestrator(retry=NotRetryable("The run is succeeded, not failed")),
        409,
        id="retry-409",
    ),
    pytest.param(
        "GET",
        "/api/v1/approvals/{approval_id}",
        {},
        None,
        FakeOrchestrator(),
        401,
        id="approval-401",
    ),
    pytest.param(
        "GET",
        "/api/v1/approvals/{approval_id}",
        ALICE,
        None,
        FakeOrchestrator(),
        404,
        id="approval-404",
    ),
    pytest.param(
        "POST",
        "/api/v1/approvals/{approval_id}/decisions",
        {},
        DECISION,
        FakeOrchestrator(),
        401,
        id="decide-401",
    ),
    pytest.param(
        "POST",
        "/api/v1/approvals/{approval_id}/decisions",
        ALICE,
        DECISION,
        FakeOrchestrator(decide=DecisionRefused(Refusal.OWN_WORK)),
        403,
        id="decide-403",
    ),
    pytest.param(
        "POST",
        "/api/v1/approvals/{approval_id}/decisions",
        ALICE,
        DECISION,
        FakeOrchestrator(decide=NotFound()),
        404,
        id="decide-404",
    ),
    pytest.param(
        "POST",
        "/api/v1/approvals/{approval_id}/decisions",
        ALICE,
        DECISION,
        FakeOrchestrator(decide=DecisionRace()),
        409,
        id="decide-409",
    ),
    pytest.param("GET", "/api/v1/teams-stub/messages", {}, None, None, 401, id="teams-401"),
    pytest.param("GET", "/api/v1/mock-jira/tickets", {}, None, None, 401, id="jira-401"),
    pytest.param(
        "POST", "/api/v1/mock-jira/tickets/{key}/done", {}, None, None, 401, id="jira-done-401"
    ),
    pytest.param(
        "POST", "/api/v1/mock-jira/tickets/{key}/done", BOB, None, None, 403, id="jira-done-403"
    ),
    pytest.param(
        "POST", "/api/v1/mock-jira/tickets/{key}/done", ALICE, None, None, 404, id="jira-done-404"
    ),
    pytest.param(
        "POST",
        "/internal/v1/runs/{run_id}/steps/{step}",
        {"X-Step-Key": "wrong", "X-N8N-Execution": "1"},
        None,
        None,
        401,
        id="step-401",
    ),
    pytest.param(
        "POST",
        "/internal/v1/schedules/tick",
        {"X-Step-Key": "wrong"},
        None,
        None,
        401,
        id="tick-401",
    ),
    pytest.param(
        "POST",
        "/internal/v1/workflow-failures",
        {"X-Step-Key": "wrong"},
        {
            "execution_id": "1",
            "workflow": "w",
            "last_node": "n",
            "message": "m",
            "execution_url": "http://n8n/e/1",
        },
        None,
        401,
        id="workflow-failure-401",
    ),
]


@pytest.mark.parametrize(("method", "path", "headers", "body", "orchestrator", "status"), CASES)
def test_the_route_answers_the_status_and_declares_it(
    method: str,
    path: str,
    headers: dict[str, str],
    body: object,
    orchestrator: object,
    status: int,
):
    app = app_with(orchestrator=orchestrator)
    concrete = path.format(run_id="run_x", approval_id="apr_x", step="run_agents", key="MOCK-1")
    response = TestClient(app).request(method, concrete, headers=headers, json=body)
    assert response.status_code == status
    declared_status(app, method, path, response)
