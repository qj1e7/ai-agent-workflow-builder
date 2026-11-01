import asyncio
import contextlib
import logging
import traceback
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from platform_api.db import Database, UnitOfWork
from platform_api.monitoring import (
    PLATFORM,
    SAFETY_CHECKER,
    ActivityEvent,
    AgentEvent,
    ApprovalAnnouncedData,
    ApprovalAnnounceFailedData,
    ApprovalDecidedData,
    DeniedReason,
    PendingEvent,
    WireVerdict,
    WriteActionDeniedData,
    user_actor,
)
from platform_api.orchestration import approvals
from platform_api.orchestration.agents import (
    AgentRejected,
    AgentRuntime,
    AgentUnavailable,
    Callback,
    CardsInputs,
    CardToRun,
    CarryForward,
    GithubSource,
    ModelAccess,
    SoftwareToCheck,
    TaskFailed,
    TaskFinished,
    TaskOutput,
    TaskRequest,
    WatchlistInputs,
)
from platform_api.orchestration.approvals import (
    AlreadyRecorded,
    ApprovalRequest,
    ApprovalStatus,
    Approved,
    Decision,
    Declined,
    Open,
    Recorded,
    Refusal,
    Refused,
    Verdict,
    approval_status,
)
from platform_api.orchestration.cards import ReviewedCards, bind_cards, review_cards
from platform_api.orchestration.dispatch import (
    RETRY_POLICY,
    ApprovalChannel,
    ApprovalNotice,
    ApprovalOutcome,
    AskedStep,
    DispatchFailure,
    MessageRef,
    OutcomeVerdict,
    RetryPolicy,
    WorkflowEngine,
    without_addresses,
)
from platform_api.orchestration.person_runs import PersonRuns, runs_of
from platform_api.orchestration.runs import (
    PLANNER,
    Acting,
    AwaitingApproval,
    Begin,
    Failed,
    Failure,
    FailureReason,
    Leg,
    Moved,
    Pending,
    Proposed,
    Refuse,
    Rejected,
    Replay,
    RunState,
    StepName,
    Succeeded,
    Supersede,
    Working,
    created_events,
    deadline,
    fail,
    holder_of,
    referee,
    state_name,
    step_finished,
)
from platform_api.orchestration.spec import (
    CardsTask,
    RunSpec,
    RunStarted,
    WatchlistTask,
)
from platform_api.orchestration.store import (
    ANNOUNCE,
    SHOW_OUTCOME,
    START_LEG,
    DecisionConflict,
    OutboxRow,
    RunRecord,
    Store,
)
from platform_api.orchestration.watch import Reviewed, Unusable, all_could_not_read, review
from platform_api.orchestration.watch_store import WatchStore
from platform_api.orchestration.write_actions import (
    AuthorizedWrite,
    Deny,
    DenyReason,
    Proposal,
    ProposedIntent,
    UnboundIntent,
    WriteFailed,
    WriteGateway,
    bind,
    check,
    describe,
    digest,
    intents,
)
from platform_api.shared import (
    ApprovalId,
    Digest,
    N8nExecutionId,
    Principal,
    ProposalId,
    Role,
    RunId,
    TaskId,
    UserId,
    new_id,
)
from platform_api.wire import ApprovalStepView, StepOutcome

log = logging.getLogger(__name__)


class ActivityLogPort(Protocol):
    async def append(
        self, uow: UnitOfWork, run_id: RunId, events: Iterable[PendingEvent]
    ) -> list[ActivityEvent]: ...

    async def last_seqs(self, uow: UnitOfWork, run_ids: Collection[RunId]) -> dict[RunId, int]: ...

    async def ingest_agent_events(
        self, uow: UnitOfWork, run_id: RunId, task_id: TaskId, events: Iterable[AgentEvent]
    ) -> list[ActivityEvent]: ...


type CallbackMinter = Callable[[RunId, TaskId, datetime], tuple[str, str]]
"""Mints the agent's callback `(url, token)` for a task. The same inputs give the same token."""


@dataclass(frozen=True)
class StepReply:
    proceed: bool
    outcome: StepOutcome
    detail: str


class RetryLater(Exception): ...


@dataclass(frozen=True)
class RunDetail:
    record: RunRecord
    last_seq: int
    proposal: Proposal | None
    approval: ApprovalRequest | None
    decisions: tuple[Decision, ...]


def _links(state: RunState) -> tuple[ProposalId | None, ApprovalId | None]:
    match state:
        case Proposed(proposal_id=pid):
            return pid, None
        case (
            AwaitingApproval(proposal_id=pid, approval_id=aid)
            | Acting(proposal_id=pid, approval_id=aid)
            | Rejected(proposal_id=pid, approval_id=aid)
        ):
            return pid, aid
        case _:
            return None, None


@dataclass(frozen=True)
class ApprovalDetail:
    request: ApprovalRequest
    proposal: Proposal
    decisions: tuple[Decision, ...]
    why_not: Refusal | None


@dataclass(frozen=True)
class Decided:
    status: ApprovalStatus
    decision: Decision
    repeated: bool


@dataclass(frozen=True)
class DecisionRefused:
    reason: Refusal


@dataclass(frozen=True)
class DecisionRace:
    pass


@dataclass(frozen=True)
class NotFound:
    pass


type DecisionResult = Decided | DecisionRefused | DecisionRace | NotFound


@dataclass(frozen=True)
class Retried:
    state: Pending | Acting


@dataclass(frozen=True)
class NotRetryable:
    detail: str


type RetryResult = Retried | NotRetryable | NotFound


def approval_link(approval_id: ApprovalId) -> str:
    return f"/approvals/{approval_id}"


async def _through_channel[T](call: Awaitable[T]) -> T:
    """An adapter's call, with any error it raises as a DispatchFailure. Anything else would end
    the whole tick, and the next tick would meet the same message first."""
    try:
        return await call
    except DispatchFailure:
        raise
    except Exception as error:
        # The traceback helps a maintainer, but an adapter's error may name a secret address.
        log.error("the Teams adapter failed: %s", without_addresses(traceback.format_exc()))
        raise DispatchFailure(f"the Teams adapter failed ({type(error).__name__})") from None


def _asked_steps(request: ApprovalRequest, names: Mapping[UserId, str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for step in request.policy.steps:
        match step.eligible:
            case approvals.AnyApprover():
                who: list[str] = []
            case approvals.OneOf(users):
                who = sorted({names[u] for u in users})
        steps.append({"label": step.label, "who": who})
    return steps


def _notice_people(request: ApprovalRequest) -> set[UserId]:
    people = set(request.parties)
    for step in request.policy.steps:
        if isinstance(step.eligible, approvals.OneOf):
            people |= step.eligible.users
    return people


def steps_view(request: ApprovalRequest, decisions: Iterable[Decision]) -> list[ApprovalStepView]:
    by_step = {d.step_index: d for d in decisions if d.approval_id == request.id}
    views: list[ApprovalStepView] = []
    open_seen = False
    for index, step in enumerate(request.policy.steps):
        decision = by_step.get(index)
        if decision is not None:
            status = "approved" if decision.verdict is Verdict.APPROVE else "declined"
            views.append(
                ApprovalStepView(
                    index=index,
                    label=step.label,
                    status=status,
                    decided_by=decision.by,
                    decided_at=decision.at,
                )
            )
            if status == "declined":
                open_seen = True
            continue
        status = "waiting" if open_seen else "open"
        open_seen = True
        views.append(ApprovalStepView(index=index, label=step.label, status=status))
    return views


DENIED_ON_THE_WIRE: Mapping[DenyReason, DeniedReason] = {
    DenyReason.RUN_MISMATCH: "run_mismatch",
    DenyReason.NOT_APPROVED: "not_approved",
    DenyReason.INVALID_DECISIONS: "invalid_decisions",
    DenyReason.DIGEST_MISMATCH: "digest_mismatch",
    DenyReason.UNREGISTERED_ACTION: "unregistered_action",
}


def _denied(reason: DeniedReason, detail: str) -> PendingEvent:
    return PendingEvent(
        SAFETY_CHECKER,
        "write_action_denied",
        f"The safety checker blocked a write action: {detail}.",
        WriteActionDeniedData(reason=reason, detail=detail),
    )


def _decided(request: ApprovalRequest, decision: Decision, display: str) -> PendingEvent:
    verdict: WireVerdict = "approve" if decision.verdict is Verdict.APPROVE else "decline"
    steps = request.policy.steps
    which = "the request" if len(steps) == 1 else f"step {decision.step_index + 1} of {len(steps)}"
    return PendingEvent(
        user_actor(decision.by, display),
        "approval_decided",
        f"{display} {verdict}d {which} ({steps[decision.step_index].label}).",
        ApprovalDecidedData(
            approval_id=request.id,
            step=decision.step_index,
            verdict=verdict,
            by=decision.by,
            digest=decision.seen_digest,
        ),
    )


class ActiveModel(Protocol):
    async def access(self, uow: UnitOfWork) -> ModelAccess | None: ...


class RolesNow(Protocol):
    """The People list, read inside the deciding transaction (ADR 0029)."""

    async def roles_now(self, uow: UnitOfWork, person_id: UserId) -> frozenset[Role] | None: ...


class Orchestrator:
    def __init__(
        self,
        db: Database,
        activity: ActivityLogPort,
        engine: WorkflowEngine,
        channel: ApprovalChannel,
        agents: AgentRuntime,
        gateway: WriteGateway,
        mint_callback: CallbackMinter,
        retry_policy: RetryPolicy = RETRY_POLICY,
        models: ActiveModel | None = None,
        people: RolesNow | None = None,
        *,
        public_base_url: str,
    ) -> None:
        self._db = db
        self._public_base_url = public_base_url.rstrip("/")
        self._models = models
        self._people = people
        self._store = Store()
        self._watch = WatchStore()
        self._activity = activity
        self._engine = engine
        self._channel = channel
        self._agents = agents
        self._gateway = gateway
        self._mint_callback = mint_callback
        self._retry = retry_policy
        self._wake = asyncio.Event()

    async def start_run(
        self, spec: RunSpec, principal: Principal, idempotency_key: str
    ) -> RunStarted:
        async with self._db.transaction("orchestration") as uow:
            run_id = RunId(new_id("run"))
            pending = Pending(run_id, 1, None, deadline(Pending, uow.now))
            record = RunRecord(
                run_id=run_id,
                spec=spec,
                started_by=principal.user_id,
                started_at=uow.now,
                updated_at=uow.now,
                version=1,
                state=pending,
                retried_by=(),
                carry_forward=None,
            )
            record, created = await self._store.insert_run(uow, record, idempotency_key)
            if not created:
                return RunStarted(record.run_id, False)
            await self._store.record_leg_attempt(uow, run_id, Leg.WORK, 1, None)
            await self._enqueue_leg(uow, record, Leg.WORK, uow.now)
            await self._activity.append(
                uow,
                run_id,
                created_events(
                    spec.use_case_id,
                    spec.use_case_version,
                    spec.use_case_name,
                    user_actor(principal.user_id, principal.display),
                    1,
                    spec.trigger,
                ),
            )
        self.nudge()
        return RunStarted(run_id, True)

    async def on_step(self, run_id: RunId, step: StepName, execution: N8nExecutionId) -> StepReply:
        match step:
            case StepName.RUN_AGENTS:
                return await self._run_agents(run_id, execution)
            case StepName.ASK_APPROVAL:
                return await self._ask_approval(run_id, execution)
            case StepName.WRITE_ACTION:
                return await self._write_action(run_id, execution)

    async def _admit(
        self, uow: UnitOfWork, run_id: RunId, step: StepName, execution: N8nExecutionId
    ) -> RunRecord | StepReply:
        record = await self._store.load_run(uow, run_id, lock=True)
        if record is None:
            return StepReply(False, "refused", f"Unknown run {run_id}")
        match referee(record.state, step, execution):
            case Begin():
                return record
            case Replay(proceed):
                return StepReply(proceed, "replayed", f"{step.value} was already answered")
            case Supersede(holder):
                return StepReply(False, "superseded", f"Execution {holder} holds this leg")
            case Refuse(fails_run):
                return await self._refuse(uow, record, step, execution, fails_run)

    async def _refuse(
        self,
        uow: UnitOfWork,
        record: RunRecord,
        step: StepName,
        execution: N8nExecutionId,
        fails_run: bool,
    ) -> StepReply:
        detail = f"{step.value} is not allowed while the run is {state_name(record.state)}"
        events: list[PendingEvent] = []
        if step is StepName.WRITE_ACTION:
            events.append(_denied("out_of_order", detail))
        events.append(step_finished(step, execution, 1, "refused", detail))
        if fails_run:
            failure = Failure(
                FailureReason.OUT_OF_ORDER_STEP,
                f"The workflow called {step.value} out of order. Reload it from git and start "
                "a new run",
                retryable=False,
            )
            moved = fail(_active(record.state), failure).preceded_by(*events)
            await self._commit(uow, record, moved)
            await self._store.cancel_outbox(uow, record.run_id)
        else:
            await self._activity.append(uow, record.run_id, events)
        return StepReply(False, "refused", detail)

    async def _run_agents(self, run_id: RunId, execution: N8nExecutionId) -> StepReply:
        async with self._db.transaction("orchestration") as uow:
            admitted = await self._admit(uow, run_id, StepName.RUN_AGENTS, execution)
            if isinstance(admitted, StepReply):
                return admitted
            record = admitted
            match record.state:
                case Pending() as pending:
                    moved = pending.begin_work(execution, uow.now)
                    await self._store.record_leg_attempt(
                        uow, run_id, Leg.WORK, pending.attempt, execution
                    )
                case Working() as working:
                    moved = working.retry_step()
                case _:
                    raise AssertionError("the referee admits run_agents only in Pending or Working")
            record = await self._commit(uow, record, moved)
            model = await self._models.access(uow) if self._models is not None else None
        working = moved.state
        request = self._task_request(record, working, model)
        reply = await self._agents.run_task(request)

        async with self._db.transaction("orchestration") as uow:
            current = await self._store.load_run(uow, run_id, lock=True)
            if (
                current is None
                or current.version != record.version
                or not isinstance(current.state, Working)
            ):
                return StepReply(False, "superseded", "The run moved on while the agents ran")
            working = current.state
            match reply:
                case AgentUnavailable(detail):
                    raise RetryLater(detail)
                case AgentRejected(detail):
                    moved2 = working.fail(
                        Failure(FailureReason.AGENT_ERROR, detail, retryable=False)
                    ).preceded_by(self._finished(working, "failed", detail))
                    await self._commit(uow, current, moved2)
                    await self._store.cancel_outbox(uow, run_id)
                    return StepReply(False, "failed", detail)
                case TaskFailed(error=error, events=events, findings=findings):
                    await self._activity.ingest_agent_events(uow, run_id, working.task_id, events)
                    task = current.spec.task
                    unread = (
                        all_could_not_read(task, error, findings)
                        if isinstance(task, WatchlistTask)
                        else None
                    )
                    if unread is not None:
                        await self._watch.record_review(uow, current, unread, None)
                    detail = f"{error.type}: {error.message}"
                    moved2 = working.fail(
                        Failure(FailureReason.AGENT_ERROR, detail, retryable=error.retryable)
                    ).preceded_by(self._finished(working, "failed", detail))
                    await self._commit(uow, current, moved2)
                    await self._store.cancel_outbox(uow, run_id)
                    return StepReply(False, "failed", detail)
                case TaskFinished(output=output, events=events):
                    await self._activity.ingest_agent_events(uow, run_id, working.task_id, events)
                    return await self._finish_work(uow, current, working, output.summary, output)

    def _finished(self, working: Working, outcome: StepOutcome, detail: str) -> PendingEvent:
        return step_finished(
            StepName.RUN_AGENTS, working.execution, working.try_number, outcome, detail
        )

    async def _finish_work(
        self,
        uow: UnitOfWork,
        record: RunRecord,
        working: Working,
        summary: str,
        output: TaskOutput,
    ) -> StepReply:
        reviewed: Reviewed | None = None
        task = record.spec.task
        if isinstance(task, CardsTask):
            match review_cards(task, output.proposed):
                case Unusable(detail):
                    return await self._fail_work(
                        uow, record, working, FailureReason.AGENT_ERROR, detail
                    )
                case ReviewedCards() as checked:
                    bound = bind_cards(task, checked)
        else:
            match review(task, output.findings, output.proposed):
                case Unusable(detail):
                    return await self._fail_work(
                        uow, record, working, FailureReason.AGENT_ERROR, detail
                    )
                case Reviewed() as reviewed:
                    pass
            intents = [ProposedIntent(p.kind, dict(p.fields), p.reason) for p in output.proposed]
            bound = bind(intents, record.spec.bindings)
        proposal: Proposal | None = None
        match bound:
            case UnboundIntent(kinds):
                detail = f"No connector is bound for {', '.join(kinds)}"
                return await self._fail_work(
                    uow, record, working, FailureReason.UNBOUND_INTENT, detail
                )
            case ():
                moved = working.finish_with_nothing_to_write(summary)
                reply = StepReply(False, "nothing_to_write", summary)
            case actions:
                proposal = Proposal(
                    ProposalId(new_id("prp")), record.run_id, actions, digest(actions)
                )
                await self._store.insert_proposal(uow, proposal)
                lines = tuple(describe(action) for action in actions)
                moved = working.propose(
                    proposal.id, proposal.digest, lines, PLANNER, summary, uow.now
                )
                reply = StepReply(True, "proposed", summary)
        if reviewed is not None:
            await self._watch.record_review(
                uow, record, reviewed, None if proposal is None else proposal.id
            )
        await self._commit(uow, record, moved)
        return reply

    async def _fail_work(
        self,
        uow: UnitOfWork,
        record: RunRecord,
        working: Working,
        reason: FailureReason,
        detail: str,
    ) -> StepReply:
        moved = working.fail(Failure(reason, detail, retryable=False)).preceded_by(
            self._finished(working, "failed", detail)
        )
        await self._commit(uow, record, moved)
        await self._store.cancel_outbox(uow, record.run_id)
        return StepReply(False, "failed", detail)

    def _task_request(
        self, record: RunRecord, working: Working, model: ModelAccess | None
    ) -> TaskRequest:
        url, token = self._mint_callback(
            record.run_id, working.task_id, working.callback_expires_at
        )
        spec = record.spec
        inputs: WatchlistInputs | CardsInputs
        match spec.task:
            case WatchlistTask(tag_pattern, software):
                inputs = WatchlistInputs(
                    tag_pattern=tag_pattern,
                    software=[
                        SoftwareToCheck(
                            id=s.id,
                            name=s.name,
                            source=GithubSource(ref=s.source.ref),
                            our_version=s.our_version,
                            open_ticket=s.open_ticket,
                            awaiting_approval=s.awaiting_approval,
                        )
                        for s in software
                    ],
                )
            case CardsTask(agents):
                inputs = CardsInputs(
                    agents=[CardToRun(card=a.card, values=dict(a.values)) for a in agents]
                )
        return TaskRequest(
            task_id=working.task_id,
            run_id=record.run_id,
            instruction=spec.instruction,
            inputs=inputs,
            carry_forward=CarryForward(),
            callback=Callback(url=url, token=token),
            model=model,
        )

    async def _ask_approval(self, run_id: RunId, execution: N8nExecutionId) -> StepReply:
        async with self._db.transaction("orchestration") as uow:
            admitted = await self._admit(uow, run_id, StepName.ASK_APPROVAL, execution)
            if isinstance(admitted, StepReply):
                return admitted
            record = admitted
            assert isinstance(record.state, Proposed)
            proposed = record.state
            proposal = await self._store.load_proposal(uow, proposed.proposal_id)
            assert proposal is not None
            request = ApprovalRequest(
                id=ApprovalId(new_id("apr")),
                run_id=run_id,
                proposal_id=proposal.id,
                digest=proposal.digest,
                policy=record.spec.approval_policy,
                parties=frozenset({record.started_by, record.spec.owner, *record.retried_by}),
            )
            await self._store.insert_approval(uow, request)
            link = approval_link(request.id)
            moved = proposed.open_approval(request.id, steps_view(request, ()), link)
            await self._commit(uow, record, moved)
            names = await self._store.names(uow, _notice_people(request))
            await self._store.enqueue(
                uow,
                run_id,
                ANNOUNCE,
                {
                    "run_id": run_id,
                    "approval_id": request.id,
                    "use_case_name": record.spec.use_case_name,
                    "actions": list(intents(proposal.actions)),
                    "link": link,
                    "summary": proposed.summary,
                    "lines": [describe(a).line for a in proposal.actions],
                    "digest": request.digest,
                    "steps": _asked_steps(request, names),
                    "not_deciding": sorted({names[p] for p in request.parties}),
                },
                uow.now,
            )
        self.nudge()
        return StepReply(False, "approval_opened", f"Approval {request.id} opened")

    async def _write_action(self, run_id: RunId, execution: N8nExecutionId) -> StepReply:
        async with self._db.transaction("orchestration") as uow:
            admitted = await self._admit(uow, run_id, StepName.WRITE_ACTION, execution)
            if isinstance(admitted, StepReply):
                return admitted
            record = admitted
            assert isinstance(record.state, Acting)
            moved = record.state.begin_write(execution)
            acting = moved.state
            await self._store.record_leg_attempt(uow, run_id, Leg.ACT, acting.attempt, execution)
            record = await self._commit(uow, record, moved)
            proposal = await self._store.load_proposal(uow, acting.proposal_id)
            request = await self._store.load_approval(uow, acting.approval_id)
            assert proposal is not None and request is not None
            decisions = await self._store.load_decisions(uow, request.id)
            verdict = check(acting, proposal, request, decisions, self._gateway.registry)
            match verdict:
                case Deny(reason):
                    detail = f"the safety checker denied the write: {reason.value}"
                    moved2 = acting.fail(
                        Failure(FailureReason.SAFETY_DENIED, detail, retryable=False)
                    ).preceded_by(
                        _denied(DENIED_ON_THE_WIRE[reason], detail),
                        step_finished(StepName.WRITE_ACTION, execution, 1, "refused", detail),
                    )
                    await self._commit(uow, record, moved2)
                    await self._store.cancel_outbox(uow, run_id)
                    return StepReply(False, "refused", detail)
                case AuthorizedWrite() as authorized:
                    pass
        try:
            written = await self._gateway.execute(authorized)
        except WriteFailed as error:
            async with self._db.transaction("orchestration") as uow:
                current = await self._store.load_run(uow, run_id, lock=True)
                if current is None or current.version != record.version:
                    return StepReply(False, "superseded", "The run moved on during the write")
                detail = str(error)
                moved2 = acting.fail(
                    Failure(FailureReason.WRITE_FAILED, detail, retryable=True)
                ).preceded_by(step_finished(StepName.WRITE_ACTION, execution, 1, "failed", detail))
                await self._commit(uow, current, moved2)
                await self._store.cancel_outbox(uow, run_id)
            return StepReply(False, "failed", detail)

        async with self._db.transaction("orchestration") as uow:
            current = await self._store.load_run(uow, run_id, lock=True)
            if current is None or current.version != record.version:
                return StepReply(False, "superseded", "The run moved on during the write")
            detail = "Created " + ", ".join(w.external_reference for w in written)
            moved3 = acting.succeed(execution, written, detail)
            await self._commit(uow, current, moved3)
        return StepReply(True, "written", detail)

    async def on_workflow_failure(
        self, execution: N8nExecutionId, workflow: str, last_node: str, message: str
    ) -> None:
        async with self._db.transaction("orchestration") as uow:
            run_id = await self._store.run_for_execution(uow, execution)
            if run_id is None:
                log.warning("workflow failure for an unknown execution %s", execution)
                return
            record = await self._store.load_run(uow, run_id, lock=True)
            if record is None:
                return
            state = record.state
            match state:
                case Pending() | Working() | Proposed() | Acting():
                    holder = holder_of(state)
                    if holder is not None and holder != execution:
                        return
                    failure = Failure(
                        FailureReason.WORKFLOW_NODE_ERROR,
                        f"The n8n workflow '{workflow}' failed at its step '{last_node}': "
                        f"{message}",
                        retryable=True,
                    )
                    await self._commit(uow, record, fail(state, failure))
                    await self._store.cancel_outbox(uow, run_id)
                case AwaitingApproval() | Succeeded() | Rejected() | Failed():
                    return

    async def get_approval(
        self, approval_id: ApprovalId, principal: Principal
    ) -> ApprovalDetail | None:
        async with self._db.transaction("orchestration") as uow:
            request = await self._store.load_approval(uow, approval_id)
            if request is None:
                return None
            proposal = await self._store.load_proposal(uow, request.proposal_id)
            assert proposal is not None
            decisions = await self._store.load_decisions(uow, approval_id)
        return ApprovalDetail(
            request, proposal, decisions, approvals.why_not(request, decisions, principal)
        )

    async def decide(
        self,
        approval_id: ApprovalId,
        principal: Principal,
        step_index: int,
        verdict: Verdict,
        seen_digest: Digest,
    ) -> DecisionResult:
        async with self._db.transaction("orchestration") as uow:
            request = await self._store.load_approval(uow, approval_id)
            if request is None:
                return NotFound()
            record = await self._store.load_run(uow, request.run_id, lock=True)
            assert record is not None
            decisions = await self._store.load_decisions(uow, approval_id)
            if self._people is not None:
                roles = await self._people.roles_now(uow, principal.user_id)
                principal = replace(principal, roles=roles or frozenset())
            outcome = approvals.decide(
                request, decisions, principal, step_index, verdict, seen_digest, uow.now
            )
            match outcome:
                case Refused(reason):
                    return DecisionRefused(reason)
                case AlreadyRecorded(decision):
                    return Decided(approval_status(request, decisions), decision, True)
                case Recorded(decision):
                    try:
                        await self._store.insert_decision(uow, decision)
                    except DecisionConflict:
                        return DecisionRace()
                    all_decisions = (*decisions, decision)
                    status = approval_status(request, all_decisions)
                    decided = _decided(request, decision, principal.display)
                    if not isinstance(record.state, AwaitingApproval):
                        await self._activity.append(uow, record.run_id, [decided])
                        return Decided(status, decision, False)
                    if isinstance(status, Approved | Declined):
                        await self._enqueue_outcome(uow, record, request, status, principal)
                    match status:
                        case Approved():
                            moved = record.state.approve(uow.now).preceded_by(decided)
                            record = await self._commit(uow, record, moved)
                            await self._store.record_leg_attempt(
                                uow, record.run_id, Leg.ACT, 1, None
                            )
                            await self._enqueue_leg(uow, record, Leg.ACT, uow.now)
                        case Declined(by, step):
                            moved_r = record.state.reject(by, principal.display, step)
                            await self._commit(uow, record, moved_r.preceded_by(decided))
                        case Open() | approvals.Invalid():
                            await self._activity.append(uow, record.run_id, [decided])
        self.nudge()
        return Decided(status, decision, False)

    async def retry(self, run_id: RunId, principal: Principal) -> RetryResult:
        async with self._db.transaction("orchestration") as uow:
            record = await self._store.load_run(uow, run_id, lock=True)
            if record is None:
                return NotFound()
            state = record.state
            if not isinstance(state, Failed):
                return NotRetryable(f"The run is {state_name(state)}, not failed")
            if not state.failure.retryable:
                return NotRetryable(
                    f"{state.failure.reason.value} cannot be retried. Start a new run"
                )
            moved = state.retry(user_actor(principal.user_id, principal.display), uow.now)
            record = await self._commit(uow, record, moved, retried_by=principal.user_id)
            leg = Leg.ACT if isinstance(moved.state, Acting) else Leg.WORK
            await self._store.record_leg_attempt(uow, run_id, leg, moved.state.attempt, None)
            await self._enqueue_leg(uow, record, leg, uow.now + self._retry.operator_retry_delay)
        self.nudge()
        return Retried(moved.state)

    async def get_run(self, run_id: RunId) -> RunDetail | None:
        async with self._db.transaction("orchestration") as uow:
            record = await self._store.load_run(uow, run_id)
            if record is None:
                return None
            return await self._detail(uow, record)

    async def list_runs(self) -> list[RunDetail]:
        async with self._db.transaction("orchestration") as uow:
            return await self._details(uow, await self._store.list_runs(uow))

    async def runs_for(self, viewer: Principal) -> PersonRuns:
        async with self._db.transaction("orchestration") as uow:
            details = await self._details(uow, await self._store.open_runs(uow))
        return runs_of(details, viewer)

    async def _detail(self, uow: UnitOfWork, record: RunRecord) -> RunDetail:
        (detail,) = await self._details(uow, [record])
        return detail

    async def _details(self, uow: UnitOfWork, records: Sequence[RunRecord]) -> list[RunDetail]:
        """One query per table, however many runs, so the run list stays cheap as history grows."""
        links = [_links(record.state) for record in records]
        proposal_ids = [pid for pid, _ in links if pid is not None]
        approval_ids = [aid for _, aid in links if aid is not None]
        last_seqs = await self._activity.last_seqs(uow, [record.run_id for record in records])
        proposals = await self._store.load_proposals(uow, proposal_ids)
        approvals = await self._store.load_approvals(uow, approval_ids)
        decisions = await self._store.load_decisions_for(uow, approval_ids)
        return [
            RunDetail(
                record,
                last_seqs[record.run_id],
                proposals.get(pid) if pid is not None else None,
                approvals.get(aid) if aid is not None else None,
                decisions.get(aid, ()) if aid is not None else (),
            )
            for record, (pid, aid) in zip(records, links, strict=True)
        ]

    def nudge(self) -> None:
        self._wake.set()

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._retry.tick_interval.total_seconds())

    async def tick(self, now: datetime | None = None) -> None:
        now = now or self._db.clock()
        async with self._db.transaction("orchestration") as uow:
            due = await self._store.take_due_outbox(uow, now, self._retry.lease, self._retry.batch)
        for row in due:
            # Sends before this one may have taken a while, so the lease is renewed first, and a
            # row another replica took meanwhile is left to it.
            async with self._db.transaction("orchestration") as uow:
                held = await self._store.renew_lease(
                    uow, row, max(now, self._db.clock()) + self._retry.lease
                )
            if held is None:
                log.info("another tick took outbox row %s, so this one leaves it", row.id)
                continue
            try:
                await self._dispatch(held, now)
            except Exception:
                # One broken row must not stop the rest. It keeps its lease, so it is tried
                # again once that runs out, not on every tick.
                log.error(
                    "outbox row %s could not be sent: %s",
                    row.id,
                    without_addresses(traceback.format_exc()),
                )
        async with self._db.transaction("orchestration") as uow:
            overdue = await self._store.runs_past_deadline(uow, now)
        for run_id in overdue:
            await self._expire(run_id, now)

    async def _dispatch(self, row: OutboxRow, now: datetime) -> None:
        try:
            if row.kind == START_LEG:
                await self._dispatch_leg(row)
            elif row.kind == ANNOUNCE:
                await self._dispatch_announcement(row)
            elif row.kind == SHOW_OUTCOME:
                await self._dispatch_outcome(row)
            else:
                raise DispatchFailure(f"unknown outbox kind {row.kind}")
        except DispatchFailure as error:
            await self._dispatch_failed(row, now, str(error))

    async def _dispatch_leg(self, row: OutboxRow) -> None:
        leg = Leg(row.payload["leg"])
        attempt = int(row.payload["attempt"])
        execution = await self._engine.start_leg(row.payload["workflow"], leg, row.run_id)
        async with self._db.transaction("orchestration") as uow:
            await self._store.outbox_sent(uow, row.id)
            # The run first, then its leg attempt: the order every step call takes. n8n can call
            # a step before this transaction ends, and the opposite order deadlocked with it.
            record = await self._store.load_run(uow, row.run_id, lock=True)
            if record is None:
                return
            await self._store.record_leg_attempt(uow, row.run_id, leg, attempt, execution)
            match record.state:
                case Pending(claimant=None, attempt=a) as pending if a == attempt:
                    await self._store.save_run(uow, record, pending.claim(execution))
                case Acting(claimant=None, attempt=a) as acting if a == attempt:
                    await self._store.save_run(uow, record, acting.claim(execution))
                case _:
                    pass

    def approval_url(self, approval_id: ApprovalId) -> str:
        """The approval page as an absolute address, for a card read outside the Portal."""
        return f"{self._public_base_url}{approval_link(approval_id)}"

    async def _dispatch_announcement(self, row: OutboxRow) -> None:
        payload = row.payload
        approval_id = ApprovalId(payload["approval_id"])
        # A notice queued before a field was added has none of it.
        notice = ApprovalNotice(
            run_id=RunId(payload["run_id"]),
            approval_id=approval_id,
            use_case_name=payload["use_case_name"],
            actions=tuple(payload["actions"]),
            link=payload["link"],
            open_url=self.approval_url(approval_id),
            summary=payload.get("summary", ""),
            lines=tuple(payload.get("lines", ())),
            digest=payload.get("digest", ""),
            steps=tuple(AskedStep(s["label"], tuple(s["who"])) for s in payload.get("steps", ())),
            not_deciding=tuple(payload.get("not_deciding", ())),
        )
        ref = await _through_channel(self._channel.announce(notice))
        async with self._db.transaction("orchestration") as uow:
            await self._store.save_message_ref(uow, approval_id, ref)
            await self._store.outbox_sent(uow, row.id)
            await self._activity.append(
                uow,
                row.run_id,
                [
                    PendingEvent(
                        PLATFORM,
                        "approval_announced",
                        f"The approval request was posted to the Teams channel "
                        f"{self._channel.name}.",
                        ApprovalAnnouncedData(
                            approval_id=notice.approval_id,
                            channel=self._channel.name,
                            link=notice.link,
                        ),
                        dedupe_key=f"announced:{notice.approval_id}",
                    )
                ],
            )

    async def _enqueue_outcome(
        self,
        uow: UnitOfWork,
        record: RunRecord,
        request: ApprovalRequest,
        status: Approved | Declined,
        decider: Principal,
    ) -> None:
        match status:
            case Approved(approvers):
                verdict: OutcomeVerdict = "approved"
                deciders = approvers
            case Declined(by):
                verdict = "declined"
                deciders = (by,)
        names = {**await self._store.names(uow, deciders), decider.user_id: decider.display}
        await self._store.enqueue(
            uow,
            record.run_id,
            SHOW_OUTCOME,
            {
                "approval_id": request.id,
                "verdict": verdict,
                "by": [names[d] for d in deciders],
                "use_case_name": record.spec.use_case_name,
            },
            uow.now,
        )

    async def _dispatch_outcome(self, row: OutboxRow) -> None:
        approval_id = ApprovalId(row.payload["approval_id"])
        async with self._db.transaction("orchestration") as uow:
            ref: MessageRef | None = await self._store.message_ref(uow, approval_id)
            waiting = ref is None and await self._store.announcement_pending(uow, approval_id)
            if ref is None and not waiting:
                # The request was never posted, so there is no card to show it on.
                await self._store.outbox_sent(uow, row.id)
                return
        if ref is None:
            raise DispatchFailure("the approval request is not in Teams yet")
        if ref.adapter != self._channel.adapter:
            # The platform moved between the practice copy and real Teams since the post. The
            # adapter in use cannot show the outcome on a message it did not post.
            log.info(
                "not showing the outcome of %s in Teams: it was posted by %s, and the platform "
                "now posts through %s",
                approval_id,
                ref.adapter,
                self._channel.adapter,
            )
            async with self._db.transaction("orchestration") as uow:
                await self._store.outbox_sent(uow, row.id)
            return
        outcome = ApprovalOutcome(
            verdict=row.payload["verdict"],
            by=tuple(row.payload["by"]),
            use_case_name=row.payload["use_case_name"],
            open_url=self.approval_url(approval_id),
        )
        await _through_channel(self._channel.update(ref, outcome))
        async with self._db.transaction("orchestration") as uow:
            await self._store.outbox_sent(uow, row.id)

    async def _dispatch_failed(self, row: OutboxRow, now: datetime, error: str) -> None:
        failures = row.attempt + 1
        if failures <= len(self._retry.delays):
            async with self._db.transaction("orchestration") as uow:
                await self._store.outbox_retry(
                    uow, row.id, now + self._retry.delays[failures - 1], error
                )
            return
        if row.kind == SHOW_OUTCOME:
            async with self._db.transaction("orchestration") as uow:
                await self._store.outbox_give_up(uow, row.id, error)
            log.warning("gave up showing the outcome of %s in Teams: %s", row.payload, error)
            return
        async with self._db.transaction("orchestration") as uow:
            await self._store.outbox_give_up(uow, row.id, error)
            record = await self._store.load_run(uow, row.run_id, lock=True)
            if record is None:
                return
            if row.kind == ANNOUNCE:
                approval_id = ApprovalId(row.payload["approval_id"])
                await self._activity.append(
                    uow,
                    row.run_id,
                    [
                        PendingEvent(
                            PLATFORM,
                            "approval_announce_failed",
                            "The approval request could not be posted to Teams. Share the "
                            "approval link by hand.",
                            ApprovalAnnounceFailedData(
                                approval_id=approval_id, channel=self._channel.name, message=error
                            ),
                        )
                    ],
                )
                return
            match record.state:
                case Pending() | Acting() as state if state.attempt == int(row.payload["attempt"]):
                    failure = Failure(
                        FailureReason.DISPATCH_FAILED,
                        f"The workflow engine did not take the {row.payload['leg']} leg: {error}",
                        retryable=True,
                    )
                    await self._commit(uow, record, fail(state, failure))
                    await self._store.cancel_outbox(uow, row.run_id)
                case _:
                    pass

    async def _expire(self, run_id: RunId, now: datetime) -> None:
        async with self._db.transaction("orchestration") as uow:
            record = await self._store.load_run(uow, run_id, lock=True)
            if record is None:
                return
            match record.state:
                case Pending() | Working() | Proposed() | Acting() as state:
                    if state.deadline_at > now:
                        return
                    failure = Failure(
                        FailureReason.TIMED_OUT,
                        "The workflow engine did not come back while the run was "
                        f"{state_name(state)}",
                        retryable=True,
                    )
                    await self._commit(uow, record, fail(state, failure))
                    await self._store.cancel_outbox(uow, run_id)
                case _:
                    return

    async def _commit(
        self,
        uow: UnitOfWork,
        record: RunRecord,
        moved: Moved[Any],
        *,
        retried_by: UserId | None = None,
    ) -> RunRecord:
        saved = await self._store.save_run(uow, record, moved.state, retried_by=retried_by)
        await self._activity.append(uow, record.run_id, moved.events)
        await self._watch.run_moved(uow, record, moved.state)
        return saved

    async def _enqueue_leg(
        self, uow: UnitOfWork, record: RunRecord, leg: Leg, next_at: datetime
    ) -> None:
        attempt = record.state.attempt if isinstance(record.state, Pending | Acting) else 1
        await self._store.enqueue(
            uow,
            record.run_id,
            START_LEG,
            {"workflow": record.spec.workflow, "leg": leg.value, "attempt": attempt},
            next_at,
        )


def _active(state: RunState) -> Pending | Working | Proposed | Acting:
    match state:
        case Pending() | Working() | Proposed() | Acting():
            return state
        case _:
            raise AssertionError(f"{type(state).__name__} is not an active state")
