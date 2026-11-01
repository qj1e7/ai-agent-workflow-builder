import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from platform_api.db import Database, UnitOfWork
from platform_api.orchestration.jira import JiraError
from platform_api.orchestration.runs import (
    STATE_NAMES,
    Acting,
    Failed,
    Outcome,
    Rejected,
    RunState,
    Succeeded,
)
from platform_api.orchestration.spec import WatchlistTask
from platform_api.orchestration.store import STATE_TYPES, RunRecord
from platform_api.orchestration.watch import (
    Checked,
    CouldNotCheck,
    CouldNotRead,
    FromFirstCheck,
    FromTicketDone,
    Given,
    KnownNewest,
    LatestCheck,
    LearnedVersion,
    OpenTicket,
    PendingTicket,
    ReadNewest,
    Reviewed,
    Standing,
    standing,
)
from platform_api.shared import ApprovalId, ProposalId, RunId, SoftwareId, UseCaseId
from platform_api.wire import RunState as RunStateName

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WrittenTicket:
    proposal_id: ProposalId
    action_index: int
    software_id: SoftwareId
    version: str
    key: str


@dataclass(frozen=True)
class Facts:
    learned: Mapping[SoftwareId, LearnedVersion]
    checks: Mapping[SoftwareId, LatestCheck]
    pending: Mapping[SoftwareId, PendingTicket]
    open_tickets: Mapping[SoftwareId, OpenTicket]


@dataclass(frozen=True)
class LastCheck:
    run_id: RunId
    state: RunStateName
    started_at: datetime


async def _save_newest(
    uow: UnitOfWork, use_case_id: UseCaseId, read: ReadNewest, run_id: RunId
) -> None:
    await uow.conn.execute(
        "INSERT INTO orchestration.software_checks (use_case_id, software_id, run_id, "
        "checked_at, newest_version, newest_at, problem) VALUES (%s, %s, %s, %s, %s, %s, NULL) "
        "ON CONFLICT (use_case_id, software_id) DO UPDATE SET run_id = EXCLUDED.run_id, "
        "checked_at = EXCLUDED.checked_at, newest_version = EXCLUDED.newest_version, "
        "newest_at = EXCLUDED.newest_at, problem = NULL",
        (use_case_id, read.software_id, run_id, uow.now, read.newest, uow.now),
    )


async def _save_problem_keeping_last_read(
    uow: UnitOfWork, use_case_id: UseCaseId, unread: CouldNotRead, run_id: RunId
) -> None:
    await uow.conn.execute(
        "INSERT INTO orchestration.software_checks (use_case_id, software_id, run_id, "
        "checked_at, problem) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (use_case_id, software_id) DO UPDATE SET run_id = EXCLUDED.run_id, "
        "checked_at = EXCLUDED.checked_at, problem = EXCLUDED.problem",
        (use_case_id, unread.software_id, run_id, uow.now, unread.problem),
    )


class WatchStore:
    async def record_review(
        self,
        uow: UnitOfWork,
        record: RunRecord,
        reviewed: Reviewed,
        proposal_id: ProposalId | None,
    ) -> None:
        """Keeps what one check learned. The same review again changes nothing."""
        use_case_id = record.spec.use_case_id
        for entry in reviewed.learned:
            if isinstance(entry, ReadNewest):
                await _save_newest(uow, use_case_id, entry, record.run_id)
            else:
                await _save_problem_keeping_last_read(uow, use_case_id, entry, record.run_id)
            if isinstance(entry, ReadNewest) and entry.starting_point:
                await uow.conn.execute(
                    "INSERT INTO orchestration.our_versions (use_case_id, software_id, version, "
                    "source, learned_at, ticket_key) VALUES (%s, %s, %s, 'first_check', %s, NULL) "
                    "ON CONFLICT (use_case_id, software_id) DO NOTHING",
                    (use_case_id, entry.software_id, entry.newest, uow.now),
                )
        if proposal_id is None:
            return
        for ticket in reviewed.tickets:
            await uow.conn.execute(
                "INSERT INTO orchestration.proposed_tickets (proposal_id, action_index, run_id, "
                "use_case_id, software_id, version, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'proposed') "
                "ON CONFLICT (proposal_id, action_index) DO NOTHING",
                (
                    proposal_id,
                    ticket.action_index,
                    record.run_id,
                    use_case_id,
                    ticket.software_id,
                    ticket.version,
                ),
            )

    async def run_moved(self, uow: UnitOfWork, record: RunRecord, after: RunState) -> None:
        """Follows a watchlist run's tickets: written when the act leg wrote them, dropped when
        the run was declined or failed. The next check proposes dropped tickets again."""
        if not isinstance(record.spec.task, WatchlistTask):
            return
        match after:
            case Failed() | Rejected():
                await uow.conn.execute(
                    "UPDATE orchestration.proposed_tickets SET status = 'dropped' "
                    "WHERE run_id = %s AND status = 'proposed'",
                    (record.run_id,),
                )
            case Succeeded(outcome=Outcome.WRITTEN, written=written) if isinstance(
                record.state, Acting
            ):
                for index, done in enumerate(written):
                    await uow.conn.execute(
                        "UPDATE orchestration.proposed_tickets SET status = 'written', "
                        "ticket_key = %s WHERE proposal_id = %s AND action_index = %s "
                        "AND status IN ('proposed', 'dropped')",
                        (done.external_reference, record.state.proposal_id, index),
                    )
            case _:
                pass

    async def written_tickets(self, uow: UnitOfWork, use_case_id: UseCaseId) -> list[WrittenTicket]:
        rows = await (
            await uow.conn.execute(
                "SELECT proposal_id, action_index, software_id, version, ticket_key "
                "FROM orchestration.proposed_tickets WHERE use_case_id = %s AND status = 'written' "
                "ORDER BY proposal_id, action_index",
                (use_case_id,),
            )
        ).fetchall()
        return [
            WrittenTicket(
                ProposalId(row["proposal_id"]),
                int(row["action_index"]),
                SoftwareId(row["software_id"]),
                str(row["version"]),
                str(row["ticket_key"]),
            )
            for row in rows
        ]

    async def ticket_done(
        self, uow: UnitOfWork, use_case_id: UseCaseId, ticket: WrittenTicket, at: datetime
    ) -> None:
        """A Done ticket is the evidence that moves our version to the version it named."""
        await uow.conn.execute(
            "UPDATE orchestration.proposed_tickets SET status = 'done', done_at = %s "
            "WHERE proposal_id = %s AND action_index = %s AND status = 'written'",
            (at, ticket.proposal_id, ticket.action_index),
        )
        await uow.conn.execute(
            "INSERT INTO orchestration.our_versions (use_case_id, software_id, version, source, "
            "learned_at, ticket_key) VALUES (%s, %s, %s, 'ticket_done', %s, %s) "
            "ON CONFLICT (use_case_id, software_id) DO UPDATE SET version = EXCLUDED.version, "
            "source = EXCLUDED.source, learned_at = EXCLUDED.learned_at, "
            "ticket_key = EXCLUDED.ticket_key",
            (use_case_id, ticket.software_id, ticket.version, at, ticket.key),
        )

    async def facts(self, uow: UnitOfWork, use_case_id: UseCaseId) -> Facts:
        learned: dict[SoftwareId, LearnedVersion] = {}
        for row in await (
            await uow.conn.execute(
                "SELECT software_id, version, source, learned_at, ticket_key "
                "FROM orchestration.our_versions WHERE use_case_id = %s",
                (use_case_id,),
            )
        ).fetchall():
            software_id = SoftwareId(row["software_id"])
            if row["source"] == "ticket_done":
                learned[software_id] = FromTicketDone(
                    str(row["version"]), row["learned_at"], str(row["ticket_key"])
                )
            else:
                learned[software_id] = FromFirstCheck(str(row["version"]), row["learned_at"])
        checks: dict[SoftwareId, LatestCheck] = {}
        for row in await (
            await uow.conn.execute(
                "SELECT software_id, run_id, checked_at, newest_version, newest_at, problem "
                "FROM orchestration.software_checks WHERE use_case_id = %s",
                (use_case_id,),
            )
        ).fetchall():
            software_id = SoftwareId(row["software_id"])
            run_id = RunId(row["run_id"])
            if row["problem"] is not None:
                last_read = (
                    None
                    if row["newest_version"] is None
                    else KnownNewest(str(row["newest_version"]), row["newest_at"])
                )
                checks[software_id] = CouldNotCheck(
                    run_id, row["checked_at"], str(row["problem"]), last_read
                )
            else:
                checks[software_id] = Checked(run_id, row["checked_at"], str(row["newest_version"]))
        pending: dict[SoftwareId, PendingTicket] = {}
        open_tickets: dict[SoftwareId, OpenTicket] = {}
        for row in await (
            await uow.conn.execute(
                "SELECT t.software_id, t.proposal_id, t.action_index, t.version, t.status, "
                "t.ticket_key, a.approval_id FROM orchestration.proposed_tickets t "
                "LEFT JOIN orchestration.approval_requests a ON a.proposal_id = t.proposal_id "
                "WHERE t.use_case_id = %s AND t.status IN ('proposed', 'written') "
                "ORDER BY t.proposal_id, t.action_index",
                (use_case_id,),
            )
        ).fetchall():
            software_id = SoftwareId(row["software_id"])
            if row["status"] == "proposed":
                approval = row["approval_id"]
                pending[software_id] = PendingTicket(
                    ProposalId(row["proposal_id"]),
                    int(row["action_index"]),
                    str(row["version"]),
                    None if approval is None else ApprovalId(approval),
                )
            else:
                open_tickets[software_id] = OpenTicket(str(row["ticket_key"]), str(row["version"]))
        return Facts(learned, checks, pending, open_tickets)

    async def last_check(self, uow: UnitOfWork, use_case_id: UseCaseId) -> LastCheck | None:
        row = await (
            await uow.conn.execute(
                "SELECT run_id, state, started_at FROM orchestration.runs WHERE use_case_id = %s "
                "ORDER BY started_at DESC, run_id DESC LIMIT 1",
                (use_case_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return LastCheck(
            RunId(row["run_id"]), STATE_NAMES[STATE_TYPES[row["state"]]], row["started_at"]
        )


class TicketStatusPort(Protocol):
    """Answers which of the given tickets are Done in Jira, and when. A read, so no approval."""

    async def done_tickets(self, keys: Collection[str]) -> Mapping[str, datetime]: ...


@dataclass(frozen=True)
class WatchlistStanding:
    software: Mapping[SoftwareId, Standing]
    last_check: LastCheck | None


class WatchlistFacts(Protocol):
    """The builder's port to the facts orchestration keeps about a watchlist."""

    async def standings(
        self, use_case_id: UseCaseId, given: Mapping[SoftwareId, Given | None]
    ) -> WatchlistStanding: ...


class WatchFacts:
    def __init__(self, db: Database, tickets: TicketStatusPort) -> None:
        self._db = db
        self._tickets = tickets
        self._store = WatchStore()

    async def standings(
        self, use_case_id: UseCaseId, given: Mapping[SoftwareId, Given | None]
    ) -> WatchlistStanding:
        await self._refresh(use_case_id)
        async with self._db.transaction("orchestration") as uow:
            facts = await self._store.facts(uow, use_case_id)
            last_check = await self._store.last_check(uow, use_case_id)
        return WatchlistStanding(
            {
                software_id: standing(
                    typed,
                    facts.learned.get(software_id),
                    facts.checks.get(software_id),
                    facts.pending.get(software_id),
                    facts.open_tickets.get(software_id),
                )
                for software_id, typed in given.items()
            },
            last_check,
        )

    async def _refresh(self, use_case_id: UseCaseId) -> None:
        async with self._db.transaction("orchestration") as uow:
            written = await self._store.written_tickets(uow, use_case_id)
        if not written:
            return
        try:
            done = await self._tickets.done_tickets([ticket.key for ticket in written])
        except JiraError as error:
            # The watchlist still shows what the platform knows. The next view asks Jira again.
            log.warning("could not ask Jira which tickets are done: %s", error)
            return
        if not done:
            return
        async with self._db.transaction("orchestration") as uow:
            for ticket in written:
                if ticket.key in done:
                    await self._store.ticket_done(uow, use_case_id, ticket, done[ticket.key])
