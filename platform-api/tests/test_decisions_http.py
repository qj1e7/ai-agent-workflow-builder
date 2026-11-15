from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from platform_api.auth import DEV_PEOPLE
from platform_api.orchestration.approvals import AnyApprover, ApprovalPolicy, ApprovalStep
from platform_api.orchestration.people_store import People
from platform_api.orchestration.runs import AwaitingApproval, Pending
from platform_api.shared import UseCaseId, UserId
from tests.conftest import PostgresUrls
from tests.oidc_support import (
    ALICE_CLAIMS,
    BOB_CLAIMS,
    OIDC_ALICE,
    Clock,
    FakeIssuer,
    bearer,
    oidc_app,
    token,
)
from tests.support import CAROL, SPEC
from tests.test_oidc_approvals import decide, decline
from tests.test_orchestrator import (
    ASK_APPROVAL,
    RUN_AGENTS,
    Harness,
    open_harness,
    work_leg_to_approval,
)

pytestmark = pytest.mark.anyio

DECISIONS = "/api/v1/decisions"


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


async def digest_of(client: httpx.AsyncClient, approval_id: str, headers: dict[str, str]) -> str:
    return (await client.get(f"/api/v1/approvals/{approval_id}", headers=headers)).json()["digest"]


async def test_each_person_reads_only_their_own_decisions_newest_first_with_their_runs(
    harness: Harness, client: httpx.AsyncClient
):
    bob, alice = bearer(token(claims=BOB_CLAIMS)), bearer(token(claims=ALICE_CLAIMS))
    first, _, first_approval = await work_leg_to_approval(harness, by=OIDC_ALICE)
    digest = await digest_of(client, first_approval, bob)
    assert (await decline(client, first_approval, bob, digest, "Wrong version")).status_code == 201
    harness.advance(timedelta(minutes=5))
    two = ApprovalPolicy(
        (ApprovalStep("Team approver", AnyApprover()), ApprovalStep("Second", AnyApprover()))
    )
    assert await People(harness.db).seed_dev(DEV_PEOPLE)
    spec = replace(
        SPEC,
        use_case_id=UseCaseId("uc_weekly"),
        use_case_name="Weekly closed-ticket summary",
        owner=UserId("carol"),
        approval_policy=two,
    )
    second = (await harness.orchestrator.start_run(spec, CAROL, "key-2")).run_id
    await harness.orchestrator.tick()
    started = await harness.state(second)
    assert isinstance(started, Pending) and started.claimant is not None
    await harness.orchestrator.on_step(second, RUN_AGENTS, started.claimant)
    await harness.orchestrator.on_step(second, ASK_APPROVAL, started.claimant)
    state = await harness.state(second)
    assert isinstance(state, AwaitingApproval)
    second_approval = state.approval_id
    digest = await digest_of(client, second_approval, bob)
    assert (await decide(client, second_approval, bob, digest)).status_code == 201
    harness.advance(timedelta(minutes=5))
    declined = await decline(client, second_approval, alice, digest, "Needs testing", step=1)
    assert declined.status_code == 201

    mine = (await client.get(DECISIONS, headers=bob)).json()
    assert mine["total"] == 2
    newest, oldest = mine["decisions"]
    assert newest["run_id"] != first and oldest["run_id"] == first
    assert (newest["use_case_id"], newest["use_case_name"]) == (
        "uc_weekly",
        "Weekly closed-ticket summary",
    )
    assert oldest["use_case_name"] == SPEC.use_case_name
    assert {k: newest[k] for k in ("verdict", "reason", "run_state", "declined_by")} == {
        "verdict": "approve",
        "reason": None,
        "run_state": "rejected",
        "declined_by": "alice",
    }, "Bob said yes first, and Alice declined after him"
    assert newest["approved_before"] == ["bob"]
    assert oldest["approved_before"] == []
    assert {k: oldest[k] for k in ("verdict", "reason", "run_state", "declined_by")} == {
        "verdict": "decline",
        "reason": "Wrong version",
        "run_state": "rejected",
        "declined_by": "bob",
    }
    assert newest["at"] > oldest["at"]
    assert (oldest["written"], oldest["tickets"], oldest["connector"]) == (0, True, "jira")

    hers = (await client.get(DECISIONS, headers=alice)).json()
    assert [(d["verdict"], d["reason"]) for d in hers["decisions"]] == [
        ("decline", "Needs testing")
    ]


async def test_a_verdict_keeps_only_those_decisions_and_none_is_an_empty_list(
    harness: Harness, client: httpx.AsyncClient
):
    bob = bearer(token(claims=BOB_CLAIMS))
    _, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    assert (
        await decide(client, approval_id, bob, await digest_of(client, approval_id, bob))
    ).status_code == 201
    approvals = (await client.get(DECISIONS, params={"verdict": "approve"}, headers=bob)).json()
    assert [d["verdict"] for d in approvals["decisions"]] == ["approve"]
    declines = (await client.get(DECISIONS, params={"verdict": "decline"}, headers=bob)).json()
    assert declines == {"decisions": [], "total": 0}
    nobody = bearer(token(claims=ALICE_CLAIMS))
    assert (await client.get(DECISIONS, headers=nobody)).json() == {"decisions": [], "total": 0}


async def test_decisions_need_a_signed_in_person_and_a_known_verdict(client: httpx.AsyncClient):
    assert (await client.get(DECISIONS)).status_code == 401
    bob = bearer(token(claims=BOB_CLAIMS))
    assert (
        await client.get(DECISIONS, params={"verdict": "maybe"}, headers=bob)
    ).status_code == 422
