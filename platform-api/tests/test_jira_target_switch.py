"""ADR 0041 and issue 166: an approved Jira write is made only in the Jira it was approved for.

Each test approves a write while one Jira is set up, then restarts the platform with another
JIRA_BASE_URL, as a deploy or a settings change does, and lets the write run. Jira B is a second
Jira site with a project of the same key, MOCK.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import timedelta

import httpx
import pytest

from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.dispatch import Identity, identity_of
from platform_api.orchestration.jira import PRACTICE_SITE, JiraWriteConnector, jira_site
from platform_api.orchestration.runs import Failed, FailureReason, Succeeded
from platform_api.orchestration.service import NotRetryable, Orchestrator, Retried
from platform_api.orchestration.write_actions import (
    Site,
    WriteConnector,
    WriteGateway,
    digest,
)
from platform_api.settings import settings_from_env
from platform_api.shared import JIRA_SITE_CHANGED, WRITE_STOP_ADVICE, ApprovalId, RunId
from platform_api.wiring import jira_for
from tests.conftest import PostgresUrls
from tests.support import ALICE, BOB, LOCAL_ENV
from tests.test_orchestrator import (
    PUBLIC_BASE_URL,
    WRITE_ACTION,
    Harness,
    mint,
    open_harness,
    work_leg_to_approval,
)

pytestmark = pytest.mark.anyio

B = "https://jira-b.example"
STOPPED = f"{JIRA_SITE_CHANGED} {WRITE_STOP_ADVICE}"


@dataclass
class JiraB:
    calls: list[str] = field(default_factory=list[str])
    tokens: list[str] = field(default_factory=list[str])

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.tokens.append(request.headers.get("authorization", ""))
        if request.method == "POST" and path == "/rest/api/2/issue":
            fields = json.loads(request.content)["fields"]
            self.calls.append(f"create in {fields['project']['key']}")
            return httpx.Response(201, json={"id": "10901", "key": "MOCK-901"})
        self.calls.append(f"{request.method} {path}")
        return httpx.Response(404, json={"errorMessages": ["no such route"]})


@dataclass
class Switches:
    h: Harness
    b: JiraB
    client: httpx.AsyncClient

    def restart(self, base_url: str | None, token: str = "b-token-1") -> None:
        """platform-api again, with the practice Jira or with a JIRA_BASE_URL, as wiring builds
        its write connector."""
        env = dict(LOCAL_ENV)
        if base_url is not None:
            env["JIRA_BASE_URL"], env["JIRA_API_TOKEN"] = base_url, token
        settings = settings_from_env(env)
        connector: WriteConnector = self.h.jira
        if base_url is not None:
            adapter, _ = jira_for(settings, self.h.db, self.client)
            connector = JiraWriteConnector(adapter, self.h.db, jira_site(settings.jira.base_url))
        self.h.orchestrator = Orchestrator(
            self.h.db,
            self.h.log,
            self.h.engine,
            self.h.teams,
            self.h.agent,
            WriteGateway(self.h.db, [connector], poll=0.05),
            mint,
            public_base_url=PUBLIC_BASE_URL,
        )


@pytest.fixture
async def s(postgres: PostgresUrls) -> AsyncIterator[Switches]:
    b = JiraB()
    async with (
        open_harness(postgres) as h,
        httpx.AsyncClient(transport=httpx.MockTransport(b.handle)) as client,
    ):
        yield Switches(h, b, client)


async def bob_approves(h: Harness, approval_id: ApprovalId) -> None:
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    await h.orchestrator.decide(approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest)
    await h.orchestrator.tick()


async def stopped_for_the_site(h: Harness, run_id: RunId) -> None:
    state = await h.state(run_id)
    assert isinstance(state, Failed)
    assert state.failure.reason is FailureReason.SAFETY_DENIED
    assert (state.failure.message, state.failure.retryable) == (JIRA_SITE_CHANGED, False)
    events = await h.log.read_after(run_id, 0)
    [denied] = [e for e in events if e.kind == "write_action_denied"]
    assert denied.data.reason == "target_changed"
    assert events[-1].kind == "run_failed"
    assert events[-1].summary == f"The run failed (SafetyDenied): {STOPPED}"
    refused = await h.orchestrator.retry(run_id, ALICE)
    assert refused == NotRetryable(f"SafetyDenied cannot be retried: {STOPPED}")


async def test_the_approval_covers_the_jira_site_the_ticket_goes_to(s: Switches):
    _, _, approval_id = await work_leg_to_approval(s.h)
    detail = await s.h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    assert [dict(a.target) for a in detail.proposal.actions] == [
        {"project": "MOCK", "site": "practice"}
    ]
    assert detail.site_names == ("the practice Jira",)
    [card] = await s.h.teams.messages()
    assert card.card is not None
    assert "Create Jira ticket in MOCK on the practice Jira: " in json.dumps(card.card.as_json())

    s.restart(B)
    detail = await s.h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    assert detail.site_names == ("a Jira that is no longer set up",)


async def test_a_write_approved_on_the_practice_jira_is_not_made_on_jira_b_after_the_switch(
    s: Switches,
):
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    await bob_approves(s.h, approval_id)
    s.restart(B)
    reply = await s.h.orchestrator.on_step(run_id, WRITE_ACTION, s.h.engine.executions[-1])
    assert (reply.outcome, reply.detail) == (
        "refused",
        "the safety checker denied the write: target_changed",
    )
    assert s.b.calls == [], "Jira B was asked nothing"
    assert await s.h.jira.tickets() == []
    await stopped_for_the_site(s.h, run_id)


async def test_a_retry_after_the_switch_asks_jira_b_nothing_and_makes_no_ticket(s: Switches):
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    await bob_approves(s.h, approval_id)
    s.h.jira.store.answering = False
    failed = await s.h.orchestrator.on_step(run_id, WRITE_ACTION, s.h.engine.executions[-1])
    assert failed.outcome == "failed"
    state = await s.h.state(run_id)
    assert isinstance(state, Failed) and state.failure.retryable
    s.h.jira.store.answering = True
    s.restart(B)
    assert isinstance(await s.h.orchestrator.retry(run_id, ALICE), Retried)
    s.h.advance(timedelta(seconds=31))
    await s.h.orchestrator.tick()
    reply = await s.h.orchestrator.on_step(run_id, WRITE_ACTION, s.h.engine.executions[-1])
    assert reply.outcome == "refused"
    assert s.b.calls == [], "the retry did not look for the label on Jira B, nor make a ticket"
    assert await s.h.jira.tickets() == []
    assert (await s.h.kinds(run_id)).count("approval_decided") == 1
    await stopped_for_the_site(s.h, run_id)


async def test_a_write_approved_on_jira_b_is_still_made_there_after_a_new_token(s: Switches):
    s.restart(B, token="b-token-1")
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    detail = await s.h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    assert [dict(a.target) for a in detail.proposal.actions] == [
        {"project": "MOCK", "site": identity_of("jira", B)}
    ]
    assert detail.site_names == ("jira-b.example",)
    await bob_approves(s.h, approval_id)
    s.restart(B + "/", token="b-token-2")
    reply = await s.h.orchestrator.on_step(run_id, WRITE_ACTION, s.h.engine.executions[-1])
    assert (reply.outcome, reply.detail) == ("written", "Created MOCK-901")
    assert s.b.calls == ["create in MOCK"]
    assert s.b.tokens == ["Bearer b-token-2"]
    assert isinstance(await s.h.state(run_id), Succeeded)
    assert await s.h.jira.tickets() == []


async def saved_before_sites(h: Harness, run_id: RunId, approval_id: ApprovalId) -> None:
    """The run's proposal and approval request as code from before ADR 0041 saved them: a
    target with no site, and a digest of that."""
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    actions = tuple(
        replace(a, target={k: v for k, v in a.target.items() if k != "site"})
        for a in detail.proposal.actions
    )
    old = digest(actions)
    async with h.db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "UPDATE orchestration.proposals SET actions = jsonb_set(actions, '{0,target}', "
            "(actions #> '{0,target}') - 'site'), digest = %s WHERE run_id = %s",
            (old, run_id),
        )
        await uow.conn.execute(
            "UPDATE orchestration.approval_requests SET digest = %s WHERE approval_id = %s",
            (old, approval_id),
        )


async def test_a_write_saved_before_sites_were_kept_is_denied_by_default(s: Switches):
    run_id, _, approval_id = await work_leg_to_approval(s.h)
    await saved_before_sites(s.h, run_id, approval_id)
    detail = await s.h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None and dict(detail.proposal.actions[0].target) == {"project": "MOCK"}
    assert detail.site_names == ("a Jira that is no longer set up",)
    await bob_approves(s.h, approval_id)
    reply = await s.h.orchestrator.on_step(run_id, WRITE_ACTION, s.h.engine.executions[-1])
    assert reply.outcome == "refused"
    assert await s.h.jira.tickets() == [], "a row from before is not taken as the practice Jira's"
    await stopped_for_the_site(s.h, run_id)


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("HTTPS://Jira.Example.COM:8443/jira/", "https://jira.example.com:8443/jira"),
        ("https://jira.example.com/", "https://jira.example.com"),
    ],
)
def test_a_site_is_its_address_with_the_scheme_and_host_in_lower_case(one: str, other: str):
    assert jira_site(one) == jira_site(other)


@pytest.mark.parametrize(
    "other",
    [
        "https://jira.example.com/jira",
        "https://jira.example.com:443/jira",
        "https://jira.example.com:8443",
        "https://jira.example.org:443/Jira",
    ],
)
def test_a_site_keeps_the_port_and_the_path(other: str):
    assert jira_site(other) != jira_site("https://jira.example.com:443/Jira")


def test_a_site_names_the_practice_jira_or_the_host():
    assert jira_site(None) == PRACTICE_SITE == Site(Identity("practice"), "the practice Jira")
    site = jira_site("https://Jira.Example.com:8443/jira")
    assert site == Site(
        identity_of("jira", "https://jira.example.com:8443/jira"), "jira.example.com"
    )
