"""PostgreSQL text cannot hold a NUL byte. The API refuses one before it reaches a store (#49)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from platform_api.app import create_app
from platform_api.builder import Builder, Watchlist
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.db import Database
from platform_api.orchestration import ScheduleBook
from platform_api.wire import NUL_MESSAGE, WireIn
from tests.declared import STEP_KEY, app_with
from tests.support import LOCAL_ENV, fixture
from tests.test_builder_http import NothingLearned, SecondCallRepeats

pytestmark = pytest.mark.anyio

NUL = "\u0000"
ALICE = {"X-Dev-User": "alice"}
USE_CASE = {
    "name": "Watch LangGraph",
    "instruction": "Check LangGraph for new releases.",
    "agents": [
        {
            "card_id": VERSION_CHECKER_ID,
            "values": {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"},
        }
    ],
}
CARD = {
    "name": "Ticket raiser",
    "purpose": "Raises a ticket.",
    "inputs": [{"name": "Where", "kind": "jira_project"}],
    "blocks": [{"say": "Raise one.", "tool": "jira.create_ticket"}],
}


@pytest.fixture
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db))
    app = app_with(builder=Builder(db, SecondCallRepeats(), watchlist, "http://localhost:8000"))
    app.state.watchlist = watchlist
    app.state.model_settings = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def refused(response: httpx.Response) -> list[Any]:
    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert (problem["type"], problem["msg"]) == ("nul_character", NUL_MESSAGE)
    return problem["loc"]


def agent(**changes: Any) -> dict[str, Any]:
    return {**USE_CASE, "agents": [{**USE_CASE["agents"][0], **changes}]}


@pytest.mark.parametrize(
    ("body", "where"),
    [
        ({**USE_CASE, "name": f"Watch{NUL}"}, ["body", "name"]),
        ({**USE_CASE, "instruction": f"Check{NUL}"}, ["body", "instruction"]),
        (agent(card_id=f"crd{NUL}"), ["body", "agents", 0, "card_id"]),
        (agent(values={"Jira project": f"MO{NUL}CK"}), ["body", "agents", 0, "values"]),
        (agent(values={f"Jira project{NUL}": "MOCK"}), ["body", "agents", 0, "values"]),
    ],
)
async def test_a_nul_byte_in_a_new_agent_use_case_is_a_422_naming_the_field(
    client: httpx.AsyncClient, body: dict[str, Any], where: list[Any]
):
    response = await client.post("/api/v1/agent-use-cases", json=body, headers=ALICE)
    assert refused(response) == where
    assert (await client.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"] == []


@pytest.mark.parametrize(
    ("method", "path", "body", "where"),
    [
        ("POST", "/api/v1/agent-cards", {**CARD, "purpose": NUL}, ["body", "purpose"]),
        ("POST", "/api/v1/agent-cards", {**CARD, "good_for": ["a", NUL]}, ["body", "good_for"]),
        (
            "PUT",
            "/api/v1/agent-cards/crd_x",
            {**CARD, "blocks": [{"say": f"Raise{NUL}"}]},
            ["body", "blocks", 0, "say"],
        ),
        ("POST", "/api/v1/agent-cards/check", {**CARD, "name": NUL}, ["body", "name"]),
        ("POST", "/api/v1/builder/plan", {"task": f"Check{NUL}"}, ["body", "task"]),
        ("POST", "/api/v1/use-cases/suggest", {"text": NUL}, ["body", "text"]),
        (
            "POST",
            "/api/v1/watchlist/software",
            {"name": f"Lang{NUL}Graph", "repo": "langchain-ai/langgraph"},
            ["body", "name"],
        ),
        (
            "PUT",
            "/api/v1/drafts/d1",
            {"step": 1, "content": {"steps": [{"say": f"x{NUL}"}]}},
            ["body", "content"],
        ),
        ("PUT", "/api/v1/drafts/d1", {"step": 1, "content": {NUL: 1}}, ["body", "content"]),
        (
            "POST",
            "/api/v1/approvals/apr_x/decisions",
            {"step": 0, "verdict": "approve", "digest": f"sha256:{NUL}"},
            ["body", "digest"],
        ),
        (
            "PUT",
            "/api/v1/settings/model",
            {"style": "anthropic", "base_url": "https://x.test", "model": NUL, "api_key": "k"},
            ["body", "model"],
        ),
        (
            "POST",
            "/internal/v1/workflow-failures",
            {
                "execution_id": "41",
                "workflow": "run",
                "last_node": "Run agents",
                "message": f"Refused{NUL}",
                "execution_url": "http://n8n:5678/execution/41",
            },
            ["body", "message"],
        ),
    ],
)
async def test_every_route_that_takes_text_refuses_a_nul_byte_naming_the_field(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, Any], where: list[Any]
):
    response = await client.request(method, path, json=body, headers={**ALICE, **STEP_KEY})
    assert refused(response) == where


async def test_a_nul_byte_deep_in_an_agent_event_is_refused(client: httpx.AsyncClient):
    body = fixture("agent/callback-event.json")
    body["event"]["data"]["reason"] = f"Releases{NUL}"
    response = await client.post(
        f"/internal/v1/runs/run_01JB8/agent-events?task={body['task_id']}",
        json=body,
        headers={"X-Callback-Token": "t"},
    )
    assert refused(response) == ["body", "event"]


async def test_text_that_only_spells_out_a_nul_still_saves(client: httpx.AsyncClient):
    body = {**USE_CASE, "name": "Watch \\u0000 and \\x00"}
    response = await client.post("/api/v1/agent-use-cases", json=body, headers=ALICE)
    assert response.status_code == 201, response.text
    [saved] = (await client.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"]
    assert saved["name"] == "Watch \\u0000 and \\x00"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/use-cases/uc%00x"),
        ("POST", "/api/v1/use-cases/uc%00x/runs"),
        ("POST", "/api/v1/use-cases/uc%00x/pause"),
        ("DELETE", "/api/v1/use-cases/uc%00x"),
        ("GET", "/api/v1/agent-cards/crd%00x"),
        ("GET", "/api/v1/runs/run%00x"),
        ("DELETE", "/api/v1/drafts/d%00"),
    ],
)
async def test_a_path_with_a_nul_byte_names_nothing(
    client: httpx.AsyncClient, method: str, path: str
):
    response = await client.request(method, path, headers={**ALICE, "Idempotency-Key": "k"})
    assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_a_query_with_a_nul_byte_is_a_422_naming_the_parameter(client: httpx.AsyncClient):
    response = await client.get(
        "/internal/v1/runs/run_x/jira/tickets?project=MOCK&task=t%00",
        headers={"Authorization": "Bearer t"},
    )
    assert refused(response) == ["query", "task"]


def subclasses(cls: type) -> set[type]:
    found = set(cls.__subclasses__())
    return found.union(*(subclasses(c) for c in found))


def test_every_request_body_refuses_a_nul_byte():
    schema = create_app(LOCAL_ENV).openapi()
    bodies = {
        operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        .rsplit("/", 1)[1]
        .removesuffix("-Input")
        for item in schema["paths"].values()
        for operation in item.values()
        if "requestBody" in operation
    }
    assert bodies - {c.__name__ for c in subclasses(WireIn)} == set()
