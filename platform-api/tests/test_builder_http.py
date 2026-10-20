from collections.abc import AsyncIterator

import httpx
import pytest

from platform_api.app import create_app
from platform_api.builder import Builder
from platform_api.db import Database
from platform_api.orchestration import RunSpec, RunStarted
from platform_api.shared import Principal, RunId, UseCaseId

pytestmark = pytest.mark.anyio

ALICE = {"X-Dev-User": "alice"}
GOOD = {
    "template": "release_check",
    "name": "LangGraph releases",
    "instruction": "Check langchain-ai/langgraph for new releases and open a ticket for the team.",
    "params": {"repo": "langchain-ai/langgraph", "ticket_project": "MOCK"},
}


class SecondCallRepeats:
    def __init__(self) -> None:
        self.calls = 0

    async def start_run(self, spec: RunSpec, principal: Principal, idempotency_key: str):
        self.calls += 1
        return RunStarted(RunId("run_1"), created=self.calls == 1)

    async def latest_carry_forward(self, use_case_id: UseCaseId) -> str | None:
        return None


@pytest.fixture
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app({"AUTH_MODE": "dev", "PUBLIC_BASE_URL": "http://localhost:8000"})
    app.state.builder = Builder(db, SecondCallRepeats(), "http://localhost:8000")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def save(client: httpx.AsyncClient) -> str:
    r = await client.post("/api/v1/use-cases", json=GOOD, headers=ALICE)
    assert r.status_code == 201
    return r.json()["use_case_id"]


async def test_templates_are_listed_with_the_last_seen_tag_param(client: httpx.AsyncClient):
    r = await client.get("/api/v1/templates", headers=ALICE)
    [template] = r.json()["templates"]
    assert [p["name"] for p in template["params"]] == [
        "repo",
        "tag_pattern",
        "ticket_project",
        "last_seen_tag",
    ]


async def test_a_saved_use_case_can_be_read_and_listed(client: httpx.AsyncClient):
    use_case_id = await save(client)
    got = await client.get(f"/api/v1/use-cases/{use_case_id}", headers=ALICE)
    assert got.status_code == 200
    assert got.json()["owner"] == "alice"
    listed = await client.get("/api/v1/use-cases", headers=ALICE)
    assert [u["use_case_id"] for u in listed.json()["use_cases"]] == [use_case_id]


async def test_a_bad_repo_gets_a_422_naming_the_field(client: httpx.AsyncClient):
    bad = {**GOOD, "params": {**GOOD["params"], "repo": "owner/.."}}
    r = await client.post("/api/v1/use-cases", json=bad, headers=ALICE)
    assert r.status_code == 422
    [problem] = r.json()["detail"]
    assert problem["loc"] == ["body", "params", "repo"]
    assert isinstance(problem["msg"], str)


async def test_an_unknown_template_gets_a_422_naming_the_template(client: httpx.AsyncClient):
    r = await client.post("/api/v1/use-cases", json={**GOOD, "template": "nope"}, headers=ALICE)
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "template"]


async def test_an_unknown_use_case_is_a_404(client: httpx.AsyncClient):
    assert (await client.get("/api/v1/use-cases/uc_nope", headers=ALICE)).status_code == 404
    r = await client.post(
        "/api/v1/use-cases/uc_nope/runs", headers={**ALICE, "Idempotency-Key": "k"}
    )
    assert r.status_code == 404


async def test_a_repeated_idempotency_key_gets_200_with_the_same_body(client: httpx.AsyncClient):
    use_case_id = await save(client)
    headers = {**ALICE, "Idempotency-Key": "k"}
    first = await client.post(f"/api/v1/use-cases/{use_case_id}/runs", headers=headers)
    second = await client.post(f"/api/v1/use-cases/{use_case_id}/runs", headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert (
        first.json()
        == second.json()
        == {
            "run_id": "run_1",
            "state": "pending",
            "events_url": "/api/v1/runs/run_1/events",
        }
    )


async def test_suggest_matches_the_instruction(client: httpx.AsyncClient):
    r = await client.post(
        "/api/v1/use-cases/suggest", json={"text": GOOD["instruction"]}, headers=ALICE
    )
    assert r.json()["template"]["key"] == "release_check"
    assert r.json()["matched_terms"] == ["releases", "ticket"]


async def test_every_builder_route_needs_a_signed_in_user(client: httpx.AsyncClient):
    assert (await client.get("/api/v1/use-cases")).status_code == 401
    assert (await client.post("/api/v1/use-cases", json=GOOD)).status_code == 401
