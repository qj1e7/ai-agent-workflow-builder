"""Set-up approvals (ADR 0051, flow steps 7 to 9): an Approver's yes to set up one revision of a
drafted workflow, bound to that revision's digest.

The gate is the one every run's request goes through (approvals.py): any Approver on the team who
is not a party decides, a party is refused as own work, and a decision on another digest is
refused. Only one step for now: a workflow that changes someone's access, which needs two, is held
by the builder until build step 10. A request waits two working days, as ADR 0024 says, and a new
revision replaces one that still waits.

After the person's own step the platform posts the request in Teams, shows its outcome there,
and, once approved, has the use case builder set the approved revision up. Each is a job keyed by
our own request id, retried on the run outbox's delays."""

import asyncio
import contextlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol, cast
from zoneinfo import ZoneInfo

from platform_api.db import Database, UnitOfWork, json
from platform_api.orchestration import approvals
from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalStatus,
    ApprovalStep,
    Approved,
    Closed,
    Decision,
    Declined,
    Ended,
    Open,
    Recorded,
    Refusal,
    Refused,
    Verdict,
    approval_status,
)
from platform_api.orchestration.dispatch import (
    RETRY_POLICY,
    ApprovalOutcome,
    DispatchFailure,
    Identity,
    MessageRef,
    OutcomeVerdict,
    RetryPolicy,
    SetUpChannel,
    SetUpNotice,
    without_addresses,
)
from platform_api.orchestration.service import RolesNow
from platform_api.orchestration.working_hours import EXPIRES_AFTER, after_working_time
from platform_api.shared import ApprovalId, Digest, Principal, UserId, new_id

log = logging.getLogger(__name__)

SET_UP_LINK: Final = "/setup-approvals/{approval_id}"
DECLINE_REASONS: Final = ("Too risky without approval", "Wrong project or channel", "Not needed")
"""Why an Approver declines a set-up, picked from a short list (chat-first README, decision 3)."""
type SetUpDeclineReason = Literal[
    "Too risky without approval", "Wrong project or channel", "Not needed"
]
REASONS_NOW: Final[Mapping[str, str]] = {"Too risky without a yes": "Too risky without approval"}
"""A reason recorded before 25 Nov 2026, in the words it reads in now."""
NOTHING_SET_UP: Final = "Nothing was set up."
LEASE: Final = timedelta(minutes=5)
"""Long enough for a set-up to create the workflow in n8n and read it back."""
WORK_EVERY: Final = timedelta(seconds=5)
ENDED_AS: Final[Mapping[str, Ended]] = {"expired": Ended.EXPIRED, "replaced": Ended.CANCELLED}
STORED_AS: Final[Mapping[Ended, str]] = {Ended.EXPIRED: "expired", Ended.CANCELLED: "replaced"}

type JobKind = Literal["announce", "outcome", "set_up"]


def set_up_link(approval_id: ApprovalId) -> str:
    return SET_UP_LINK.format(approval_id=approval_id)


@dataclass(frozen=True)
class SetUpAsk:
    """What the builder sends for approval: one revision, by its digest, with the parties it
    worked out and the words the Teams card shows."""

    drafted_id: str
    revision: int
    digest: Digest
    name: str
    in_short: str
    parties: frozenset[UserId]
    sent_by: UserId


@dataclass(frozen=True)
class SetUpRequest:
    id: ApprovalId
    drafted_id: str
    revision: int
    digest: Digest
    name: str
    in_short: str
    policy: ApprovalPolicy
    parties: frozenset[UserId]
    sent_by: UserId
    created_at: datetime
    expires_at: datetime | None
    ended: Ended | None


@dataclass(frozen=True)
class SetUpState:
    """A request and its decisions, as the builder's views read them."""

    request: SetUpRequest
    status: ApprovalStatus
    decisions: tuple[Decision, ...]
    names: Mapping[UserId, str]
    """The name of the sender and of each person who decided."""
    post: Literal["waiting", "sent", "failed"]
    set_up: Literal["waiting", "done", "failed"] | None
    """None until it is approved."""


@dataclass(frozen=True)
class ApprovedSetUp:
    approval_id: ApprovalId
    drafted_id: str
    revision: int
    digest: Digest
    approvers: tuple[UserId, ...]
    parties: frozenset[UserId]


@dataclass(frozen=True)
class SetUpFinished:
    """Set up, or refused for good with the reason the builder recorded. Never tried again."""


@dataclass(frozen=True)
class TryAgain:
    """n8n did not answer. The job tries again on the outbox's delays."""

    detail: str


class SetUps(Protocol):
    """What the use case builder does once a set-up is approved, which orchestration may not
    import. Each call is for one approval, so asking twice changes nothing."""

    async def set_up(self, approved: ApprovedSetUp) -> SetUpFinished | TryAgain: ...

    async def gave_up(self, approved: ApprovedSetUp, detail: str) -> None: ...


@dataclass(frozen=True)
class Decided:
    status: ApprovalStatus
    decision: Decision
    repeated: bool


@dataclass(frozen=True)
class DecisionRefused:
    reason: Refusal


@dataclass(frozen=True)
class NoSuchRequest:
    pass


type SetUpDecision = Decided | DecisionRefused | NoSuchRequest


class SetUpApprovals:
    def __init__(
        self,
        db: Database,
        channel: SetUpChannel,
        people: RolesNow,
        public_base_url: str,
        time_zone: ZoneInfo,
        retry: RetryPolicy = RETRY_POLICY,
    ) -> None:
        self._db = db
        self._channel = channel
        self._people = people
        self._public_base_url = public_base_url.rstrip("/")
        self._zone = time_zone
        self._retry = retry
        self._setups: SetUps | None = None
        self._wake = asyncio.Event()

    def serve(self, setups: SetUps) -> None:
        """The builder's side, bound once both are built."""
        self._setups = setups

    def nudge(self) -> None:
        self._wake.set()

    async def send(self, ask: SetUpAsk) -> SetUpRequest:
        """A request for this revision. Sending the same revision again while its request still
        waits answers that request."""
        async with self._db.transaction("orchestration") as uow:
            for waiting in await _requests_of(uow, ask.drafted_id, lock=True):
                if waiting.ended is None and not await _decisions(uow, waiting.id):
                    if waiting.revision == ask.revision and waiting.digest == ask.digest:
                        return waiting
                    await self._end(uow, waiting, Ended.CANCELLED)
            request = SetUpRequest(
                id=ApprovalId(new_id("apr")),
                drafted_id=ask.drafted_id,
                revision=ask.revision,
                digest=ask.digest,
                name=ask.name,
                in_short=ask.in_short,
                policy=ApprovalPolicy((ApprovalStep("Any Approver", AnyApprover()),)),
                parties=ask.parties,
                sent_by=ask.sent_by,
                created_at=uow.now,
                expires_at=after_working_time(uow.now, EXPIRES_AFTER, self._zone),
                ended=None,
            )
            await uow.conn.execute(
                "INSERT INTO orchestration.setup_requests (approval_id, drafted_id, revision,"
                " digest, name, in_short, policy, parties, sent_by, created_at, expires_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    request.id,
                    request.drafted_id,
                    request.revision,
                    request.digest,
                    request.name,
                    request.in_short,
                    json([{"label": s.label} for s in request.policy.steps]),
                    json(sorted(request.parties)),
                    request.sent_by,
                    request.created_at,
                    request.expires_at,
                ),
            )
            await _queue(uow, request.id, "announce", uow.now)
        self.nudge()
        return request

    async def replace_waiting(self, drafted_id: str) -> None:
        """A new revision replaces any request for the drafted workflow that still waits."""
        async with self._db.transaction("orchestration") as uow:
            for request in await _requests_of(uow, drafted_id, lock=True):
                if request.ended is None and not await _decisions(uow, request.id):
                    await self._end(uow, request, Ended.CANCELLED)
        self.nudge()

    async def latest(self, drafted_id: str) -> SetUpState | None:
        """The newest request for the drafted workflow, read once, so its words never disagree."""
        async with self._db.transaction("orchestration") as uow:
            requests = await _requests_of(uow, drafted_id)
            return None if not requests else await self._state(uow, requests[-1])

    async def get(self, approval_id: ApprovalId) -> SetUpState | None:
        async with self._db.transaction("orchestration") as uow:
            request = await _request(uow, approval_id)
            return None if request is None else await self._state(uow, request)

    async def names(self, ids: Iterable[UserId]) -> dict[UserId, str]:
        """Each person's name on the People list, or "Someone" for one no longer on it."""
        async with self._db.transaction("orchestration") as uow:
            return await _names(uow, ids)

    async def waiting_for(self, principal: Principal) -> list[SetUpState]:
        """Every set-up approval still waiting that this person may decide now, by the gate's own
        rule, the newest first."""
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    f"SELECT {COLUMNS} FROM orchestration.setup_requests WHERE ended IS NULL"
                    " ORDER BY created_at DESC, approval_id"
                )
            ).fetchall()
            states = [await self._state(uow, _row_request(row)) for row in rows]
            roles = await self._people.roles_now(uow, principal.user_id)
        now = replace(principal, roles=roles or frozenset())
        return [
            state
            for state in states
            if not isinstance(state.status, Approved | Declined | Closed)
            and approvals.why_not(state.request, state.decisions, now) is None
        ]

    async def why_not(self, state: SetUpState, principal: Principal) -> Refusal | None:
        """Why this person can't decide it now, by the gate's own rule, with their roles now."""
        async with self._db.transaction("orchestration") as uow:
            roles = await self._people.roles_now(uow, principal.user_id)
        now = replace(principal, roles=roles or frozenset())
        return approvals.why_not(state.request, state.decisions, now)

    async def decide(
        self,
        approval_id: ApprovalId,
        principal: Principal,
        verdict: Verdict,
        seen_digest: Digest,
        reason: SetUpDeclineReason | None,
    ) -> SetUpDecision:
        """The gate's rules decide alone. A decline needs a reason from the short list, which the
        route holds to; it rides along only on a decline the gate recorded."""
        async with self._db.transaction("orchestration") as uow:
            request = await _request(uow, approval_id, lock=True)
            if request is None:
                return NoSuchRequest()
            decisions = await _decisions(uow, approval_id)
            roles = await self._people.roles_now(uow, principal.user_id)
            principal = replace(principal, roles=roles or frozenset())
            step = next(
                (
                    d.step_index
                    for d in decisions
                    if d.by == principal.user_id and d.verdict is verdict
                ),
                _next_step(request, decisions),
            )
            outcome = approvals.decide(
                request, decisions, principal, step, verdict, seen_digest, uow.now
            )
            if isinstance(outcome, Refused):
                return DecisionRefused(outcome.reason)
            if not isinstance(outcome, Recorded):
                return Decided(approval_status(request, decisions), outcome.decision, True)
            decision = outcome.decision
            if verdict is Verdict.DECLINE:
                decision = replace(decision, reason=reason)
            await _insert_decision(uow, decision)
            status = approval_status(request, (*decisions, decision))
            if isinstance(status, Approved | Declined):
                await _queue(uow, request.id, "outcome", uow.now)
            if isinstance(status, Approved):
                await _queue(uow, request.id, "set_up", uow.now)
        log.info(
            "%s %sd the set-up of %s revision %d",
            principal.user_id,
            verdict.value,
            request.drafted_id,
            request.revision,
        )
        self.nudge()
        return Decided(status, decision, False)

    async def set_up_again(self, approval_id: ApprovalId) -> bool:
        """Tries the set-up of an approved request again, once its job gave up. False when there
        is nothing to try again."""
        async with self._db.transaction("orchestration") as uow:
            done = await uow.conn.execute(
                "UPDATE orchestration.setup_jobs SET gave_up_at = NULL, attempt = 0,"
                " next_at = %s, error = NULL"
                " WHERE approval_id = %s AND kind = 'set_up' AND gave_up_at IS NOT NULL",
                (uow.now, approval_id),
            )
            again = done.rowcount == 1
        self.nudge()
        return again

    async def work_forever(self, stop: asyncio.Event, every: timedelta = WORK_EVERY) -> None:
        while not stop.is_set():
            try:
                await self.work_once()
            except Exception:
                log.exception("the set-up approvals' jobs failed")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), every.total_seconds())

    async def work_once(self, now: datetime | None = None) -> None:
        """Ends the requests nobody answered in time, then does every job that is due."""
        now = now or self._db.clock()
        await self._expire(now)
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    "SELECT approval_id, kind, attempt FROM orchestration.setup_jobs"
                    " WHERE done_at IS NULL AND gave_up_at IS NULL AND next_at <= %s"
                    " ORDER BY next_at FOR UPDATE SKIP LOCKED",
                    (now,),
                )
            ).fetchall()
            for row in rows:
                await uow.conn.execute(
                    "UPDATE orchestration.setup_jobs SET next_at = %s, attempt = attempt + 1"
                    " WHERE approval_id = %s AND kind = %s",
                    (now + LEASE, row["approval_id"], row["kind"]),
                )
        for row in rows:
            approval_id, kind = ApprovalId(row["approval_id"]), row["kind"]
            try:
                failed = await self._job(approval_id, kind)
            except DispatchFailure as error:
                failed = str(error)
            except Exception as error:
                log.exception("set-up job %s of %s failed", kind, approval_id)
                failed = f"the job could not be done ({type(error).__name__})"
            await self._after(approval_id, kind, int(row["attempt"]) + 1, failed, now)

    async def _job(self, approval_id: ApprovalId, kind: JobKind) -> str | None:
        """None when done, else why it failed, for a try again."""
        async with self._db.transaction("orchestration") as uow:
            request = await _request(uow, approval_id)
            assert request is not None
            state = await self._state(uow, request)
            names = await _names(uow, request.parties | {request.sent_by})
        match kind:
            case "announce":
                notice = SetUpNotice(
                    approval_id=request.id,
                    name=request.name,
                    in_short=request.in_short,
                    sent_by=names[request.sent_by],
                    link=set_up_link(request.id),
                    open_url=f"{self._public_base_url}{set_up_link(request.id)}",
                    not_deciding=tuple(sorted({names[p] for p in request.parties})),
                )
                ref = await self._channel.announce_set_up(notice)
                async with self._db.transaction("orchestration") as uow:
                    await uow.conn.execute(
                        "UPDATE orchestration.setup_requests SET message = %s"
                        " WHERE approval_id = %s",
                        (
                            json({"channel": ref.channel, "id": ref.id, "identity": ref.identity}),
                            request.id,
                        ),
                    )
                return None
            case "outcome":
                ref = await self._message(request.id)
                if ref is None:
                    return "it was never posted in Teams"
                await self._channel.update(ref, self._outcome(request, state))
                return None
            case "set_up":
                setups = self._setups
                assert setups is not None
                match await setups.set_up(_approved(state)):
                    case SetUpFinished():
                        return None
                    case TryAgain(detail):
                        return detail

    async def _after(
        self, approval_id: ApprovalId, kind: JobKind, tried: int, failed: str | None, now: datetime
    ) -> None:
        async with self._db.transaction("orchestration") as uow:
            if failed is None:
                await uow.conn.execute(
                    "UPDATE orchestration.setup_jobs SET done_at = %s, error = NULL"
                    " WHERE approval_id = %s AND kind = %s",
                    (uow.now, approval_id, kind),
                )
                return
            said = without_addresses(failed)
            log.warning("set-up job %s of %s failed on try %d: %s", kind, approval_id, tried, said)
            if tried <= len(self._retry.delays):
                await uow.conn.execute(
                    "UPDATE orchestration.setup_jobs SET next_at = %s, error = %s"
                    " WHERE approval_id = %s AND kind = %s",
                    (now + self._retry.delays[tried - 1], said, approval_id, kind),
                )
                return
            await uow.conn.execute(
                "UPDATE orchestration.setup_jobs SET gave_up_at = %s, error = %s"
                " WHERE approval_id = %s AND kind = %s",
                (uow.now, said, approval_id, kind),
            )
            request = await _request(uow, approval_id)
            assert request is not None
            state = await self._state(uow, request)
        if kind == "set_up" and self._setups is not None:
            await self._setups.gave_up(_approved(state), said)

    async def _expire(self, now: datetime) -> None:
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    "SELECT approval_id FROM orchestration.setup_requests r"
                    " WHERE r.ended IS NULL AND r.expires_at <= %s AND NOT EXISTS"
                    " (SELECT 1 FROM orchestration.setup_decisions d"
                    "  WHERE d.approval_id = r.approval_id)",
                    (now,),
                )
            ).fetchall()
        for row in rows:
            async with self._db.transaction("orchestration") as uow:
                request = await _request(uow, ApprovalId(row["approval_id"]), lock=True)
                if (
                    request is not None
                    and request.ended is None
                    and not await _decisions(uow, request.id)
                ):
                    await self._end(uow, request, Ended.EXPIRED)

    async def _end(self, uow: UnitOfWork, request: SetUpRequest, ended: Ended) -> None:
        await uow.conn.execute(
            "UPDATE orchestration.setup_requests SET ended = %s, ended_at = %s"
            " WHERE approval_id = %s AND ended IS NULL",
            (STORED_AS[ended], uow.now, request.id),
        )
        await _queue(uow, request.id, "outcome", uow.now)

    async def _state(self, uow: UnitOfWork, request: SetUpRequest) -> SetUpState:
        decisions = tuple(await _decisions(uow, request.id))
        names = await _names(uow, {request.sent_by, *(d.by for d in decisions)})
        jobs = {
            row["kind"]: row
            for row in await (
                await uow.conn.execute(
                    "SELECT kind, done_at, gave_up_at FROM orchestration.setup_jobs"
                    " WHERE approval_id = %s",
                    (request.id,),
                )
            ).fetchall()
        }
        status = approval_status(request, decisions)
        posted = _job_state(jobs.get("announce"))
        set_up = _job_state(jobs.get("set_up"))
        return SetUpState(
            request,
            status,
            decisions,
            names,
            "sent" if posted == "done" else posted,
            set_up if isinstance(status, Approved) else None,
        )

    async def _message(self, approval_id: ApprovalId) -> MessageRef | None:
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT message FROM orchestration.setup_requests WHERE approval_id = %s",
                    (approval_id,),
                )
            ).fetchone()
        held: object = None if row is None else row["message"]
        if not isinstance(held, dict):
            return None
        kept = cast(dict[str, str], held)
        return MessageRef(
            channel=kept["channel"], id=kept["id"], identity=Identity(kept["identity"])
        )

    def _outcome(self, request: SetUpRequest, state: SetUpState) -> ApprovalOutcome:
        verdict: OutcomeVerdict
        by: tuple[str, ...] = ()
        reason = None
        match state.status:
            case Approved(approvers):
                verdict, by = "approved", tuple(state.names[a] for a in approvers)
            case Declined(decider, _):
                verdict, by = "declined", (state.names[decider],)
                reason = next((d.reason for d in state.decisions if d.by == decider), None)
            case _:
                verdict = "expired" if request.ended is Ended.EXPIRED else "replaced"
        return ApprovalOutcome(
            verdict=verdict,
            by=by,
            use_case_name=request.name,
            open_url=f"{self._public_base_url}{set_up_link(request.id)}",
            reason=reason,
            nothing=NOTHING_SET_UP,
        )


def _approved(state: SetUpState) -> ApprovedSetUp:
    request, status = state.request, state.status
    assert isinstance(status, Approved)
    return ApprovedSetUp(
        request.id,
        request.drafted_id,
        request.revision,
        request.digest,
        status.approvers,
        request.parties,
    )


def _job_state(row: Mapping[str, Any] | None) -> Literal["waiting", "done", "failed"]:
    if row is None or (row["done_at"] is None and row["gave_up_at"] is None):
        return "waiting"
    return "done" if row["done_at"] is not None else "failed"


def _next_step(request: SetUpRequest, decisions: Sequence[Decision]) -> int:
    status = approval_status(request, decisions)
    return status.next_step if isinstance(status, Open) else len(decisions)


async def _queue(uow: UnitOfWork, approval_id: ApprovalId, kind: JobKind, at: datetime) -> None:
    await uow.conn.execute(
        "INSERT INTO orchestration.setup_jobs (approval_id, kind, next_at) VALUES (%s, %s, %s)"
        " ON CONFLICT (approval_id, kind) DO NOTHING",
        (approval_id, kind, at),
    )


def _row_request(row: Mapping[str, Any]) -> SetUpRequest:
    return SetUpRequest(
        id=ApprovalId(row["approval_id"]),
        drafted_id=row["drafted_id"],
        revision=int(row["revision"]),
        digest=Digest(row["digest"]),
        name=row["name"],
        in_short=row["in_short"],
        policy=ApprovalPolicy(
            tuple(ApprovalStep(str(s["label"]), AnyApprover()) for s in row["policy"])
        ),
        parties=frozenset(UserId(p) for p in row["parties"]),
        sent_by=UserId(row["sent_by"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        ended=None if row["ended"] is None else ENDED_AS[row["ended"]],
    )


COLUMNS: Final = (
    "approval_id, drafted_id, revision, digest, name, in_short, policy, parties, sent_by,"
    " created_at, expires_at, ended"
)


async def _request(
    uow: UnitOfWork, approval_id: ApprovalId, lock: bool = False
) -> SetUpRequest | None:
    row = await (
        await uow.conn.execute(
            f"SELECT {COLUMNS} FROM orchestration.setup_requests WHERE approval_id = %s"
            + (" FOR UPDATE" if lock else ""),
            (approval_id,),
        )
    ).fetchone()
    return None if row is None else _row_request(row)


async def _requests_of(uow: UnitOfWork, drafted_id: str, lock: bool = False) -> list[SetUpRequest]:
    rows = await (
        await uow.conn.execute(
            f"SELECT {COLUMNS} FROM orchestration.setup_requests WHERE drafted_id = %s"
            " ORDER BY created_at, approval_id" + (" FOR UPDATE" if lock else ""),
            (drafted_id,),
        )
    ).fetchall()
    return [_row_request(row) for row in rows]


async def _decisions(uow: UnitOfWork, approval_id: ApprovalId) -> list[Decision]:
    rows = await (
        await uow.conn.execute(
            "SELECT approval_id, step_index, by, verdict, seen_digest, at, reason"
            " FROM orchestration.setup_decisions WHERE approval_id = %s ORDER BY step_index",
            (approval_id,),
        )
    ).fetchall()
    return [
        Decision(
            ApprovalId(row["approval_id"]),
            int(row["step_index"]),
            UserId(row["by"]),
            Verdict(row["verdict"]),
            Digest(row["seen_digest"]),
            row["at"],
            REASONS_NOW.get(row["reason"], row["reason"]),
        )
        for row in rows
    ]


async def _insert_decision(uow: UnitOfWork, decision: Decision) -> None:
    await uow.conn.execute(
        "INSERT INTO orchestration.setup_decisions (approval_id, step_index, by, verdict,"
        " seen_digest, at, reason) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            decision.approval_id,
            decision.step_index,
            decision.by,
            decision.verdict.value,
            decision.seen_digest,
            decision.at,
            decision.reason,
        ),
    )


async def _names(uow: UnitOfWork, ids: Iterable[UserId]) -> dict[UserId, str]:
    wanted = list(dict.fromkeys(ids))
    rows = await (
        await uow.conn.execute(
            "SELECT id, display FROM orchestration.people WHERE id = ANY(%s)", (wanted,)
        )
    ).fetchall()
    found = {UserId(row["id"]): str(row["display"]) for row in rows}
    return {user: found.get(user, "Someone") for user in wanted}
