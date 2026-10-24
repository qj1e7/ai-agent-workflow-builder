import asyncio
import hashlib
import json
from collections.abc import Collection, Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Literal, Protocol

from platform_api.db import Database
from platform_api.monitoring import ActionLine
from platform_api.orchestration.approvals import (
    ApprovalRequest,
    Approved,
    Decision,
    Invalid,
    approval_status,
)
from platform_api.orchestration.runs import Acting, WriteDone
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


def describe(action: WriteAction) -> ActionLine:
    if action.connector == "jira" and action.operation == "create_ticket":
        title = str(action.fields.get("title", ""))
        return ActionLine(
            connector="jira",
            operation="create_ticket",
            line=f"Create Jira ticket in {action.target.get('project', '?')}: {title}",
        )
    return ActionLine(
        connector=action.connector,
        operation=action.operation,
        line=f"{action.operation} on {action.connector}",
    )


def intent(action: WriteAction) -> str:
    if action.connector == "jira" and action.operation == "create_ticket":
        project = action.target.get("project", "?")
        return f'create a Jira ticket in {project} titled "{action.fields.get("title", "")}"'
    return f"{action.operation} on {action.connector}"


class WriteFailed(Exception): ...


@dataclass(frozen=True)
class WriteKey:
    run_id: RunId
    proposal_id: ProposalId
    index: int

    @property
    def text(self) -> str:
        return f"{self.run_id}/{self.proposal_id}/{self.index}"


class WriteConnector(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def operations(self) -> frozenset[str]: ...

    async def execute(self, action: WriteAction, key: WriteKey) -> str: ...


def registry_of(connectors: Iterable[WriteConnector]) -> Registry:
    return {connector.name: connector.operations for connector in connectors}


class MockJiraConnector:
    name = "jira"
    operations = frozenset({"create_ticket"})

    def __init__(self, db: Database) -> None:
        self._db = db

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute("LOCK TABLE orchestration.mock_jira_tickets IN EXCLUSIVE MODE")
            existing = await (
                await uow.conn.execute(
                    "SELECT key FROM orchestration.mock_jira_tickets WHERE idempotency_key = %s",
                    (key.text,),
                )
            ).fetchone()
            if existing is not None:
                return str(existing["key"])
            number_row = await (
                await uow.conn.execute(
                    "SELECT coalesce(max(number), 0) + 1 AS number "
                    "FROM orchestration.mock_jira_tickets"
                )
            ).fetchone()
            assert number_row is not None
            number = int(number_row["number"])
            project = str(action.target.get("project", "MOCK"))
            ticket = f"{project}-{number}"
            await uow.conn.execute(
                "INSERT INTO orchestration.mock_jira_tickets "
                "(key, number, project, title, body, created_at, run_id, proposal_id, "
                "idempotency_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    ticket,
                    number,
                    project,
                    str(action.fields.get("title", "")),
                    str(action.fields.get("body", "")),
                    uow.now,
                    key.run_id,
                    key.proposal_id,
                    key.text,
                ),
            )
            return ticket

    async def tickets(self) -> list[MockTicket]:
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    f"SELECT {TICKET_COLUMNS} FROM orchestration.mock_jira_tickets ORDER BY number"
                )
            ).fetchall()
        return [_ticket(row) for row in rows]

    async def mark_done(self, key: str) -> MockTicket | None:
        """Marks a ticket Done. A ticket already Done keeps its first done time."""
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "UPDATE orchestration.mock_jira_tickets SET status = 'Done', "
                    "done_at = coalesce(done_at, %s) WHERE key = %s "
                    f"RETURNING {TICKET_COLUMNS}",
                    (uow.now, key),
                )
            ).fetchone()
        return None if row is None else _ticket(row)

    async def done_tickets(self, keys: Collection[str]) -> Mapping[str, datetime]:
        if not keys:
            return {}
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    "SELECT key, done_at FROM orchestration.mock_jira_tickets "
                    "WHERE key = ANY(%s) AND status = 'Done'",
                    (list(keys),),
                )
            ).fetchall()
        return {str(row["key"]): row["done_at"] for row in rows}


type TicketStatus = Literal["To Do", "Done"]

TICKET_COLUMNS = "key, project, title, body, created_at, run_id, proposal_id, status, done_at"


@dataclass(frozen=True)
class MockTicket:
    key: str
    project: str
    title: str
    body: str
    created_at: datetime
    run_id: RunId
    proposal_id: ProposalId
    status: TicketStatus = "To Do"
    done_at: datetime | None = None


def _ticket(row: Mapping[str, Any]) -> MockTicket:
    status: TicketStatus = "Done" if row["status"] == "Done" else "To Do"
    return MockTicket(
        key=row["key"],
        project=row["project"],
        title=row["title"],
        body=row["body"],
        created_at=row["created_at"],
        run_id=RunId(row["run_id"]),
        proposal_id=ProposalId(row["proposal_id"]),
        status=status,
        done_at=row["done_at"],
    )


CONNECTOR_TIMEOUT = timedelta(seconds=30)


@dataclass(frozen=True)
class Done:
    external_reference: str


@dataclass(frozen=True)
class InFlight:
    started_at: datetime


class WriteGateway:
    def __init__(
        self,
        db: Database,
        connectors: Iterable[WriteConnector],
        connector_timeout: timedelta = CONNECTOR_TIMEOUT,
        poll: float = 0.5,
    ) -> None:
        self._db = db
        self._connectors = {c.name: c for c in connectors}
        self._timeout = connector_timeout
        self._poll = poll

    @property
    def registry(self) -> Registry:
        return registry_of(self._connectors.values())

    async def execute(self, write: AuthorizedWrite) -> tuple[WriteDone, ...]:
        done: list[WriteDone] = []
        for index, action in enumerate(write.proposal.actions):
            reference = await self._execute_one(write.proposal, index, action)
            done.append(WriteDone(action.connector, action.operation, reference, write.approvers))
        return tuple(done)

    async def _execute_one(self, proposal: Proposal, index: int, action: WriteAction) -> str:
        key = WriteKey(proposal.run_id, proposal.id, index)
        while True:
            match await self._record(key):
                case Done(reference):
                    return reference
                case InFlight(started_at) if self._db.clock() - started_at < self._timeout:
                    await asyncio.sleep(self._poll)
                    continue
                case InFlight() | None:
                    pass
            await self._mark_started(key)
            try:
                reference = await self._connectors[action.connector].execute(action, key)
            except Exception as error:
                raise WriteFailed(
                    f"{action.connector} {action.operation} failed: {error}"
                ) from error
            await self._mark_done(key, reference)
            return reference

    async def _record(self, key: WriteKey) -> Done | InFlight | None:
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT status, started_at, external_reference "
                    "FROM orchestration.write_executions WHERE idempotency_key = %s",
                    (key.text,),
                )
            ).fetchone()
        if row is None:
            return None
        if row["status"] == "done":
            return Done(str(row["external_reference"]))
        return InFlight(row["started_at"])

    async def _mark_started(self, key: WriteKey) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.write_executions "
                "(proposal_id, action_index, run_id, idempotency_key, status, started_at) "
                "VALUES (%s, %s, %s, %s, 'started', %s) "
                "ON CONFLICT (idempotency_key) DO UPDATE SET started_at = EXCLUDED.started_at "
                "WHERE orchestration.write_executions.status = 'started'",
                (key.proposal_id, key.index, key.run_id, key.text, uow.now),
            )

    async def _mark_done(self, key: WriteKey, reference: str) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.write_executions SET status = 'done', done_at = %s, "
                "external_reference = %s WHERE idempotency_key = %s",
                (uow.now, reference, key.text),
            )
