from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import pytest

from platform_api.monitoring import ActionLine, user_actor
from platform_api.orchestration.runs import (
    CALLBACK_LIFETIME,
    DEADLINES,
    LEG_STEPS,
    REFEREE_TABLE,
    ROOM_LEAD,
    STEP_LEG,
    Acting,
    AwaitingApproval,
    Begin,
    Caller,
    Failed,
    Failure,
    FailureReason,
    Leg,
    Outcome,
    Pending,
    Proposed,
    Refuse,
    Rejected,
    Replay,
    ResumeAct,
    ResumeWork,
    RunState,
    Stage,
    StepName,
    Succeeded,
    Supersede,
    Verdict,
    Working,
    WriteDone,
    created_events,
    referee,
)
from platform_api.shared import ApprovalId, Digest, N8nExecutionId, ProposalId, RunId, UserId
from platform_api.wire import ApprovalStepView

RUN = RunId("run_1")
PROPOSAL = ProposalId("prp_1")
APPROVAL = ApprovalId("apr_1")
HOLDER = N8nExecutionId("41")
OTHER = N8nExecutionId("42")
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
AGENT_DOWN = Failure(FailureReason.AGENT_ERROR, "GitHub was unavailable", retryable=True)
WRITE_DOWN = Failure(FailureReason.WRITE_FAILED, "Jira timed out", retryable=True)
ALICE = user_actor(UserId("alice"), "Alice")
TICKET = WriteDone("jira", "create_ticket", "MOCK-1", (UserId("bob"),))

PENDING_UNCLAIMED = Pending(RUN, 1, None, NOW)
PENDING = Pending(RUN, 1, HOLDER, NOW)
WORKING = Working(RUN, HOLDER, 1, 1, NOW, NOW)
PROPOSED = Proposed(RUN, PROPOSAL, HOLDER, 1, NOW)
AWAITING = AwaitingApproval(RUN, PROPOSAL, APPROVAL)
ACTING_UNCLAIMED = Acting(RUN, PROPOSAL, APPROVAL, 1, None, NOW)
ACTING = Acting(RUN, PROPOSAL, APPROVAL, 1, HOLDER, NOW)
WRITTEN = Succeeded(RUN, Outcome.WRITTEN, (TICKET,))
NOTHING_WRITTEN = Succeeded(RUN, Outcome.NOTHING_TO_WRITE, ())
REJECTED = Rejected(RUN, PROPOSAL, APPROVAL, UserId("bob"), 0)
FAILED = Failed(RUN, Stage.WORKING, AGENT_DOWN, ResumeWork(2))

STOP = Replay(False)
GO_ON = Replay(True)
SUPERSEDED = Supersede(HOLDER)
REFUSED = Refuse(fails_run=False)
REFUSED_AND_FAILED = Refuse(fails_run=True)


class Row(NamedTuple):
    name: str
    state: RunState
    caller: N8nExecutionId
    run_agents: Verdict
    ask_approval: Verdict
    write_action: Verdict


TABLE = [
    Row("failed, any caller", FAILED, OTHER, STOP, STOP, STOP),
    Row("rejected, any caller", REJECTED, OTHER, STOP, STOP, STOP),
    Row("pending unclaimed", PENDING_UNCLAIMED, OTHER, Begin(), REFUSED, REFUSED),
    Row("pending, the claimant", PENDING, HOLDER, Begin(), REFUSED_AND_FAILED, REFUSED_AND_FAILED),
    Row("pending, another execution", PENDING, OTHER, SUPERSEDED, REFUSED, REFUSED),
    Row("working, the claimant", WORKING, HOLDER, Begin(), REFUSED_AND_FAILED, REFUSED_AND_FAILED),
    Row("working, another execution", WORKING, OTHER, SUPERSEDED, SUPERSEDED, REFUSED),
    Row("proposed, the claimant", PROPOSED, HOLDER, GO_ON, Begin(), REFUSED_AND_FAILED),
    Row("proposed, another execution", PROPOSED, OTHER, SUPERSEDED, SUPERSEDED, REFUSED),
    Row("awaiting approval, any caller", AWAITING, HOLDER, STOP, STOP, REFUSED),
    Row("acting unclaimed", ACTING_UNCLAIMED, OTHER, STOP, STOP, Begin()),
    Row("acting, the claimant", ACTING, HOLDER, STOP, STOP, Begin()),
    Row("acting, another execution", ACTING, OTHER, STOP, STOP, SUPERSEDED),
    Row("succeeded after a write", WRITTEN, HOLDER, STOP, STOP, STOP),
    Row("succeeded with nothing written", NOTHING_WRITTEN, HOLDER, STOP, STOP, REFUSED),
]


@pytest.mark.parametrize(
    ("state", "caller", "step", "expected"),
    [
        pytest.param(row.state, row.caller, step, expected, id=f"{row.name}: {step.value}")
        for row in TABLE
        for step, expected in zip(StepName, row[3:], strict=True)
    ],
)
def test_referee(state: RunState, caller: N8nExecutionId, step: StepName, expected: Verdict):
    assert referee(state, step, caller) == expected


def test_referee_table_covers_every_step_and_state():
    states = (
        PENDING,
        WORKING,
        PROPOSED,
        AWAITING,
        ACTING,
        WRITTEN,
        NOTHING_WRITTEN,
        REJECTED,
        FAILED,
    )
    for state in states:
        for step in StepName:
            for caller in (HOLDER, OTHER):
                referee(state, step, caller)


def test_a_superseded_call_in_proposed_matches_one_row_only():
    matching = [
        row for row in REFEREE_TABLE if row.matches(PROPOSED, StepName.RUN_AGENTS, Caller.OTHER)
    ]
    assert len(matching) == 1


def kinds(events) -> list[str]:
    return [e.kind for e in events]


def test_start_emits_created_then_dispatched():
    events = created_events("uc_1", 1, "LangGraph releases", ALICE, 1)
    assert kinds(events) == ["run_created", "leg_dispatched"]
    assert events[0].actor == ALICE
    assert events[1].data.model_dump() == {"leg": "work", "attempt": 1}


@pytest.mark.parametrize(
    "moved_events",
    [created_events("uc_1", 1, "LangGraph releases", ALICE, 1)[1:], AWAITING.approve(NOW).events],
)
def test_dispatched_summary_says_queued_because_the_engine_has_not_been_called_yet(moved_events):
    [dispatched] = moved_events
    assert dispatched.kind == "leg_dispatched"
    assert "queued" in dispatched.summary
    assert "sent" not in dispatched.summary


def test_pending_begins_work_with_the_working_deadline():
    moved = PENDING_UNCLAIMED.begin_work(HOLDER, NOW)
    assert moved.state == Working(
        RUN, HOLDER, 1, 1, NOW + DEADLINES[Working], NOW + CALLBACK_LIFETIME
    )
    assert moved.state.task_id == "run_1/work/1"
    assert kinds(moved.events) == ["step_started"]
    assert moved.events[0].data.model_dump() == {
        "step": "run_agents",
        "n8n_execution_id": "41",
        "try_number": 1,
    }


def test_working_retries_the_step_on_the_same_execution():
    moved = WORKING.retry_step()
    assert moved.state == Working(RUN, HOLDER, 1, 2, NOW, NOW)
    assert moved.state.task_id == WORKING.task_id
    assert kinds(moved.events) == ["step_retried"]
    assert moved.events[0].data.model_dump()["try_number"] == 2


def test_working_proposes_then_finishes_the_step():
    line = ActionLine(connector="jira", operation="create_ticket", line="Create Jira ticket")
    moved = WORKING.propose(PROPOSAL, Digest("sha256:x"), (line,), ROOM_LEAD, "2 new releases", NOW)
    assert moved.state == Proposed(RUN, PROPOSAL, HOLDER, 1, NOW + DEADLINES[Proposed])
    assert kinds(moved.events) == ["write_action_proposed", "step_finished"]
    assert moved.events[0].actor == ROOM_LEAD
    assert moved.events[1].data.model_dump()["outcome"] == "proposed"


def test_working_with_nothing_to_write_succeeds():
    moved = WORKING.finish_with_nothing_to_write("No new releases since 1.2.16")
    assert moved.state == NOTHING_WRITTEN
    assert kinds(moved.events) == ["step_finished", "run_succeeded"]
    assert moved.events[0].data.model_dump()["outcome"] == "nothing_to_write"
    assert moved.events[1].data.model_dump() == {"outcome": "nothing_to_write"}


def test_proposed_opens_the_approval_and_ends_the_work_leg():
    step = ApprovalStepView(index=0, label="Team approver", status="open")
    moved = PROPOSED.open_approval(APPROVAL, [step], "/approvals/apr_1")
    assert moved.state == AWAITING
    assert kinds(moved.events) == ["step_started", "approval_requested", "step_finished"]
    assert moved.events[2].data.model_dump()["outcome"] == "approval_opened"


def test_approval_moves_to_acting_and_dispatches_the_act_leg():
    moved = AWAITING.approve(NOW)
    assert moved.state == Acting(RUN, PROPOSAL, APPROVAL, 1, None, NOW + DEADLINES[Acting])
    assert kinds(moved.events) == ["leg_dispatched"]
    assert moved.events[0].data.model_dump() == {"leg": "act", "attempt": 1}


def test_rejection_ends_the_run():
    moved = AWAITING.reject(UserId("bob"), "Bob", 0)
    assert moved.state == REJECTED
    assert kinds(moved.events) == ["run_rejected"]
    assert moved.events[0].data.model_dump() == {"by": "bob", "step": 0}


def test_acting_claims_the_act_leg_then_succeeds():
    claimed = ACTING_UNCLAIMED.begin_write(HOLDER)
    assert claimed.state == ACTING
    assert kinds(claimed.events) == ["step_started"]
    moved = claimed.state.succeed(HOLDER, (TICKET,), "Created MOCK-1")
    assert moved.state == WRITTEN
    assert kinds(moved.events) == ["write_action_done", "step_finished", "run_succeeded"]
    assert moved.events[0].data.model_dump()["approved_by"] == ["bob"]
    assert moved.events[2].data.model_dump() == {"outcome": "written"}


@pytest.mark.parametrize(
    ("state", "stage", "resume"),
    [
        pytest.param(PENDING, Stage.PENDING, ResumeWork(2), id="pending"),
        pytest.param(WORKING, Stage.WORKING, ResumeWork(2), id="working"),
        pytest.param(PROPOSED, Stage.PROPOSED, ResumeWork(2), id="proposed"),
        pytest.param(ACTING, Stage.ACTING, ResumeAct(PROPOSAL, APPROVAL, 2), id="acting"),
    ],
)
def test_failing_keeps_where_to_resume(state, stage, resume):
    moved = state.fail(AGENT_DOWN)
    assert moved.state == Failed(RUN, stage, AGENT_DOWN, resume)
    assert kinds(moved.events) == ["run_failed"]
    assert moved.events[0].data.model_dump() == {
        "stage": stage.value,
        "reason": "AgentError",
        "retryable": True,
        "message": "GitHub was unavailable",
    }


def test_retry_after_a_work_leg_failure_starts_the_work_leg_again():
    moved = FAILED.retry(ALICE, LATER)
    assert isinstance(moved.state, Pending)
    assert moved.state == Pending(RUN, 2, None, LATER + DEADLINES[Pending])
    fresh = moved.state.begin_work(OTHER, LATER).state
    assert fresh.task_id == "run_1/work/2"
    assert fresh.task_id != WORKING.task_id
    assert kinds(moved.events) == ["run_retried", "leg_dispatched"]
    assert moved.events[0].actor == ALICE
    assert moved.events[1].data.model_dump() == {"leg": "work", "attempt": 2}


def test_retry_after_an_act_leg_failure_keeps_the_approval():
    failed = ACTING.fail(WRITE_DOWN).state
    moved = failed.retry(ALICE, LATER)
    assert moved.state == Acting(RUN, PROPOSAL, APPROVAL, 2, None, LATER + DEADLINES[Acting])
    assert moved.events[1].data.model_dump() == {"leg": "act", "attempt": 2}


def test_deadlines_cover_the_retry_budgets_in_the_design():
    expected = {
        Pending: timedelta(minutes=4),
        Working: timedelta(minutes=8),
        Proposed: timedelta(minutes=3),
        Acting: timedelta(minutes=8),
    }
    assert expected == DEADLINES


def test_each_step_belongs_to_one_leg():
    assert LEG_STEPS[Leg.WORK] == (StepName.RUN_AGENTS, StepName.ASK_APPROVAL)
    assert LEG_STEPS[Leg.ACT] == (StepName.WRITE_ACTION,)
    assert set(STEP_LEG) == set(StepName)
