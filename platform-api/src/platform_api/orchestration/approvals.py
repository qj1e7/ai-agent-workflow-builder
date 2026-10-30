from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from platform_api.shared import ApprovalId, Digest, Principal, ProposalId, Role, RunId, UserId


@dataclass(frozen=True)
class AnyApprover:
    pass


@dataclass(frozen=True)
class OneOf:
    users: frozenset[UserId]


type Eligibility = AnyApprover | OneOf


@dataclass(frozen=True)
class ApprovalStep:
    label: str
    eligible: Eligibility


@dataclass(frozen=True)
class ApprovalPolicy:
    steps: tuple[ApprovalStep, ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("an approval policy needs at least one step")


@dataclass(frozen=True)
class ApprovalRequest:
    id: ApprovalId
    run_id: RunId
    proposal_id: ProposalId
    digest: Digest
    policy: ApprovalPolicy
    parties: frozenset[UserId]


class Verdict(Enum):
    APPROVE = "approve"
    DECLINE = "decline"


@dataclass(frozen=True)
class Decision:
    approval_id: ApprovalId
    step_index: int
    by: UserId
    verdict: Verdict
    seen_digest: Digest
    at: datetime


@dataclass(frozen=True)
class Open:
    next_step: int


@dataclass(frozen=True)
class Approved:
    approvers: tuple[UserId, ...]


@dataclass(frozen=True)
class Declined:
    by: UserId
    step: int


class DecisionFault(Enum):
    CONFLICTING_DECISIONS = "conflicting_decisions"
    STALE_DIGEST = "stale_digest"
    OWN_WORK = "own_work"
    SAME_PERSON_TWICE = "same_person_twice"


@dataclass(frozen=True)
class Invalid:
    fault: DecisionFault


type ApprovalStatus = Open | Approved | Declined | Invalid


def _recorded(request: ApprovalRequest, decisions: Iterable[Decision]) -> frozenset[Decision]:
    return frozenset(d for d in decisions if d.approval_id == request.id)


def _fault(request: ApprovalRequest, recorded: frozenset[Decision]) -> DecisionFault | None:
    steps = [d.step_index for d in recorded]
    if len(set(steps)) < len(steps):
        return DecisionFault.CONFLICTING_DECISIONS
    if any(d.seen_digest != request.digest for d in recorded):
        return DecisionFault.STALE_DIGEST
    if any(d.by in request.parties for d in recorded):
        return DecisionFault.OWN_WORK
    deciders = [d.by for d in recorded]
    if len(set(deciders)) < len(deciders):
        return DecisionFault.SAME_PERSON_TWICE
    return None


def approval_status(request: ApprovalRequest, decisions: Iterable[Decision]) -> ApprovalStatus:
    recorded = _recorded(request, decisions)
    fault = _fault(request, recorded)
    if fault is not None:
        return Invalid(fault)
    by_step = {d.step_index: d for d in recorded}
    approvers: list[UserId] = []
    for index in range(len(request.policy.steps)):
        decision = by_step.get(index)
        if decision is None:
            return Open(index)
        if decision.verdict is Verdict.DECLINE:
            return Declined(decision.by, index)
        approvers.append(decision.by)
    return Approved(tuple(approvers))


class Refusal(Enum):
    INVALID_DECISIONS = "invalid_decisions"
    NOT_OPEN = "not_open"
    WRONG_STEP = "wrong_step"
    NOT_AN_APPROVER = "not_an_approver"
    OWN_WORK = "own_work"
    DECIDED_EARLIER_STEP = "decided_earlier_step"
    NOT_ELIGIBLE = "not_eligible"
    STALE_DIGEST = "stale_digest"


@dataclass(frozen=True)
class Recorded:
    decision: Decision


@dataclass(frozen=True)
class AlreadyRecorded:
    decision: Decision


@dataclass(frozen=True)
class Refused:
    reason: Refusal


def _eligible(step: ApprovalStep, user: UserId) -> bool:
    match step.eligible:
        case AnyApprover():
            return True
        case OneOf(users):
            return user in users


def _refusal(
    request: ApprovalRequest,
    recorded: frozenset[Decision],
    status: ApprovalStatus,
    principal: Principal,
    step_index: int,
) -> Refusal | None:
    if isinstance(status, Invalid):
        return Refusal.INVALID_DECISIONS
    if not isinstance(status, Open):
        return Refusal.NOT_OPEN
    if step_index != status.next_step:
        return Refusal.WRONG_STEP
    if Role.APPROVER not in principal.roles:
        return Refusal.NOT_AN_APPROVER
    if principal.user_id in request.parties:
        return Refusal.OWN_WORK
    if any(decision.by == principal.user_id for decision in recorded):
        return Refusal.DECIDED_EARLIER_STEP
    if not _eligible(request.policy.steps[step_index], principal.user_id):
        return Refusal.NOT_ELIGIBLE
    return None


def why_not(
    request: ApprovalRequest, decisions: Iterable[Decision], principal: Principal
) -> Refusal | None:
    recorded = _recorded(request, decisions)
    status = approval_status(request, recorded)
    if not isinstance(status, Open):
        return Refusal.NOT_OPEN
    return _refusal(request, recorded, status, principal, status.next_step)


def decide(
    request: ApprovalRequest,
    decisions: Iterable[Decision],
    principal: Principal,
    step_index: int,
    verdict: Verdict,
    seen_digest: Digest,
    now: datetime,
) -> Recorded | AlreadyRecorded | Refused:
    recorded = _recorded(request, decisions)
    for earlier in recorded:
        if (
            earlier.step_index == step_index
            and earlier.by == principal.user_id
            and earlier.verdict is verdict
        ):
            return AlreadyRecorded(earlier)
    reason = _refusal(request, recorded, approval_status(request, recorded), principal, step_index)
    if reason is not None:
        return Refused(reason)
    if seen_digest != request.digest:
        return Refused(Refusal.STALE_DIGEST)
    return Recorded(Decision(request.id, step_index, principal.user_id, verdict, seen_digest, now))
