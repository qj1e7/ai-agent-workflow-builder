import pytest
from fastapi.testclient import TestClient

from platform_api.monitoring import activity_events_adapter
from tests.declared import ALICE, FakeLog, app_with, declared_status
from tests.support import fixture

NEVER_FAILED = activity_events_adapter.validate_python(fixture("runs/success.json"))
CALLBACK_EVENT = fixture("agent/callback-event.json")

CASES = [
    pytest.param("GET", "/api/v1/runs/{run_id}/events", {}, None, [], 401, id="events-401"),
    pytest.param(
        "GET", "/api/v1/runs/{run_id}/troubleshoot", {}, None, [], 401, id="troubleshoot-401"
    ),
    pytest.param(
        "GET", "/api/v1/runs/{run_id}/troubleshoot", ALICE, None, [], 404, id="troubleshoot-404"
    ),
    pytest.param(
        "GET",
        "/api/v1/runs/{run_id}/troubleshoot",
        ALICE,
        None,
        NEVER_FAILED,
        409,
        id="troubleshoot-409",
    ),
    pytest.param(
        "POST",
        "/internal/v1/runs/{run_id}/agent-events?task=run_x/work/1/1",
        {"X-Callback-Token": "forged"},
        CALLBACK_EVENT,
        [],
        401,
        id="agent-events-401",
    ),
]


@pytest.mark.parametrize(("method", "path", "headers", "body", "events", "status"), CASES)
def test_the_route_answers_the_status_and_declares_it(
    method: str, path: str, headers: dict[str, str], body: object, events: list, status: int
):
    app = app_with(log=FakeLog(events))
    response = TestClient(app).request(
        method, path.format(run_id="run_x"), headers=headers, json=body
    )
    assert response.status_code == status
    declared_status(app, method, path.split("?")[0], response)
