"""The Planner is told which Jira projects the platform can see, so it can check a project the
task names before it reads the task back as understood."""

import json

import httpx
import pytest

from platform_api.db import Database, UnitOfWork
from platform_api.orchestration.agents import HttpAgentRuntime, ModelAccess
from platform_api.orchestration.planning import CardPlanning
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.write_actions import (
    MockJiraConnector,
    Proposal,
    WriteAction,
    WriteKey,
    digest,
)
from platform_api.shared import ProposalId, RunId
from tests.support import ALICE, NOW, SPEC

pytestmark = pytest.mark.anyio

RUN = RunId("run_1")
PRP = ProposalId("prp_1")
ACCESS = ModelAccess(
    style="anthropic", base_url="https://llm-gateway.example", model="m", api_key="k-not-real"
)
ROWS = {
    "status": "understood",
    "rows": [
        {"kind": kind, "text": "", "state": "missing", "note": "x"}
        for kind in ("schedule", "look_for", "do", "where")
    ],
}


class Connected:
    async def access(self, uow: UnitOfWork) -> ModelAccess | None:
        return ACCESS


def runtime(seen: list[httpx.Request]) -> HttpAgentRuntime:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ROWS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return HttpAgentRuntime("http://agent-runtime:8100", "agent-key-not-real", client=client)


async def write_ticket(db: Database, project: str) -> None:
    action = WriteAction("jira", "create_ticket", {"project": project}, {"title": "x", "body": ""})
    async with db.transaction("orchestration") as uow:
        await Store().insert_run(
            uow,
            RunRecord(RUN, SPEC, ALICE.user_id, NOW, NOW, 1, Pending(RUN, 1, None, NOW), (), None),
            "k",
        )
        await Store().insert_proposal(uow, Proposal(PRP, RUN, (action,), digest((action,))))
    await MockJiraConnector(db).execute(action, WriteKey(RUN, PRP, 0))


async def test_the_practice_jira_has_its_home_project_and_each_project_written_to(db: Database):
    jira = MockJiraConnector(db)
    assert await jira.projects() == ["MOCK"]
    await write_ticket(db, "OPS")
    assert await jira.projects() == ["MOCK", "OPS"]


async def test_the_planner_is_told_the_jira_projects_the_platform_can_see(db: Database):
    await write_ticket(db, "ACCESS")
    seen: list[httpx.Request] = []
    planning = CardPlanning(db, Connected(), runtime(seen), MockJiraConnector(db))
    await planning.understand("Every Friday find bug tickets in ACCESS")
    sent = json.loads(seen[0].content)
    assert (sent["task"], sent["jira_projects"]) == (
        "Every Friday find bug tickets in ACCESS",
        ["ACCESS", "MOCK"],
    )
