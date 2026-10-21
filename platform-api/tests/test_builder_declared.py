import pytest
from fastapi.testclient import TestClient

from platform_api.orchestration import RunStarted
from platform_api.shared import RunId
from tests.declared import ALICE, BOB, FakeBuilder, app_with, declared_status

USE_CASE = {
    "template": "release_check",
    "name": "LangGraph releases",
    "instruction": "Check langchain-ai/langgraph for new releases.",
    "params": {"repo": "langchain-ai/langgraph", "ticket_project": "MOCK"},
}
KEY = {"Idempotency-Key": "k"}
REPEATED = FakeBuilder(started=RunStarted(RunId("run_1"), created=False))

CASES = [
    pytest.param("GET", "/api/v1/templates", {}, None, None, 401, id="templates-401"),
    pytest.param("GET", "/api/v1/use-cases", {}, None, None, 401, id="use-cases-401"),
    pytest.param("POST", "/api/v1/use-cases", {}, USE_CASE, None, 401, id="create-401"),
    pytest.param("POST", "/api/v1/use-cases", BOB, USE_CASE, None, 403, id="create-403"),
    pytest.param(
        "POST", "/api/v1/use-cases/suggest", {}, {"text": "releases"}, None, 401, id="suggest-401"
    ),
    pytest.param("GET", "/api/v1/use-cases/{use_case_id}", {}, None, None, 401, id="get-401"),
    pytest.param("GET", "/api/v1/use-cases/{use_case_id}", ALICE, None, None, 404, id="get-404"),
    pytest.param(
        "POST", "/api/v1/use-cases/{use_case_id}/runs", KEY, None, None, 401, id="start-401"
    ),
    pytest.param(
        "POST",
        "/api/v1/use-cases/{use_case_id}/runs",
        {**BOB, **KEY},
        None,
        None,
        403,
        id="start-403",
    ),
    pytest.param(
        "POST",
        "/api/v1/use-cases/{use_case_id}/runs",
        {**ALICE, **KEY},
        None,
        None,
        404,
        id="start-404",
    ),
    pytest.param(
        "POST",
        "/api/v1/use-cases/{use_case_id}/runs",
        {**ALICE, **KEY},
        None,
        REPEATED,
        200,
        id="start-200-repeat",
    ),
]


@pytest.mark.parametrize(("method", "path", "headers", "body", "builder", "status"), CASES)
def test_the_route_answers_the_status_and_declares_it(
    method: str, path: str, headers: dict[str, str], body: object, builder: object, status: int
):
    app = app_with(builder=builder)
    response = TestClient(app).request(
        method, path.format(use_case_id="uc_x"), headers=headers, json=body
    )
    assert response.status_code == status
    declared_status(app, method, path, response)
