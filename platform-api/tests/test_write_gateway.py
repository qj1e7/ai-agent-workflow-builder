import asyncio
from dataclasses import replace
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
from platform_api.orchestration.jira import PRACTICE_SITE
from platform_api.orchestration.runs import Acting, Pending, WriteDone
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.write_actions import (
    NOT_TRIED,
    AuthorizedWrite,
    Made,
    MadeBefore,
    NotMade,
    Proposal,
    WriteAction,
    WriteGateway,
    WriteKey,
    WritingRun,
    check,
    digest,
    registry_of,
    sites_of,
    subject_key,
)
from platform_api.shared import ApprovalId, ProposalId, RunId, UserId
from tests.conftest import PostgresUrls
from tests.practice import PracticeKit
from tests.support import ALICE, NOW, SPEC

pytestmark = pytest.mark.anyio

RUN = RunId("run_1")
PRP = ProposalId("prp_1")
APR = ApprovalId("apr_1")
BOB = UserId("bob")
ACTION = WriteAction(
    "jira",
    "create_ticket",
    {"project": "MOCK", "site": "practice"},
    {"title": "New releases", "body": "..."},
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
RACE_LIMIT = 20.0
"""Seconds a test of tries running together may take, so a claim that never settles fails in
seconds instead of hanging CI."""


class BlockingConnector:
    name = "jira"
    operations = frozenset({"create_ticket"})
    site = PRACTICE_SITE

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

    def link(self, reference: str) -> str | None:
        return None


THE_RUN = WritingRun(SPEC.use_case_id, test=False)


def authorized(
    connector: BlockingConnector | PracticeKit | FlakyConnector, proposal: Proposal = PROPOSAL
) -> AuthorizedWrite:
    acting = Acting(proposal.run_id, proposal.id, APR, 1, None, NOW)
    request = ApprovalRequest(
        APR, proposal.run_id, proposal.id, proposal.digest, REQUEST.policy, REQUEST.parties
    )
    decisions = (Decision(APR, 0, BOB, Verdict.APPROVE, proposal.digest, NOW),)
    registry, sites = registry_of([connector]), sites_of([connector])
    verdict = check(acting, THE_RUN, proposal, request, decisions, registry, sites)
    assert isinstance(verdict, AuthorizedWrite)
    return verdict


async def seed_run(db: Database, proposal: Proposal = PROPOSAL) -> None:
    run_id = proposal.run_id
    record = RunRecord(
        run_id, SPEC, ALICE.user_id, NOW, NOW, 1, Pending(run_id, 1, None, NOW), (), None
    )
    async with db.transaction("orchestration") as uow:
        await Store().insert_run(uow, record, f"k-{run_id}")
        await Store().insert_proposal(uow, proposal)


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
    results = await asyncio.wait_for(asyncio.gather(first, second), RACE_LIMIT)
    written = (WriteDone("jira", "create_ticket", "MOCK-1", (BOB,)),)
    assert results[0].written == results[1].written == written
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
        failed = await gateway.execute(write)
        assert failed.failure is not None and failed.failure.retryable
        clock["now"] = NOW + timedelta(seconds=31)
        done = await gateway.execute(write)
        assert done.written[0].external_reference == "MOCK-2"
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
    assert first.written == second.written
    assert (first.fresh, second.fresh) == (first.written, ())
    assert len(connector.calls) == 1


async def test_mock_jira_makes_one_ticket_per_idempotency_key(db: Database):
    await seed_run(db)
    jira = PracticeKit(db)
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
    jira = PracticeKit(db)
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


async def test_a_write_jira_refuses_fails_for_good_and_one_it_cannot_reach_may_be_retried(
    db: Database,
):
    await seed_run(db)
    jira = PracticeKit(db)
    gateway = WriteGateway(db, [jira])
    refused = WriteAction(
        "jira", "create_ticket", {"project": "MOCK", "site": "practice"}, {"title": "", "body": ""}
    )
    proposal = Proposal(PRP, RUN, (refused,), digest((refused,)))
    request = ApprovalRequest(
        APR, RUN, PRP, proposal.digest, REQUEST.policy, frozenset({ALICE.user_id})
    )
    decisions = (Decision(APR, 0, BOB, Verdict.APPROVE, proposal.digest, NOW),)
    registry, sites = registry_of([jira]), sites_of([jira])
    write = check(ACTING, THE_RUN, proposal, request, decisions, registry, sites)
    assert isinstance(write, AuthorizedWrite)
    refused = (await gateway.execute(write)).failure
    assert refused is not None and refused.retryable is False
    assert "summary" in refused.message

    jira.store.fail_next(503, times=3)
    gateway = WriteGateway(db, [jira], connector_timeout=timedelta(0))
    down = (await gateway.execute(authorized(jira))).failure
    assert down is not None and down.retryable is True


async def test_each_written_ticket_says_where_people_open_it(db: Database):
    await seed_run(db)
    jira = PracticeKit(db)
    [done] = (await WriteGateway(db, [jira]).execute(authorized(jira))).written
    assert (done.external_reference, done.url) == ("MOCK-1", "/jira/MOCK-1")
    assert BlockingConnector().link("MOCK-9") is None


async def test_two_gateways_racing_on_one_write_make_one_ticket(db: Database):
    await seed_run(db)
    jira = PracticeKit(db)
    write = authorized(jira)
    first, second = await asyncio.wait_for(
        asyncio.gather(
            WriteGateway(db, [jira], poll=0.05).execute(write),
            WriteGateway(db, [jira], poll=0.05).execute(write),
        ),
        RACE_LIMIT,
    )
    assert first.written == second.written
    assert [t.key for t in await jira.tickets()] == ["MOCK-1"]


async def test_a_claim_that_meets_the_other_unique_key_says_someone_else_holds_it(db: Database):
    # write_executions has two unique keys, and ON CONFLICT names only idempotency_key. A row
    # that holds this write's (proposal_id, action_index) under another idempotency key is the
    # same collision that two tries inserting at once can meet, made certain.
    await seed_run(db)
    async with db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "INSERT INTO orchestration.write_executions "
            "(proposal_id, action_index, run_id, idempotency_key, status, started_at) "
            "VALUES (%s, 0, %s, 'held-by-another-try', 'started', %s)",
            (PRP, RUN, uow.now),
        )
    gateway = WriteGateway(db, [BlockingConnector()])
    assert await asyncio.wait_for(gateway._claim(WriteKey(RUN, PRP, 0)), RACE_LIMIT) is False


@pytest.mark.parametrize("race", range(10))
async def test_five_gateways_racing_on_one_write_call_the_connector_once(db: Database, race: int):
    await seed_run(db)
    connector = BlockingConnector()
    connector.release.set()
    write = authorized(connector)
    gateways = [WriteGateway(db, [connector], poll=0.02) for _ in range(5)]
    results = await asyncio.wait_for(
        asyncio.gather(*(gateway.execute(write) for gateway in gateways)), RACE_LIMIT
    )
    assert all(result.written == results[0].written for result in results)
    assert connector.calls == [f"{RUN}/{PRP}/0"]


class FlakyConnector:
    """Makes a ticket per write key, and fails each title in `down` while it is there."""

    name = "jira"
    operations = frozenset({"create_ticket"})
    site = PRACTICE_SITE

    def __init__(self) -> None:
        self.made: dict[str, str] = {}
        self.down: set[str] = set()

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        if action.fields["title"] in self.down:
            raise RuntimeError("Jira is down")
        return self.made.setdefault(key.text, f"MOCK-{len(self.made) + 1}")

    def link(self, reference: str) -> str | None:
        return None


def three(run_id: RunId, proposal_id: ProposalId, subject: str | None = None) -> Proposal:
    actions = tuple(replace(ACTION, fields={"title": title, "body": ""}) for title in "ABC")
    if subject is not None:
        actions = (replace(actions[0], subject=subject), *actions[1:])
    return Proposal(proposal_id, run_id, actions, digest(actions))


async def test_a_part_done_proposal_says_so_and_a_retry_makes_only_the_rest(db: Database):
    proposal = three(RUN, PRP)
    await seed_run(db, proposal)
    connector = FlakyConnector()
    connector.down = {"B"}
    gateway = WriteGateway(db, [connector])
    first = await gateway.execute(authorized(connector, proposal))
    assert first.made == 1 and first.failure is not None and first.failure.retryable
    assert [type(result) for result in first.results] == [Made, NotMade, NotMade]
    assert first.results[2] == NotMade(proposal.actions[2], NOT_TRIED)

    connector.down = set()
    # The failed try released its claim, so the retry needs no wait for the in-flight timeout.
    again = await asyncio.wait_for(gateway.execute(authorized(connector, proposal)), RACE_LIMIT)
    assert (again.made, again.failure) == (3, None)
    assert [done.external_reference for done in again.written] == ["MOCK-1", "MOCK-2", "MOCK-3"]
    assert [done.external_reference for done in again.fresh] == ["MOCK-2", "MOCK-3"]
    assert len(connector.made) == 3


async def test_safety_a_subject_made_by_one_run_is_never_made_again_by_another(db: Database):
    first, second = three(RUN, PRP, "langgraph 1.2.16"), three(RunId("run_2"), ProposalId("prp_2"))
    second = replace(second, actions=(replace(second.actions[0], subject="langgraph 1.2.16"),))
    second = replace(second, digest=digest(second.actions))
    await seed_run(db, first)
    await seed_run(db, second)
    connector = FlakyConnector()
    gateway = WriteGateway(db, [connector])
    await gateway.execute(authorized(connector, first))
    carried = await gateway.execute(authorized(connector, second))
    assert carried.results == (MadeBefore(second.actions[0], "MOCK-1", None, RUN),)
    assert (carried.made, carried.written, carried.failure) == (1, (), None)
    assert list(connector.made) == [
        subject_key(SPEC.use_case_id, "langgraph 1.2.16"),
        f"{RUN}/{PRP}/1",
        f"{RUN}/{PRP}/2",
    ]
