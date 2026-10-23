import json
from collections.abc import AsyncIterator

import httpx
import pytest

from platform_api.auth import DEV_USERS
from platform_api.oidc import principal_from_claims
from tests.conftest import PostgresUrls
from tests.oidc_support import (
    ALICE_CLAIMS,
    BOB_CLAIMS,
    BOB_ID,
    OIDC_ALICE,
    Clock,
    FakeIssuer,
    bearer,
    oidc_app,
    token,
)
from tests.support import MOCK_OIDC_CONFIG
from tests.test_orchestrator import Harness, open_harness, work_leg_to_approval

NOBODY_CLAIMS: dict[str, object] = {"oid": "n0b0dy00-0000-4000-8000-000000000009", "roles": []}


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
    assert (approved.status_code, approved.json()["decision"]["by"]) == (201, BOB_ID)


@pytest.mark.anyio
async def test_a_person_without_a_known_role_cannot_decide(
    harness: Harness, client: httpx.AsyncClient
):
    _, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    nobody = bearer(token(claims=NOBODY_CLAIMS))
    view = (await client.get(f"/api/v1/approvals/{approval_id}", headers=nobody)).json()
    assert (view["you_can_decide"], view["why_not"]) == (False, "not_an_approver")
    refused = await decide(client, approval_id, nobody, view["digest"])
    assert (refused.status_code, refused.json()["refusal"]) == (403, "not_an_approver")


def test_the_mock_identity_provider_issues_the_dev_users_with_their_roles():
    config = json.loads(MOCK_OIDC_CONFIG.read_text())
    mappings = config["tokenCallbacks"][0]["requestMappings"]
    claims_by_subject = {
        m["match"]: m["claims"] for m in mappings if m["requestParam"] == "subject"
    }
    assert set(claims_by_subject) == {user.id for user in DEV_USERS.users}
    for user in DEV_USERS.users:
        claims = claims_by_subject[user.id]
        principal = principal_from_claims(claims)
        assert (principal.display, principal.roles) == (user.display, frozenset(user.roles))
        assert claims["aud"] == ["platform-api"]
