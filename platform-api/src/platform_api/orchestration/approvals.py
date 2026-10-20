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


type ApprovalStatus = Open | Approved | Declined


def _by_step(request: ApprovalRequest, decisions: Iterable[Decision]) -> dict[int, Decision]:
    recorded: dict[int, Decision] = {}
    for decision in decisions:
        if decision.approval_id == request.id:
            recorded.setdefault(decision.step_index, decision)
    return recorded


def approval_status(request: ApprovalRequest, decisions: Iterable[Decision]) -> ApprovalStatus:
    recorded = _by_step(request, decisions)
    approvers: list[UserId] = []
    for index in range(len(request.policy.steps)):
        decision = recorded.get(index)
        if decision is None:
            return Open(index)
        if decision.verdict is Verdict.DECLINE:
            return Declined(decision.by, index)
        approvers.append(decision.by)
    return Approved(tuple(approvers))


class Refusal(Enum):
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


def decide(
    request: ApprovalRequest,
    decisions: Iterable[Decision],
    principal: Principal,
    step_index: int,
    verdict: Verdict,
    seen_digest: Digest,
    now: datetime,
) -> Recorded | AlreadyRecorded | Refused:
    recorded = _by_step(request, decisions)
    earlier = recorded.get(step_index)
    if earlier is not None and earlier.by == principal.user_id and earlier.verdict is verdict:
        return AlreadyRecorded(earlier)
    status = approval_status(request, recorded.values())
    if not isinstance(status, Open):
        return Refused(Refusal.NOT_OPEN)
    if step_index != status.next_step:
        return Refused(Refusal.WRONG_STEP)
    if Role.APPROVER not in principal.roles:
        return Refused(Refusal.NOT_AN_APPROVER)
    if principal.user_id in request.parties:
        return Refused(Refusal.OWN_WORK)
    if any(decision.by == principal.user_id for decision in recorded.values()):
        return Refused(Refusal.DECIDED_EARLIER_STEP)
    if not _eligible(request.policy.steps[step_index], principal.user_id):
        return Refused(Refusal.NOT_ELIGIBLE)
    if seen_digest != request.digest:
        return Refused(Refusal.STALE_DIGEST)
    return Recorded(Decision(request.id, step_index, principal.user_id, verdict, seen_digest, now))
