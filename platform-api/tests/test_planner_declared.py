import pytest
from fastapi.testclient import TestClient

from platform_api.builder.planner import (
    AbilitiesReply,
    CapabilitiesView,
    NoSuchWorkflow,
    PartCheckFits,
    RegistryUnavailable,
)
from tests.declared import ALICE, BOB, FakePlannerFront, app_with, declared_status

TEXT = {"text": "Every Friday, sum up the tickets we closed this week"}
PART = {"kind": "do", "text": "Email the list"}
ANSWERED = FakePlannerFront(answer=AbilitiesReply())
CHECKED = FakePlannerFront(checked=PartCheckFits())
LISTED = FakePlannerFront(view=CapabilitiesView(capabilities=[], examples=[]))
NO_WORKFLOW = FakePlannerFront(answer=NoSuchWorkflow())
NOT_ANSWERING = FakePlannerFront(checked=RegistryUnavailable(), view=RegistryUnavailable())

CASES = [
    pytest.param("POST", "/api/v1/planner/answer", {}, TEXT, ANSWERED, 401, id="answer-401"),
    pytest.param("POST", "/api/v1/planner/answer", BOB, TEXT, ANSWERED, 403, id="answer-403"),
    pytest.param("POST", "/api/v1/planner/answer", ALICE, TEXT, ANSWERED, 200, id="answer-200"),
    pytest.param(
        "POST", "/api/v1/planner/answer", ALICE, {"intent": "abilities"}, ANSWERED, 200, id="chip"
    ),
    pytest.param(
        "POST",
        "/api/v1/planner/answer",
        ALICE,
        {"intent": "why_stopped", "use_case_id": "uc_gone"},
        NO_WORKFLOW,
        404,
        id="answer-404",
    ),
    pytest.param("POST", "/api/v1/planner/answer", ALICE, {"text": " "}, ANSWERED, 422, id="blank"),
    pytest.param(
        "POST", "/api/v1/planner/answer", ALICE, {"intent": "weather"}, ANSWERED, 422, id="intent"
    ),
    pytest.param(
        "POST",
        "/api/v1/planner/answer",
        ALICE,
        {"text": "x", "intent": "abilities"},
        ANSWERED,
        422,
        id="both",
    ),
    pytest.param("POST", "/api/v1/planner/check-part", {}, PART, CHECKED, 401, id="check-401"),
    pytest.param("POST", "/api/v1/planner/check-part", BOB, PART, CHECKED, 403, id="check-403"),
    pytest.param("POST", "/api/v1/planner/check-part", ALICE, PART, CHECKED, 200, id="check-200"),
    pytest.param(
        "POST", "/api/v1/planner/check-part", ALICE, PART, NOT_ANSWERING, 503, id="check-503"
    ),
    pytest.param(
        "POST",
        "/api/v1/planner/check-part",
        ALICE,
        {"kind": "when", "text": "x"},
        CHECKED,
        422,
        id="check-422",
    ),
    pytest.param("GET", "/api/v1/capabilities", {}, None, LISTED, 401, id="capabilities-401"),
    pytest.param("GET", "/api/v1/capabilities", BOB, None, LISTED, 200, id="capabilities-200"),
    pytest.param(
        "GET", "/api/v1/capabilities", ALICE, None, NOT_ANSWERING, 503, id="capabilities-503"
    ),
]


@pytest.mark.parametrize(("method", "path", "headers", "body", "front", "status"), CASES)
def test_the_route_answers_the_status_and_declares_it(
    method: str, path: str, headers: dict[str, str], body: object, front: object, status: int
):
    app = app_with(planner_front=front)
    response = TestClient(app).request(method, path, headers=headers, json=body)
    assert response.status_code == status
    declared_status(app, method, path, response)


def test_a_nul_byte_in_a_request_is_a_422_naming_the_field():
    response = TestClient(app_with()).post(
        "/api/v1/planner/answer", headers=ALICE, json={"text": "close\u0000 every ticket"}
    )
    assert response.status_code == 422
    assert "NUL" in response.text
