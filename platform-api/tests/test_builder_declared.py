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
    pytest.param(
        "POST", "/api/v1/builder/understand", {}, {"text": "x"}, None, 401, id="understand-401"
    ),
    pytest.param(
        "POST", "/api/v1/builder/understand", BOB, {"text": "x"}, None, 403, id="understand-403"
    ),
    pytest.param(
        "POST", "/api/v1/builder/understand", ALICE, {"text": ""}, None, 422, id="understand-422"
    ),
    pytest.param("DELETE", "/api/v1/watchlist/schedule", {}, None, None, 401, id="off-401"),
    pytest.param("DELETE", "/api/v1/watchlist/schedule", BOB, None, None, 403, id="off-403"),
    pytest.param("DELETE", "/api/v1/watchlist/schedule", ALICE, None, None, 404, id="off-404"),
]


CHANGES = [
    pytest.param("POST", "/api/v1/use-cases/uc_x/pause", None, id="pause"),
    pytest.param("POST", "/api/v1/use-cases/uc_x/resume", None, id="resume"),
    pytest.param("DELETE", "/api/v1/use-cases/uc_x", None, id="delete"),
    pytest.param("POST", "/api/v1/use-cases/uc_x/restore", None, id="restore"),
    pytest.param("PUT", "/api/v1/drafts/d1", {"step": 1, "content": {}}, id="save-draft"),
    pytest.param("GET", "/api/v1/drafts", None, id="list-drafts"),
    pytest.param("DELETE", "/api/v1/drafts/d1", None, id="delete-draft"),
]


SET_UP_OR_RUN_WORDS = (
    "Only an Operator can set up workflows or start runs. Ask an Operator on the team."
)
SET_UP_OR_RUN = [
    pytest.param("POST", "/api/v1/use-cases/uc_x/runs", KEY, None, id="start-run"),
    pytest.param("POST", "/api/v1/use-cases", {}, USE_CASE, id="create"),
    pytest.param("PUT", "/api/v1/watchlist/schedule", {}, SCHEDULE, id="schedule"),
]


@pytest.mark.parametrize(("method", "path", "headers", "body"), SET_UP_OR_RUN)
def test_an_approver_is_told_in_the_app_words_that_only_an_operator_sets_up_or_runs_workflows(
    method: str, path: str, headers: dict[str, str], body: object
):
    response = TestClient(app_with()).request(method, path, headers={**BOB, **headers}, json=body)
    assert (response.status_code, response.json()) == (403, {"detail": SET_UP_OR_RUN_WORDS})


NOT_THERE = [
    pytest.param("GET", "/api/v1/use-cases/uc_gone", {}, id="read"),
    pytest.param("POST", "/api/v1/use-cases/uc_gone/runs", KEY, id="start-run"),
    pytest.param("POST", "/api/v1/use-cases/uc_gone/pause", {}, id="pause"),
    pytest.param("POST", "/api/v1/use-cases/uc_gone/resume", {}, id="resume"),
    pytest.param("DELETE", "/api/v1/use-cases/uc_gone", {}, id="delete"),
    pytest.param("POST", "/api/v1/use-cases/uc_gone/restore", {}, id="restore"),
]


@pytest.mark.parametrize(("method", "path", "headers"), NOT_THERE)
def test_a_workflow_that_is_not_there_is_named_in_the_app_words(
    method: str, path: str, headers: dict[str, str]
):
    response = TestClient(app_with()).request(method, path, headers={**ALICE, **headers})
    assert (response.status_code, response.json()) == (404, {"detail": "No such workflow"})


@pytest.mark.parametrize(("method", "path", "body"), CHANGES)
def test_an_approver_is_told_only_an_operator_can_change_workflows(
    method: str, path: str, body: object
):
    response = TestClient(app_with()).request(method, path, headers=BOB, json=body)
    assert (response.status_code, response.json()) == (
        403,
        {"detail": "Only an Operator can change workflows."},
    )


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


def test_a_full_watchlist_is_a_422_of_its_own_type():
    response = TestClient(app_with()).post(RESTORE.format("sw_full"), headers=ALICE)
    assert response.json() == {
        "detail": [
            {
                "type": "watchlist_full",
                "loc": ["body"],
                "msg": "The watchlist holds 100 software at most",
            }
        ]
    }


def test_understand_refuses_a_nul_byte_with_a_422_naming_the_field():
    response = TestClient(app_with()).post(
        "/api/v1/builder/understand", headers=ALICE, json={"text": "close\u0000 every ticket"}
    )
    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [["body", "text"]]
    assert "NUL" in response.json()["detail"][0]["msg"]
