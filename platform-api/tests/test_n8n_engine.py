"""Run now, a test run and a retry of a use case's own n8n workflow (ENGINE-PLAN 2.3.2, 2.3.3 and
2.3.10): from the orchestrator's outbox through n8n's trigger, its run of a draft and its retry,
as spike P7 recorded n8n answering, to our API's node calls."""

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

import httpx
import pytest

from platform_api.orchestration.agents import CardsInputs, CardSpec
from platform_api.orchestration.dispatch import N8nWaker
from platform_api.orchestration.jira import PRACTICE_SITE
from platform_api.orchestration.model_settings import KeyBox
from platform_api.orchestration.n8n import N8nApi
from platform_api.orchestration.n8n_call_service import NodeCalls
from platform_api.orchestration.n8n_calls import (
    NOT_ON,
    START_OTHER_WORKFLOW,
    TEST_RUN_STOPS,
    TEST_RUN_WRITES_NOTHING,
    AgentCall,
    AgentToRun,
    AskCall,
    CannotRun,
    ExecutionFacts,
    NewRun,
    NodeCatalog,
    Publisher,
    RanVersion,
    WriteAnswer,
    decide_link,
    start_signature,
)
from platform_api.orchestration.n8n_starts import N8nStarts
from platform_api.orchestration.runs import (
    AwaitingApproval,
    Failed,
    FailureReason,
    Outcome,
    Pending,
    Succeeded,
    Working,
)
from platform_api.orchestration.service import Orchestrator, Retried
from platform_api.orchestration.spec import CardRun, CardsTask, N8nTarget, RunSpec
from platform_api.orchestration.store import RETRY, START, RunRecord, Store
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.settings import N8nOwner
from platform_api.shared import TEAM_TIME_ZONE, N8nExecutionId, Principal, RunId, UserId
from tests.conftest import PostgresUrls
from tests.fake_n8n import OWNER_EMAIL, OWNER_PASSWORD
from tests.fake_n8n import FakeN8n as N8nRecords
from tests.support import ALICE, BOB, NOW, SPEC
from tests.test_n8n_calls import (
    CARD,
    JIRA,
    OTHER_WORKFLOW,
    WORKFLOW,
    FakeN8n,
    FakeSources,
)
from tests.test_n8n_wait import (
    N8N,
    NODE_KEY,
    PROPOSE,
    READ,
    FakeLanding,
    FakeN8nWaits,
    SpecWorkflows,
    resume_url,
)
from tests.test_n8n_write import Flaky, Writes
from tests.test_orchestrator import PUBLIC_BASE_URL, mint, open_harness

pytestmark = pytest.mark.anyio

SECRET = "test-start-secret"
HOOK = "hook-7"
OWN = replace(SPEC, n8n=N8nTarget(WORKFLOW, HOOK))
PINNED = CARD.model_copy(update={"version": 3})


@dataclass
class Trigger:
    """Start from the Portal's webhook, checking a start as the block does
    (n8n-node-pack/src/nodes/StartFromPortal.node.ts): signed for its own workflow and webhook.
    Each start it takes is an execution, as mode webhook, that our node calls then read."""

    reads: FakeN8n
    hooks: Mapping[str, str]
    """Each webhook id, and the workflow whose trigger it is."""
    answer: int = 200
    posts: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    executions: list[str] = field(default_factory=list[str])

    def handle(self, request: httpx.Request) -> httpx.Response:
        _, _, hook, path = request.url.path.split("/")
        if self.answer != 200:
            return httpx.Response(self.answer)
        if path != "start" or hook not in self.hooks:
            return httpx.Response(404)
        body = json.loads(request.content)
        self.posts.append(body)
        signed = start_signature(
            SECRET, self.hooks[hook], hook, body["nonce"], body["kind"], body["expires"]
        )
        if request.headers.get("X-Wab-Signature") != signed:
            return httpx.Response(401, json={"message": "The signature does not match."})
        execution = str(201 + len(self.executions))
        self.executions.append(execution)
        self.reads.executions[execution] = ExecutionFacts(
            self.hooks[hook], "webhook", None, body["nonce"], "v1"
        )
        return httpx.Response(200, json={"message": "Workflow was started"})


@dataclass
class PinnedWorkflows(SpecWorkflows):
    """Runs the card the run's spec pinned, as the builder's facts do."""

    ran: list[CardSpec | None] = field(default_factory=list[CardSpec | None])

    async def agent_run(
        self, agent_id: str, values: Mapping[str, str], pinned: CardSpec | None = None
    ) -> AgentToRun | CannotRun | None:
        self.ran.append(pinned)
        card = pinned or CARD
        return AgentToRun(CardRun(card, dict(values), {}))


class Engine(Writes):
    trigger: Trigger
    records: N8nRecords
    pinned: PinnedWorkflows
    sources: FakeSources

    async def start(self, spec: RunSpec = OWN, by: Principal = ALICE) -> RunId:
        started = await self.orchestrator.start_run(spec, by, f"portal:{len(await self.runs())}")
        return started.run_id

    async def state(self, run_id: RunId) -> object:
        return (await self.record(run_id)).state

    async def record(self, run_id: RunId) -> RunRecord:
        async with self.h.db.transaction("orchestration") as uow:
            record = await Store().load_run(uow, run_id)
        assert record is not None
        return record

    async def outbox(self, kind: str) -> list[dict[str, Any]]:
        return await self.rows(
            "SELECT payload, status, last_error FROM orchestration.outbox WHERE kind = %s "
            "ORDER BY id",
            kind,
        )

    async def failed_by_its_deadline(self, run_id: RunId) -> None:
        await self.tick(timedelta(minutes=9))
        state = await self.state(run_id)
        assert isinstance(state, Failed) and state.failure.retryable


@pytest.fixture
async def e(postgres: PostgresUrls) -> AsyncIterator[Engine]:
    async with open_harness(postgres) as h:
        box = KeyBox("test-settings-key")
        reads, sources = FakeN8n(), FakeSources()
        workflows = PinnedWorkflows(spec=OWN)
        flaky = Flaky(h.jira)
        gateway = WriteGateway(h.db, [flaky], poll=0.05)
        calls = NodeCalls(
            h.db,
            h.log,
            h.agent,
            mint,
            NodeCatalog(workflows, sources, [JIRA]),
            workflows,
            reads,
            sources,
            {"jira": PRACTICE_SITE},
            box=box,
            gateway=gateway,
        )
        records = N8nRecords()
        records.workflows[WORKFLOW] = {"id": WORKFLOW, "versionId": "v1", "checksum": "c1"}
        records.keys.append("seed")

        def ran(execution: str, item: dict[str, Any] | None, retry_of: str | None) -> None:
            """A run of the draft is mode manual and starts from our item. A retry with
            loadWorkflow false names its original and no version of its own (P7 Q5, Q6)."""
            if retry_of is not None:
                facts = ExecutionFacts(WORKFLOW, "retry", N8nExecutionId(retry_of), None, None)
            else:
                assert item is not None
                facts = ExecutionFacts(item["workflow_id"], "manual", None, item["nonce"], "v1")
            reads.executions[execution] = facts

        records.on_run = ran
        api = N8nApi("http://n8n", N8nOwner(OWNER_EMAIL, OWNER_PASSWORD), records.client())
        trigger = Trigger(reads, {HOOK: WORKFLOW, "hook-8": OTHER_WORKFLOW})
        starts = N8nStarts(
            h.db,
            api,
            N8N,
            SECRET,
            httpx.AsyncClient(transport=httpx.MockTransport(trigger.handle)),
        )
        waits = FakeN8nWaits()
        waker_client = httpx.AsyncClient(transport=httpx.MockTransport(waits.handle))
        orchestrator = Orchestrator(
            h.db,
            h.log,
            h.engine,
            h.teams,
            h.agent,
            gateway,
            mint,
            public_base_url=PUBLIC_BASE_URL,
            waker=N8nWaker(N8N, NODE_KEY, box, waker_client),
            starts=starts,
        )
        engine = Engine(h, reads, workflows, calls, waits, orchestrator, FakeLanding())
        engine.flaky, engine.trigger, engine.records = flaky, trigger, records
        engine.pinned, engine.sources = workflows, sources
        yield engine
        await starts.close()


async def test_run_now_starts_the_workflow_through_its_own_signed_trigger(e: Engine):
    run_id = await e.start()
    assert isinstance(await e.state(run_id), Pending)
    assert await e.h.kinds(run_id) == ["run_created"]
    await e.tick()
    assert [post["kind"] for post in e.trigger.posts] == ["run_now"], "signed for its workflow"
    [execution] = e.trigger.executions
    assert e.n8n.executions[execution].mode == "webhook"
    await e.call(execution, READ, "Read release")
    state = await e.state(run_id)
    assert isinstance(state, Working) and state.execution == execution
    assert (await e.record(run_id)).started_by == ALICE.user_id


async def test_run_now_goes_from_the_trigger_to_bob_s_yes_and_one_ticket(e: Engine):
    run_id = await e.start()
    await e.tick()
    [execution] = e.trigger.executions
    await e.ask(execution)
    assert isinstance(await e.state(run_id), AwaitingApproval)
    await e.decide(BOB)
    await e.tick()
    answer = await e.write(execution)
    assert isinstance(answer, WriteAnswer) and (answer.made, answer.of) == (1, 1)
    assert await e.tickets() == ["MOCK-1"]
    done = await e.state(run_id)
    assert isinstance(done, Succeeded) and done.outcome is Outcome.WRITTEN


async def test_safety_a_test_run_runs_the_draft_by_hand_asks_nobody_and_writes_nothing(
    e: Engine,
):
    """ENGINE-PLAN 2.3.3, with P7's body: n8n runs the stored draft from Start from the Portal
    with our start item, and answers the execution's id at once."""
    run_id = await e.start(replace(OWN, stops_at_gate=True))
    await e.tick()
    assert e.trigger.posts == [], "a draft has no live trigger, so nothing goes to it"
    [(workflow, body)] = e.records.draft_runs
    item = body["triggerToStartFrom"]["data"]["data"]["main"][0][0]["json"]
    assert (workflow, body["triggerToStartFrom"]["name"]) == (WORKFLOW, "Start from the Portal")
    assert (item["kind"], item["workflow_id"]) == ("test", WORKFLOW)
    pending = await e.state(run_id)
    assert isinstance(pending, Pending) and pending.claimant is not None, "watched by its id"
    execution = pending.claimant
    assert e.n8n.executions[execution].mode == "manual"

    assert await e.ask(execution) == TEST_RUN_STOPS
    assert await e.write(execution) == TEST_RUN_WRITES_NOTHING
    assert await e.state(run_id) == Succeeded(run_id, Outcome.TEST_PASSED, ())
    await e.tick()
    assert await e.rows("SELECT 1 FROM orchestration.approval_requests") == []
    assert await e.h.teams.messages() == [], "nobody was asked"
    assert await e.tickets() == []


async def test_safety_a_start_is_signed_for_its_own_workflow_and_no_other_takes_it(e: Engine):
    run_id = await e.start()
    await e.tick()
    [post] = e.trigger.posts
    for workflow, hook in ((OTHER_WORKFLOW, HOOK), (WORKFLOW, "hook-8")):
        forged = start_signature(
            SECRET, workflow, hook, post["nonce"], post["kind"], post["expires"]
        )
        sent = start_signature(SECRET, WORKFLOW, HOOK, post["nonce"], post["kind"], post["expires"])
        assert forged != sent, "the signature names the workflow and its trigger"
    stolen = "999"
    e.n8n.executions[stolen] = ExecutionFacts(OTHER_WORKFLOW, "webhook", None, post["nonce"], "v1")
    assert await e.call(stolen, READ, "Read release") == START_OTHER_WORKFLOW
    assert isinstance(await e.state(run_id), Pending), "the start still waits for its own run"


async def test_a_start_n8n_does_not_take_fails_the_run_in_its_words_and_a_retry_starts_again(
    e: Engine,
):
    e.trigger.answer = 502
    run_id = await e.start()
    for delay in (0, 2, 5, 15, 30, 60):
        await e.tick(timedelta(seconds=delay))
    failed = await e.state(run_id)
    assert isinstance(failed, Failed)
    assert (failed.failure.reason, failed.failure.retryable) == (
        FailureReason.DISPATCH_FAILED,
        True,
    )
    assert failed.failure.message == "n8n did not take the start: n8n answered the start with 502"

    e.trigger.answer = 200
    assert await e.orchestrator.retry(run_id, ALICE) == Retried("pending")
    assert isinstance(await e.state(run_id), Pending), "n8n never ran it, so it starts again"
    await e.tick(timedelta(seconds=3))
    assert [post["kind"] for post in e.trigger.posts] == ["retry"]
    [execution] = e.trigger.executions
    await e.call(execution, READ, "Read release")
    assert isinstance(await e.state(run_id), Working)


async def test_retry_is_n8n_s_own_retry_of_the_run_s_newest_execution_from_the_outbox(e: Engine):
    """ENGINE-PLAN 2.3.10: never Failed.retry(). The run stays failed until the retry's first call
    joins it, and it picks up at the block that stopped."""
    run_id = await e.start()
    await e.tick()
    [execution] = e.trigger.executions
    e.sources.down = True
    await e.call(execution, READ, "Read release")
    await e.failed_by_its_deadline(run_id)

    assert await e.orchestrator.retry(run_id, ALICE) == Retried("pending")
    assert await e.orchestrator.retry(run_id, ALICE) == Retried("pending"), "pressed twice"
    assert isinstance(await e.state(run_id), Failed), "nothing ran yet"
    assert [row["payload"] for row in await e.outbox(RETRY)] == [{"execution_id": execution}]
    assert (await e.h.kinds(run_id))[-1] == "run_retried"
    assert e.records.retries == [], "after the short delay, never inside the request"

    await e.tick(timedelta(seconds=3))
    assert e.records.retries == [execution]
    assert [row["status"] for row in await e.outbox(RETRY)] == ["sent"]
    retry = next(x for x, facts in e.n8n.executions.items() if facts.mode == "retry")
    e.sources.down = False
    await e.call(retry, READ, "Read release")
    joined = await e.state(run_id)
    assert isinstance(joined, Working) and joined.execution == retry
    assert ALICE.user_id in (await e.record(run_id)).retried_by
    await e.call(retry, PROPOSE, "Propose a change")
    await e.call(retry, AskCall(resume_url(retry)), "Ask for a yes")
    assert isinstance(await e.state(run_id), AwaitingApproval)


async def test_a_retry_n8n_still_runs_after_the_wait_counts_as_taken(e: Engine):
    run_id = await e.start()
    await e.tick()
    [execution] = e.trigger.executions
    e.sources.down = True
    await e.call(execution, READ, "Read release")
    await e.failed_by_its_deadline(run_id)
    e.records.retry_answer = "slow"
    await e.orchestrator.retry(run_id, ALICE)
    await e.tick(timedelta(seconds=3))
    assert [row["status"] for row in await e.outbox(RETRY)] == ["sent"]


async def test_a_retry_n8n_refuses_is_given_up_and_the_run_stays_failed(e: Engine):
    run_id = await e.start()
    await e.tick()
    [execution] = e.trigger.executions
    e.sources.down = True
    await e.call(execution, READ, "Read release")
    await e.failed_by_its_deadline(run_id)
    e.records.retry_answer = "succeeded"
    await e.orchestrator.retry(run_id, ALICE)
    await e.tick(timedelta(seconds=3))
    [row] = await e.outbox(RETRY)
    assert row["status"] == "given_up" and "409" in row["last_error"]
    assert isinstance(await e.state(run_id), Failed)


async def test_a_start_names_its_kind_and_a_test_run_never_goes_to_the_trigger(e: Engine):
    await e.start()
    await e.start(replace(OWN, test=True))
    starts = [row["payload"]["kind"] for row in await e.outbox(START)]
    assert starts == ["run_now", "test"]


async def test_the_agent_runs_the_card_the_use_case_pinned_and_knows_the_last_run_s_day(
    e: Engine,
):
    """An Operator may save a newer version of the card. The use case runs the one it pinned."""
    spec = replace(OWN, task=CardsTask((CardRun(PINNED, {"Project": "MOCK"}, {}),)))
    e.pinned.spec = spec
    first = await e.start(spec)
    await e.tick()
    async with e.h.db.transaction("orchestration") as uow:
        record = await Store().load_run(uow, first)
        assert record is not None
        await Store().save_run(uow, record, Succeeded(first, Outcome.NOTHING_TO_WRITE, ()))
    e.h.advance(timedelta(days=1))
    await e.start(spec)
    await e.tick()
    execution = e.trigger.executions[-1]
    await e.call(execution, AgentCall(CARD.id, {"Project": "MOCK"}), "Compare")
    assert e.pinned.ran == [PINNED]
    [request] = e.h.agent.requests
    assert isinstance(request.inputs, CardsInputs)
    assert [agent.card.version for agent in request.inputs.agents] == [3]
    assert request.carry_forward.last_run_on == NOW.astimezone(TEAM_TIME_ZONE).date()


def test_safety_a_schedule_never_starts_a_workflow_that_is_not_on():
    """Our records decide, whatever n8n has live: a publish that never finished, or a pause n8n
    did not take."""
    facts = ExecutionFacts(WORKFLOW, "trigger", None, None, "v1")
    version = RanVersion("safe", Publisher(UserId("alice")))
    assert decide_link(facts, None, None, None, version, NOW, on=False) == NOT_ON
    assert decide_link(facts, None, None, None, version, NOW) == NewRun(UserId("alice"), "schedule")
