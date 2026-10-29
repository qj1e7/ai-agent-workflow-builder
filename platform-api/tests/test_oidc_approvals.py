import json
from collections.abc import AsyncIterator

import httpx
import pytest

from platform_api.auth import DEV_PEOPLE
from platform_api.oidc import identity_from_claims
from tests.conftest import PostgresUrls
from tests.oidc_support import (
    ALICE_CLAIMS,
    BOB_CLAIMS,
    NOBODY_CLAIMS,
    OIDC_ALICE,
    Clock,
    FakeIssuer,
    bearer,
    oidc_app,
    token,
)
from tests.support import MOCK_OIDC_CONFIG
from tests.test_orchestrator import Harness, open_harness, work_leg_to_approval


@pytest.fixture
async def harness(postgres: PostgresUrls) -> AsyncIterator[Harness]:
    async with open_harness(postgres) as h:
        yield h


@pytest.fixture
async def client(harness: Harness) -> AsyncIterator[httpx.AsyncClient]:
    app = oidc_app(FakeIssuer(), Clock())
    app.state.orchestrator = harness.orchestrator
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def decide(
    client: httpx.AsyncClient, approval_id: str, headers: dict[str, str], digest: str
) -> httpx.Response:
    return await client.post(
        f"/api/v1/approvals/{approval_id}/decisions",
        headers=headers,
        json={"step": 0, "verdict": "approve", "digest": digest},
    )


@pytest.mark.anyio
async def test_an_approver_who_started_the_run_cannot_approve_it(
    harness: Harness, client: httpx.AsyncClient
):
    _, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    alice = bearer(token(claims=ALICE_CLAIMS))
    view = (await client.get(f"/api/v1/approvals/{approval_id}", headers=alice)).json()
    assert (view["you_can_decide"], view["why_not"]) == (False, "own_work")
    refused = await decide(client, approval_id, alice, view["digest"])
    assert (refused.status_code, refused.json()["refusal"]) == (403, "own_work")
    bob = bearer(token(claims=BOB_CLAIMS))
    approved = await decide(client, approval_id, bob, view["digest"])
    assert (approved.status_code, approved.json()["decision"]["by"]) == (201, "bob")


@pytest.mark.anyio
async def test_a_person_not_on_the_list_cannot_read_or_decide_whatever_the_token_claims(
    harness: Harness, client: httpx.AsyncClient
):
    _, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    nobody = bearer(token(claims=NOBODY_CLAIMS))
    me = (await client.get("/api/v1/me", headers=nobody)).json()
    assert (me["roles"], me["on_list"]) == ([], False)
    read = await client.get(f"/api/v1/approvals/{approval_id}", headers=nobody)
    assert read.status_code == 403
    assert "Ask an Operator" in read.json()["detail"]
    alice = bearer(token(claims=ALICE_CLAIMS))
    digest = (await client.get(f"/api/v1/approvals/{approval_id}", headers=alice)).json()["digest"]
    refused = await decide(client, approval_id, nobody, digest)
    assert refused.status_code == 403
    assert "Ask an Operator" in refused.json()["detail"]


def test_the_mock_identity_provider_issues_the_dev_people_and_two_more():
    config = json.loads(MOCK_OIDC_CONFIG.read_text())
    mappings = config["tokenCallbacks"][0]["requestMappings"]
    claims_by_subject = {
        m["match"]: m["claims"] for m in mappings if m["requestParam"] == "subject"
    }
    assert set(claims_by_subject) == {"alice", "bob", "carol", "dave", "erin", "mallory"}
    for person in DEV_PEOPLE:
        claims = claims_by_subject[person.id]
        identity = identity_from_claims(claims)
        assert (identity.user_name, identity.name) == (person.email, person.display)
        assert claims["aud"] == ["platform-api"]
    oids = [identity_from_claims(c).subject for c in claims_by_subject.values()]
    assert len(set(oids)) == len(oids)
