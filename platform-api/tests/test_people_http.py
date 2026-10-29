import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.db import Database
from platform_api.orchestration.approvals import Refusal, Verdict
from platform_api.orchestration.model_settings import KeyBox, ModelSettings
from platform_api.orchestration.people_store import People
from platform_api.orchestration.service import DecisionRefused
from platform_api.settings import FirstPeople
from platform_api.shared import DevIdentity, ExternalIdentity, Principal, Role, UserId
from tests.conftest import PostgresUrls
from tests.declared import declared_status
from tests.support import LOCAL_ENV
from tests.test_model_settings import FakeChecks
from tests.test_orchestrator import open_harness, work_leg_to_approval

pytestmark = pytest.mark.anyio

ALICE = {"X-Dev-User": "alice"}
BOB = {"X-Dev-User": "bob"}
CAROL = {"X-Dev-User": "carol"}
STALE = "sha256:" + "0" * 64
NCS = "https://ai-gateway.ncs.example/v1"


@pytest.fixture
async def people(db: Database) -> People:
    service = People(db)
    assert await service.seed_dev(DEV_PEOPLE)
    return service


@pytest.fixture
def app(db: Database, people: People) -> FastAPI:
    application = create_app(LOCAL_ENV)
    application.state.people = people
    application.state.model_settings = ModelSettings(
        db,
        FakeChecks(),  # type: ignore[arg-type]
        KeyBox("test-settings-secret-not-real"),
    )
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def me(client: httpx.AsyncClient, who: dict[str, str]) -> dict[str, Any]:
    response = await client.get("/api/v1/me", headers=who)
    assert response.status_code == 200, response.text
    return response.json()


async def roster(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    response = await client.get("/api/v1/people", headers=BOB)
    assert response.status_code == 200
    return {p["id"]: p for p in response.json()["people"]}


async def add(
    client: httpx.AsyncClient,
    who: dict[str, str],
    email: str,
    display: str,
    operator: bool = False,
    approver: bool = False,
) -> httpx.Response:
    return await client.post(
        "/api/v1/people",
        headers=who,
        json={"email": email, "display": display, "operator": operator, "approver": approver},
    )


async def pending_for(client: httpx.AsyncClient, who: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/confirmations", headers=who)
    assert response.status_code == 200
    return response.json()["confirmations"]


async def decide(
    client: httpx.AsyncClient, who: dict[str, str], confirmation: dict[str, Any], verdict: str
) -> httpx.Response:
    return await client.post(
        f"/api/v1/confirmations/{confirmation['confirmation_id']}/decisions",
        headers=who,
        json={"verdict": verdict, "digest": confirmation["digest"]},
    )


async def history(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/settings/history", headers=CAROL)
    assert response.status_code == 200
    return response.json()["changes"]


async def test_the_dev_seed_lists_alice_bob_and_carol_with_roles(client: httpx.AsyncClient):
    people = await roster(client)
    assert {k: (p["operator"], p["approver"], p["signed_in"]) for k, p in people.items()} == {
        "alice": (True, True, False),
        "bob": (False, True, True),
        "carol": (True, False, False),
    }
    assert people["alice"]["email"] == "alice@example.test"
    assert people["alice"]["added_by"] == "deploy"
    assert (await me(client, ALICE))["roles"] == ["operator", "approver"]
    assert (await roster(client))["alice"]["signed_in"] is True
    [seeded] = await history(client)
    assert (seeded["area"], seeded["by"], seeded["by_name"]) == ("people", "deploy", None)
    assert seeded["summary"].startswith("The deploy put Alice (alice@example.test")


async def test_seeding_happens_once(db: Database, people: People, client: httpx.AsyncClient):
    assert await people.seed_dev(DEV_PEOPLE) is False
    assert (
        await people.seed_first(FirstPeople("x@ncs.example", ("y@ncs.example", "z@ncs.example")))
        is False
    )
    assert set(await roster(client)) == {"alice", "bob", "carol"}
    assert len(await history(client)) == 1


async def test_the_first_deploy_names_the_first_people(
    db: Database, caplog: pytest.LogCaptureFixture
):
    fresh = People(db)
    with caplog.at_level(logging.WARNING, logger="platform_api.orchestration.people_store"):
        assert await fresh.seed_first(None) is False
    assert "FIRST_OPERATOR and FIRST_APPROVERS are not set" in caplog.text
    first = FirstPeople("jo.tan@ncs.example", ("Jo.Tan@ncs.example", "mei@ncs.example"))
    assert await fresh.seed_first(first) is True
    listed = {p.display: p.roles for p in await fresh.listed()}
    assert listed == {
        "Jo Tan": frozenset({Role.OPERATOR, Role.APPROVER}),
        "Mei": frozenset({Role.APPROVER}),
    }
    again = FirstPeople("other@ncs.example", ("a@ncs.example", "b@ncs.example"))
    assert await fresh.seed_first(again) is False
    assert {p.display for p in await fresh.listed()} == {"Jo Tan", "Mei"}
    jo = await fresh.resolve(ExternalIdentity("oid-jo", "JO.TAN@ncs.example", "Jo Tan Wei"))
    assert jo is not None and (jo.display, jo.roles) == ("Jo Tan", listed["Jo Tan"])
    assert await fresh.resolve(ExternalIdentity("oid-jo", None, None)) == jo
    assert await fresh.resolve(ExternalIdentity("oid-other", "jo.tan@ncs.example", "Imp")) is None


async def test_an_unknown_or_removed_dev_user_gets_401(client: httpx.AsyncClient, app: FastAPI):
    response = await client.get("/api/v1/use-cases", headers={"X-Dev-User": "mallory"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Unknown or missing X-Dev-User"}
    users = (await client.get("/api/v1/dev/users")).json()["users"]
    assert [u["id"] for u in users] == ["alice", "bob", "carol"]


async def test_an_operator_adds_people_and_the_list_grows(client: httpx.AsyncClient, app: FastAPI):
    added = await add(client, ALICE, "dave@example.test", "Dave", operator=True)
    assert added.status_code == 201, added.text
    dave = added.json()
    assert (dave["operator"], dave["approver"], dave["pending_approver"], dave["signed_in"]) == (
        True,
        False,
        None,
        False,
    )
    assert dave["id"].startswith("per_")
    assert (await me(client, {"X-Dev-User": dave["id"]})) == {
        "id": dave["id"],
        "display": "Dave",
        "roles": ["operator"],
        "on_list": True,
    }
    users = (await client.get("/api/v1/dev/users")).json()["users"]
    assert [u["display"] for u in users] == ["Alice", "Bob", "Carol", "Dave"]
    refused = await add(client, BOB, "erin@example.test", "Erin", operator=True)
    assert refused.status_code == 403
    declared_status(app, "POST", "/api/v1/people", refused)
    twice = await add(client, ALICE, "DAVE@example.test", "Dave again", operator=True)
    assert twice.status_code == 409
    assert twice.json() == {
        "refusal": "already_on_the_list",
        "message": "Someone with this email is already on the list.",
    }
    declared_status(app, "POST", "/api/v1/people", twice)
    no_role = await add(client, ALICE, "erin@example.test", "Erin")
    assert (no_role.status_code, no_role.json()["refusal"]) == (409, "no_role")
    bad = await add(client, ALICE, "erin", "Erin", operator=True)
    assert (bad.status_code, bad.json()["refusal"]) == (409, "bad_email")


async def test_a_new_approver_waits_for_another_approver(client: httpx.AsyncClient, app: FastAPI):
    dave = (await add(client, ALICE, "dave@example.test", "Dave", operator=True)).json()
    asked = await client.post(f"/api/v1/people/{dave['id']}/approver", headers=ALICE)
    assert asked.status_code == 202, asked.text
    assert asked.json()["pending_approver"]["asked_by"] == "alice"
    assert asked.json()["approver"] is False
    assert (await me(client, {"X-Dev-User": dave["id"]}))["roles"] == ["operator"]

    again = await client.post(f"/api/v1/people/{dave['id']}/approver", headers=CAROL)
    assert (again.status_code, again.json()["refusal"]) == (409, "already_asked")
    declared_status(app, "POST", "/api/v1/people/{person_id}/approver", again)

    [waiting] = await pending_for(client, ALICE)
    assert (waiting["kind"], waiting["summary"], waiting["about"]["id"]) == (
        "approver",
        "Make Dave an Approver",
        dave["id"],
    )
    assert (waiting["you_can_decide"], waiting["why_not"]) == (False, "you_asked")
    [as_bob] = await pending_for(client, BOB)
    assert (as_bob["you_can_decide"], as_bob["why_not"]) == (True, None)
    [as_carol] = await pending_for(client, CAROL)
    assert as_carol["why_not"] == "not_an_approver"

    self_confirm = await decide(client, ALICE, waiting, "confirm")
    assert self_confirm.status_code == 403
    assert self_confirm.json()["refusal"] == "you_asked"
    declared_status(app, "POST", "/api/v1/confirmations/{confirmation_id}/decisions", self_confirm)
    not_approver = await decide(client, CAROL, waiting, "confirm")
    assert (not_approver.status_code, not_approver.json()["refusal"]) == (403, "not_an_approver")
    stale = await decide(client, BOB, {**waiting, "digest": STALE}, "confirm")
    assert (stale.status_code, stale.json()["refusal"]) == (409, "digest_changed")
    declared_status(app, "POST", "/api/v1/confirmations/{confirmation_id}/decisions", stale)
    assert (await me(client, {"X-Dev-User": dave["id"]}))["roles"] == ["operator"]

    confirmed = await decide(client, BOB, waiting, "confirm")
    assert confirmed.status_code == 201, confirmed.text
    assert (confirmed.json()["decision"], confirmed.json()["decided_by"]) == ("confirmed", "bob")
    declared_status(app, "POST", "/api/v1/confirmations/{confirmation_id}/decisions", confirmed)
    assert (await me(client, {"X-Dev-User": dave["id"]}))["roles"] == ["operator", "approver"]
    assert (await roster(client))[dave["id"]]["pending_approver"] is None
    assert await pending_for(client, BOB) == []
    twice = await decide(client, BOB, waiting, "confirm")
    assert (twice.status_code, twice.json()["refusal"]) == (409, "already_decided")

    lines = await history(client)
    assert [(line["by"], line["confirmed_by"]) for line in lines[:2]] == [
        ("alice", "bob"),
        ("alice", None),
    ]
    assert lines[0]["summary"] == "Bob confirmed Dave as an Approver, as Alice asked."
    assert lines[0]["confirmation_id"] == waiting["confirmation_id"]
    assert (lines[0]["by_name"], lines[0]["confirmed_by_name"]) == ("Alice", "Bob")


async def test_not_now_leaves_the_role_off(client: httpx.AsyncClient):
    dave = (await add(client, ALICE, "dave@example.test", "Dave", approver=True)).json()
    assert dave["pending_approver"] is not None
    [waiting] = await pending_for(client, BOB)
    declined = await decide(client, BOB, waiting, "not_now")
    assert (declined.status_code, declined.json()["decision"]) == (201, "not_now")
    assert (await roster(client))[dave["id"]]["approver"] is False
    assert (await history(client))[0]["summary"] == (
        "Bob said not now to making Dave an Approver, as Alice asked."
    )
    asked_again = await client.post(f"/api/v1/people/{dave['id']}/approver", headers=CAROL)
    assert asked_again.status_code == 202


async def test_nobody_removes_their_own_operator_role(client: httpx.AsyncClient, app: FastAPI):
    own = await client.put("/api/v1/people/alice/operator", headers=ALICE, json={"operator": False})
    assert (own.status_code, own.json()["refusal"]) == (409, "own_operator_role")
    declared_status(app, "PUT", "/api/v1/people/{person_id}/operator", own)
    by_carol = await client.put(
        "/api/v1/people/alice/operator", headers=CAROL, json={"operator": False}
    )
    assert by_carol.status_code == 200
    assert (by_carol.json()["operator"], by_carol.json()["approver"]) == (False, True)
    assert (await me(client, ALICE))["roles"] == ["approver"]
    back = await client.put("/api/v1/people/alice/operator", headers=CAROL, json={"operator": True})
    assert back.json()["operator"] is True
    missing = await client.put(
        "/api/v1/people/nobody/operator", headers=CAROL, json={"operator": True}
    )
    assert missing.status_code == 404
    declared_status(app, "PUT", "/api/v1/people/{person_id}/operator", missing)


async def test_two_approvers_always_stay(client: httpx.AsyncClient, app: FastAPI):
    floor = await client.delete("/api/v1/people/bob/approver", headers=CAROL)
    assert (floor.status_code, floor.json()["refusal"]) == (409, "two_approvers")
    declared_status(app, "DELETE", "/api/v1/people/{person_id}/approver", floor)
    gone = await client.delete("/api/v1/people/bob", headers=CAROL)
    assert (gone.status_code, gone.json()["refusal"]) == (409, "two_approvers")
    declared_status(app, "DELETE", "/api/v1/people/{person_id}", gone)
    assert (await me(client, BOB))["roles"] == ["approver"]


async def confirmed_approver(client: httpx.AsyncClient, email: str, display: str) -> str:
    person = (await add(client, ALICE, email, display, operator=True, approver=True)).json()
    [waiting] = [c for c in await pending_for(client, BOB) if c["about"]["id"] == person["id"]]
    assert (await decide(client, BOB, waiting, "confirm")).status_code == 201
    return str(person["id"])


async def test_two_removals_at_the_same_moment_leave_two_approvers(client: httpx.AsyncClient):
    dave = await confirmed_approver(client, "dave@example.test", "Dave")
    assert sum(p["approver"] for p in (await roster(client)).values()) == 3
    first, second = await asyncio.gather(
        client.delete(f"/api/v1/people/{dave}/approver", headers=ALICE),
        client.delete("/api/v1/people/alice/approver", headers=CAROL),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    refused = first if first.status_code == 409 else second
    assert refused.json()["refusal"] == "two_approvers"
    assert sum(p["approver"] for p in (await roster(client)).values()) == 2


async def test_removing_a_person_takes_effect_at_once(client: httpx.AsyncClient, app: FastAPI):
    dave = (await add(client, ALICE, "dave@example.test", "Dave", operator=True)).json()
    assert (await me(client, {"X-Dev-User": dave["id"]}))["on_list"] is True
    yourself = await client.delete(
        f"/api/v1/people/{dave['id']}", headers={"X-Dev-User": dave["id"]}
    )
    assert (yourself.status_code, yourself.json()["refusal"]) == (409, "yourself")
    removed = await client.delete(f"/api/v1/people/{dave['id']}", headers=ALICE)
    assert removed.status_code == 204
    assert (await client.get("/api/v1/me", headers={"X-Dev-User": dave["id"]})).status_code == 401
    assert dave["id"] not in await roster(client)
    assert (await history(client))[0]["summary"] == "Alice removed Dave from the list."
    missing = await client.delete(f"/api/v1/people/{dave['id']}", headers=ALICE)
    assert missing.status_code == 404
    back = await add(client, CAROL, "Dave@example.test", "Dave T", operator=True)
    assert (back.status_code, back.json()["id"], back.json()["display"]) == (
        201,
        dave["id"],
        "Dave T",
    )


async def test_a_removed_approver_cannot_decide_a_run_in_the_same_minute(
    postgres: PostgresUrls, client: httpx.AsyncClient, people: People
):
    dave_id = await confirmed_approver(client, "dave@example.test", "Dave")
    dave = Principal(UserId(dave_id), frozenset({Role.APPROVER, Role.OPERATOR}), "Dave")
    async with open_harness(postgres, people=people, keep_data=True) as h:
        alice = Principal(UserId("alice"), frozenset({Role.OPERATOR, Role.APPROVER}), "Alice")
        _, _, approval_id = await work_leg_to_approval(h, by=alice)
        detail = await h.orchestrator.get_approval(approval_id, dave)
        assert detail is not None and detail.why_not is None
        assert (
            await client.delete(f"/api/v1/people/{dave_id}/approver", headers=CAROL)
        ).status_code == 200
        outcome = await h.orchestrator.decide(
            approval_id, dave, 0, Verdict.APPROVE, detail.request.digest
        )
        assert outcome == DecisionRefused(Refusal.NOT_AN_APPROVER)
        bob = Principal(UserId("bob"), frozenset({Role.APPROVER}), "Bob")
        assert (await client.delete("/api/v1/people/bob", headers=ALICE)).status_code == 409
        decided = await h.orchestrator.decide(
            approval_id, bob, 0, Verdict.APPROVE, detail.request.digest
        )
        assert not isinstance(decided, DecisionRefused)


async def test_the_model_address_is_a_confirmation_too(client: httpx.AsyncClient, people: People):
    saved = await client.put(
        "/api/v1/settings/model",
        headers=ALICE,
        json={
            "style": "openai",
            "base_url": NCS,
            "model": "ncs-llm-small",
            "api_key": "k-not-real",
        },
    )
    assert saved.json()["status"] == "awaiting_confirmation", saved.text
    [waiting] = await pending_for(client, BOB)
    assert (waiting["kind"], waiting["summary"], waiting["about"]) == (
        "model_address",
        "Use ncs-llm-small at ai-gateway.ncs.example",
        None,
    )
    view = (await client.get("/api/v1/settings/model", headers=BOB)).json()
    assert view["pending"]["digest"] == waiting["digest"]
    assert (await decide(client, ALICE, waiting, "confirm")).status_code == 403
    confirmed = await decide(client, BOB, waiting, "confirm")
    assert (confirmed.status_code, confirmed.json()["kind"]) == (201, "model_address")
    view = (await client.get("/api/v1/settings/model", headers=BOB)).json()
    assert (view["pending"], view["active"]["model"]) == (None, "ncs-llm-small")
    assert (view["changes"][0]["by"], view["changes"][0]["confirmed_by"]) == ("alice", "bob")
    assert (await history(client))[0]["area"] == "model"
    assert await pending_for(client, BOB) == []


async def test_the_dev_identity_resolves_only_people_on_the_list(people: People):
    assert await people.resolve(DevIdentity(UserId("alice"))) == Principal(
        UserId("alice"), frozenset({Role.OPERATOR, Role.APPROVER}), "Alice"
    )
    assert await people.resolve(DevIdentity(UserId("mallory"))) is None
    assert await people.person(UserId("bob")) is not None
    assert await people.person(UserId("mallory")) is None


async def test_removing_a_person_closes_the_request_about_them(
    client: httpx.AsyncClient, app: FastAPI
):
    dave = (
        await add(client, ALICE, "dave@example.test", "Dave", operator=True, approver=True)
    ).json()
    [waiting] = await pending_for(client, BOB)
    assert (await client.delete(f"/api/v1/people/{dave['id']}", headers=ALICE)).status_code == 204
    assert await pending_for(client, BOB) == []
    lines = await history(client)
    assert lines[0]["summary"] == "Alice removed Dave from the list."
    assert lines[1]["summary"] == (
        "The request to make Dave an Approver was closed, because Alice removed Dave from the list."
    )
    assert lines[1]["confirmation_id"] == waiting["confirmation_id"]
    back = await add(client, CAROL, "dave@example.test", "Dave", operator=True)
    assert back.status_code == 201
    stale = await decide(client, BOB, waiting, "confirm")
    assert (stale.status_code, stale.json()["refusal"]) == (409, "already_decided")
    declared_status(app, "POST", "/api/v1/confirmations/{confirmation_id}/decisions", stale)
    assert (await roster(client))[dave["id"]]["approver"] is False
    asked = await client.post(f"/api/v1/people/{dave['id']}/approver", headers=CAROL)
    assert asked.status_code == 202
    [fresh] = await pending_for(client, BOB)
    assert fresh["digest"] != waiting["digest"]


async def test_a_request_whose_asker_left_the_list_cannot_be_confirmed(
    client: httpx.AsyncClient, app: FastAPI
):
    dave = (await add(client, ALICE, "dave@example.test", "Dave", operator=True)).json()
    erin = (await add(client, ALICE, "erin@example.test", "Erin", operator=True)).json()
    asked = await client.post(
        f"/api/v1/people/{erin['id']}/approver", headers={"X-Dev-User": dave["id"]}
    )
    assert asked.status_code == 202
    assert (await client.delete(f"/api/v1/people/{dave['id']}", headers=ALICE)).status_code == 204
    [waiting] = await pending_for(client, BOB)
    assert (waiting["you_can_decide"], waiting["why_not"]) == (False, "asker_gone")
    refused = await decide(client, BOB, waiting, "confirm")
    assert (refused.status_code, refused.json()["refusal"]) == (403, "asker_gone")
    declared_status(app, "POST", "/api/v1/confirmations/{confirmation_id}/decisions", refused)
    assert (await roster(client))[erin["id"]]["approver"] is False


async def test_a_re_added_person_signs_in_afresh(client: httpx.AsyncClient, people: People):
    dave = (await add(client, ALICE, "dave@example.test", "Dave", operator=True)).json()
    first = await people.resolve(ExternalIdentity("oid-dave", "dave@example.test", "Dave T"))
    assert first is not None and first.user_id == dave["id"]
    assert first.display == "Dave"
    assert (await roster(client))[dave["id"]]["signed_in"] is True
    assert (await client.delete(f"/api/v1/people/{dave['id']}", headers=ALICE)).status_code == 204
    back = await add(client, ALICE, "Dave@example.test", "Dave T", operator=True)
    assert (back.status_code, back.json()["id"], back.json()["signed_in"]) == (
        201,
        dave["id"],
        False,
    )
    assert await people.resolve(ExternalIdentity("oid-dave", None, None)) is None
    again = await people.resolve(ExternalIdentity("oid-dave-2", "dave@example.test", "Dave T"))
    assert again is not None and (again.user_id, again.display) == (dave["id"], "Dave T")
    assert (await roster(client))[dave["id"]]["signed_in"] is True
    assert (await client.delete(f"/api/v1/people/{dave['id']}", headers=ALICE)).status_code == 204
    other = (await add(client, ALICE, "dave.t@example.test", "Dave T", operator=True)).json()
    assert other["id"] != dave["id"]
    assert await people.resolve(ExternalIdentity("oid-dave-2", None, None)) is None
