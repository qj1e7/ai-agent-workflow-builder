import asyncio
import hashlib
import json
from collections.abc import Collection, Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol

import psycopg

from platform_api.db import Database, UnitOfWork
from platform_api.monitoring import ActionLine
from platform_api.orchestration.approvals import (
    ApprovalRequest,
    ApprovalStatus,
    Approved,
    Closed,
    Decision,
    Ended,
    Invalid,
    approval_status,
)
from platform_api.orchestration.dispatch import Identity
from platform_api.orchestration.runs import Acting, Failure, FailureReason, WriteDone
from platform_api.shared import ApprovalId, Digest, ProposalId, RunId, UseCaseId, UserId

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
    subject: str | None = None
    """What the change is about, such as the release a ticket is for, when the block that
    proposed it names it. A use case makes each subject once across all its runs (ADR 0026). The
    digest leaves it out: the Approver says yes to the change, and the subject only keys it."""


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


@dataclass(frozen=True)
class Site:
    """Where a connector writes now, such as one Jira (ADR 0041). Its identity goes in each
    action's target, so the Approver's yes covers it, and the safety checker compares it with the
    connector's at the write. Its name is how people read it, and is never stored."""

    identity: Identity
    name: str


type Sites = Mapping[str, Site]

GONE_SITE = "a Jira that is no longer set up"


def at_sites(actions: Iterable[WriteAction], sites: Sites) -> tuple[WriteAction, ...]:
    """The actions, each with the site its connector writes to now in its target. An action whose
    connector has no site gets none, and the safety checker denies it."""
    return tuple(
        replace(action, target={**action.target, "site": sites[action.connector].identity})
        if action.connector in sites
        else action
        for action in actions
    )


def site_name(action: WriteAction, sites: Sites) -> str:
    """Where the action writes, as people read it. A target with another site than its
    connector's now, or with none, names a place the platform no longer writes to."""
    now = sites.get(action.connector)
    if now is not None and action.target.get("site") == now.identity:
        return now.name
    return GONE_SITE


class DenyReason(Enum):
    RUN_MISMATCH = "run_mismatch"
    NOT_APPROVED = "not_approved"
    INVALID_DECISIONS = "invalid_decisions"
    DIGEST_MISMATCH = "digest_mismatch"
    UNREGISTERED_ACTION = "unregistered_action"
    TARGET_CHANGED = "target_changed"
    EXPIRED = "expired"
    TEST_RUN = "test_run"


@dataclass(frozen=True)
class Deny:
    reason: DenyReason


@dataclass(frozen=True)
class WritingRun:
    """What the safety checker reads from the run beside its state: the use case, which keys
    each subject's write, and whether it is a test run, which never writes."""

    use_case_id: UseCaseId
    test: bool


@dataclass(frozen=True, init=False)
class AuthorizedWrite:
    proposal: Proposal
    approval_id: ApprovalId
    approvers: tuple[UserId, ...]
    use_case_id: UseCaseId

    def __init__(self) -> None:
        raise TypeError("only check() issues an AuthorizedWrite")


def _issue(
    proposal: Proposal,
    approval_id: ApprovalId,
    approvers: tuple[UserId, ...],
    use_case_id: UseCaseId,
) -> AuthorizedWrite:
    write = object.__new__(AuthorizedWrite)
    object.__setattr__(write, "proposal", proposal)
    object.__setattr__(write, "approval_id", approval_id)
    object.__setattr__(write, "approvers", approvers)
    object.__setattr__(write, "use_case_id", use_case_id)
    return write


def _expired(
    request: ApprovalRequest, decisions: Iterable[Decision], status: ApprovalStatus
) -> bool:
    """The request reached its expiry without its yes: it ended unanswered, or its last yes came
    after the expiry, before the tick ended it. A yes given in time stays good after the expiry,
    so a wake n8n takes late, or a lost run carried on, still writes."""
    match status:
        case Closed(ended=Ended.EXPIRED):
            return True
        case Approved() if request.expires_at is not None:
            yeses = (d.at for d in decisions if d.approval_id == request.id)
            return any(at > request.expires_at for at in yeses)
        case _:
            return False


def check(
    acting: Acting,
    run: WritingRun,
    proposal: Proposal,
    request: ApprovalRequest,
    decisions: Iterable[Decision],
    registry: Registry,
    sites: Sites,
) -> AuthorizedWrite | Deny:
    same_run = (
        acting.run_id == proposal.run_id == request.run_id
        and acting.proposal_id == proposal.id == request.proposal_id
        and acting.approval_id == request.id
    )
    if not same_run:
        return Deny(DenyReason.RUN_MISMATCH)
    if run.test:
        return Deny(DenyReason.TEST_RUN)
    decisions = tuple(decisions)
    status = approval_status(request, decisions)
    if isinstance(status, Invalid):
        return Deny(DenyReason.INVALID_DECISIONS)
    if _expired(request, decisions, status):
        return Deny(DenyReason.EXPIRED)
    if not isinstance(status, Approved):
        return Deny(DenyReason.NOT_APPROVED)
    if digest(proposal.actions) != request.digest:
        return Deny(DenyReason.DIGEST_MISMATCH)
    for action in proposal.actions:
        if action.operation not in registry.get(action.connector, frozenset()):
            return Deny(DenyReason.UNREGISTERED_ACTION)
        now = sites.get(action.connector)
        if now is None or action.target.get("site") != now.identity:
            return Deny(DenyReason.TARGET_CHANGED)
    return _issue(proposal, request.id, status.approvers, run.use_case_id)


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


def _line(action: WriteAction, where: str) -> ActionLine:
    if _is_ticket(action):
        project = action.target.get("project", "?")
        return ActionLine(
            connector="jira",
            operation="create_ticket",
            line=f"Create Jira ticket in {project}{where}: {shown_title(action)}",
        )
    return ActionLine(
        connector=action.connector,
        operation=action.operation,
        line=f"{action.operation} on {action.connector}",
    )


def describe(action: WriteAction) -> ActionLine:
    return _line(action, "")


def describe_at(action: WriteAction, sites: Sites) -> ActionLine:
    """describe()'s line with the Jira named, for the Approver to read before saying yes."""
    return _line(action, f" on {site_name(action, sites)}")


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
    subject: str | None = None
    """The subject's key across every run of the use case, when the action names a subject."""

    @property
    def text(self) -> str:
        """What the write is made under: its subject's key, else this action of this proposal."""
        return self.subject or f"{self.run_id}/{self.proposal_id}/{self.index}"


def subject_key(use_case_id: str, subject: str) -> str:
    """One key per use case and subject, of fixed length and safe as a Jira label."""
    hashed = hashlib.sha256(f"{use_case_id}\n{subject}".encode()).hexdigest()[:40]
    return f"subject/{hashed}"


def write_key(use_case_id: str, proposal: Proposal, index: int) -> WriteKey:
    subject = proposal.actions[index].subject
    across = None if subject is None else subject_key(use_case_id, subject)
    return WriteKey(proposal.run_id, proposal.id, index, across)


async def made_subjects(uow: UnitOfWork, keys: Collection[str]) -> dict[str, RunId]:
    """Which of these subject keys are made, each with the run whose write made it."""
    if not keys:
        return {}
    rows = await (
        await uow.conn.execute(
            "SELECT idempotency_key, run_id FROM orchestration.write_executions "
            "WHERE status = 'done' AND idempotency_key = ANY(%s)",
            (list(keys),),
        )
    ).fetchall()
    return {row["idempotency_key"]: RunId(row["run_id"]) for row in rows}


def still_to_make(
    use_case_id: str, actions: Sequence[WriteAction], made: Mapping[str, RunId]
) -> tuple[tuple[WriteAction, ...], tuple[str, ...]]:
    """The actions to ask a yes for, and a sentence for each one left out: an earlier run made
    its subject, or an action before it here has the same subject. Approvers see only what will
    be made, and the run's log says what was left out."""
    kept: list[WriteAction] = []
    left_out: list[str] = []
    seen: set[str] = set()
    for action in actions:
        if action.subject is None:
            kept.append(action)
            continue
        key = subject_key(use_case_id, action.subject)
        line = describe(action).line
        if key in made:
            left_out.append(f"Left out, already made in run {made[key]}: {line}.")
        elif key in seen:
            left_out.append(f"Left out, proposed twice: {line}.")
        else:
            seen.add(key)
            kept.append(action)
    return tuple(kept), tuple(left_out)


class WriteConnector(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def operations(self) -> frozenset[str]: ...

    @property
    def site(self) -> Site: ...

    async def execute(self, action: WriteAction, key: WriteKey) -> str: ...

    def link(self, reference: str) -> str | None:
        """Where people open what execute made, or None when it has no page."""
        ...


def registry_of(connectors: Iterable[WriteConnector]) -> Registry:
    return {connector.name: connector.operations for connector in connectors}


def sites_of(connectors: Iterable[WriteConnector]) -> Sites:
    return {connector.name: connector.site for connector in connectors}


CONNECTOR_TIMEOUT = timedelta(seconds=30)


@dataclass(frozen=True)
class Done:
    external_reference: str
    run_id: RunId


@dataclass(frozen=True)
class InFlight:
    started_at: datetime


@dataclass(frozen=True)
class Made:
    """A change this run made, by this try or an earlier one."""

    done: WriteDone
    now: bool
    """This try made it, so it is logged now. An earlier try logged its own."""


@dataclass(frozen=True)
class MadeBefore:
    """A change whose subject another run of the use case made first, so this run skips it."""

    action: WriteAction
    external_reference: str
    url: str | None
    run_id: RunId


@dataclass(frozen=True)
class NotMade:
    action: WriteAction
    why: str


type ActionResult = Made | MadeBefore | NotMade

NOT_TRIED = "Not tried, because a change before it failed."


@dataclass(frozen=True)
class Carried:
    """What the gateway did with an approved proposal, change by change, in order. It stops at
    the first change that fails, so a retry makes only the changes still to make."""

    results: tuple[ActionResult, ...]
    failure: Failure | None

    @property
    def made(self) -> int:
        """The changes that exist now, whichever run made them."""
        return sum(1 for result in self.results if not isinstance(result, NotMade))

    @property
    def written(self) -> tuple[WriteDone, ...]:
        return tuple(result.done for result in self.results if isinstance(result, Made))

    @property
    def fresh(self) -> tuple[WriteDone, ...]:
        """What this try wrote, which is what it logs."""
        return tuple(r.done for r in self.results if isinstance(r, Made) and r.now)


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

    @property
    def sites(self) -> Sites:
        return sites_of(self._connectors.values())

    async def execute(self, write: AuthorizedWrite) -> Carried:
        proposal = write.proposal
        results: list[ActionResult] = []
        failure: Failure | None = None
        for index, action in enumerate(proposal.actions):
            if failure is not None:
                results.append(NotMade(action, NOT_TRIED))
                continue
            try:
                reference, run_id, now = await self._execute_one(
                    write_key(write.use_case_id, proposal, index), action
                )
            except WriteFailed as error:
                failure = Failure(FailureReason.WRITE_FAILED, str(error), error.retryable)
                results.append(NotMade(action, str(error)))
                continue
            link = self._connectors[action.connector].link(reference)
            if run_id != proposal.run_id:
                results.append(MadeBefore(action, reference, link, run_id))
                continue
            done = WriteDone(action.connector, action.operation, reference, write.approvers, link)
            results.append(Made(done, now))
        return Carried(tuple(results), failure)

    async def _execute_one(self, key: WriteKey, action: WriteAction) -> tuple[str, RunId, bool]:
        """What the key's write made, the run whose write made it, and whether this try did."""
        while True:
            match await self._record(key):
                case Done(reference, run_id):
                    return reference, run_id, False
                case InFlight(started_at) if self._db.clock() - started_at < self._timeout:
                    await asyncio.sleep(self._poll)
                    continue
                case InFlight() | None:
                    pass
            if not await self._claim(key):
                # Another try claimed this key between our read and our claim.
                await asyncio.sleep(self._poll)
                continue
            try:
                reference = await self._connectors[action.connector].execute(action, key)
            except WriteRefused as refused:
                await self._release(key)
                raise WriteFailed(
                    f"{action.connector} {action.operation} was refused: {refused}", retryable=False
                ) from refused
            except Exception as error:
                await self._release(key)
                raise WriteFailed(
                    f"{action.connector} {action.operation} failed: {error}"
                ) from error
            await self._mark_done(key, reference)
            return reference, key.run_id, True

    async def _record(self, key: WriteKey) -> Done | InFlight | None:
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT status, started_at, external_reference, run_id "
                    "FROM orchestration.write_executions WHERE idempotency_key = %s",
                    (key.text,),
                )
            ).fetchone()
        if row is None:
            return None
        if row["status"] == "done":
            return Done(str(row["external_reference"]), RunId(row["run_id"]))
        return InFlight(row["started_at"])

    async def _claim(self, key: WriteKey) -> bool:
        """Claims the key in one statement: a new row, or a started one whose try is older than
        the in-flight timeout. False means another try holds it or it is done, so two tries
        never call the connector for one key at once.

        The table has a second unique key, (proposal_id, action_index), which ON CONFLICT does not
        name. Two tries that insert at the same moment can meet there instead, and that means
        the same thing: another try holds the key."""
        try:
            async with self._db.transaction("orchestration") as uow:
                row = await (
                    await uow.conn.execute(
                        "INSERT INTO orchestration.write_executions "
                        "(proposal_id, action_index, run_id, idempotency_key, status, started_at) "
                        "VALUES (%s, %s, %s, %s, 'started', %s) "
                        "ON CONFLICT (idempotency_key) "
                        "DO UPDATE SET started_at = EXCLUDED.started_at "
                        "WHERE orchestration.write_executions.status = 'started' "
                        "AND orchestration.write_executions.started_at <= %s "
                        "RETURNING idempotency_key",
                        (
                            key.proposal_id,
                            key.index,
                            key.run_id,
                            key.text,
                            uow.now,
                            uow.now - self._timeout,
                        ),
                    )
                ).fetchone()
        except psycopg.errors.UniqueViolation:
            return False
        return row is not None

    async def _release(self, key: WriteKey) -> None:
        """This try failed and stopped, so the next try may claim the key at once instead of
        after the in-flight timeout. The connector keeps its own record of each key, so a change
        the failed try did make is found there, not made twice."""
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.write_executions SET started_at = %s "
                "WHERE idempotency_key = %s AND status = 'started'",
                (datetime.fromtimestamp(0, UTC), key.text),
            )

    async def _mark_done(self, key: WriteKey, reference: str) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.write_executions SET status = 'done', done_at = %s, "
                "external_reference = %s WHERE idempotency_key = %s",
                (uow.now, reference, key.text),
            )
