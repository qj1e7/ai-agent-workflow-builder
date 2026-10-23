import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import NewType

RunId = NewType("RunId", str)
ApprovalId = NewType("ApprovalId", str)
ProposalId = NewType("ProposalId", str)
UseCaseId = NewType("UseCaseId", str)
UserId = NewType("UserId", str)
Digest = NewType("Digest", str)
N8nExecutionId = NewType("N8nExecutionId", str)
TaskId = NewType("TaskId", str)


class Role(Enum):
    OPERATOR = "operator"
    APPROVER = "approver"


@dataclass(frozen=True)
class Principal:
    user_id: UserId
    roles: frozenset[Role]
    display: str


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(prefix: str) -> str:
    value = int(time.time() * 1000)
    head = "".join(_CROCKFORD[(value >> (5 * i)) & 31] for i in range(9, -1, -1))
    tail = "".join(secrets.choice(_CROCKFORD) for _ in range(16))
    return f"{prefix}_{head}{tail}"
