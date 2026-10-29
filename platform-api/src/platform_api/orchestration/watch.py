"""What the platform learns about watched software, and how it reads the agents' answer.

Pure. The tables and the refresh against Jira are in watch_store.py.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from platform_api.orchestration.agents import Finding, ProposedIntentIn, TaskError
from platform_api.orchestration.spec import WatchlistTask
from platform_api.shared import ApprovalId, ProposalId, RunId, SoftwareId


@dataclass(frozen=True)
class Given:
    """Typed by the Operator who added the software."""

    version: str
    at: datetime


@dataclass(frozen=True)
class FromFirstCheck:
    """The newest release at the first check, because nothing was typed."""

    version: str
    at: datetime


@dataclass(frozen=True)
class FromTicketDone:
    version: str
    at: datetime
    ticket: str


type LearnedVersion = FromFirstCheck | FromTicketDone
type OurVersion = Given | LearnedVersion


@dataclass(frozen=True)
class Checked:
    run_id: RunId
    at: datetime
    newest: str


@dataclass(frozen=True)
class CouldNotCheck:
    run_id: RunId
    at: datetime
    problem: str


type LatestCheck = Checked | CouldNotCheck


@dataclass(frozen=True)
class PendingTicket:
    """Proposed and waiting for an Approver. The approval id is None until the run asks."""

    proposal_id: ProposalId
    action_index: int
    version: str
    approval_id: ApprovalId | None


@dataclass(frozen=True)
class OpenTicket:
    key: str
    version: str


@dataclass(frozen=True)
class SoftwareFacts:
    our_version: OurVersion | None
    latest_check: LatestCheck | None
    pending: PendingTicket | None
    open_ticket: OpenTicket | None


type Status = Literal[
    "cant_check", "behind", "awaiting_approval", "ticket_open", "up_to_date", "not_checked"
]

ATTENTION_ORDER: tuple[Status, ...] = (
    "cant_check",
    "behind",
    "awaiting_approval",
    "ticket_open",
    "not_checked",
    "up_to_date",
)
"""Rows that need a person first, up to date last."""


def _numbers(version: str) -> tuple[int, ...] | None:
    parts = version.split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else None


def newer(candidate: str, than: str) -> bool:
    """Plain version numbers compare part by part. Anything else counts as newer when it differs."""
    left, right = _numbers(candidate), _numbers(than)
    if left is None or right is None:
        return candidate != than
    return left > right


def status_of(facts: SoftwareFacts) -> Status:
    """First match wins: a check that failed, then tickets in flight, then the version gap."""
    match facts:
        case SoftwareFacts(latest_check=CouldNotCheck()):
            return "cant_check"
        case SoftwareFacts(pending=PendingTicket()):
            return "awaiting_approval"
        case SoftwareFacts(open_ticket=OpenTicket()):
            return "ticket_open"
        case SoftwareFacts(latest_check=Checked(newest=newest), our_version=ours):
            behind = ours is not None and newer(newest, ours.version)
            return "behind" if behind else "up_to_date"
        case _:
            return "not_checked"


@dataclass(frozen=True)
class Standing:
    facts: SoftwareFacts
    status: Status


def standing(
    given: Given | None,
    learned: LearnedVersion | None,
    latest_check: LatestCheck | None,
    pending: PendingTicket | None,
    open_ticket: OpenTicket | None,
) -> Standing:
    facts = SoftwareFacts(learned or given, latest_check, pending, open_ticket)
    return Standing(facts, status_of(facts))


@dataclass(frozen=True)
class ReadNewest:
    software_id: SoftwareId
    newest: str
    starting_point: bool


@dataclass(frozen=True)
class CouldNotRead:
    software_id: SoftwareId
    problem: str


type Learned = ReadNewest | CouldNotRead


@dataclass(frozen=True)
class TicketToPropose:
    action_index: int
    software_id: SoftwareId
    version: str


@dataclass(frozen=True)
class Reviewed:
    learned: tuple[Learned, ...]
    tickets: tuple[TicketToPropose, ...]


@dataclass(frozen=True)
class Unusable:
    detail: str


def review(
    task: WatchlistTask, findings: Sequence[Finding], proposed: Sequence[ProposedIntentIn]
) -> Reviewed | Unusable:
    """Reads the agents' answer against the list the check was given.

    The agents' words are untrusted input, like their proposals (ADR 0008), so nothing is kept
    until it fits the list: exactly one finding per listed software, every version shaped like
    the tag pattern, a starting point only where the platform sent no version, and a ticket only
    for listed software that is behind, not held, and titled with the versions the platform
    knows, so the version our version moves to on Done is the one the Approver saw.
    """
    listed = {software.id: software for software in task.software}
    # ASCII and fullmatch: "$" alone would allow a trailing newline, and "\d" other scripts.
    tag = re.compile(task.tag_pattern, re.ASCII)
    learned: list[Learned] = []
    read: dict[SoftwareId, Finding] = {}
    for finding in findings:
        software_id = SoftwareId(finding.software_id)
        software = listed.get(software_id)
        if software is None:
            return Unusable(f"The agents reported on {software_id}, which is not on the list")
        if any(entry.software_id == software_id for entry in learned):
            return Unusable(f"The agents reported twice on {software.name}")
        if any(tag.fullmatch(version) is None for version in finding.new_versions):
            return Unusable(f"The agents named a version for {software.name} that is not a tag")
        if finding.state == "cant_check":
            learned.append(CouldNotRead(software_id, finding.detail))
            continue
        if finding.newest is None:
            return Unusable(
                f"The agents gave no newest version for {software.name} ({finding.state})"
            )
        if tag.fullmatch(finding.newest) is None:
            return Unusable(f"The agents named a version for {software.name} that is not a tag")
        starting_point = finding.state == "starting_point"
        if starting_point != (software.our_version is None):
            return Unusable(
                f"The agents took {finding.newest} as our version of {software.name}"
                if starting_point
                else f"The agents did not take a starting point for {software.name}"
            )
        read[software_id] = finding
        learned.append(ReadNewest(software_id, finding.newest, starting_point))
    for software in task.software:
        if not any(entry.software_id == software.id for entry in learned):
            return Unusable(f"The agents did not report on {software.name}")

    tickets: list[TicketToPropose] = []
    for index, intent in enumerate(proposed):
        if intent.subject is None:
            return Unusable("The agents proposed a ticket without naming its software")
        software_id = SoftwareId(intent.subject)
        software = listed.get(software_id)
        if software is None:
            return Unusable(
                f"The agents proposed a ticket for {software_id}, which is not on the list"
            )
        if any(ticket.software_id == software_id for ticket in tickets):
            return Unusable(f"The agents proposed two tickets for {software.name}")
        if software.open_ticket is not None or software.awaiting_approval:
            return Unusable(
                f"The agents proposed a ticket for {software.name}, which has one already"
            )
        finding = read.get(software_id)
        if finding is None or finding.newest is None:
            return Unusable(
                f"The agents proposed a ticket for {software.name} without reading its "
                "newest version"
            )
        if finding.state != "behind":
            return Unusable(
                f"The agents proposed a ticket for {software.name} but found it {finding.state}"
            )
        if software.our_version is None or not newer(finding.newest, software.our_version):
            return Unusable(
                f"The agents proposed a ticket for {software.name}, but {finding.newest} is not "
                f"newer than our version {software.our_version}"
            )
        expected = f"Upgrade {software.name} from {software.our_version} to {finding.newest}"
        if intent.fields.get("title") != expected:
            return Unusable(
                f'The agents titled the ticket for {software.name} differently from "{expected}"'
            )
        tickets.append(TicketToPropose(index, software_id, finding.newest))
    return Reviewed(tuple(learned), tuple(tickets))


UNREADABLE = frozenset({"UpstreamUnavailable", "UpstreamRejected"})
"""The error types the agents answer with when no listed source could be read."""


def nothing_read(task: WatchlistTask, error: TaskError) -> Reviewed | None:
    """A check that could read no source fails, and says so for every listed software, so no
    row keeps a status this check could not confirm. Any other failure leaves the rows alone."""
    if error.type not in UNREADABLE:
        return None
    problem = error.message if error.message.endswith(".") else f"{error.message}."
    return Reviewed(tuple(CouldNotRead(software.id, problem) for software in task.software), ())
