from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest

from platform_api.app import create_app
from platform_api.db import Database
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.write_actions import (
    Proposal,
    WriteAction,
    WriteKey,
    digest,
)
from platform_api.shared import ProposalId, RunId
from tests.practice import BASE, PracticeKit
from tests.support import ALICE, LOCAL_ENV, NOW, SPEC

pytestmark = pytest.mark.anyio

RUN = RunId("run_1")
PRP = ProposalId("prp_1")
ACTION = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "Upgrade", "body": ""})
AS_ALICE = {"X-Dev-User": "alice"}
AS_BOB = {"X-Dev-User": "bob"}
AS_CAROL = {"X-Dev-User": "carol"}


@pytest.fixture
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with db.transaction("orchestration") as uow:
        await Store().insert_run(
            uow,
            RunRecord(RUN, SPEC, ALICE.user_id, NOW, NOW, 1, Pending(RUN, 1, None, NOW), (), None),
            "k",
        )
        await Store().insert_proposal(uow, Proposal(PRP, RUN, (ACTION,), digest((ACTION,))))
    jira = PracticeKit(db)
    assert await jira.execute(ACTION, WriteKey(RUN, PRP, 0)) == "MOCK-1"
    app = create_app(LOCAL_ENV)
    app.state.practice_jira = jira.store
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_an_operator_marks_a_ticket_done_once_however_often_they_press(
    client: httpx.AsyncClient,
):
    listed = await client.get("/api/v1/mock-jira/tickets", headers=AS_BOB)
    [ticket] = listed.json()["tickets"]
    assert (ticket["status"], ticket["done_at"]) == ("To Do", None)

    done = await client.post("/api/v1/mock-jira/tickets/MOCK-1/done", headers=AS_CAROL)
    assert done.status_code == 200
    assert done.json()["status"] == "Done" and done.json()["done_at"] is not None
    again = await client.post("/api/v1/mock-jira/tickets/MOCK-1/done", headers=AS_ALICE)
    assert (again.status_code, again.json()) == (200, done.json())
    listed = await client.get("/api/v1/mock-jira/tickets", headers=AS_BOB)
    assert listed.json()["tickets"][0]["done_at"] == done.json()["done_at"]


async def test_only_an_operator_can_mark_a_ticket_done(client: httpx.AsyncClient):
    refused = await client.post("/api/v1/mock-jira/tickets/MOCK-1/done", headers=AS_BOB)
    assert refused.status_code == 403
    assert "Operator" in refused.json()["detail"]
    assert (await client.post("/api/v1/mock-jira/tickets/MOCK-1/done")).status_code == 401
    listed = await client.get("/api/v1/mock-jira/tickets", headers=AS_BOB)
    assert listed.json()["tickets"][0]["status"] == "To Do"


async def test_an_unknown_ticket_is_a_404(client: httpx.AsyncClient):
    missing = await client.post("/api/v1/mock-jira/tickets/MOCK-404/done", headers=AS_ALICE)
    assert (missing.status_code, missing.json()) == (404, {"detail": "No such ticket"})


async def search_keys(kit: PracticeKit, jql: str) -> list[str]:
    response = await kit.client.get(
        f"{BASE}/rest/api/2/search",
        params={"jql": jql},
        headers={"Authorization": kit.jira.auth_header},
    )
    assert response.status_code == 200, response.text
    return [issue["key"] for issue in response.json()["issues"]]


async def test_the_practice_jira_answers_updated_issuetype_and_assignee_clauses(db: Database):
    kit = PracticeKit(db)
    old = db.clock() - timedelta(days=20)
    await kit.store.create("MOCK", "Old bug", "", [], "Bug", created_at=old, assignee="Dana Lim")
    await kit.store.create("MOCK", "New task", "", [], "Task")
    await kit.store.create("MOCK", "Old task", "", [], "Task", created_at=old)

    assert await search_keys(kit, 'project = "MOCK" AND issuetype in ("bug")') == ["MOCK-1"]
    assert await search_keys(kit, 'issuetype != "Bug" ORDER BY key ASC') == ["MOCK-2", "MOCK-3"]
    assert await search_keys(kit, 'assignee = "dana lim"') == ["MOCK-1"]
    week_ago = (db.clock() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    assert await search_keys(kit, f'updated <= "{week_ago}" ORDER BY key ASC') == [
        "MOCK-1",
        "MOCK-3",
    ]
    assert await search_keys(kit, f'created >= "{week_ago}"') == ["MOCK-2"]

    await kit.store.set_labels("MOCK-1", ["touched"])
    assert await search_keys(kit, f'updated <= "{week_ago}"') == ["MOCK-3"]


async def test_a_ticket_done_moves_its_last_update_and_a_second_press_does_not(db: Database):
    kit = PracticeKit(db)
    old = db.clock() - timedelta(days=3)
    await kit.store.create("MOCK", "Old", "", [], "Task", created_at=old)
    first = await kit.store.mark_done("MOCK-1")
    assert first is not None and first.updated_at > old
    again = await kit.store.mark_done("MOCK-1")
    assert again is not None and again.updated_at == first.updated_at


async def test_the_practice_jira_refuses_a_bad_date_in_updated_with_jiras_words(db: Database):
    kit = PracticeKit(db)
    response = await kit.client.get(
        f"{BASE}/rest/api/2/search",
        params={"jql": 'updated <= "yesterday"'},
        headers={"Authorization": kit.jira.auth_header},
    )
    assert response.status_code == 400
    assert "field 'updated'" in response.text
