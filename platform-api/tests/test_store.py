from datetime import timedelta

import pytest
from pydantic import TypeAdapter

from platform_api.db import Database
from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
    Decision,
    OneOf,
    Verdict,
)
from platform_api.orchestration.runs import (
    Acting,
    AwaitingApproval,
    Failed,
    Failure,
    FailureReason,
    Leg,
    Outcome,
    Pending,
    Proposed,
    Rejected,
    ResumeAct,
    ResumeWork,
    RunState,
    Stage,
    Succeeded,
    Working,
    WriteDone,
)
from platform_api.orchestration.store import (
    DecisionConflict,
    RunRecord,
    Stale,
    Store,
    dump_state,
    load_state,
)
from platform_api.orchestration.write_actions import Proposal, WriteAction, digest
from platform_api.shared import ApprovalId, N8nExecutionId, ProposalId, RunId, UserId
from tests.support import ALICE, NOW, SPEC

pytestmark = pytest.mark.anyio

RUN = RunId("run_1")
PRP = ProposalId("prp_1")
APR = ApprovalId("apr_1")
EXEC = N8nExecutionId("41")
LATER = NOW + timedelta(minutes=1)

STATES: list[RunState] = [
    Pending(RUN, 1, None, NOW),
    Pending(RUN, 2, EXEC, NOW),
    Working(RUN, EXEC, 1, 2, NOW, LATER),
    Proposed(RUN, PRP, EXEC, 1, NOW),
    AwaitingApproval(RUN, PRP, APR),
    Acting(RUN, PRP, APR, 1, None, NOW),
    Acting(RUN, PRP, APR, 2, EXEC, NOW),
    Succeeded(
        RUN, Outcome.WRITTEN, (WriteDone("jira", "create_ticket", "MOCK-1", (UserId("bob"),)),)
    ),
    Succeeded(RUN, Outcome.NOTHING_TO_WRITE, ()),
    Rejected(RUN, PRP, APR, UserId("bob"), 0),
    Failed(RUN, Stage.WORKING, Failure(FailureReason.AGENT_ERROR, "down", True), ResumeWork(2)),
    Failed(
        RUN, Stage.ACTING, Failure(FailureReason.WRITE_FAILED, "slow", True), ResumeAct(PRP, APR, 2)
    ),
]


@pytest.mark.parametrize("state", STATES, ids=lambda s: type(s).__name__)
def test_every_state_survives_the_round_trip(state: RunState):
    name, data = dump_state(state)
    assert load_state(name, data) == state


PENDING = Pending(RUN, 1, None, NOW)


def record(state: RunState = PENDING) -> RunRecord:
    return RunRecord(RUN, SPEC, ALICE.user_id, NOW, NOW, 1, state, (), None)


async def test_the_same_idempotency_key_returns_the_first_run(db: Database):
    store = Store()
    async with db.transaction("orchestration") as uow:
        first, created = await store.insert_run(uow, record(), "key-1")
        second, created_again = await store.insert_run(
            uow,
            RunRecord(
                RunId("run_2"),
                SPEC,
                ALICE.user_id,
                NOW,
                NOW,
                1,
                Pending(RunId("run_2"), 1, None, NOW),
                (),
                None,
            ),
            "key-1",
        )
    assert (created, created_again) == (True, False)
    assert second.run_id == first.run_id == RUN


async def test_save_is_compare_and_swap_on_version(db: Database):
    store = Store()
    async with db.transaction("orchestration") as uow:
        stored, _ = await store.insert_run(uow, record(), "key-1")
        saved = await store.save_run(uow, stored, Working(RUN, EXEC, 1, 1, NOW, LATER))
        assert saved.version == 2
        with pytest.raises(Stale):
            await store.save_run(uow, stored, Proposed(RUN, PRP, EXEC, 1, NOW))
    async with db.transaction("orchestration") as uow:
        loaded = await store.load_run(uow, RUN)
    assert loaded is not None
    assert loaded.state == Working(RUN, EXEC, 1, 1, NOW, LATER)
    assert loaded.spec == SPEC


async def test_a_second_decision_on_one_step_conflicts(db: Database):
    store = Store()
    policy = ApprovalPolicy(
        (
            ApprovalStep("Team approver", AnyApprover()),
            ApprovalStep("Owner", OneOf(frozenset({UserId("carol")}))),
        )
    )
    action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "t"})
    proposal = Proposal(PRP, RUN, (action,), digest((action,)))
    request = ApprovalRequest(APR, RUN, PRP, proposal.digest, policy, frozenset({UserId("alice")}))
    async with db.transaction("orchestration") as uow:
        await store.insert_run(uow, record(), "k1")
        await store.insert_proposal(uow, proposal)
        await store.insert_approval(uow, request)
        assert await store.load_approval(uow, APR) == request
        assert await store.load_proposal(uow, PRP) == proposal
        bob = Decision(APR, 0, UserId("bob"), Verdict.APPROVE, proposal.digest, NOW)
        await store.insert_decision(uow, bob)
    async with db.transaction("orchestration") as uow:
        with pytest.raises(DecisionConflict):
            await store.insert_decision(
                uow, Decision(APR, 0, UserId("carol"), Verdict.DECLINE, proposal.digest, LATER)
            )
    async with db.transaction("orchestration") as uow:
        assert await store.load_decisions(uow, APR) == (bob,)


async def test_outbox_rows_wait_retry_and_cancel(db: Database):
    store = Store()
    async with db.transaction("orchestration") as uow:
        await store.insert_run(uow, record(), "k1")
        await store.enqueue(uow, RUN, "start_leg", {"leg": "work"}, NOW)
        await store.enqueue(uow, RUN, "start_leg", {"leg": "work"}, LATER)
        due = await store.take_due_outbox(uow, NOW)
        assert [r.payload for r in due] == [{"leg": "work"}]
        await store.outbox_retry(uow, due[0].id, LATER, "n8n refused the connection")
        assert await store.take_due_outbox(uow, NOW) == []
        retried = await store.take_due_outbox(uow, LATER)
        assert [(r.attempt) for r in retried] == [1, 0]
        await store.cancel_outbox(uow, RUN)
        assert await store.take_due_outbox(uow, LATER + timedelta(days=1)) == []
        assert await store.pending_outbox(uow, RUN) == 0


async def test_leg_attempts_map_an_execution_back_to_its_run(db: Database):
    store = Store()
    async with db.transaction("orchestration") as uow:
        await store.insert_run(uow, record(), "k1")
        await store.record_leg_attempt(uow, RUN, Leg.WORK, 1, None)
        assert await store.run_for_execution(uow, EXEC) is None
        await store.record_leg_attempt(uow, RUN, Leg.WORK, 1, EXEC)
        await store.record_leg_attempt(uow, RUN, Leg.WORK, 1, N8nExecutionId("99"))
        assert await store.run_for_execution(uow, EXEC) == RUN
        assert await store.run_for_execution(uow, N8nExecutionId("99")) is None


async def test_runs_past_deadline_lists_only_active_overdue_runs(db: Database):
    store = Store()
    async with db.transaction("orchestration") as uow:
        first, _ = await store.insert_run(uow, record(Pending(RUN, 1, None, NOW)), "k1")
        waiting = RunRecord(
            RunId("run_2"),
            SPEC,
            ALICE.user_id,
            NOW,
            NOW,
            1,
            AwaitingApproval(RunId("run_2"), PRP, APR),
            (),
            None,
        )
        await store.insert_run(uow, waiting, "k2")
        assert await store.runs_past_deadline(uow, NOW - timedelta(seconds=1)) == []
        assert await store.runs_past_deadline(uow, NOW) == [RUN]
        await store.save_run(uow, first, Succeeded(RUN, Outcome.NOTHING_TO_WRITE, ()))
        assert await store.runs_past_deadline(uow, NOW + timedelta(days=1)) == []


def test_policies_with_either_eligibility_survive_the_round_trip():
    policy = ApprovalPolicy(
        (
            ApprovalStep("Team approver", AnyApprover()),
            ApprovalStep("Owner", OneOf(frozenset({UserId("carol")}))),
        )
    )
    adapter = TypeAdapter(ApprovalPolicy)
    assert adapter.validate_python(adapter.dump_python(policy, mode="json")) == policy


async def test_a_lease_renews_only_while_it_is_still_this_ticks(db: Database):
    store = Store()
    async with db.transaction("orchestration") as uow:
        await store.insert_run(uow, record(), "k1")
        await store.enqueue(uow, RUN, "announce", {"approval_id": "apr_1"}, NOW)
        [row] = await store.take_due_outbox(uow, NOW, timedelta(minutes=1))
        assert row.leased_until == NOW + timedelta(minutes=1)
        renewed = await store.renew_lease(uow, row, NOW + timedelta(minutes=2))
        assert renewed is not None and renewed.leased_until == NOW + timedelta(minutes=2)
        # Another replica took the row after this tick's lease ran out, so its lease is not ours.
        await uow.conn.execute(
            "UPDATE orchestration.outbox SET leased_until = %s WHERE id = %s",
            (NOW + timedelta(minutes=5), row.id),
        )
        assert await store.renew_lease(uow, renewed, NOW + timedelta(minutes=3)) is None
