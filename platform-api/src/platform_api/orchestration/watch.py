"""What the platform learns about watched software, and how it reads the agents' answer.

Pure. The tables and the refresh against Jira are in watch_store.py.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from platform_api.orchestration.agents import Finding, ProposedIntentIn
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

    The agents hold no write tools, so what they say about the list is checked here before any
    of it is kept: every finding and every ticket must name a software on the list, once, and a
    ticket must not be for software the platform said was held.
    """
    listed = {software.id: software for software in task.software}
    learned: list[Learned] = []
    newest: dict[SoftwareId, str] = {}
    for finding in findings:
        software_id = SoftwareId(finding.software_id)
        if software_id not in listed:
            return Unusable(f"The agents reported on {software_id}, which is not on the list")
        if any(entry.software_id == software_id for entry in learned):
            return Unusable(f"The agents reported twice on {listed[software_id].name}")
        if finding.state == "cant_check":
            learned.append(CouldNotRead(software_id, finding.detail))
        elif finding.newest is None:
            return Unusable(
                f"The agents gave no newest version for {listed[software_id].name} "
                f"({finding.state})"
            )
        else:
            newest[software_id] = finding.newest
            learned.append(
                ReadNewest(software_id, finding.newest, finding.state == "starting_point")
            )

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
        if software_id not in newest:
            return Unusable(
                f"The agents proposed a ticket for {software.name} without reading its "
                "newest version"
            )
        tickets.append(TicketToPropose(index, software_id, newest[software_id]))
    return Reviewed(tuple(learned), tuple(tickets))
