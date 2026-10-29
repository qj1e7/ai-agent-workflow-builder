import re

import pytest
from fastapi.testclient import TestClient

from platform_api.builder.service import NothingToCheck
from platform_api.orchestration import RunStarted
from platform_api.shared import RunId
from tests.declared import ALICE, BOB, FakeBuilder, app_with, declared_status

USE_CASE = {
    "template": "software_watchlist",
    "name": "Software watchlist",
    "instruction": "Check the team's watched software for new releases.",
    "params": {"ticket_project": "MOCK"},
}
KEY = {"Idempotency-Key": "k"}
REPEATED = FakeBuilder(started=RunStarted(RunId("run_1"), created=False))
SCHEDULE = {"day": "monday", "at": "09:00"}
SOFTWARE = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
RESTORE = "/api/v1/watchlist/software/{}/restore"

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
    pytest.param(
        "POST",
        "/api/v1/use-cases/{use_case_id}/runs",
        {**ALICE, **KEY},
        None,
        FakeBuilder(started=NothingToCheck()),
        409,
        id="start-409-empty-watchlist",
    ),
    pytest.param("GET", "/api/v1/watchlist", {}, None, None, 401, id="watchlist-401"),
    pytest.param(
        "POST", "/api/v1/watchlist/software", {}, SOFTWARE, None, 401, id="add-software-401"
    ),
    pytest.param(
        "POST", "/api/v1/watchlist/software", BOB, SOFTWARE, None, 403, id="add-software-403"
    ),
    pytest.param(
        "POST",
        "/api/v1/watchlist/software",
        ALICE,
        {**SOFTWARE, "repo": "owner/.."},
        None,
        422,
        id="add-software-422",
    ),
    pytest.param("DELETE", "/api/v1/watchlist/software/sw_x", {}, None, None, 401, id="remove-401"),
    pytest.param(
        "DELETE", "/api/v1/watchlist/software/sw_x", BOB, None, None, 403, id="remove-403"
    ),
    pytest.param(
        "DELETE", "/api/v1/watchlist/software/sw_x", ALICE, None, None, 404, id="remove-404"
    ),
    pytest.param("POST", RESTORE.format("sw_x"), {}, None, None, 401, id="restore-401"),
    pytest.param("POST", RESTORE.format("sw_x"), BOB, None, None, 403, id="restore-403"),
    pytest.param("POST", RESTORE.format("sw_x"), ALICE, None, None, 404, id="restore-404"),
    pytest.param("POST", RESTORE.format("sw_again"), ALICE, None, None, 409, id="restore-409"),
    pytest.param("POST", RESTORE.format("sw_full"), ALICE, None, None, 422, id="restore-422"),
    pytest.param("PUT", "/api/v1/watchlist/schedule", {}, SCHEDULE, None, 401, id="schedule-401"),
    pytest.param("PUT", "/api/v1/watchlist/schedule", BOB, SCHEDULE, None, 403, id="schedule-403"),
    pytest.param(
        "PUT", "/api/v1/watchlist/schedule", ALICE, SCHEDULE, None, 404, id="schedule-404"
    ),
    pytest.param(
        "PUT",
        "/api/v1/watchlist/schedule",
        ALICE,
        {**SCHEDULE, "at": "09:03"},
        None,
        422,
        id="schedule-422",
    ),
    pytest.param("DELETE", "/api/v1/watchlist/schedule", {}, None, None, 401, id="off-401"),
    pytest.param("DELETE", "/api/v1/watchlist/schedule", BOB, None, None, 403, id="off-403"),
    pytest.param("DELETE", "/api/v1/watchlist/schedule", ALICE, None, None, 404, id="off-404"),
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
    declared_status(app, method, re.sub(r"/sw_[a-z]+", "/{software_id}", path), response)
