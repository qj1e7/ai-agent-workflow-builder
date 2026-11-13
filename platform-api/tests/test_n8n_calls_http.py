from typing import Any

import pytest
from fastapi.testclient import TestClient

from platform_api.orchestration.n8n_calls import (
    ANOTHER_EXECUTION,
    BUSY,
    START_USED,
    TEST_RUN_STOPS,
    AgentCall,
    Answer,
    AskCall,
    CallResult,
    NodeCall,
    NothingToChange,
    ProposeCall,
    ReadCall,
    Waiting,
    unknown,
)
from platform_api.shared import ApprovalId, N8nExecutionId
from tests.declared import NODE_KEY, NODE_KEY_ENV, FakeNodeCalls, app_with, declared_status

FROM = {
    "execution_id": "101",
    "workflow_id": "wf_7",
    "node_name": "Read release",
    "mode": "trigger",
}
READ = {**FROM, "source": "github_releases", "place": "langchain-ai/langgraph", "query": None}
AGENT = {**FROM, "node_name": "Compare", "agent": "crd_compare", "inputs": {"Project": "MOCK"}}
PROPOSE = {
    **FROM,
    "node_name": "Propose a change",
    "action": "jira.create_ticket",
    "place": "MOCK",
    "title": "Upgrade LangGraph",
    "body": "1.2.16 is out.",
    "subject": "",
}

ASK = {
    **FROM,
    "node_name": "Ask for a yes",
    "resume_url": "http://n8n:5678/webhook-waiting/101?signature=abc",
}
WAITING = Waiting(ApprovalId("apr_01"))

CASES = [
    pytest.param("/calls/read", READ, {}, None, 401, id="no-key"),
    pytest.param("/calls/read", READ, {"X-Wab-Node-Key": "wrong"}, None, 401, id="wrong-key"),
    pytest.param(
        "/calls/read", {"source": 1}, {"X-Wab-Node-Key": "wrong"}, None, 401, id="key-first"
    ),
    pytest.param("/calls/read", READ, NODE_KEY, None, 200, id="read"),
    pytest.param("/calls/read", {**READ, "extra": 1}, NODE_KEY, None, 422, id="read-extra-field"),
    pytest.param("/calls/read", READ, NODE_KEY, START_USED, 403, id="read-start-used"),
    pytest.param("/calls/read", READ, NODE_KEY, ANOTHER_EXECUTION, 409, id="read-another"),
    pytest.param("/calls/read", READ, NODE_KEY, unknown("place", "x"), 422, id="read-unknown"),
    pytest.param("/calls/read", READ, NODE_KEY, BUSY, 503, id="read-busy"),
    pytest.param("/calls/agent", AGENT, NODE_KEY, None, 200, id="agent"),
    pytest.param(
        "/calls/agent",
        {**AGENT, "inputs": {"Notes": "x" * (8 * 1024 + 1)}},
        NODE_KEY,
        None,
        422,
        id="agent-input-over-8-kb",
    ),
    pytest.param(
        "/calls/agent",
        {**AGENT, "inputs": {f"In {n}": "x" * 8000 for n in range(9)}},
        NODE_KEY,
        None,
        422,
        id="agent-inputs-over-64-kb",
    ),
    pytest.param("/calls/propose", PROPOSE, NODE_KEY, None, 200, id="propose"),
    pytest.param("/calls/propose", {**PROPOSE, "title": ""}, NODE_KEY, None, 422, id="no-title"),
    pytest.param("/calls/ask", ASK, NODE_KEY, WAITING, 200, id="ask-waiting"),
    pytest.param("/calls/ask", ASK, NODE_KEY, NothingToChange(), 200, id="ask-nothing"),
    pytest.param("/calls/ask", ASK, NODE_KEY, TEST_RUN_STOPS, 409, id="ask-test-run"),
    pytest.param(
        "/calls/ask",
        {**ASK, "resume_url": "http://n8n:5678/webhook-waiting/102?signature=abc"},
        NODE_KEY,
        None,
        422,
        id="ask-another-execution",
    ),
]


@pytest.mark.parametrize(("path", "body", "headers", "result", "status"), CASES)
def test_the_node_call_routes_answer_the_status_and_declare_it(
    path: str, body: dict[str, Any], headers: dict[str, str], result: CallResult | None, status: int
):
    app = app_with(env=NODE_KEY_ENV, node_calls=FakeNodeCalls(result))
    response = TestClient(app).post(f"/internal/v1/n8n{path}", headers=headers, json=body)
    assert response.status_code == status
    declared_status(app, "POST", f"/internal/v1/n8n{path}", response)
    if 400 <= status < 500 and result is not None:
        assert response.json() == {"detail": result.detail}  # type: ignore[union-attr]


def test_without_a_node_key_set_the_platform_takes_no_node_call():
    calls = FakeNodeCalls()
    app = app_with(node_calls=calls)
    response = TestClient(app).post("/internal/v1/n8n/calls/read", headers=NODE_KEY, json=READ)
    assert response.status_code == 401
    assert calls.calls == []


def test_each_route_hands_the_block_its_call():
    calls = FakeNodeCalls()
    client = TestClient(app_with(env=NODE_KEY_ENV, node_calls=calls))
    for path, body in (("read", READ), ("agent", AGENT), ("propose", PROPOSE)):
        assert client.post(
            f"/internal/v1/n8n/calls/{path}", headers=NODE_KEY, json=body
        ).json() == {
            "items": [{"id": "1.2.16"}],
            "replayed": False,
            "cut_off": False,
        }
    run = N8nExecutionId("101")
    assert calls.calls == [
        NodeCall(run, "Read release", ReadCall("github_releases", "langchain-ai/langgraph", None)),
        NodeCall(run, "Compare", AgentCall("crd_compare", {"Project": "MOCK"})),
        NodeCall(
            run,
            "Propose a change",
            ProposeCall("jira.create_ticket", "MOCK", "Upgrade LangGraph", "1.2.16 is out.", None),
        ),
    ]


def test_the_options_answer_the_editors_lists_only_with_the_key():
    client = TestClient(app_with(env=NODE_KEY_ENV))
    path = "/internal/v1/n8n/options?kind=places&action=jira.create_ticket"
    assert client.get(path).status_code == 401
    answered = client.get(path, headers=NODE_KEY)
    assert answered.json() == {"options": [{"id": "MOCK", "name": "MOCK"}]}
    assert client.get("/internal/v1/n8n/options?kind=secrets", headers=NODE_KEY).status_code == 422


def test_a_replayed_answer_says_so():
    calls = FakeNodeCalls(Answer((), replayed=True))
    client = TestClient(app_with(env=NODE_KEY_ENV, node_calls=calls))
    answer = client.post("/internal/v1/n8n/calls/read", headers=NODE_KEY, json=READ).json()
    assert answer == {"items": [], "replayed": True, "cut_off": False}


def test_an_ask_answers_the_request_the_execution_waits_for():
    calls = FakeNodeCalls(WAITING)
    response = TestClient(app_with(env=NODE_KEY_ENV, node_calls=calls)).post(
        "/internal/v1/n8n/calls/ask", headers=NODE_KEY, json=ASK
    )
    assert response.json() == {"status": "waiting", "request_id": "apr_01"}
    [call] = calls.calls
    assert call.work == AskCall(ASK["resume_url"])
