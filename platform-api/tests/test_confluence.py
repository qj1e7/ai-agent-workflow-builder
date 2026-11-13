"""The Confluence connection: its settings, the one adapter, the pages it may read and its check."""

import base64
import json
from dataclasses import dataclass, field
from typing import Literal

import httpx
import pytest

from platform_api.auth import ConfigError
from platform_api.db import Database
from platform_api.orchestration.agents import GitHubWorking
from platform_api.orchestration.confluence_rest import (
    CONFLUENCE_PAGE,
    ConfluencePages,
    ConfluenceRefused,
    ConfluenceRest,
    ConfluenceUnavailable,
    auth_header,
    page_text,
)
from platform_api.orchestration.model_settings import SettingsState
from platform_api.orchestration.n8n_calls import (
    GITHUB_RELEASES,
    NodeCatalog,
    NodeOption,
    ReadCall,
    ReadFailed,
    ReadItems,
    ReadSources,
    Refused,
)
from platform_api.orchestration.teams import TeamsStub
from platform_api.settings import ConfluencePage, ConfluenceSettings, settings_from_env
from platform_api.wiring import approval_channel, connections_for
from tests.practice import no_wait
from tests.support import LOCAL_ENV
from tests.test_connections import FakeJira, FakeModels, FakeRuntime
from tests.test_settings_http import ACTIVE

pytestmark = pytest.mark.anyio

WIKI = "https://ncs-test.atlassian.net/wiki"
INVENTORY = ConfluencePage("123456", "Software inventory")
PATCHES = ConfluencePage("777", "Patch housekeeping")
TABLE = (
    "<table><tbody><tr><th>Software</th><th>Ours</th><th>Checked</th></tr>"
    '<tr><td>LangGraph</td><td>1.2.14</td><td><time datetime="2026-11-04" /></td></tr>'
    "<tr><td>Redis &amp; Sentinel</td><td><p>8.0.2</p></td><td>never</td></tr></tbody></table>"
)
CONFLUENCE_ENV = {
    "CONFLUENCE_BASE_URL": WIKI,
    "CONFLUENCE_EMAIL": "bot@example.com",
    "CONFLUENCE_API_TOKEN": "confluence-token-1234",
    "CONFLUENCE_PAGES": "123456=Software inventory; 777 = Patch housekeeping",
}

type Mode = Literal["ok", "refusing", "down", "anonymous"]


@dataclass
class FakeWiki:
    """Confluence's REST API as the adapter reads it, with the pages it holds."""

    pages: dict[str, tuple[str, int, str]] = field(
        default_factory=lambda: {
            "123456": ("Software inventory", 4, TABLE),
            "777": ("Patch housekeeping", 1, "<p>Nothing yet.</p>"),
            "999": ("Board salaries", 2, "<p>Private.</p>"),
        }
    )
    mode: Mode = "ok"
    seen: list[str] = field(default_factory=list[str])

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request.url.path)
        if self.mode == "down":
            return httpx.Response(503)
        if self.mode == "refusing":
            return httpx.Response(401, json={"message": "Unauthorized"})
        path = request.url.path.removeprefix("/wiki/rest/api")
        if path == "/user/current":
            kind = "anonymous" if self.mode == "anonymous" else "known"
            return httpx.Response(200, json={"type": kind, "accountId": "5b10"})
        page_id = path.removeprefix("/content/")
        if page_id not in self.pages:
            return httpx.Response(404, json={"message": "No content found"})
        title, version, body = self.pages[page_id]
        return httpx.Response(
            200,
            json={
                "id": page_id,
                "title": title,
                "version": {"number": version},
                "body": {"storage": {"value": body, "representation": "storage"}},
            },
        )

    def rest(self) -> ConfluenceRest:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.answer))
        return ConfluenceRest(WIKI, "Bearer t", client, sleep=no_wait)

    def pages_allowed(self, *allowed: ConfluencePage) -> ConfluencePages:
        return ConfluencePages(allowed or (INVENTORY, PATCHES), self.rest())


@pytest.fixture
def wiki() -> FakeWiki:
    return FakeWiki()


def test_without_an_address_confluence_is_not_connected():
    assert settings_from_env(LOCAL_ENV).confluence == ConfluenceSettings()


def test_the_settings_name_the_wiki_the_key_and_the_pages_it_may_read():
    confluence = settings_from_env({**LOCAL_ENV, **CONFLUENCE_ENV}).confluence
    assert confluence.base_url == WIKI
    assert (confluence.email, confluence.token) == ("bot@example.com", "confluence-token-1234")
    assert confluence.pages == (INVENTORY, PATCHES)


@pytest.mark.parametrize(
    ("changes", "said"),
    [
        ({"CONFLUENCE_PAGES": ""}, "CONFLUENCE_PAGES must list the pages"),
        ({"CONFLUENCE_PAGES": "Software inventory"}, "id=title"),
        ({"CONFLUENCE_PAGES": "12a=Software inventory"}, "id=title"),
        ({"CONFLUENCE_PAGES": "1=Software inventory;2=software  INVENTORY"}, "same title"),
        ({"CONFLUENCE_PAGES": "1=A;1=B"}, "same id"),
        ({"CONFLUENCE_API_TOKEN": ""}, "CONFLUENCE_API_TOKEN is not"),
        ({"CONFLUENCE_BASE_URL": "http://ncs-test.atlassian.net/wiki"}, "https address"),
        ({"CONFLUENCE_BASE_URL": f"{WIKI}?next=x"}, "no query"),
    ],
)
def test_settings_that_cannot_work_are_refused_at_start(changes: dict[str, str], said: str):
    with pytest.raises(ConfigError, match=said):
        settings_from_env({**LOCAL_ENV, **CONFLUENCE_ENV, **changes})


def test_plain_http_is_only_for_a_service_on_the_stacks_own_network():
    env = {**LOCAL_ENV, **CONFLUENCE_ENV, "CONFLUENCE_BASE_URL": "http://mock-confluence:8400/wiki"}
    assert settings_from_env(env).confluence.base_url == "http://mock-confluence:8400/wiki"


def test_on_the_same_site_as_jira_it_signs_in_with_jiras_key():
    env = {
        **LOCAL_ENV,
        **CONFLUENCE_ENV,
        "CONFLUENCE_EMAIL": "",
        "CONFLUENCE_API_TOKEN": "",
        "JIRA_BASE_URL": "https://ncs-test.atlassian.net",
        "JIRA_API_FLAVOR": "cloud",
        "JIRA_EMAIL": "jira-bot@example.com",
        "JIRA_API_TOKEN": "jira-token-5678",
    }
    confluence = settings_from_env(env).confluence
    assert (confluence.email, confluence.token) == ("jira-bot@example.com", "jira-token-5678")


def test_cloud_signs_in_with_the_email_and_data_center_with_the_token_alone():
    cloud = ConfluenceSettings(WIKI, "bot@example.com", "tok", (INVENTORY,))
    assert auth_header(cloud) == "Basic " + base64.b64encode(b"bot@example.com:tok").decode()
    assert auth_header(ConfluenceSettings(WIKI, None, "tok", (INVENTORY,))) == "Bearer tok"


@pytest.mark.parametrize(
    ("mode", "found"),
    [
        ("ok", "working"),
        ("refusing", "token_refused"),
        ("anonymous", "token_refused"),
        ("down", "not_answering"),
    ],
)
async def test_the_check_asks_confluence_who_the_key_is_and_reads_no_page(
    wiki: FakeWiki, mode: Mode, found: str
):
    wiki.mode = mode
    assert await wiki.pages_allowed().check() == found
    assert wiki.seen == ["/wiki/rest/api/user/current"]


async def test_a_page_is_read_with_its_body_version_and_link(wiki: FakeWiki):
    read = await wiki.pages_allowed().read_page(INVENTORY)
    assert read is not None
    assert (read.id, read.title, read.version, read.storage) == (
        "123456",
        "Software inventory",
        4,
        TABLE,
    )
    assert read.url == f"{WIKI}/pages/viewpage.action?pageId=123456"


async def test_a_page_is_found_by_its_id_or_by_its_title_in_any_case_and_spacing(wiki: FakeWiki):
    pages = wiki.pages_allowed()
    assert pages.find("123456") == INVENTORY
    assert pages.find("  software   INVENTORY ") == INVENTORY
    assert pages.find("999") is None
    assert pages.find("Board salaries") is None


async def test_a_page_outside_the_list_is_refused_and_confluence_is_never_asked(wiki: FakeWiki):
    pages = wiki.pages_allowed()
    with pytest.raises(ConfluenceRefused, match="not one the platform may read"):
        await pages.read_page(ConfluencePage("999", "Board salaries"))
    assert wiki.seen == []


async def test_a_page_confluence_no_longer_has_reads_as_none(wiki: FakeWiki):
    del wiki.pages["777"]
    assert await wiki.pages_allowed().read_page(PATCHES) is None


async def test_a_refused_key_is_not_an_outage_and_says_which_key_to_replace(wiki: FakeWiki):
    wiki.mode = "refusing"
    with pytest.raises(ConfluenceRefused, match="CONFLUENCE_API_TOKEN") as refused:
        await wiki.pages_allowed().read_page(INVENTORY)
    assert refused.value.status == 401
    assert len(wiki.seen) == 1


async def test_a_confluence_that_is_down_is_tried_three_times(wiki: FakeWiki):
    wiki.mode = "down"
    with pytest.raises(ConfluenceUnavailable):
        await wiki.pages_allowed().read_page(INVENTORY)
    assert len(wiki.seen) == 3


async def test_not_connected_it_lists_no_page_and_reads_none():
    pages = ConfluencePages((INVENTORY,), None)
    assert (pages.connected, pages.allowed, pages.find("Software inventory")) == (False, (), None)
    assert await pages.places(CONFLUENCE_PAGE) == []


def test_a_page_reads_as_plain_lines_with_a_table_row_on_each():
    assert page_text(TABLE).splitlines() == [
        "Software | Ours | Checked",
        "LangGraph | 1.2.14 | 2026-11-04",
        "Redis & Sentinel | 8.0.2 | never",
    ]


class NoFacts:
    async def agents(self) -> list[NodeOption]:
        return []


async def test_a_read_block_is_offered_and_may_name_only_the_allowed_pages(wiki: FakeWiki):
    pages = wiki.pages_allowed()
    catalog = NodeCatalog(NoFacts(), pages, [])  # type: ignore[arg-type]
    offered = await catalog.options("places", {"source": CONFLUENCE_PAGE})
    assert offered == [
        NodeOption("123456", "Software inventory"),
        NodeOption("777", "Patch housekeeping"),
    ]
    assert await catalog.options("places", {"source": "github_releases"}) == []
    assert await catalog.unknown_in(ReadCall(CONFLUENCE_PAGE, "123456", None)) is None
    refused = await catalog.unknown_in(ReadCall(CONFLUENCE_PAGE, "999", None))
    assert refused == Refused(422, 'Our platform does not know the place "999".')
    assert wiki.seen == []


class GitHubPlaces:
    async def places(self, source: str) -> list[NodeOption]:
        return (
            [NodeOption("langchain-ai/langgraph", "LangGraph")] if source == GITHUB_RELEASES else []
        )

    async def read(self, source: str, place: str, query: str | None) -> ReadItems | ReadFailed:
        return [{"kind": "release", "id": "1.2.16"}]


async def test_a_read_block_reads_confluence_from_its_pages_and_github_as_before(wiki: FakeWiki):
    sources = ReadSources({CONFLUENCE_PAGE: wiki.pages_allowed()}, GitHubPlaces())
    catalog = NodeCatalog(NoFacts(), sources, [])  # type: ignore[arg-type]
    assert [o.id for o in await catalog.options("places", {"source": CONFLUENCE_PAGE})] == [
        "123456",
        "777",
    ]
    assert await catalog.options("places", {"source": GITHUB_RELEASES}) == [
        NodeOption("langchain-ai/langgraph", "LangGraph")
    ]
    assert (
        await catalog.unknown_in(ReadCall(GITHUB_RELEASES, "langchain-ai/langgraph", None)) is None
    )
    assert await catalog.unknown_in(ReadCall(CONFLUENCE_PAGE, "999", None)) is not None
    assert await sources.read(GITHUB_RELEASES, "langchain-ai/langgraph", None) == [
        {"kind": "release", "id": "1.2.16"}
    ]
    [page] = await sources.read(CONFLUENCE_PAGE, "123456", None)  # type: ignore[misc]
    assert page["title"] == "Software inventory"


async def test_a_read_block_gets_the_page_as_one_item_with_its_text(wiki: FakeWiki):
    [item] = await wiki.pages_allowed().read(CONFLUENCE_PAGE, "123456", None)  # type: ignore[misc]
    assert {k: item[k] for k in ("kind", "id", "title", "version")} == {
        "kind": "page",
        "id": "123456",
        "title": "Software inventory",
        "version": 4,
    }
    assert "LangGraph | 1.2.14 | 2026-11-04" in str(item["text"])
    json.dumps(item)


async def connections(db: Database, env: dict[str, str], confluence: ConfluencePages | None):
    settings = settings_from_env(env)
    channel, _ = approval_channel(settings, TeamsStub(db, "Ops"))
    made, _ = connections_for(
        settings,
        db,
        FakeJira("working"),
        channel,
        FakeRuntime(GitHubWorking(using_token=False)),
        FakeModels(SettingsState(True, ACTIVE, None, [])),
        confluence,
    )
    return made


async def test_not_set_up_it_says_so_tries_nothing_and_home_does_not_raise_it(db: Database):
    made = await connections(db, LOCAL_ENV, ConfluencePages((), None))
    (confluence,) = [c for c in await made.view() if c.id == "confluence"]
    assert (confluence.state, confluence.practice, confluence.checked_at) == (
        "not_set_up",
        False,
        None,
    )
    assert confluence.problem == "Confluence is not connected."
    assert confluence.fix == "Ask whoever set up the platform to connect Confluence."
    checked = await made.check_now("confluence")
    assert checked is not None and checked.state == "not_set_up"
    await made.check_due()
    assert "confluence" not in {c.id for c in await made.needing_attention()}


async def test_set_up_it_is_checked_and_kept_as_jira_is(db: Database, wiki: FakeWiki):
    made = await connections(db, {**LOCAL_ENV, **CONFLUENCE_ENV}, wiki.pages_allowed())
    (first,) = [c for c in await made.view() if c.id == "confluence"]
    assert (first.state, first.key_ends_in, first.practice) == ("working", "34", False)
    assert first.checked_at is not None
    wiki.mode = "refusing"
    refused = await made.check_now("confluence")
    assert refused is not None
    assert (refused.state, refused.problem) == (
        "needs_attention",
        "Confluence does not accept the key.",
    )
    assert refused.fix == "Ask whoever set up Confluence for a new key."
    assert [c.id for c in await made.needing_attention()] == ["confluence"]
