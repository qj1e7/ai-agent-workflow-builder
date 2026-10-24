import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from platform_api.db import Database
from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
    Decision,
    Verdict,
)
from platform_api.orchestration.runs import Acting, Pending, WriteDone
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.write_actions import (
    AuthorizedWrite,
    MockJiraConnector,
    Proposal,
    WriteAction,
    WriteFailed,
    WriteGateway,
    WriteKey,
    check,
    digest,
    registry_of,
)
from platform_api.shared import ApprovalId, ProposalId, RunId, UserId
from tests.conftest import PostgresUrls
from tests.support import ALICE, NOW, SPEC

pytestmark = pytest.mark.anyio

RUN = RunId("run_1")
PRP = ProposalId("prp_1")
APR = ApprovalId("apr_1")
BOB = UserId("bob")
ACTION = WriteAction(
    "jira", "create_ticket", {"project": "MOCK"}, {"title": "New releases", "body": "..."}
)
PROPOSAL = Proposal(PRP, RUN, (ACTION,), digest((ACTION,)))
REQUEST = ApprovalRequest(
    APR,
    RUN,
    PRP,
    PROPOSAL.digest,
    ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
    frozenset({ALICE.user_id}),
)
APPROVED = (Decision(APR, 0, BOB, Verdict.APPROVE, PROPOSAL.digest, NOW),)
ACTING = Acting(RUN, PRP, APR, 1, None, NOW)


class BlockingConnector:
    name = "jira"
    operations = frozenset({"create_ticket"})

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.release = asyncio.Event()
        self.fail_first = False

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        self.calls.append(key.text)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("Jira is down")
        await self.release.wait()
        return f"MOCK-{len(self.calls)}"


def authorized(connector: BlockingConnector | MockJiraConnector) -> AuthorizedWrite:
    verdict = check(ACTING, PROPOSAL, REQUEST, APPROVED, registry_of([connector]))
    assert isinstance(verdict, AuthorizedWrite)
    return verdict


async def seed_run(db: Database) -> None:
    async with db.transaction("orchestration") as uow:
        await Store().insert_run(
            uow,
            RunRecord(RUN, SPEC, ALICE.user_id, NOW, NOW, 1, Pending(RUN, 1, None, NOW), (), None),
            "k",
        )
        await Store().insert_proposal(uow, PROPOSAL)


async def test_a_retry_during_a_slow_write_holds_and_returns_the_same_ticket(db: Database):
    await seed_run(db)
    connector = BlockingConnector()
    gateway = WriteGateway(db, [connector], poll=0.05)
    write = authorized(connector)
    first = asyncio.create_task(gateway.execute(write))
    await asyncio.sleep(0.2)
    second = asyncio.create_task(gateway.execute(write))
    await asyncio.sleep(0.2)
    assert not first.done() and not second.done()
    connector.release.set()
    results = await asyncio.gather(first, second)
    assert results[0] == results[1] == (WriteDone("jira", "create_ticket", "MOCK-1", (BOB,)),)
    assert connector.calls == [f"{RUN}/{PRP}/0"]


async def test_a_stale_started_row_is_called_again_with_the_same_key(postgres: PostgresUrls):
    clock = {"now": NOW}
    db = Database(postgres.contexts, clock=lambda: clock["now"])
    await db.open()
    try:
        from tests.conftest import truncate_all

        truncate_all(postgres.owner)
        await seed_run(db)
        connector = BlockingConnector()
        connector.fail_first = True
        connector.release.set()
        gateway = WriteGateway(db, [connector], poll=0.05)
        write = authorized(connector)
        with pytest.raises(WriteFailed):
            await gateway.execute(write)
        clock["now"] = NOW + timedelta(seconds=31)
        done = await gateway.execute(write)
        assert done[0].external_reference == "MOCK-2"
        assert connector.calls == [f"{RUN}/{PRP}/0"] * 2
    finally:
        await db.close()


async def test_a_done_row_is_returned_without_calling_the_connector(db: Database):
    await seed_run(db)
    connector = BlockingConnector()
    connector.release.set()
    gateway = WriteGateway(db, [connector], poll=0.05)
    write = authorized(connector)
    first = await gateway.execute(write)
    second = await gateway.execute(write)
    assert first == second
    assert len(connector.calls) == 1


async def test_mock_jira_makes_one_ticket_per_idempotency_key(db: Database):
    await seed_run(db)
    jira = MockJiraConnector(db)
    key = WriteKey(RUN, PRP, 0)
    assert await jira.execute(ACTION, key) == "MOCK-1"
    assert await jira.execute(ACTION, key) == "MOCK-1"
    assert await jira.execute(ACTION, WriteKey(RUN, PRP, 1)) == "MOCK-2"
    tickets = await jira.tickets()
    assert [(t.key, t.title, t.run_id, t.proposal_id) for t in tickets] == [
        ("MOCK-1", "New releases", RUN, PRP),
        ("MOCK-2", "New releases", RUN, PRP),
    ]
    assert tickets[0].created_at.tzinfo is not None
    assert tickets[0].created_at <= datetime.now(UTC)


async def test_mock_jira_tickets_start_as_to_do_and_mark_done_is_idempotent(db: Database):
    await seed_run(db)
    jira = MockJiraConnector(db)
    await jira.execute(ACTION, WriteKey(RUN, PRP, 0))
    [ticket] = await jira.tickets()
    assert (ticket.status, ticket.done_at) == ("To Do", None)
    assert await jira.done_tickets(["MOCK-1"]) == {}
    done = await jira.mark_done("MOCK-1")
    assert done is not None and done.status == "Done" and done.done_at is not None
    assert await jira.mark_done("MOCK-1") == done
    assert await jira.done_tickets(["MOCK-1", "MOCK-9"]) == {"MOCK-1": done.done_at}
    assert await jira.done_tickets([]) == {}
    assert await jira.mark_done("MOCK-9") is None
