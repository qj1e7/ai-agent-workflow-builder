from datetime import UTC, datetime

import pytest

from platform_api.orchestration.approvals import (
    AlreadyRecorded,
    AnyApprover,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
    Approved,
    Decision,
    DecisionFault,
    Declined,
    Invalid,
    OneOf,
    Open,
    Recorded,
    Refusal,
    Refused,
    Verdict,
    approval_status,
    decide,
)
from platform_api.shared import ApprovalId, Digest, Principal, ProposalId, Role, RunId, UserId

ALICE = UserId("alice")
BOB = UserId("bob")
CAROL = UserId("carol")
APPROVAL = ApprovalId("apr_1")
DIGEST = Digest("sha256:9f2c")
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 20, 9, 5, tzinfo=UTC)
APPROVER = frozenset({Role.APPROVER})

ONE_STEP = ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),))
TWO_STEPS = ApprovalPolicy(
    (
        ApprovalStep("Team approver", AnyApprover()),
        ApprovalStep("Access owner", OneOf(frozenset({CAROL}))),
    )
)


def request(policy: ApprovalPolicy = ONE_STEP) -> ApprovalRequest:
    return ApprovalRequest(
        id=APPROVAL,
        run_id=RunId("run_1"),
        proposal_id=ProposalId("prp_1"),
        digest=DIGEST,
        policy=policy,
        parties=frozenset({ALICE}),
    )


def decision(
    step: int,
    by: UserId,
    verdict: Verdict = Verdict.APPROVE,
    approval_id: ApprovalId = APPROVAL,
    seen: Digest = DIGEST,
    at: datetime = NOW,
) -> Decision:
    return Decision(approval_id, step, by, verdict, seen, at)


STALE = decision(0, BOB, seen=Digest("sha256:old"))
CONFLICT_A = decision(0, BOB)
CONFLICT_B = decision(0, CAROL, Verdict.DECLINE, at=LATER)
BY_A_PARTY = decision(0, ALICE)
TWICE = (decision(0, BOB), decision(1, BOB))


def test_policy_rejects_no_steps():
    with pytest.raises(ValueError):
        ApprovalPolicy(())


@pytest.mark.parametrize(
    ("policy", "decisions", "expected"),
    [
        pytest.param(ONE_STEP, (), Open(0), id="no decisions is open at step 0"),
        pytest.param(ONE_STEP, (decision(0, BOB),), Approved((BOB,)), id="one step approved"),
        pytest.param(
            ONE_STEP,
            (decision(0, BOB, Verdict.DECLINE),),
            Declined(BOB, 0),
            id="one step declined",
        ),
        pytest.param(
            TWO_STEPS,
            (decision(0, BOB),),
            Open(1),
            id="two steps with only step 0 approved is still open",
        ),
        pytest.param(
            TWO_STEPS,
            (decision(0, BOB), decision(1, CAROL)),
            Approved((BOB, CAROL)),
            id="two steps both approved",
        ),
        pytest.param(
            TWO_STEPS,
            (decision(0, BOB), decision(1, CAROL, Verdict.DECLINE)),
            Declined(CAROL, 1),
            id="two steps declined at step 1",
        ),
        pytest.param(
            ONE_STEP,
            (decision(0, BOB, approval_id=ApprovalId("apr_other")),),
            Open(0),
            id="a decision on another approval does not count",
        ),
        pytest.param(
            ONE_STEP,
            (STALE,),
            Invalid(DecisionFault.STALE_DIGEST),
            id="a stored decision with another digest never counts",
        ),
        pytest.param(
            ONE_STEP,
            (CONFLICT_A, CONFLICT_B),
            Invalid(DecisionFault.CONFLICTING_DECISIONS),
            id="two different decisions on one step, approve first",
        ),
        pytest.param(
            ONE_STEP,
            (CONFLICT_B, CONFLICT_A),
            Invalid(DecisionFault.CONFLICTING_DECISIONS),
            id="two different decisions on one step, decline first",
        ),
        pytest.param(
            ONE_STEP,
            (CONFLICT_A, CONFLICT_A),
            Approved((BOB,)),
            id="an identical duplicate counts once",
        ),
        pytest.param(
            ONE_STEP,
            (BY_A_PARTY,),
            Invalid(DecisionFault.OWN_WORK),
            id="a decision by a party to the run never counts",
        ),
        pytest.param(
            TWO_STEPS,
            TWICE,
            Invalid(DecisionFault.SAME_PERSON_TWICE),
            id="one person on two steps never counts",
        ),
    ],
)
def test_approval_status(policy, decisions, expected):
    assert approval_status(request(policy), decisions) == expected


def approver(user: UserId) -> Principal:
    return Principal(user, APPROVER, user.title())


@pytest.mark.parametrize(
    ("policy", "decisions", "principal", "step", "verdict", "seen", "expected"),
    [
        pytest.param(
            ONE_STEP,
            (),
            approver(BOB),
            0,
            Verdict.APPROVE,
            DIGEST,
            Recorded(decision(0, BOB)),
            id="an eligible approver approves the open step",
        ),
        pytest.param(
            ONE_STEP,
            (),
            approver(BOB),
            0,
            Verdict.DECLINE,
            DIGEST,
            Recorded(decision(0, BOB, Verdict.DECLINE)),
            id="an eligible approver declines the open step",
        ),
        pytest.param(
            ONE_STEP,
            (decision(0, BOB),),
            approver(BOB),
            0,
            Verdict.APPROVE,
            DIGEST,
            AlreadyRecorded(decision(0, BOB)),
            id="the same decision again returns the recorded one",
        ),
        pytest.param(
            ONE_STEP,
            (decision(0, BOB),),
            approver(CAROL),
            0,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.NOT_OPEN),
            id="an approved request is closed",
        ),
        pytest.param(
            ONE_STEP,
            (decision(0, BOB, Verdict.DECLINE),),
            approver(CAROL),
            0,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.NOT_OPEN),
            id="a declined request is closed",
        ),
        pytest.param(
            ONE_STEP,
            (decision(0, BOB),),
            approver(BOB),
            0,
            Verdict.DECLINE,
            DIGEST,
            Refused(Refusal.NOT_OPEN),
            id="changing a verdict on a closed request is refused",
        ),
        pytest.param(
            TWO_STEPS,
            (),
            approver(CAROL),
            1,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.WRONG_STEP),
            id="step 1 before step 0",
        ),
        pytest.param(
            TWO_STEPS,
            (decision(0, BOB),),
            approver(CAROL),
            0,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.WRONG_STEP),
            id="step 0 again by someone else once step 1 is next",
        ),
        pytest.param(
            ONE_STEP,
            (),
            approver(BOB),
            5,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.WRONG_STEP),
            id="a step the policy does not have",
        ),
        pytest.param(
            ONE_STEP,
            (),
            Principal(BOB, frozenset({Role.OPERATOR}), "Bob"),
            0,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.NOT_AN_APPROVER),
            id="an operator cannot decide",
        ),
        pytest.param(
            ONE_STEP,
            (),
            approver(ALICE),
            0,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.OWN_WORK),
            id="a party to the run cannot decide",
        ),
        pytest.param(
            TWO_STEPS,
            (decision(0, CAROL),),
            approver(CAROL),
            1,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.DECIDED_EARLIER_STEP),
            id="two steps need two people",
        ),
        pytest.param(
            TWO_STEPS,
            (decision(0, BOB),),
            approver(UserId("dave")),
            1,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.NOT_ELIGIBLE),
            id="step 1 is only for carol",
        ),
        pytest.param(
            ONE_STEP,
            (),
            approver(BOB),
            0,
            Verdict.APPROVE,
            Digest("sha256:old"),
            Refused(Refusal.STALE_DIGEST),
            id="the approver saw different actions",
        ),
        pytest.param(
            ONE_STEP,
            (BY_A_PARTY,),
            approver(BOB),
            0,
            Verdict.APPROVE,
            DIGEST,
            Refused(Refusal.INVALID_DECISIONS),
            id="nobody can decide on top of invalid stored decisions",
        ),
    ],
)
def test_decide(policy, decisions, principal, step, verdict, seen, expected):
    assert decide(request(policy), decisions, principal, step, verdict, seen, NOW) == expected


def test_decide_stamps_the_time_it_was_given():
    result = decide(request(), (), approver(BOB), 0, Verdict.APPROVE, DIGEST, LATER)
    assert isinstance(result, Recorded)
    assert result.decision.at == LATER


def test_own_work_serializes_as_the_http_refusal():
    assert Refusal.OWN_WORK.value == "own_work"
