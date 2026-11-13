"""Tell, under the Tell rule (ENGINE-PLAN 2.3.12, D19): the fixed recipients only, the run's own
reads only, nothing in a test run, and never twice."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from platform_api.orchestration.agents import CarryForward, Finding, TaskOutput
from platform_api.orchestration.n8n_call_service import CLAIM_LEASE, CallBook, NodeCalls
from platform_api.orchestration.n8n_calls import (
    ANOTHER_EXECUTION,
    NOTHING_READ,
    AgentCall,
    ExecutionFacts,
    NodeCall,
    NodeCatalog,
    ProposeCall,
    ReadCall,
    Refused,
    TellCall,
)
from platform_api.orchestration.runs import (
    Expired,
    Failed,
    Failure,
    FailureReason,
    Lost,
    Outcome,
    Pending,
    Rejected,
    ResumeWork,
    RunState,
    Stage,
    Succeeded,
    WriteDone,
)
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.tell import (
    REACH,
    BlockResult,
    TellFlow,
    TellMessage,
    TellPractice,
    Told,
    compose,
)
from platform_api.shared import ApprovalId, N8nExecutionId, ProposalId, RunId, UserId
from tests.conftest import PostgresUrls
from tests.declared import NODE_KEY, NODE_KEY_ENV, FakeNodeCalls, app_with, declared_status
from tests.support import NOW, SPEC
from tests.test_n8n_calls import (
    CARD,
    JIRA,
    REPO,
    WORKFLOW,
    FakeN8n,
    FakeSources,
    FakeWorkflows,
)
from tests.test_orchestrator import Harness, mint, open_harness

pytestmark = pytest.mark.anyio

FLOW_URL = "https://prod.example.logic.azure.com/workflows/tell/run?sig=flow-secret"
CHANNEL = "CODESparks Ops"
BOTH = TellCall("both", "result")
READ = ReadCall("github_releases", REPO, None)
COMPARE = AgentCall(CARD.id, {"Project": "MOCK"})
MADE = (WriteDone("jira", "create_ticket", "MOCK-142", (UserId("bob"),)),)
PRP, APR = ProposalId("prp_1"), ApprovalId("apr_1")
ENDINGS: dict[str, Callable[[RunId], RunState]] = {
    "rejected": lambda run: Rejected(run, PRP, APR, UserId("bob"), 1),
    "expired": lambda run: Expired(run, PRP, APR),
    "failed": lambda run: Failed(
        run, Stage.WORKING, Failure(FailureReason.AGENT_ERROR, "boom", True), ResumeWork(2)
    ),
    "lost": lambda run: Lost(run, PRP, APR),
}


@dataclass
class Flow:
    """The Tell flow behind a real TellFlow: each post it got, and how it answers."""

    status: int = 202
    broken: bool = False
    posts: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == FLOW_URL
        self.posts.append(json.loads(request.content))
        if self.broken:
            raise RuntimeError("platform-api stopped mid-post")
        return httpx.Response(self.status)


@dataclass
class Tells:
    h: Harness
    n8n: FakeN8n
    workflows: FakeWorkflows
    flow: Flow
    sources: FakeSources
    calls: NodeCalls

    def started(self, execution: str, mode: str = "trigger", nonce: str | None = None) -> None:
        self.n8n.executions[execution] = ExecutionFacts(WORKFLOW, mode, None, nonce, "v1")

    async def call(self, execution: str, work: Any, node: str) -> object:
        return await self.calls.call(NodeCall(N8nExecutionId(execution), node, work))

    async def tell(self, execution: str = "101", tell: TellCall = BOTH) -> object:
        return await self.call(execution, tell, "Tell you")

    async def read_and_compare(self, execution: str = "101", *findings: str) -> None:
        self.h.agent.output = TaskOutput(
            summary="LangGraph 1.2.16 is out.",
            new_tags=[],
            proposed=[],
            carry_forward=CarryForward(),
            findings=[
                Finding(
                    software_id="sw_1",
                    state="behind",
                    newest="1.2.16",
                    new_versions=["1.2.16"],
                    detail=detail,
                )
                for detail in findings
            ],
        )
        await self.call(execution, READ, "Read release")
        await self.call(execution, COMPARE, "Compare")

    async def end(self, ending: Callable[[RunId], RunState]) -> None:
        async with self.h.db.transaction("orchestration") as uow:
            [run] = await Store().list_runs(uow)
            await Store().save_run(uow, run, ending(run.run_id))

    async def made(self) -> None:
        """What E2d's write does: the gateway made the changes and the run succeeded."""
        await self.end(lambda run: Succeeded(run, Outcome.WRITTEN, MADE))


def tell_platform(
    h: Harness, flow: Flow, n8n: FakeN8n, workflows: FakeWorkflows, sources: FakeSources
) -> NodeCalls:
    client = httpx.AsyncClient(transport=httpx.MockTransport(flow.handle))
    return NodeCalls(
        h.db,
        h.log,
        h.agent,
        mint,
        NodeCatalog(workflows, sources, [JIRA]),
        workflows,
        n8n,
        sources,
        {},
        start_secret="test-start-secret",
        tells=TellFlow(FLOW_URL, CHANNEL, client),
    )


@pytest.fixture
async def t(postgres: PostgresUrls) -> AsyncIterator[Tells]:
    async with open_harness(postgres) as h:
        n8n, workflows, flow, sources = FakeN8n(), FakeWorkflows(), Flow(), FakeSources()
        calls = tell_platform(h, flow, n8n, workflows, sources)
        yield Tells(h, n8n, workflows, flow, sources, calls)


async def test_a_tell_posts_what_the_run_read_to_the_one_fixed_flow(t: Tells):
    t.started("101")
    await t.read_and_compare("101", "LangGraph is behind: 1.2.16 is out.")
    assert await t.tell() == Told("sent", "Posted to CODESparks Ops and emailed the team's list.")
    [post] = t.flow.posts
    card = json.dumps(post["attachments"][0]["content"])
    for read in ("Read release", "1.2.16", "Compare", "LangGraph 1.2.16 is out.", "is behind"):
        assert read in card and read in post["emailHtml"]
    assert post["emailSubject"] == "Software watchlist: what this run found"
    assert set(post) == {"type", "attachments", "emailSubject", "emailHtml"}


async def test_a_tell_claims_no_change_and_names_no_proposal(t: Tells):
    """A Tell is a notice. It lists only reads and agent results, never a change."""
    t.started("101")
    await t.read_and_compare("101")
    propose = ProposeCall("jira.create_ticket", "MOCK", "Upgrade LangGraph", "Body.", None)
    await t.call("101", propose, "Propose a change")
    await t.tell()
    [post] = t.flow.posts
    assert "Upgrade LangGraph" not in json.dumps(post)
    assert "Propose a change" not in json.dumps(post)
    assert "It asks for nothing." in post["emailHtml"]


async def test_a_tell_after_the_write_also_reports_what_the_gateway_made(t: Tells):
    """A Tell placed after Make the approved changes runs once the run has succeeded."""
    t.started("101")
    await t.read_and_compare("101")
    await t.made()
    assert await t.tell() == Told("sent", "Posted to CODESparks Ops and emailed the team's list.")
    [post] = t.flow.posts
    card = json.dumps(post["attachments"])
    assert "Made after a yes" in card and "MOCK-142" in card and "MOCK-142" in post["emailHtml"]


async def test_after_the_run_succeeded_only_a_tell_may_call(t: Tells):
    t.started("101")
    await t.read_and_compare("101")
    await t.made()
    reads = len(t.sources.reads)
    refused = await t.call("101", ReadCall("github_releases", REPO, None), "Read again")
    assert isinstance(refused, Refused) and refused.status == 409
    assert len(t.sources.reads) == reads, "nothing is read once the run has ended"


async def test_a_tell_after_success_comes_only_from_the_execution_that_carried_the_run(
    t: Tells,
):
    t.started("101")
    await t.read_and_compare("101")
    t.h.advance(timedelta(minutes=1))
    t.n8n.executions["102"] = ExecutionFacts(WORKFLOW, "retry", N8nExecutionId("101"), None, None)
    await t.call("102", READ, "Read release")
    await t.made()
    assert await t.tell("101") == ANOTHER_EXECUTION
    assert t.flow.posts == []
    assert await t.tell("102") == Told(
        "sent", "Posted to CODESparks Ops and emailed the team's list."
    )


@pytest.mark.parametrize("ending", ["rejected", "expired"])
async def test_a_tell_after_a_no_or_no_answer_says_nothing_was_written(t: Tells, ending: str):
    """Plan 2.3.6 leaves the No exit open for a Tell. It reports what was read, and no change."""
    t.started("101")
    await t.read_and_compare("101")
    await t.end(ENDINGS[ending])
    assert await t.tell() == Told("sent", "Posted to CODESparks Ops and emailed the team's list.")
    [post] = t.flow.posts
    card = json.dumps(post["attachments"])
    assert "Nothing was written." in card and "Nothing was written." in post["emailHtml"]
    assert "Made after a yes" not in json.dumps(post)


@pytest.mark.parametrize("ending", ["failed", "lost"])
async def test_a_tell_after_a_failed_or_lost_run_is_refused(t: Tells, ending: str):
    t.started("101")
    await t.read_and_compare("101")
    await t.end(ENDINGS[ending])
    refused = await t.tell()
    assert isinstance(refused, Refused) and refused.status == 409
    assert t.flow.posts == []


async def test_a_tell_with_nothing_read_is_refused_and_sends_nothing(t: Tells):
    t.started("101")
    await t.call("101", ReadCall("github_releases", "evil/repo", None), "Read release")
    assert await t.tell() == NOTHING_READ
    assert await t.tell() == NOTHING_READ
    assert t.flow.posts == []


async def test_a_tell_in_a_test_run_sends_nothing_and_says_what_it_would_have_sent(t: Tells):
    """ENGINE-PLAN 2.3.3: a workflow with no yes is tested without a real card or email."""
    run_id = RunId("run_test")
    record = RunRecord(
        run_id, SPEC, SPEC.owner, NOW, NOW, 1, Pending(run_id, 1, None, NOW), (), None
    )
    async with t.h.db.transaction("orchestration") as uow:
        await Store().insert_run(uow, record, "portal:test")
        start = await CallBook().issue_start(uow, run_id, "test", WORKFLOW)
    t.started("101", "manual", start.nonce)
    t.workflows.holder = SPEC.owner
    await t.read_and_compare("101", "LangGraph is behind.")
    told = await t.tell()
    assert told == Told(
        "would_have_sent",
        "Would have posted to CODESparks Ops and emailed the team's list. "
        "Nothing was sent in a test run.",
    )
    assert t.flow.posts == []


@pytest.mark.parametrize("status", [500, 502, 504])
async def test_a_tell_is_never_posted_again_after_the_flow_answers_5xx(t: Tells, status: int):
    """The flow may have posted before it failed, so n8n's retryOnFail must not post again."""
    t.flow.status = status
    t.started("101")
    await t.read_and_compare("101")
    first = await t.tell()
    assert first == Told(
        "not_confirmed", f"Not confirmed: the Tell flow answered {status}. It is not sent again."
    )
    t.h.advance(CLAIM_LEASE * 2)
    assert await t.tell() == first
    assert await t.tell() == first
    assert len(t.flow.posts) == 1


async def test_a_tell_cut_off_mid_post_is_kept_as_sending_and_never_posted_again(t: Tells):
    """Sending is kept before the post, so a stop between the post and its answer is safe."""
    t.flow.broken = True
    t.started("101")
    await t.read_and_compare("101")
    with pytest.raises(RuntimeError):
        await t.tell()
    t.h.advance(CLAIM_LEASE * 2)
    assert await t.tell() == Told("sending", "Sending, not confirmed. It is not sent again.")
    assert len(t.flow.posts) == 1


async def test_a_retry_of_the_run_gets_the_tells_first_answer_and_posts_nothing(t: Tells):
    t.started("101")
    await t.read_and_compare("101")
    first = await t.tell()
    t.n8n.executions["102"] = ExecutionFacts(WORKFLOW, "retry", N8nExecutionId("101"), None, None)
    assert await t.tell("102") == first
    assert len(t.flow.posts) == 1


async def test_only_when_something_to_report_sends_nothing_when_nothing_was_found(t: Tells):
    t.started("101")
    await t.read_and_compare("101")
    told = await t.tell(tell=TellCall("channel", "only_when_something_to_report"))
    assert told == Told("nothing_to_report", "Nothing to report, so nothing was sent.")
    assert t.flow.posts == []


async def test_only_when_something_to_report_sends_the_agents_findings(t: Tells):
    t.started("101")
    await t.read_and_compare("101", "Cert web-01 expires in 9 days.")
    told = await t.tell(tell=TellCall("channel", "only_when_something_to_report"))
    assert told == Told("sent", "Posted to CODESparks Ops.")
    [post] = t.flow.posts
    assert "emailHtml" not in post and "Cert web-01" in json.dumps(post["attachments"])


async def test_the_practice_copy_keeps_the_notice_once_as_the_flow_would_get_it(t: Tells):
    practice = TellPractice(t.h.db, CHANNEL)
    t.calls = NodeCalls(
        t.h.db,
        t.h.log,
        t.h.agent,
        mint,
        NodeCatalog(t.workflows, FakeSources(), [JIRA]),
        t.workflows,
        t.n8n,
        FakeSources(),
        {},
        tells=practice,
    )
    t.started("101")
    await t.read_and_compare("101")
    assert await t.tell(tell=TellCall("email", "result")) == Told(
        "sent", "Emailed the team's list."
    )
    [kept] = await practice.messages()
    assert kept["block"] == "Tell you"
    assert kept["body"]["attachments"] == []
    assert kept["body"]["emailSubject"] == "Software watchlist: what this run found"


def test_text_the_run_read_never_becomes_a_link_in_the_card_or_the_email():
    read = BlockResult(
        "Read page",
        "read",
        ({"id": "https://evil.example/approve", "title": "<script>alert(1)</script>"},),
    )
    message = compose("Cert reminder", [read], REACH["both"])
    body = json.dumps(message.body())
    assert "evil.example" not in body and "https://evil" not in body
    assert message.email is not None
    assert "<script>" not in message.email.html and "&lt;script&gt;" in message.email.html


@pytest.mark.parametrize(
    ("where", "card", "email"),
    [("channel", True, False), ("email", False, True), ("both", True, True)],
)
def test_where_picks_the_card_the_email_or_both(where: Any, card: bool, email: bool):
    message: TellMessage = compose("Release check", [], REACH[where])
    body = message.body()
    assert bool(body["attachments"]) is card
    assert ("emailHtml" in body) is email


TELL_BODY = {
    "execution_id": "101",
    "workflow_id": "wf_7",
    "node_name": "Tell you",
    "mode": "trigger",
    "where": "both",
    "what": "result",
}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**TELL_BODY, "where": "https://evil.example/hook"}, id="an-address"),
        pytest.param({**TELL_BODY, "where": "#other-channel"}, id="another-channel"),
        pytest.param({**TELL_BODY, "to": "someone@example.com"}, id="a-recipient"),
        pytest.param({**TELL_BODY, "text": "Approve now: https://evil.example"}, id="its-own-text"),
        pytest.param({**TELL_BODY, "what": "everything"}, id="another-what"),
    ],
)
def test_a_tell_that_names_its_own_recipients_or_words_is_refused(body: dict[str, Any]):
    calls = FakeNodeCalls(Told("sent", "Posted."))
    app = app_with(env=NODE_KEY_ENV, node_calls=calls)
    response = TestClient(app).post("/internal/v1/n8n/calls/tell", headers=NODE_KEY, json=body)
    assert response.status_code == 422
    assert "evil.example" not in response.text
    assert calls.calls == []


def test_the_tell_route_hands_the_block_its_choices_and_answers_what_it_did():
    calls = FakeNodeCalls(Told("would_have_sent", "Would have posted."))
    app = app_with(env=NODE_KEY_ENV, node_calls=calls)
    response = TestClient(app).post("/internal/v1/n8n/calls/tell", headers=NODE_KEY, json=TELL_BODY)
    assert response.json() == {"status": "would_have_sent", "line": "Would have posted."}
    declared_status(app, "POST", "/internal/v1/n8n/calls/tell", response)
    assert calls.calls == [NodeCall(N8nExecutionId("101"), "Tell you", BOTH)]


def test_a_refused_tell_answers_403_with_its_words():
    app = app_with(env=NODE_KEY_ENV, node_calls=FakeNodeCalls(NOTHING_READ))
    response = TestClient(app).post("/internal/v1/n8n/calls/tell", headers=NODE_KEY, json=TELL_BODY)
    assert response.status_code == 403
    assert response.json() == {"detail": NOTHING_READ.detail}
    declared_status(app, "POST", "/internal/v1/n8n/calls/tell", response)
