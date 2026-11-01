from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from platform_api.db import Database
from platform_api.monitoring import ActivityLog
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.runs import (
    AwaitingApproval,
    Failed,
    Pending,
    Rejected,
    RunState,
    Succeeded,
)
from platform_api.orchestration.service import Orchestrator, Retried
from platform_api.orchestration.teams import TeamsStub
from platform_api.orchestration.workflows import load_all
from platform_api.orchestration.write_actions import MockJiraConnector, WriteGateway
from platform_api.shared import ApprovalId, RunId
from tests.conftest import PostgresUrls, truncate_all
from tests.fake_engine import FakeWorkflowEngine
from tests.support import ALICE, BOB, NOW, SPEC, fixture
from tests.test_orchestrator import FakeAgent, mint

pytestmark = pytest.mark.anyio


@dataclass
class Stack:
    db: Database
    clock: dict[str, datetime]
    log: ActivityLog
    engine: FakeWorkflowEngine
    agent: FakeAgent
    jira: MockJiraConnector
    orchestrator: Orchestrator

    async def state(self, run_id: RunId) -> RunState:
        detail = await self.orchestrator.get_run(run_id)
        assert detail is not None
        return detail.record.state

    async def kinds(self, run_id: RunId) -> list[str]:
        return [e.kind for e in await self.log.read_after(run_id, 0)]

    async def approve(self, run_id: RunId, verdict: Verdict) -> ApprovalId:
        state = await self.state(run_id)
        assert isinstance(state, AwaitingApproval)
        detail = await self.orchestrator.get_approval(state.approval_id, BOB)
        assert detail is not None and detail.why_not is None
        await self.orchestrator.decide(state.approval_id, BOB, 0, verdict, detail.request.digest)
        return state.approval_id


@pytest.fixture
async def stack(postgres: PostgresUrls) -> AsyncIterator[Stack]:
    truncate_all(postgres.owner)
    clock = {"now": NOW}
    db = Database(postgres.contexts, clock=lambda: clock["now"])
    await db.open()
    log = ActivityLog(db)
    engine = FakeWorkflowEngine(load_all())
    agent = FakeAgent()
    jira = MockJiraConnector(db)
    orchestrator = Orchestrator(
        db,
        log,
        engine,
        TeamsStub(db, "CODESparks Ops"),
        agent,
        WriteGateway(db, [jira], poll=0.05),
        mint,
        public_base_url="http://localhost:8000",
    )
    engine.bind(orchestrator)
    try:
        yield Stack(db, clock, log, engine, agent, jira, orchestrator)
    finally:
        await db.close()


def recorded_kinds(story: str) -> list[str]:
    return [e["kind"] for e in fixture(f"runs/{story}.json")]


async def test_the_success_path(stack: Stack):
    started = await stack.orchestrator.start_run(SPEC, ALICE, "key-1")
    run_id = started.run_id
    await stack.engine.drain()
    assert isinstance(await stack.state(run_id), AwaitingApproval)
    assert await stack.jira.tickets() == []

    await stack.approve(run_id, Verdict.APPROVE)
    await stack.engine.drain()
    assert isinstance(await stack.state(run_id), Succeeded)
    assert [t.key for t in await stack.jira.tickets()] == ["MOCK-1"]
    assert await stack.kinds(run_id) == recorded_kinds("success")
    assert [(e.leg.value, e.status, e.steps) for e in stack.engine.executions] == [
        (
            "work",
            "success",
            [("run_agents", True, "proposed"), ("ask_approval", False, "approval_opened")],
        ),
        ("act", "success", [("write_action", True, "written")]),
    ]


async def test_the_rejected_path(stack: Stack):
    run_id = (await stack.orchestrator.start_run(SPEC, ALICE, "key-1")).run_id
    await stack.engine.drain()
    await stack.approve(run_id, Verdict.DECLINE)
    await stack.engine.drain()
    assert isinstance(await stack.state(run_id), Rejected)
    assert await stack.jira.tickets() == []
    assert [e.leg.value for e in stack.engine.executions] == ["work"]
    assert await stack.kinds(run_id) == recorded_kinds("rejected")


async def test_the_failure_then_retry_path(stack: Stack):
    stack.agent.mode = "failed"
    run_id = (await stack.orchestrator.start_run(SPEC, ALICE, "key-1")).run_id
    await stack.engine.drain()
    failed = await stack.state(run_id)
    assert isinstance(failed, Failed)
    assert await stack.kinds(run_id) == recorded_kinds("failure")
    before = len(recorded_kinds("failure"))

    stack.agent.mode = "finished"
    retried = await stack.orchestrator.retry(run_id, ALICE)
    assert isinstance(retried, Retried) and isinstance(retried.state, Pending)
    stack.clock["now"] += timedelta(seconds=3)
    await stack.engine.drain()
    assert isinstance(await stack.state(run_id), AwaitingApproval)
    await stack.approve(run_id, Verdict.APPROVE)
    await stack.engine.drain()
    assert isinstance(await stack.state(run_id), Succeeded)

    kinds = await stack.kinds(run_id)
    assert kinds[before] == "run_retried"
    assert kinds[before + 1 :] == recorded_kinds("success")[1:]
    assert [r.task_id for r in stack.agent.requests] == [f"{run_id}/work/1", f"{run_id}/work/2"]
    events = await stack.log.read_after(run_id, 0)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


async def test_the_approval_gate_holds_until_a_decision(stack: Stack):
    run_id = (await stack.orchestrator.start_run(SPEC, ALICE, "key-1")).run_id
    await stack.engine.drain()
    stack.clock["now"] += timedelta(days=1)
    await stack.engine.drain()
    assert isinstance(await stack.state(run_id), AwaitingApproval)
    assert await stack.jira.tickets() == []
    assert len(stack.engine.executions) == 1
