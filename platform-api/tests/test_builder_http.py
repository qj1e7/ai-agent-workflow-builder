from collections.abc import AsyncIterator, Mapping

import httpx
import pytest

from platform_api.app import create_app
from platform_api.builder import Builder, Watchlist
from platform_api.db import Database
from platform_api.orchestration import (
    Given,
    RunSpec,
    RunStarted,
    ScheduleBook,
    SoftwareFacts,
    Standing,
    WatchlistStanding,
)
from platform_api.shared import Principal, RunId, SoftwareId, UseCaseId
from tests.support import LOCAL_ENV

pytestmark = pytest.mark.anyio

ALICE = {"X-Dev-User": "alice"}
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
GOOD = {
    "template": "software_watchlist",
    "name": "Software watchlist",
    "instruction": "Check the team's watched software for new releases.",
    "params": {"ticket_project": "MOCK"},
}


class SecondCallRepeats:
    def __init__(self) -> None:
        self.calls = 0

    async def start_run(self, spec: RunSpec, principal: Principal, idempotency_key: str):
        self.calls += 1
        return RunStarted(RunId("run_1"), created=self.calls == 1)


class NothingLearned:
    async def standings(
        self, use_case_id: UseCaseId, given: Mapping[SoftwareId, Given | None]
    ) -> WatchlistStanding:
        return WatchlistStanding(
            {
                software_id: Standing(SoftwareFacts(typed, None, None, None), "not_checked")
                for software_id, typed in given.items()
            },
            None,
        )


@pytest.fixture
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(LOCAL_ENV)
    watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db))
    app.state.builder = Builder(db, SecondCallRepeats(), watchlist, "http://localhost:8000")
    app.state.watchlist = watchlist
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def save(client: httpx.AsyncClient) -> str:
    """The watchlist is the one use case a person can still make: by adding software."""
    r = await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    assert r.status_code == 201
    return r.json()["use_case_id"]


async def test_the_two_templates_are_listed_and_neither_takes_a_repository(
    client: httpx.AsyncClient,
):
    r = await client.get("/api/v1/templates", headers=ALICE)
    watchlist, agents = r.json()["templates"]
    assert watchlist["key"] == "software_watchlist"
    assert [p["name"] for p in watchlist["params"]] == ["ticket_project"]
    assert (agents["key"], agents["blocks"], agents["params"]) == ("agent_cards", [], [])


async def test_the_watchlist_template_is_listed_but_not_built_by_hand(client: httpx.AsyncClient):
    r = await client.post("/api/v1/use-cases", json=GOOD, headers=ALICE)
    assert r.status_code == 422
    [problem] = r.json()["detail"]
    assert (problem["loc"], problem["msg"]) == (
        ["body", "template"],
        "Add software on the Software page",
    )
    assert (await client.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"] == []


async def test_a_saved_use_case_can_be_read_and_listed(client: httpx.AsyncClient):
    use_case_id = await save(client)
    got = await client.get(f"/api/v1/use-cases/{use_case_id}", headers=ALICE)
    assert got.status_code == 200
    assert got.json()["owner"] == "alice"
    listed = await client.get("/api/v1/use-cases", headers=ALICE)
    assert [u["use_case_id"] for u in listed.json()["use_cases"]] == [use_case_id]


async def test_an_unknown_template_gets_a_422_naming_the_template(client: httpx.AsyncClient):
    r = await client.post("/api/v1/use-cases", json={**GOOD, "template": "nope"}, headers=ALICE)
    assert r.status_code == 422
    [problem] = r.json()["detail"]
    assert (problem["loc"], problem["msg"]) == (["body", "template"], "Unknown template 'nope'")
    assert (await client.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"] == []


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


async def test_suggest_answers_no_template_now_that_none_is_offered(client: httpx.AsyncClient):
    text = "Check langchain-ai/langgraph for new releases and open a ticket for the team."
    r = await client.post("/api/v1/use-cases/suggest", json={"text": text}, headers=ALICE)
    assert r.status_code == 200
    assert r.json() == {"template": None, "matched_terms": []}


async def test_every_builder_route_needs_a_signed_in_user(client: httpx.AsyncClient):
    assert (await client.get("/api/v1/use-cases")).status_code == 401
    assert (await client.post("/api/v1/use-cases", json=GOOD)).status_code == 401
