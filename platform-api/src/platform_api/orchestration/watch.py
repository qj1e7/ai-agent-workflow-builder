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
    ticket: str | None
    """The Done ticket's key, or None when it is not in the Jira set up now (ADR 0041)."""


type LearnedVersion = FromFirstCheck | FromTicketDone
type OurVersion = Given | LearnedVersion


@dataclass(frozen=True)
class Checked:
    run_id: RunId
    at: datetime
    newest: str
    github_name: str | None = None


@dataclass(frozen=True)
class KnownNewest:
    version: str
    at: datetime


@dataclass(frozen=True)
class CouldNotCheck:
    run_id: RunId
    at: datetime
    problem: str
    last_read: KnownNewest | None = None
    github_name: str | None = None
    not_found: bool = False


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


# The project prefix some tags carry, such as docker-v, n8n@ or langchain==, then an optional v.
_PREFIX = re.compile(r"(?:[A-Za-z][A-Za-z0-9._-]*?[@=-]+)?[vV]?(\d+(?:\.\d+)*)", re.ASCII)


def _numbers(version: str) -> tuple[int, ...] | None:
    found = _PREFIX.fullmatch(version)
    return tuple(int(part) for part in found[1].split(".")) if found else None


def newer(candidate: str, than: str) -> bool:
    """Plain version numbers, with or without one v in front, compare part by part. Anything
    else counts as newer when it differs."""
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
    github_name: str | None = None


@dataclass(frozen=True)
class CouldNotRead:
    software_id: SoftwareId
    problem: str
    github_name: str | None = None
    not_found: bool = False


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
        if finding.not_found and finding.full_name is not None:
            return Unusable(
                f"The agents said GitHub both has and has not got the repository of {software.name}"
            )
        if finding.state == "cant_check":
            learned.append(
                CouldNotRead(software_id, finding.detail, finding.full_name, finding.not_found)
            )
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
        learned.append(ReadNewest(software_id, finding.newest, starting_point, finding.full_name))
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
        expected = (
            f"Upgrade {software.name} to {finding.newest}"
            if software.from_first_check
            else f"Upgrade {software.name} from {software.our_version} to {finding.newest}"
        )
        if intent.fields.get("title") != expected:
            return Unusable(
                f'The agents titled the ticket for {software.name} differently from "{expected}"'
            )
        tickets.append(TicketToPropose(index, software_id, finding.newest))
    return Reviewed(tuple(learned), tuple(tickets))


def unread_of(task: WatchlistTask, reviewed: Reviewed) -> tuple[str, ...]:
    """The software the check couldn't read, by name, in the watchlist's order."""
    missed = {entry.software_id for entry in reviewed.learned if isinstance(entry, CouldNotRead)}
    return tuple(software.name for software in task.software if software.id in missed)


NOTHING_READABLE_TYPES = frozenset({"UpstreamUnavailable", "UpstreamRejected"})


def _could_not_read(software_id: SoftwareId, own: Finding | None, shared: str) -> CouldNotRead:
    if own is None:
        return CouldNotRead(software_id, shared)
    kept = None if own.not_found else own.full_name
    return CouldNotRead(software_id, own.detail.strip(), kept, own.not_found)


def all_could_not_read(
    task: WatchlistTask, error: TaskError, findings: Sequence[Finding]
) -> Reviewed | None:
    if error.type not in NOTHING_READABLE_TYPES:
        return None
    shared = error.message if error.message.endswith(".") else f"{error.message}."
    own = {
        SoftwareId(f.software_id): f
        for f in findings
        if f.state == "cant_check" and f.detail.strip()
    }
    return Reviewed(
        tuple(
            _could_not_read(software.id, own.get(software.id), shared) for software in task.software
        ),
        (),
    )
