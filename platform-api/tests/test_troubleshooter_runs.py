"""The troubleshooter's advice after real runs, read through the route."""

from datetime import timedelta
from typing import Any, cast

import httpx
import pytest

from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.jira import JiraPort, JiraUnavailable, JiraWriteConnector
from platform_api.orchestration.runs import Acting, Failed, StepName
from platform_api.orchestration.service import Orchestrator, Retried
from platform_api.orchestration.write_actions import WriteGateway
from platform_api.shared import WRITE_STOP_ADVICE, N8nExecutionId, RunId
from tests.conftest import PostgresUrls
from tests.support import ALICE, BOB
from tests.test_monitoring_http import ALICE as HEADERS
from tests.test_monitoring_http import app_for
from tests.test_orchestrator import (
    PUBLIC_BASE_URL,
    Harness,
    mint,
    open_harness,
    work_leg_to_approval,
)

pytestmark = pytest.mark.anyio


class LossyPort:
    """Jira's REST port with the connection dropped after the 201: the ticket exists and the
    platform never hears its key."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def create_issue(self, issue: Any) -> str:
        await self.inner.create_issue(issue)
        raise JiraUnavailable("Jira could not be read: read timed out")


def gateway_for(h: Harness, connectors: list[Any]) -> Orchestrator:
    return Orchestrator(
        h.db,
        h.log,
        h.engine,
        h.teams,
        h.agent,
        WriteGateway(h.db, connectors, poll=0.05),
        mint,
        public_base_url=PUBLIC_BASE_URL,
    )


async def lost_write(h: Harness) -> RunId:
    run_id, _, approval_id = await work_leg_to_approval(h, by=ALICE)
    detail = await h.orchestrator.get_approval(approval_id, BOB)
    assert detail is not None
    await h.orchestrator.decide(approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest)
    await h.orchestrator.tick()
    lossy = gateway_for(h, [JiraWriteConnector(cast(JiraPort, LossyPort(h.jira.jira)), h.db)])
    reply = await lossy.on_step(run_id, StepName.WRITE_ACTION, N8nExecutionId("42"))
    assert reply.outcome == "failed"
    assert [t.key for t in await h.jira.tickets()] == ["MOCK-1"]
    return run_id


async def retry_to_the_write(h: Harness, run_id: RunId) -> None:
    retried = await h.orchestrator.retry(run_id, ALICE)
    assert isinstance(retried, Retried) and isinstance(retried.state, Acting)
    h.advance(timedelta(seconds=40))
    await h.orchestrator.tick()


async def troubleshoot(h: Harness, postgres: PostgresUrls, run_id: RunId) -> dict[str, Any]:
    transport = httpx.ASGITransport(app=app_for(h.log, postgres))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        got = await client.get(f"/api/v1/runs/{run_id}/troubleshoot", headers=HEADERS)
    assert got.status_code == 200, got.text
    return got.json()


async def test_a_ticket_the_platform_cannot_prove_it_made_is_not_met_with_start_a_new_run(
    postgres: PostgresUrls,
):
    async with open_harness(postgres) as h:
        run_id = await lost_write(h)
        [ticket] = await h.jira.tickets()
        await h.jira.store.set_labels(ticket.key, [*ticket.labels, "wab-run_other-prp_other-0"])
        await retry_to_the_write(h, run_id)
        reply = await h.orchestrator.on_step(run_id, StepName.WRITE_ACTION, N8nExecutionId("43"))
        state = await h.state(run_id)
        assert reply.outcome == "failed"
        assert isinstance(state, Failed) and state.stage.value == "acting"

        advice = (await troubleshoot(h, postgres, run_id))["advice"]

    assert "refused the write" in advice["likely_cause"]
    assert "can't prove it made" in advice["likely_cause"]
    assert "failure text" in advice["likely_cause"]
    suggestion = advice["suggestion"]
    assert WRITE_STOP_ADVICE in suggestion


async def test_a_denied_write_with_a_ticket_in_jira_says_to_check_jira_first(
    postgres: PostgresUrls,
):
    async with open_harness(postgres) as h:
        run_id = await lost_write(h)
        await retry_to_the_write(h, run_id)
        no_jira = gateway_for(h, [])
        reply = await no_jira.on_step(run_id, StepName.WRITE_ACTION, N8nExecutionId("43"))
        assert reply.outcome == "refused"
        got = await troubleshoot(h, postgres, run_id)

    assert got["failure"]["reason"] == "SafetyDenied"
    suggestion = got["advice"]["suggestion"]
    assert WRITE_STOP_ADVICE in suggestion
