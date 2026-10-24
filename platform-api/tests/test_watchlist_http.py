from collections.abc import AsyncIterator, Mapping

import httpx
import pytest

from platform_api.app import create_app
from platform_api.builder import Watchlist
from platform_api.db import Database
from platform_api.orchestration import Given, SoftwareFacts, Standing, WatchlistStanding
from platform_api.shared import SoftwareId, UseCaseId
from tests.support import LOCAL_ENV

pytestmark = pytest.mark.anyio

ALICE = {"X-Dev-User": "alice"}
BOB = {"X-Dev-User": "bob"}
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
REDIS = {"name": "Redis", "repo": "redis/redis"}


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
    app.state.watchlist = Watchlist(db, NothingLearned())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_the_watchlist_is_null_until_software_is_added_then_lists_it(
    client: httpx.AsyncClient,
):
    empty = await client.get("/api/v1/watchlist", headers=BOB)
    assert (empty.status_code, empty.json()) == (200, {"watchlist": None})

    added = await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    assert added.status_code == 201
    view = added.json()
    assert view["version"] == 1 and view["ticket_project"] == "MOCK"
    [row] = view["software"]
    assert (row["name"], row["our_version"], row["status"], row["added_by"]) == (
        "LangGraph",
        "1.2.14",
        "not_checked",
        "alice",
    )
    assert row["our_version_source"]["kind"] == "given"
    assert (view["last_check"], view["schedule"]) == (None, None)

    again = await client.get("/api/v1/watchlist", headers=BOB)
    assert again.json() == {"watchlist": view}


async def test_a_repository_watched_twice_is_a_409(client: httpx.AsyncClient):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    r = await client.post(
        "/api/v1/watchlist/software", json={**LANGGRAPH, "name": "Again"}, headers=ALICE
    )
    assert r.status_code == 409
    assert r.json() == {"detail": "langchain-ai/langgraph is already watched"}


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({**LANGGRAPH, "name": "  "}, "name"),
        ({**LANGGRAPH, "name": "x" * 81}, "name"),
        ({**LANGGRAPH, "repo": "langgraph"}, "repo"),
        ({**LANGGRAPH, "repo": "owner/.."}, "repo"),
        ({**LANGGRAPH, "our_version": "v1.2.14"}, "our_version"),
        ({**LANGGRAPH, "our_version": "1.2"}, "our_version"),
        ({**LANGGRAPH, "colour": "red"}, "colour"),
        ({"repo": "redis/redis"}, "name"),
    ],
)
async def test_a_field_problem_is_a_422_naming_the_field(
    client: httpx.AsyncClient, body: dict[str, str], field: str
):
    r = await client.post("/api/v1/watchlist/software", json=body, headers=ALICE)
    assert r.status_code == 422
    assert [problem["loc"][-1] for problem in r.json()["detail"]] == [field]
    assert (await client.get("/api/v1/watchlist", headers=ALICE)).json() == {"watchlist": None}


async def test_removing_software_answers_the_list_that_is_left(client: httpx.AsyncClient):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    both = (await client.post("/api/v1/watchlist/software", json=REDIS, headers=ALICE)).json()
    langgraph = next(row["id"] for row in both["software"] if row["name"] == "LangGraph")
    left = await client.delete(f"/api/v1/watchlist/software/{langgraph}", headers=ALICE)
    assert left.status_code == 200
    assert left.json()["version"] == 3
    assert [row["name"] for row in left.json()["software"]] == ["Redis"]
    gone = await client.delete(f"/api/v1/watchlist/software/{langgraph}", headers=ALICE)
    assert (gone.status_code, gone.json()) == (404, {"detail": "No such watched software"})


async def test_only_an_operator_changes_the_list_and_anyone_signed_in_reads_it(
    client: httpx.AsyncClient,
):
    assert (await client.get("/api/v1/watchlist")).status_code == 401
    refused = await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=BOB)
    assert refused.status_code == 403
    assert (await client.delete("/api/v1/watchlist/software/sw_x", headers=BOB)).status_code == 403
    assert (await client.get("/api/v1/watchlist", headers=BOB)).json() == {"watchlist": None}
