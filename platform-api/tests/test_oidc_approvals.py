import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from platform_api.auth import DEV_PEOPLE
from platform_api.oidc import identity_from_claims
from platform_api.orchestration.approvals import AnyApprover, ApprovalPolicy, ApprovalStep
from platform_api.orchestration.people_store import People
from platform_api.orchestration.runs import AwaitingApproval, Rejected
from platform_api.orchestration.service import Retried
from platform_api.orchestration.spec import RunSpec
from platform_api.shared import ApprovalId, N8nExecutionId, Principal, UserId
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
from tests.support import (
    CAROL,
    FASTAPI,
    LANGGRAPH,
    MOCK_OIDC_CONFIG,
    POSTGRES,
    REDIS,
    SPEC,
    SUMMARY,
    WATCHLIST_SPEC,
)
from tests.test_orchestrator import (
    ASK_APPROVAL,
    RUN_AGENTS,
    Harness,
    open_harness,
    work_leg_to_approval,
)
from tests.test_watchlist_runs import ONE_BEHIND, finding


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


async def retried_to_approval(
    h: Harness, spec: RunSpec, started_by: Principal, retried_by: tuple[Principal, ...]
) -> ApprovalId:
    h.agent.mode = "failed"
    run_id = (await h.orchestrator.start_run(spec, started_by, "key-1")).run_id
    await h.orchestrator.tick()
    execution = 41
    for retrier in retried_by:
        await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId(str(execution)))
        await h.orchestrator.retry(run_id, retrier)
        h.advance(timedelta(seconds=3))
        await h.orchestrator.tick()
        execution += 1
    h.agent.mode = "finished"
    await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId(str(execution)))
    await h.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId(str(execution)))
    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    return state.approval_id


@pytest.mark.anyio
async def test_the_approval_page_says_who_asked_and_what_the_agents_found(
    harness: Harness, client: httpx.AsyncClient
):
    _, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    bob = bearer(token(claims=BOB_CLAIMS))
    view = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()
    asked = ("use_case_id", "use_case_name", "owner", "started_by", "trigger", "retried_by")
    assert {key: view[key] for key in asked} == {
        "use_case_id": SPEC.use_case_id,
        "use_case_name": SPEC.use_case_name,
        "owner": "alice",
        "started_by": "alice",
        "trigger": "person",
        "retried_by": [],
    }
    assert view["found"] == SUMMARY
    assert view["not_checked"] == [], "the check read every software"
    assert (view["you_can_decide"], view["why_not"]) == (True, None)


@pytest.mark.anyio
async def test_the_approval_names_the_software_the_check_could_not_read_while_it_waits(
    harness: Harness, client: httpx.AsyncClient
):
    harness.agent.output = ONE_BEHIND.model_copy(
        update={
            "findings": [
                finding(POSTGRES, "cant_check", None, "GitHub answered 503."),
                finding(LANGGRAPH, "behind", "1.2.16"),
                finding(FASTAPI, "cant_check", None, "GitHub answered 404 Not Found."),
                finding(REDIS, "starting_point", "8.2.1"),
            ]
        }
    )
    run_id = (await harness.orchestrator.start_run(WATCHLIST_SPEC, OIDC_ALICE, "key-1")).run_id
    await harness.orchestrator.tick()
    await harness.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("41"))
    await harness.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId("41"))
    state = await harness.state(run_id)
    assert isinstance(state, AwaitingApproval)
    bob = bearer(token(claims=BOB_CLAIMS))
    view = (await client.get(f"/api/v1/approvals/{state.approval_id}", headers=bob)).json()
    assert view["not_checked"] == ["FastAPI", "PostgreSQL"], "named in the watchlist's order"
    assert [a["fields"]["title"] for a in view["actions"]] == [
        "Upgrade LangGraph from 1.2.14 to 1.2.16"
    ]
    declined = await decline(client, state.approval_id, bob, view["digest"], None)
    assert declined.status_code == 201
    view = (await client.get(f"/api/v1/approvals/{state.approval_id}", headers=bob)).json()
    assert view["not_checked"] == ["FastAPI", "PostgreSQL"], "the decided record keeps it"
    assert view["found"] == "", "found still goes once it is decided"


@pytest.mark.anyio
async def test_the_parties_the_approval_page_names_are_the_ones_the_gate_refuses(
    harness: Harness, client: httpx.AsyncClient
):
    spec = replace(SPEC, owner=UserId("carol"))
    approval_id = await retried_to_approval(
        harness, spec, started_by=CAROL, retried_by=(OIDC_ALICE, OIDC_ALICE)
    )
    alice = bearer(token(claims=ALICE_CLAIMS))
    view = (await client.get(f"/api/v1/approvals/{approval_id}", headers=alice)).json()
    assert (view["owner"], view["started_by"], view["retried_by"]) == ("carol", "carol", ["alice"])
    assert (view["you_can_decide"], view["why_not"]) == (False, "own_work")
    refused = await decide(client, approval_id, alice, view["digest"])
    assert (refused.status_code, refused.json()["refusal"]) == (403, "own_work")
    bob = bearer(token(claims=BOB_CLAIMS))
    approved = await decide(client, approval_id, bob, view["digest"])
    assert (approved.status_code, approved.json()["decision"]["by"]) == (201, "bob")


@pytest.mark.anyio
async def test_a_retry_after_the_yes_does_not_change_whom_the_approval_names(
    harness: Harness, client: httpx.AsyncClient
):
    run_id, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    bob = bearer(token(claims=BOB_CLAIMS))
    digest = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()["digest"]
    assert (await decide(client, approval_id, bob, digest)).status_code == 201
    await harness.orchestrator.tick()
    await harness.orchestrator.on_workflow_failure(
        N8nExecutionId("42"), "run", "Do write action", "timed out"
    )
    assert isinstance(await harness.orchestrator.retry(run_id, CAROL), Retried)
    view = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()
    assert (view["owner"], view["started_by"], view["retried_by"]) == ("alice", "alice", [])


async def decline(
    client: httpx.AsyncClient,
    approval_id: str,
    headers: dict[str, str],
    digest: str,
    reason: str | None,
    step: int = 0,
) -> httpx.Response:
    body: dict[str, object] = {"step": step, "verdict": "decline", "digest": digest}
    if reason is not None:
        body["reason"] = reason
    return await client.post(
        f"/api/v1/approvals/{approval_id}/decisions", headers=headers, json=body
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("reason", "why"),
    [
        ("Wrong version", "a reason goes only with a decline"),
        ("x" * 201, "a reason is at most 200 characters"),
        ("   ", "a reason has words in it"),
    ],
)
async def test_a_decision_with_a_reason_it_cannot_take_is_refused_and_decides_nothing(
    harness: Harness, client: httpx.AsyncClient, reason: str, why: str
):
    _, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    bob = bearer(token(claims=BOB_CLAIMS))
    digest = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()["digest"]
    verdict = "approve" if why.startswith("a reason goes only") else "decline"
    refused = await client.post(
        f"/api/v1/approvals/{approval_id}/decisions",
        headers=bob,
        json={"step": 0, "verdict": verdict, "digest": digest, "reason": reason},
    )
    assert refused.status_code == 422, why
    view = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()
    assert [s["status"] for s in view["steps"]] == ["open"], "nothing was decided"
    assert (view["you_can_decide"], view["why_not"]) == (True, None)


@pytest.mark.anyio
async def test_a_decline_keeps_its_reason_on_the_request_the_run_and_the_teams_card(
    harness: Harness, client: httpx.AsyncClient
):
    run_id, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    bob = bearer(token(claims=BOB_CLAIMS))
    digest = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()["digest"]
    declined = await decline(client, approval_id, bob, digest, "  Wrong version ")
    assert declined.status_code == 201
    assert declined.json()["decision"]["reason"] == "Wrong version"
    again = await decline(client, approval_id, bob, digest, "Not this week")
    assert again.status_code == 200
    assert again.json()["decision"]["reason"] == "Wrong version", "a repeat keeps the first note"
    view = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()
    [step] = view["steps"]
    assert (step["status"], step["decided_by"], step["reason"]) == (
        "declined",
        "bob",
        "Wrong version",
    )
    run = (await client.get(f"/api/v1/runs/{run_id}", headers=bob)).json()
    assert run["approval"]["steps"][0]["reason"] == "Wrong version"
    [rejected] = [e for e in await harness.log.read_after(run_id, 0) if e.kind == "run_rejected"]
    assert rejected.data.model_dump() == {"by": "bob", "step": 0, "reason": "Wrong version"}
    assert (
        rejected.summary == "Bob declined the request. Nothing was written. Reason: Wrong version."
    )
    await harness.orchestrator.tick()
    [message] = await harness.teams.messages()
    assert message.card is not None
    body = message.card.as_json()["body"]
    assert [run["text"] for block in body[:2] for run in block["inlines"]] == [
        "Declined by Bob",
        "Nothing was written. Reason: Wrong version.",
    ]


@pytest.mark.anyio
async def test_a_decline_with_no_reason_says_nothing_was_written_and_gives_no_reason(
    harness: Harness, client: httpx.AsyncClient
):
    run_id, _, approval_id = await work_leg_to_approval(harness, by=OIDC_ALICE)
    bob = bearer(token(claims=BOB_CLAIMS))
    digest = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()["digest"]
    declined = await decline(client, approval_id, bob, digest, None)
    assert (declined.status_code, declined.json()["decision"]["reason"]) == (201, None)
    assert isinstance(await harness.state(run_id), Rejected)
    [rejected] = [e for e in await harness.log.read_after(run_id, 0) if e.kind == "run_rejected"]
    assert rejected.data.model_dump() == {"by": "bob", "step": 0, "reason": None}
    await harness.orchestrator.tick()
    [message] = await harness.teams.messages()
    assert message.card is not None
    assert message.card.as_json()["body"][1]["inlines"][0]["text"] == "Nothing was written."


@pytest.mark.anyio
async def test_when_the_second_approver_declines_the_teams_card_says_who_said_yes_first(
    harness: Harness, client: httpx.AsyncClient
):
    two = ApprovalPolicy(
        (ApprovalStep("Team approver", AnyApprover()), ApprovalStep("Second", AnyApprover()))
    )
    spec = replace(SPEC, owner=UserId("carol"), approval_policy=two)
    assert await People(harness.db).seed_dev(DEV_PEOPLE)
    approval_id = await retried_to_approval(harness, spec, started_by=CAROL, retried_by=())
    bob, alice = bearer(token(claims=BOB_CLAIMS)), bearer(token(claims=ALICE_CLAIMS))
    digest = (await client.get(f"/api/v1/approvals/{approval_id}", headers=bob)).json()["digest"]
    assert (await decide(client, approval_id, bob, digest)).status_code == 201
    declined = await decline(client, approval_id, alice, digest, "Needs testing first", step=1)
    assert declined.status_code == 201
    await harness.orchestrator.tick()
    [message] = await harness.teams.messages()
    assert message.card is not None
    body = message.card.as_json()["body"]
    assert [run["text"] for block in body[:2] for run in block["inlines"]] == [
        "Approved by Bob, then declined by Alice",
        "Nothing was written. Reason: Needs testing first.",
    ]


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
