"""The Confluence page an agent reads while a card run works: one run, one task, and only a page
on the allowed list."""

from collections.abc import AsyncIterator

import httpx
import pytest

from platform_api.app import create_app
from platform_api.db import Database
from platform_api.orchestration.confluence_reads_http import NOT_CONNECTED
from platform_api.orchestration.confluence_rest import ConfluencePages
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.shared import RunId
from tests.support import ALICE, LOCAL_ENV, NOW, SPEC
from tests.test_confluence import CERT_LIST, TABLE, FakeWiki
from tests.test_jira_reads_http import CARD_RUN, OTHER_RUN, TASK, card_spec, header, token_for

pytestmark = pytest.mark.anyio


@pytest.fixture
def wiki() -> FakeWiki:
    return FakeWiki()


@pytest.fixture
async def app_and_client(
    db: Database, wiki: FakeWiki
) -> AsyncIterator[tuple[object, httpx.AsyncClient]]:
    async with db.transaction("orchestration") as uow:
        for run_id, spec, key in ((CARD_RUN, card_spec(), "a"), (OTHER_RUN, SPEC, "b")):
            record = RunRecord(
                run_id, spec, ALICE.user_id, NOW, NOW, 1, Pending(run_id, 1, None, NOW), (), None
            )
            await Store().insert_run(uow, record, key)
    app = create_app(LOCAL_ENV)
    app.state.db = db
    app.state.confluence = wiki.pages_allowed()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield app, client


@pytest.fixture
def client(app_and_client: tuple[object, httpx.AsyncClient]) -> httpx.AsyncClient:
    return app_and_client[1]


def read(client: httpx.AsyncClient, page: str, run: RunId = CARD_RUN, token: str | None = None):
    return client.get(
        f"/internal/v1/runs/{run}/confluence/pages/{page}",
        params={"task": TASK},
        headers=header(token),
    )


async def test_a_page_is_read_by_its_id_with_its_body_and_its_text(client: httpx.AsyncClient):
    r = await read(client, "123456")
    assert r.status_code == 200
    page = r.json()
    assert (page["id"], page["title"], page["version"], page["storage"]) == (
        "123456",
        "Cert List",
        4,
        TABLE,
    )
    assert page["text"].splitlines()[1] == "PRD | a.example | 2026-12-04"


async def test_a_page_is_read_by_its_title(client: httpx.AsyncClient):
    r = await read(client, "cert%20list")
    assert (r.status_code, r.json()["id"]) == (200, CERT_LIST.id)


@pytest.mark.parametrize("page", ["999", "Board salaries", "..%2F..%2Fuser%2Fcurrent"])
async def test_a_page_outside_the_allowed_list_is_refused_before_confluence_is_asked(
    client: httpx.AsyncClient, wiki: FakeWiki, page: str
):
    r = await read(client, page)
    assert (r.status_code, r.json()["detail"]) == (
        403,
        "This run may not read that Confluence page",
    )
    assert wiki.seen == []


async def test_only_a_card_run_with_its_own_token_reads(client: httpx.AsyncClient, wiki: FakeWiki):
    assert (await read(client, "123456", token="bad")).status_code == 401
    other = await read(client, "123456", token=token_for(OTHER_RUN))
    assert other.status_code == 401
    release = await read(client, "123456", run=OTHER_RUN, token=token_for(OTHER_RUN))
    assert (release.status_code, release.json()["detail"]) == (
        403,
        "This run does not read Confluence",
    )
    assert wiki.seen == []


async def test_not_connected_every_page_is_refused_in_plain_words(
    app_and_client: tuple[object, httpx.AsyncClient],
):
    app, client = app_and_client
    app.state.confluence = ConfluencePages((CERT_LIST,), None)  # type: ignore[attr-defined]
    r = await read(client, "123456")
    assert (r.status_code, r.json()["detail"]) == (424, NOT_CONNECTED)


async def test_a_refusal_is_424_with_its_words_and_an_outage_is_503(
    client: httpx.AsyncClient, wiki: FakeWiki
):
    wiki.mode = "refusing"
    refused = await read(client, "123456")
    assert refused.status_code == 424
    assert "CONFLUENCE_API_TOKEN" in refused.json()["detail"]
    wiki.mode = "down"
    down = await read(client, "123456")
    assert (down.status_code, down.json()["detail"]) == (503, "Confluence could not answer")


async def test_a_page_confluence_no_longer_has_is_404(client: httpx.AsyncClient, wiki: FakeWiki):
    del wiki.pages["123456"]
    r = await read(client, "123456")
    assert (r.status_code, r.json()["detail"]) == (404, "Confluence has no such page")
