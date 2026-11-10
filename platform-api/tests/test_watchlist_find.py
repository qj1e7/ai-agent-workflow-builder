import re
from collections.abc import AsyncIterator

import httpx
import pytest

from platform_api.app import create_app
from platform_api.builder import TAG_PATTERN, Watchlist
from platform_api.db import Database
from platform_api.orchestration import (
    FindSoftwareResult,
    FoundSoftware,
    RuntimeDown,
    ScheduleBook,
    SoftwareNotChecked,
    SoftwareNotKnown,
)
from platform_api.orchestration.agents import SoftwareMatch
from platform_api.orchestration.watch import newer
from tests.support import LOCAL_ENV
from tests.test_watchlist_http import ALICE, BOB, LANGGRAPH, NothingLearned, people_in

pytestmark = pytest.mark.anyio


def match(repo: str, newest: str | None = "1.2.20") -> SoftwareMatch:
    return SoftwareMatch(
        repo=repo,
        what="A project",
        why="From our list of known projects.",
        releases="published" if newest else "none",
        newest=newest,
    )


class FakeFinder:
    def __init__(self, answer: FindSoftwareResult | RuntimeDown) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str]] = []

    async def find(self, name: str, tag_pattern: str) -> FindSoftwareResult | RuntimeDown:
        self.asked.append((name, tag_pattern))
        return self.answer


@pytest.fixture
def finder() -> FakeFinder:
    return FakeFinder(FoundSoftware(matches=[match("langchain-ai/langgraph")]))


@pytest.fixture
async def client(db: Database, finder: FakeFinder) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(LOCAL_ENV)
    app.state.people = await people_in(db)
    app.state.watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db), finder=finder)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def find(client: httpx.AsyncClient, name: str, who: dict[str, str] = ALICE):
    return await client.post("/api/v1/watchlist/find", json={"name": name}, headers=who)


async def test_a_name_gives_the_checked_projects_and_sends_the_watchlists_own_tag_rule(
    client: httpx.AsyncClient, finder: FakeFinder
):
    reply = await find(client, "LangGraph")
    assert reply.status_code == 200
    assert reply.json() == {
        "status": "found",
        "matches": [
            {
                "kind": "github",
                "repo": "langchain-ai/langgraph",
                "what": "A project",
                "why": "From our list of known projects.",
                "releases": "published",
                "newest": "1.2.20",
                "already_listed": None,
            }
        ],
    }
    assert finder.asked == [("LangGraph", TAG_PATTERN)]


async def test_the_name_is_trimmed_before_it_is_looked_up(
    client: httpx.AsyncClient, finder: FakeFinder
):
    await find(client, "  Kubernetes \n")
    assert [name for name, _ in finder.asked] == ["Kubernetes"]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
async def test_a_blank_name_is_refused_and_nothing_is_looked_up(
    client: httpx.AsyncClient, finder: FakeFinder, blank: str
):
    reply = await find(client, blank)
    assert reply.status_code == 422
    assert reply.json()["detail"][0]["loc"] == ["body", "name"]
    assert finder.asked == []


async def test_a_match_that_is_already_watched_says_under_which_name(client: httpx.AsyncClient):
    await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    reply = await find(client, "LangGraph")
    assert reply.json()["matches"][0]["already_listed"] == "LangGraph"


async def test_the_address_is_compared_without_regard_to_case(
    client: httpx.AsyncClient, finder: FakeFinder
):
    await client.post(
        "/api/v1/watchlist/software",
        json={"name": "Graph", "repo": "LangChain-AI/LangGraph"},
        headers=ALICE,
    )
    reply = await find(client, "LangGraph")
    assert reply.json()["matches"][0]["already_listed"] == "Graph"


async def test_finding_saves_nothing(client: httpx.AsyncClient):
    await find(client, "LangGraph")
    assert (await client.get("/api/v1/watchlist", headers=ALICE)).json() == {"watchlist": None}


async def test_only_an_operator_may_find(client: httpx.AsyncClient, finder: FakeFinder):
    assert (await find(client, "LangGraph", BOB)).status_code == 403
    assert finder.asked == []


async def test_a_name_the_list_lacks_is_said_plainly(client: httpx.AsyncClient, finder: FakeFinder):
    finder.answer = SoftwareNotKnown(message="I don't know a GitHub project called Zorblax.")
    assert (await find(client, "Zorblax")).json() == {
        "status": "not_known",
        "message": "I don't know a GitHub project called Zorblax.",
    }


async def test_when_github_cannot_say_no_project_is_offered(
    client: httpx.AsyncClient, finder: FakeFinder
):
    finder.answer = SoftwareNotChecked(message="I couldn't reach GitHub, so I can't check Redis.")
    body = (await find(client, "Redis")).json()
    assert body == {
        "status": "not_checked",
        "message": "I couldn't reach GitHub, so I can't check Redis.",
    }


async def test_when_the_runtime_does_not_answer_the_answer_is_not_checked(
    client: httpx.AsyncClient, finder: FakeFinder
):
    finder.answer = RuntimeDown("The agent runtime answered 503")
    body = (await find(client, "Redis")).json()
    assert body["status"] == "not_checked"
    assert body["message"].startswith("I couldn't ask the agent runtime just now")
    assert "503" not in body["message"]


@pytest.mark.parametrize(
    ("tag", "counts"),
    [
        ("1.2.14", True),
        ("v2.14.2", True),
        ("docker-v29.1.0", True),
        ("n8n@2.4.2", True),
        ("langchain==0.3.1", True),
        ("langchain-core==0.3.1", False),
        ("cli==0.4.37", False),
        ("n8n@2.4.2-beta.1", False),
    ],
)
def test_the_watchlists_tag_rule_counts_moby_n8n_and_langchain_tags(tag: str, counts: bool):
    assert (re.fullmatch(TAG_PATTERN, tag, re.ASCII) is not None) is counts


@pytest.mark.parametrize(
    ("candidate", "than", "is_newer"),
    [
        ("docker-v29.2.0", "docker-v29.1.0", True),
        ("docker-v29.1.0", "docker-v29.1.0", False),
        ("docker-v29.1.0", "docker-v29.2.0", False),
        ("docker-v29.2.0", "29.1.0", True),
        ("n8n@2.10.0", "n8n@2.9.0", True),
        ("n8n@2.9.0", "2.10.0", False),
        ("langchain==0.3.2", "langchain==0.3.1", True),
        ("langchain==0.3.1", "0.3.2", False),
    ],
)
def test_prefixed_tags_compare_by_number_not_by_difference(
    candidate: str, than: str, is_newer: bool
):
    assert newer(candidate, than) is is_newer


LOG4J = "org.apache.logging.log4j:log4j-core"


async def test_a_package_match_keeps_its_kind_and_is_found_listed_only_as_that_package(
    client: httpx.AsyncClient, finder: FakeFinder
):
    package = SoftwareMatch(
        kind="maven",
        repo=LOG4J,
        what="Log4j core",
        why="From our list of known packages. Your team installs it from Maven Central.",
        releases="published",
        newest="2.24.3",
    )
    finder.answer = FoundSoftware(matches=[package])
    reply = await find(client, "Log4j")
    assert reply.status_code == 200
    [guess] = reply.json()["matches"]
    assert (guess["kind"], guess["repo"], guess["already_listed"]) == ("maven", LOG4J, None)

    added = await client.post(
        "/api/v1/watchlist/software",
        json={"name": "Log4j", "package": {"kind": "maven", "ref": LOG4J}},
        headers=ALICE,
    )
    assert added.status_code == 201
    [guess] = (await find(client, "Log4j")).json()["matches"]
    assert guess["already_listed"] == "Log4j"


def test_a_match_must_be_a_name_its_source_could_hold():
    with pytest.raises(ValueError):
        SoftwareMatch(
            kind="maven", repo="owner/name", what="x", why="", releases="none", newest=None
        )
