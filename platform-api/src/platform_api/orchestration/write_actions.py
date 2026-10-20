import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from enum import Enum

from platform_api.orchestration.approvals import (
    ApprovalRequest,
    Approved,
    Decision,
    Invalid,
    approval_status,
)
from platform_api.orchestration.runs import Acting
from platform_api.shared import ApprovalId, Digest, ProposalId, RunId, UserId

type Json = str | int | float | bool | None | Mapping[str, Json] | Sequence[Json]


@dataclass(frozen=True)
class ProposedIntent:
    kind: str
    fields: Mapping[str, Json]
    reason: str


@dataclass(frozen=True)
class WriteAction:
    connector: str
    operation: str
    target: Mapping[str, Json]
    fields: Mapping[str, Json]


@dataclass(frozen=True)
class Proposal:
    id: ProposalId
    run_id: RunId
    actions: tuple[WriteAction, ...]
    digest: Digest


def digest(actions: Iterable[WriteAction]) -> Digest:
    payload = [
        {
            "connector": action.connector,
            "operation": action.operation,
            "target": dict(action.target),
            "fields": dict(action.fields),
        }
        for action in actions
    ]
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return Digest("sha256:" + hashlib.sha256(text.encode()).hexdigest())


@dataclass(frozen=True)
class Binding:
    connector: str
    operation: str
    target: Mapping[str, Json]


@dataclass(frozen=True)
class UnboundIntent:
    kinds: tuple[str, ...]


def bind(
    intents: Iterable[ProposedIntent], bindings: Mapping[str, Binding]
) -> tuple[WriteAction, ...] | UnboundIntent:
    actions: list[WriteAction] = []
    unbound: list[str] = []
    for intent in intents:
        binding = bindings.get(intent.kind)
        if binding is None:
            if intent.kind not in unbound:
                unbound.append(intent.kind)
            continue
        actions.append(
            WriteAction(binding.connector, binding.operation, binding.target, intent.fields)
        )
    if unbound:
        return UnboundIntent(tuple(unbound))
    return tuple(actions)


type Registry = Mapping[str, Set[str]]


class DenyReason(Enum):
    RUN_MISMATCH = "run_mismatch"
    NOT_APPROVED = "not_approved"
    INVALID_DECISIONS = "invalid_decisions"
    DIGEST_MISMATCH = "digest_mismatch"
    UNREGISTERED_ACTION = "unregistered_action"


@dataclass(frozen=True)
class Deny:
    reason: DenyReason


@dataclass(frozen=True, init=False)
class AuthorizedWrite:
    proposal: Proposal
    approval_id: ApprovalId
    approvers: tuple[UserId, ...]

    def __init__(self) -> None:
        raise TypeError("only check() issues an AuthorizedWrite")


def _issue(
    proposal: Proposal, approval_id: ApprovalId, approvers: tuple[UserId, ...]
) -> AuthorizedWrite:
    write = object.__new__(AuthorizedWrite)
    object.__setattr__(write, "proposal", proposal)
    object.__setattr__(write, "approval_id", approval_id)
    object.__setattr__(write, "approvers", approvers)
    return write


def check(
    acting: Acting,
    proposal: Proposal,
    request: ApprovalRequest,
    decisions: Iterable[Decision],
    registry: Registry,
) -> AuthorizedWrite | Deny:
    same_run = (
        acting.run_id == proposal.run_id == request.run_id
        and acting.proposal_id == proposal.id == request.proposal_id
        and acting.approval_id == request.id
    )
    if not same_run:
        return Deny(DenyReason.RUN_MISMATCH)
    status = approval_status(request, decisions)
    if isinstance(status, Invalid):
        return Deny(DenyReason.INVALID_DECISIONS)
    if not isinstance(status, Approved):
        return Deny(DenyReason.NOT_APPROVED)
    if digest(proposal.actions) != request.digest:
        return Deny(DenyReason.DIGEST_MISMATCH)
    for action in proposal.actions:
        if action.operation not in registry.get(action.connector, frozenset()):
            return Deny(DenyReason.UNREGISTERED_ACTION)
    return _issue(proposal, request.id, status.approvers)
