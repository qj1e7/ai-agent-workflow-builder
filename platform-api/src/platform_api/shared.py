import re
import secrets
import time
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as clock_time
from enum import Enum
from typing import Literal, NewType
from zoneinfo import ZoneInfo

RunId = NewType("RunId", str)
ApprovalId = NewType("ApprovalId", str)
ProposalId = NewType("ProposalId", str)
UseCaseId = NewType("UseCaseId", str)
UserId = NewType("UserId", str)
Digest = NewType("Digest", str)
N8nExecutionId = NewType("N8nExecutionId", str)
TaskId = NewType("TaskId", str)
SoftwareId = NewType("SoftwareId", str)

JIRA_PROJECT_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,254}\Z")
"""A Jira project key as Jira allows it: a capital letter, then at least one more capital letter,
digit or underscore, such as MOCK or AB_1. Data Center allows 255 characters at most (ADR 0035)."""
type TicketStatus = Literal["To Do", "Done"]
"""A Jira ticket's status as the platform reads it: Done is Jira's status category done, and
every other status counts as To Do, not done yet."""
STORED_JIRA_PROJECT_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,254}\Z")
"""A project key as the platform once allowed it, one letter included. Values saved then keep
working when read or run. Only a key being entered must take JIRA_PROJECT_PATTERN."""
JIRA_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,254}-[1-9][0-9]{0,8}\Z")
"""A ticket key: a project key, a dash and the ticket's number, such as AB_1-12."""
STORED_JIRA_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,254}-[1-9][0-9]{0,8}\Z")
"""A ticket key in a project of the older shape, such as A-12."""

TEAM_TIME_ZONE = ZoneInfo("Asia/Singapore")
"""The zone the team works in, unless the TEAM_TIME_ZONE setting names another. The agents'
today, a run's day and every plain day an agent sends are days in it."""


def day_start(day: date, zone: ZoneInfo) -> datetime:
    """The first moment of a plain day in a zone. A day ends where the next day starts."""
    return datetime.combine(day, clock_time(), zone)


WRITE_STOP_ADVICE = (
    "Check Jira for a ticket with this run's label. If there is one, the work is done and no "
    "new run is needed. If there is none, report it to support, and start a new run only once "
    "the cause is fixed."
)
"""What to do after a stop at the write step that retrying cannot fix. A new run does not look
for this run's ticket, so it can make a duplicate. The run's failure summary, the retry refusal
and the AI troubleshooter all use this one text (ADR 0035)."""
BEFORE_WRITE_STOP_ADVICE = "Start a new run."
"""What to do after a stop before the write step that retrying cannot fix: nothing was written."""


def stop_advice(at_write_step: bool) -> str:
    return WRITE_STOP_ADVICE if at_write_step else BEFORE_WRITE_STOP_ADVICE


class Role(Enum):
    OPERATOR = "operator"
    APPROVER = "approver"


@dataclass(frozen=True)
class Principal:
    """A person on the People list: our id, their roles from our table, and their name."""

    user_id: UserId
    roles: frozenset[Role]
    display: str


@dataclass(frozen=True)
class DevIdentity:
    """Local mode: X-Dev-User carries our person id."""

    person_id: UserId


@dataclass(frozen=True)
class ExternalIdentity:
    """What a verified token says: the identity provider's subject, the user name it signs in
    with, and the name it shows. None of it grants a role."""

    subject: str
    user_name: str | None
    name: str | None

    @property
    def display(self) -> str:
        return self.name or self.user_name or self.subject


type Identity = DevIdentity | ExternalIdentity


@dataclass(frozen=True)
class SeedPerson:
    id: UserId
    email: str
    display: str
    roles: frozenset[Role]


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(prefix: str) -> str:
    value = int(time.time() * 1000)
    head = "".join(_CROCKFORD[(value >> (5 * i)) & 31] for i in range(9, -1, -1))
    tail = "".join(secrets.choice(_CROCKFORD) for _ in range(16))
    return f"{prefix}_{head}{tail}"


def has_id_shape(value: str, prefix: str) -> bool:
    """Whether value looks like new_id(prefix) made it: the prefix, _, and 26 characters."""
    head, underscore, body = value.partition("_")
    return (
        head == prefix
        and underscore == "_"
        and len(body) == 26
        and all(c in _CROCKFORD for c in body)
    )
