from dataclasses import dataclass
from enum import Enum
from typing import NewType

RunId = NewType("RunId", str)
ApprovalId = NewType("ApprovalId", str)
ProposalId = NewType("ProposalId", str)
UserId = NewType("UserId", str)
Digest = NewType("Digest", str)


class Role(Enum):
    OPERATOR = "operator"
    APPROVER = "approver"


@dataclass(frozen=True)
class Principal:
    user_id: UserId
    roles: frozenset[Role]
