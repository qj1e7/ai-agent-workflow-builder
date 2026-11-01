import asyncio
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

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


def one_line(text: str, limit: int) -> str:
    """text on one line and cut to limit characters, with an ellipsis when cut.

    Every piece of model-written text that people read goes through here, so it cannot break
    out of the sentence the platform wrote around it.
    """
    flat = " ".join(text.split())
    if len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return flat


TITLE_LIMIT = 120
TITLES_SHOWN = 5


def shown_title(action: WriteAction) -> str:
    """The ticket title as people read it. The stored field and the digest keep the agent's text."""
    return one_line(str(action.fields.get("title", "")).replace('"', ""), TITLE_LIMIT)


def _is_ticket(action: WriteAction) -> bool:
    return action.connector == "jira" and action.operation == "create_ticket"


def describe(action: WriteAction) -> ActionLine:
    if _is_ticket(action):
        project = action.target.get("project", "?")
        return ActionLine(
            connector="jira",
            operation="create_ticket",
            line=f"Create Jira ticket in {project}: {shown_title(action)}",
        )
    return ActionLine(
        connector=action.connector,
        operation=action.operation,
        line=f"{action.operation} on {action.connector}",
    )


def _ticket_phrase(project: str, title: str) -> str:
    return f'create a Jira ticket in {project} titled "{title}"'


def intent(action: WriteAction) -> str:
    if _is_ticket(action):
        return _ticket_phrase(str(action.target.get("project", "?")), shown_title(action))
    return f"{action.operation} on {action.connector}"


def listed(items: Sequence[str]) -> str:
    """Items as English reads them: "a", "a and b", "a, b and c"."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def intents(actions: Sequence[WriteAction]) -> tuple[str, ...]:
    """One phrase per kind of write. Tickets for one project become one phrase that names each
    title, so a check with many tickets still reads as one sentence."""
    phrases: list[str] = []
    titles: dict[str, list[str]] = {}
    slot: dict[str, int] = {}
    for action in actions:
        if not _is_ticket(action):
            phrases.append(intent(action))
            continue
        project = str(action.target.get("project", "?"))
        if project not in titles:
            slot[project] = len(phrases)
            phrases.append("")
            titles[project] = []
        titles[project].append(shown_title(action))
    for project, group in titles.items():
        if len(group) == 1:
            phrases[slot[project]] = _ticket_phrase(project, group[0])
            continue
        quoted = [f'"{title}"' for title in group[:TITLES_SHOWN]]
        more = len(group) - len(quoted)
        shown = listed(quoted) if more == 0 else f"{', '.join(quoted)} and {more} more"
        phrases[slot[project]] = f"create {len(group)} Jira tickets in {project}: {shown}"
    return tuple(phrases)


class WriteFailed(Exception):
    """A write did not happen. When retryable, a retry of the run may make it."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class WriteRefused(Exception):
    """The other system refused the write itself, such as a missing project or no permission.
    A connector raises it so the run says to start again, not to retry (ADR 0035)."""


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

    def link(self, reference: str) -> str | None:
        """Where people open what execute made, or None when it has no page."""
        ...


def registry_of(connectors: Iterable[WriteConnector]) -> Registry:
    return {connector.name: connector.operations for connector in connectors}


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
            link = self._connectors[action.connector].link(reference)
            done.append(
                WriteDone(action.connector, action.operation, reference, write.approvers, link)
            )
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
            except WriteRefused as refused:
                raise WriteFailed(
                    f"{action.connector} {action.operation} was refused: {refused}", retryable=False
                ) from refused
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
