from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum

from platform_api.monitoring import (
    PLATFORM,
    WORKFLOW,
    ActionLine,
    Actor,
    ApprovalRequestedData,
    LegDispatchedData,
    PendingEvent,
    RunCreatedData,
    RunFailedData,
    RunRejectedData,
    RunRetriedData,
    RunSucceededData,
    StepFinishedData,
    StepRetriedData,
    StepStartedData,
    WriteActionDoneData,
    WriteActionProposedData,
    agent_actor,
)
from platform_api.shared import (
    ApprovalId,
    Digest,
    N8nExecutionId,
    ProposalId,
    RunId,
    TaskId,
    UserId,
)
from platform_api.wire import ApprovalStepView, StepOutcome, Trigger
from platform_api.wire import RunState as RunStateName


class Leg(Enum):
    WORK = "work"
    ACT = "act"


class StepName(Enum):
    RUN_AGENTS = "run_agents"
    ASK_APPROVAL = "ask_approval"
    WRITE_ACTION = "write_action"


LEG_STEPS: Mapping[Leg, tuple[StepName, ...]] = {
    Leg.WORK: (StepName.RUN_AGENTS, StepName.ASK_APPROVAL),
    Leg.ACT: (StepName.WRITE_ACTION,),
}
STEP_LEG: Mapping[StepName, Leg] = {step: leg for leg, steps in LEG_STEPS.items() for step in steps}


class FailureReason(Enum):
    AGENT_ERROR = "AgentError"
    WORKFLOW_NODE_ERROR = "WorkflowNodeError"
    TIMED_OUT = "TimedOut"
    DISPATCH_FAILED = "DispatchFailed"
    WRITE_FAILED = "WriteFailed"
    SAFETY_DENIED = "SafetyDenied"
    UNBOUND_INTENT = "UnboundIntent"
    OUT_OF_ORDER_STEP = "OutOfOrderStep"


class Stage(Enum):
    PENDING = "pending"
    WORKING = "working"
    PROPOSED = "proposed"
    ACTING = "acting"


class Outcome(Enum):
    WRITTEN = "written"
    NOTHING_TO_WRITE = "nothing_to_write"


@dataclass(frozen=True)
class Failure:
    reason: FailureReason
    message: str
    retryable: bool


@dataclass(frozen=True)
class WriteDone:
    connector: str
    operation: str
    external_reference: str
    approved_by: tuple[UserId, ...]
    url: str | None = None
    """Where people open what was written, such as the ticket's page in Jira (ADR 0035)."""


@dataclass(frozen=True)
class Moved[S]:
    state: S
    events: tuple[PendingEvent, ...]

    def __post_init__(self) -> None:
        if not self.events:
            raise ValueError("a transition always reports at least one event")

    def preceded_by(self, *events: PendingEvent) -> Moved[S]:
        return Moved(self.state, (*events, *self.events))

    def followed_by(self, *events: PendingEvent) -> Moved[S]:
        return Moved(self.state, (*self.events, *events))


@dataclass(frozen=True)
class ResumeWork:
    attempt: int


@dataclass(frozen=True)
class ResumeAct:
    proposal_id: ProposalId
    approval_id: ApprovalId
    attempt: int


def _step_started(step: StepName, execution: N8nExecutionId, try_number: int) -> PendingEvent:
    return PendingEvent(
        WORKFLOW,
        "step_started",
        f"Workflow step {step.value} started (n8n execution {execution}).",
        StepStartedData(step=step.value, n8n_execution_id=execution, try_number=try_number),
    )


def sentence(text: str) -> str:
    """text with one closing full stop. A model's summary often brings its own."""
    return text if text.endswith((".", "!", "?", "…")) else f"{text}."


def step_finished(
    step: StepName,
    execution: N8nExecutionId,
    try_number: int,
    outcome: StepOutcome,
    detail: str,
) -> PendingEvent:
    return PendingEvent(
        WORKFLOW,
        "step_finished",
        f"Workflow step {step.value} finished: {sentence(detail)}",
        StepFinishedData(
            step=step.value,
            n8n_execution_id=execution,
            try_number=try_number,
            outcome=outcome,
            detail=detail,
        ),
    )


def _leg_dispatched(leg: Leg, attempt: int) -> PendingEvent:
    return PendingEvent(
        PLATFORM,
        "leg_dispatched",
        f"The {leg.value} leg was queued for the workflow engine (attempt {attempt}).",
        LegDispatchedData(leg=leg.value, attempt=attempt),
    )


def _run_failed(stage: Stage, failure: Failure) -> PendingEvent:
    tail = " You can retry." if failure.retryable else " Start a new run."
    return PendingEvent(
        PLATFORM,
        "run_failed",
        f"The run failed ({failure.reason.value}): {sentence(failure.message)}{tail}",
        RunFailedData(
            stage=stage.value,
            reason=failure.reason.value,
            retryable=failure.retryable,
            message=failure.message,
        ),
    )


@dataclass(frozen=True)
class Failed:
    run_id: RunId
    stage: Stage
    failure: Failure
    resume: ResumeWork | ResumeAct

    def retry(self, by: Actor, now: datetime) -> Moved[Pending] | Moved[Acting]:
        match self.resume:
            case ResumeWork(attempt):
                pending = Pending(self.run_id, attempt, None, deadline(Pending, now))
                return Moved(pending, _retried(by, Leg.WORK, attempt))
            case ResumeAct(proposal_id, approval_id, attempt):
                acting = Acting(
                    self.run_id, proposal_id, approval_id, attempt, None, deadline(Acting, now)
                )
                return Moved(acting, _retried(by, Leg.ACT, attempt))


def _retried(by: Actor, leg: Leg, attempt: int) -> tuple[PendingEvent, ...]:
    retried = PendingEvent(
        by,
        "run_retried",
        f"{by.display} retried the run. The {leg.value} leg starts again (attempt {attempt}).",
        RunRetriedData(leg=leg.value, attempt=attempt),
    )
    return (retried, _leg_dispatched(leg, attempt))


@dataclass(frozen=True)
class Succeeded:
    run_id: RunId
    outcome: Outcome
    written: tuple[WriteDone, ...]


@dataclass(frozen=True)
class Rejected:
    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId
    by: UserId
    step: int


@dataclass(frozen=True)
class Acting:
    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId
    attempt: int
    claimant: N8nExecutionId | None
    deadline_at: datetime

    def claim(self, execution: N8nExecutionId) -> Acting:
        return replace(self, claimant=execution)

    def begin_write(self, execution: N8nExecutionId) -> Moved[Acting]:
        return Moved(self.claim(execution), (_step_started(StepName.WRITE_ACTION, execution, 1),))

    def succeed(
        self, execution: N8nExecutionId, written: tuple[WriteDone, ...], detail: str
    ) -> Moved[Succeeded]:
        done = tuple(
            PendingEvent(
                PLATFORM,
                "write_action_done",
                f"{w.connector} {w.operation} done: {w.external_reference}, approved by "
                f"{', '.join(w.approved_by)}.",
                WriteActionDoneData(
                    connector=w.connector,
                    operation=w.operation,
                    external_reference=w.external_reference,
                    approved_by=list(w.approved_by),
                    url=w.url,
                ),
            )
            for w in written
        )
        succeeded = PendingEvent(
            PLATFORM,
            "run_succeeded",
            f"The run succeeded. {len(written)} write action was done."
            if len(written) == 1
            else f"The run succeeded. {len(written)} write actions were done.",
            RunSucceededData(outcome=Outcome.WRITTEN.value),
        )
        return Moved(
            Succeeded(self.run_id, Outcome.WRITTEN, written),
            (
                *done,
                step_finished(StepName.WRITE_ACTION, execution, 1, "written", detail),
                succeeded,
            ),
        )

    def fail(self, failure: Failure) -> Moved[Failed]:
        resume = ResumeAct(self.proposal_id, self.approval_id, self.attempt + 1)
        return Moved(
            Failed(self.run_id, Stage.ACTING, failure, resume),
            (_run_failed(Stage.ACTING, failure),),
        )


@dataclass(frozen=True)
class AwaitingApproval:
    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId

    def approve(self, now: datetime) -> Moved[Acting]:
        state = Acting(
            self.run_id, self.proposal_id, self.approval_id, 1, None, deadline(Acting, now)
        )
        return Moved(state, (_leg_dispatched(Leg.ACT, 1),))

    def reject(self, by: UserId, by_display: str, step: int) -> Moved[Rejected]:
        rejected = PendingEvent(
            PLATFORM,
            "run_rejected",
            f"{by_display} declined the request. Nothing was written.",
            RunRejectedData(by=by, step=step),
        )
        return Moved(
            Rejected(self.run_id, self.proposal_id, self.approval_id, by, step), (rejected,)
        )


@dataclass(frozen=True)
class Proposed:
    run_id: RunId
    proposal_id: ProposalId
    execution: N8nExecutionId
    attempt: int
    deadline_at: datetime
    # The agents' summary, for the approval message. Runs saved before it existed load with "".
    summary: str = ""

    def open_approval(
        self, approval_id: ApprovalId, steps: list[ApprovalStepView], link: str
    ) -> Moved[AwaitingApproval]:
        requested = PendingEvent(
            PLATFORM,
            "approval_requested",
            f"Approval requested. Waiting for the {steps[0].label}.",
            ApprovalRequestedData(approval_id=approval_id, steps=steps, link=link),
        )
        return Moved(
            AwaitingApproval(self.run_id, self.proposal_id, approval_id),
            (
                _step_started(StepName.ASK_APPROVAL, self.execution, 1),
                requested,
                step_finished(
                    StepName.ASK_APPROVAL,
                    self.execution,
                    1,
                    "approval_opened",
                    f"Approval {approval_id} opened",
                ),
            ),
        )

    def fail(self, failure: Failure) -> Moved[Failed]:
        return Moved(
            Failed(self.run_id, Stage.PROPOSED, failure, ResumeWork(self.attempt + 1)),
            (_run_failed(Stage.PROPOSED, failure),),
        )


@dataclass(frozen=True)
class Working:
    run_id: RunId
    execution: N8nExecutionId
    attempt: int
    try_number: int
    deadline_at: datetime
    callback_expires_at: datetime

    @property
    def task_id(self) -> TaskId:
        return TaskId(f"{self.run_id}/work/{self.attempt}")

    def retry_step(self) -> Moved[Working]:
        next_try = self.try_number + 1
        retried = PendingEvent(
            WORKFLOW,
            "step_retried",
            f"Workflow step run_agents is trying again (try {next_try}, n8n execution "
            f"{self.execution}).",
            StepRetriedData(
                step=StepName.RUN_AGENTS.value,
                n8n_execution_id=self.execution,
                try_number=next_try,
            ),
        )
        return Moved(replace(self, try_number=next_try), (retried,))

    def propose(
        self,
        proposal_id: ProposalId,
        digest: Digest,
        lines: tuple[ActionLine, ...],
        proposer: Actor,
        summary: str,
        now: datetime,
    ) -> Moved[Proposed]:
        count = len(lines)
        proposed = PendingEvent(
            proposer,
            "write_action_proposed",
            f"The agents proposed {count} write action{'' if count == 1 else 's'}: "
            + "; ".join(line.line for line in lines)
            + ".",
            WriteActionProposedData(proposal_id=proposal_id, digest=digest, actions=list(lines)),
        )
        return Moved(
            Proposed(
                self.run_id,
                proposal_id,
                self.execution,
                self.attempt,
                deadline(Proposed, now),
                summary,
            ),
            (
                proposed,
                step_finished(
                    StepName.RUN_AGENTS, self.execution, self.try_number, "proposed", summary
                ),
            ),
        )

    def finish_with_nothing_to_write(self, summary: str) -> Moved[Succeeded]:
        succeeded = PendingEvent(
            PLATFORM,
            "run_succeeded",
            f"The run succeeded. There was nothing to write: {sentence(summary)}",
            RunSucceededData(outcome=Outcome.NOTHING_TO_WRITE.value),
        )
        return Moved(
            Succeeded(self.run_id, Outcome.NOTHING_TO_WRITE, ()),
            (
                step_finished(
                    StepName.RUN_AGENTS,
                    self.execution,
                    self.try_number,
                    "nothing_to_write",
                    summary,
                ),
                succeeded,
            ),
        )

    def fail(self, failure: Failure) -> Moved[Failed]:
        return Moved(
            Failed(self.run_id, Stage.WORKING, failure, ResumeWork(self.attempt + 1)),
            (_run_failed(Stage.WORKING, failure),),
        )


@dataclass(frozen=True)
class Pending:
    run_id: RunId
    attempt: int
    claimant: N8nExecutionId | None
    deadline_at: datetime

    def claim(self, execution: N8nExecutionId) -> Pending:
        return replace(self, claimant=execution)

    def begin_work(self, execution: N8nExecutionId, now: datetime) -> Moved[Working]:
        working = Working(
            self.run_id,
            execution,
            self.attempt,
            1,
            deadline(Working, now),
            now + CALLBACK_LIFETIME,
        )
        return Moved(working, (_step_started(StepName.RUN_AGENTS, execution, 1),))

    def fail(self, failure: Failure) -> Moved[Failed]:
        return Moved(
            Failed(self.run_id, Stage.PENDING, failure, ResumeWork(self.attempt + 1)),
            (_run_failed(Stage.PENDING, failure),),
        )


type RunState = (
    Pending | Working | Proposed | AwaitingApproval | Acting | Succeeded | Rejected | Failed
)
type ActiveState = Pending | Working | Proposed | Acting

STATE_NAMES: Mapping[type[RunState], RunStateName] = {
    Pending: "pending",
    Working: "working",
    Proposed: "proposed",
    AwaitingApproval: "awaiting_approval",
    Acting: "acting",
    Succeeded: "succeeded",
    Rejected: "rejected",
    Failed: "failed",
}


def state_name(state: RunState) -> RunStateName:
    return STATE_NAMES[type(state)]


CALLBACK_LIFETIME = timedelta(hours=2)

DEADLINES: Mapping[type[ActiveState], timedelta] = {
    Pending: timedelta(minutes=4),
    Working: timedelta(minutes=8),
    Proposed: timedelta(minutes=3),
    Acting: timedelta(minutes=8),
}


def deadline(state: type[ActiveState], now: datetime) -> datetime:
    return now + DEADLINES[state]


def fail(state: ActiveState, failure: Failure) -> Moved[Failed]:
    return state.fail(failure)


def created_events(
    use_case_id: str,
    use_case_version: int,
    use_case_name: str,
    by: Actor,
    attempt: int,
    trigger: Trigger = "person",
) -> tuple[PendingEvent, ...]:
    summary = (
        f"{by.display} started a run of the {use_case_name}."
        if trigger == "person"
        else f"{by.display}'s schedule started a check of the {use_case_name}."
    )
    created = PendingEvent(
        by,
        "run_created",
        summary,
        RunCreatedData(
            use_case_id=use_case_id,
            use_case_version=use_case_version,
            started_by=UserId(by.id),
            trigger=trigger,
        ),
    )
    return (created, _leg_dispatched(Leg.WORK, attempt))


PLANNER = agent_actor("planner", "Planner")


class Caller(Enum):
    UNCLAIMED = "unclaimed"
    CLAIMANT = "claimant"
    OTHER = "other"


def caller_of(state: RunState, execution: N8nExecutionId) -> Caller:
    match state:
        case Pending(claimant=None) | Acting(claimant=None):
            return Caller.UNCLAIMED
        case Pending(claimant=holder) | Acting(claimant=holder):
            return Caller.CLAIMANT if holder == execution else Caller.OTHER
        case Working(execution=holder) | Proposed(execution=holder):
            return Caller.CLAIMANT if holder == execution else Caller.OTHER
        case AwaitingApproval() | Succeeded() | Rejected() | Failed():
            return Caller.OTHER


def holder_of(state: RunState) -> N8nExecutionId | None:
    match state:
        case Pending(claimant=holder) | Acting(claimant=holder):
            return holder
        case Working(execution=holder) | Proposed(execution=holder):
            return holder
        case AwaitingApproval() | Succeeded() | Rejected() | Failed():
            return None


@dataclass(frozen=True)
class Begin:
    pass


@dataclass(frozen=True)
class Replay:
    proceed: bool


@dataclass(frozen=True)
class Supersede:
    holder: N8nExecutionId


@dataclass(frozen=True)
class Refuse:
    fails_run: bool


type Verdict = Begin | Replay | Supersede | Refuse


class RowVerdict(Enum):
    BEGIN = "begin"
    REPLAY_TRUE = "replay proceed"
    REPLAY_FALSE = "replay stop"
    SUPERSEDE = "supersede"
    REFUSE = "refuse"


ANY_CALLER = frozenset(Caller)
CLAIM_OR_UNCLAIMED = frozenset({Caller.UNCLAIMED, Caller.CLAIMANT})
CLAIMANT = frozenset({Caller.CLAIMANT})
OTHER = frozenset({Caller.OTHER})


def _written(state: RunState) -> bool:
    return isinstance(state, Succeeded) and state.outcome is Outcome.WRITTEN


def _not_written(state: RunState) -> bool:
    return not _written(state)


@dataclass(frozen=True)
class RefereeRow:
    steps: frozenset[StepName]
    states: tuple[type[RunState], ...]
    callers: frozenset[Caller]
    verdict: RowVerdict
    only_if: Callable[[RunState], bool] = lambda _: True

    def matches(self, state: RunState, step: StepName, caller: Caller) -> bool:
        return (
            step in self.steps
            and isinstance(state, self.states)
            and caller in self.callers
            and self.only_if(state)
        )


RUN_AGENTS = frozenset({StepName.RUN_AGENTS})
ASK_APPROVAL = frozenset({StepName.ASK_APPROVAL})
WRITE_ACTION = frozenset({StepName.WRITE_ACTION})

REFEREE_TABLE: tuple[RefereeRow, ...] = (
    RefereeRow(frozenset(StepName), (Failed, Rejected), ANY_CALLER, RowVerdict.REPLAY_FALSE),
    RefereeRow(RUN_AGENTS, (Pending,), CLAIM_OR_UNCLAIMED, RowVerdict.BEGIN),
    RefereeRow(RUN_AGENTS, (Pending,), OTHER, RowVerdict.SUPERSEDE),
    RefereeRow(RUN_AGENTS, (Working,), CLAIMANT, RowVerdict.BEGIN),
    RefereeRow(RUN_AGENTS, (Proposed,), CLAIMANT, RowVerdict.REPLAY_TRUE),
    RefereeRow(
        RUN_AGENTS | ASK_APPROVAL,
        (Working, Proposed),
        OTHER,
        RowVerdict.SUPERSEDE,
    ),
    RefereeRow(
        RUN_AGENTS,
        (AwaitingApproval, Acting, Succeeded),
        ANY_CALLER,
        RowVerdict.REPLAY_FALSE,
    ),
    RefereeRow(ASK_APPROVAL, (Proposed,), CLAIMANT, RowVerdict.BEGIN),
    RefereeRow(
        ASK_APPROVAL,
        (AwaitingApproval, Acting, Succeeded),
        ANY_CALLER,
        RowVerdict.REPLAY_FALSE,
    ),
    RefereeRow(ASK_APPROVAL, (Pending, Working), ANY_CALLER, RowVerdict.REFUSE),
    RefereeRow(WRITE_ACTION, (Acting,), CLAIM_OR_UNCLAIMED, RowVerdict.BEGIN),
    RefereeRow(WRITE_ACTION, (Acting,), OTHER, RowVerdict.SUPERSEDE),
    RefereeRow(
        WRITE_ACTION,
        (Succeeded,),
        ANY_CALLER,
        RowVerdict.REPLAY_FALSE,
        _written,
    ),
    RefereeRow(
        WRITE_ACTION,
        (Pending, Working, Proposed, AwaitingApproval, Succeeded),
        ANY_CALLER,
        RowVerdict.REFUSE,
        _not_written,
    ),
)


def _first_matching_row(state: RunState, step: StepName, caller: Caller) -> RefereeRow:
    for row in REFEREE_TABLE:
        if row.matches(state, step, caller):
            return row
    raise AssertionError(f"the referee table has no row for {step} in {type(state).__name__}")


def referee(state: RunState, step: StepName, execution: N8nExecutionId) -> Verdict:
    caller = caller_of(state, execution)
    row = _first_matching_row(state, step, caller)
    match row.verdict:
        case RowVerdict.BEGIN:
            return Begin()
        case RowVerdict.REPLAY_TRUE:
            return Replay(True)
        case RowVerdict.REPLAY_FALSE:
            return Replay(False)
        case RowVerdict.SUPERSEDE:
            holder = holder_of(state)
            assert holder is not None
            return Supersede(holder)
        case RowVerdict.REFUSE:
            return Refuse(fails_run=caller is Caller.CLAIMANT)
