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
    ExecutionLinkedData,
    ExecutionResumedData,
    LegDispatchedData,
    PendingEvent,
    RunCreatedData,
    RunExpiredData,
    RunFailedData,
    RunLostData,
    RunRejectedData,
    RunRetriedData,
    RunSkippedData,
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
    stop_advice,
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
    TEST_PASSED = "test_passed"


TEST_PASSED = "Test run passed up to the yes. Nothing was written."
SKIPPED = "An earlier run is still waiting for a yes."
NO_ANSWER = "No answer. Nothing was written."


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
    unread: tuple[str, ...] = ()


def _resumed(execution: N8nExecutionId, how: str) -> PendingEvent:
    return PendingEvent(
        WORKFLOW,
        "execution_resumed",
        f"n8n execution {execution} {how}.",
        ExecutionResumedData(execution_id=execution),
    )


def write_done(written: WriteDone) -> PendingEvent:
    """One change made, with who approved it (AGENTS.md: log every agent action)."""
    return PendingEvent(
        PLATFORM,
        "write_action_done",
        f"{written.connector} {written.operation} done: {written.external_reference}, approved "
        f"by {', '.join(written.approved_by)}.",
        WriteActionDoneData(
            connector=written.connector,
            operation=written.operation,
            external_reference=written.external_reference,
            approved_by=list(written.approved_by),
            url=written.url,
        ),
    )


def _run_written(count: int) -> PendingEvent:
    return PendingEvent(
        PLATFORM,
        "run_succeeded",
        f"The run succeeded. {count} write action was done."
        if count == 1
        else f"The run succeeded. {count} write actions were done.",
        RunSucceededData(outcome=Outcome.WRITTEN.value),
    )


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


def _what_next(stage: Stage, failure: Failure) -> str:
    """Before the write step nothing can have been written, so a new run is safe. At the write
    step a new run can make a second ticket, so the advice is to look for this run's ticket
    first. A stop that can be retried says so, because a retry resumes the same approved
    proposal."""
    if failure.retryable:
        return " You can retry."
    return " " + stop_advice(stage is Stage.ACTING)


def cannot_retry(stage: Stage, failure: Failure) -> str:
    return (
        f"{failure.reason.value} cannot be retried: {sentence(failure.message)} "
        f"{stop_advice(stage is Stage.ACTING)}"
    )


def run_failed(stage: Stage, failure: Failure) -> PendingEvent:
    tail = _what_next(stage, failure)
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
            case ResumeAct(proposal_id, approval_id, attempt, unread):
                acting = Acting(
                    self.run_id,
                    proposal_id,
                    approval_id,
                    attempt,
                    None,
                    deadline(Acting, now),
                    unread,
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
class Skipped:
    """A run n8n started while an earlier run of the same workflow waited for a yes. It ends at
    its first call, so the Approvers never see two requests for one change."""

    run_id: RunId
    waiting: RunId


@dataclass(frozen=True)
class Expired:
    """Nobody answered the request before it expired (ADR 0024). Nothing was written."""

    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId
    unread: tuple[str, ...] = ()


@dataclass(frozen=True)
class Lost:
    """Approved, but the waiting n8n execution could not take the yes (ENGINE-PLAN 2.3.13).
    Nothing was written, and the approved proposal stays on the record."""

    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId
    unread: tuple[str, ...] = ()

    def taken(self, execution: N8nExecutionId, now: datetime) -> Moved[Acting]:
        """n8n took the yes after all: the execution that waited for it asks to make the
        changes. Our record of the wake was lost, or the wake met the 409 of a resume already
        done."""
        acting = Acting(
            self.run_id,
            self.proposal_id,
            self.approval_id,
            1,
            execution,
            deadline(Acting, now),
            self.unread,
        )
        return Moved(acting, (_resumed(execution, "took the yes after all and carries on"),))


@dataclass(frozen=True)
class Succeeded:
    run_id: RunId
    outcome: Outcome
    written: tuple[WriteDone, ...]
    unread: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rejected:
    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId
    by: UserId
    step: int
    unread: tuple[str, ...] = ()


@dataclass(frozen=True)
class Acting:
    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId
    attempt: int
    claimant: N8nExecutionId | None
    deadline_at: datetime
    unread: tuple[str, ...] = ()

    def claim(self, execution: N8nExecutionId) -> Acting:
        return replace(self, claimant=execution)

    def begin_write(self, execution: N8nExecutionId) -> Moved[Acting]:
        return Moved(self.claim(execution), (_step_started(StepName.WRITE_ACTION, execution, 1),))

    def succeed(
        self, execution: N8nExecutionId, written: tuple[WriteDone, ...], detail: str
    ) -> Moved[Succeeded]:
        return Moved(
            Succeeded(self.run_id, Outcome.WRITTEN, written, self.unread),
            (
                *(write_done(w) for w in written),
                step_finished(StepName.WRITE_ACTION, execution, 1, "written", detail),
                _run_written(len(written)),
            ),
        )

    def made(
        self, written: tuple[WriteDone, ...], fresh: tuple[WriteDone, ...]
    ) -> Moved[Succeeded]:
        """Make the approved changes made the last of the run's changes in n8n. It logs only
        what this try made: an earlier try logged its own, and a change another run made first
        is in that run's log."""
        if not written:
            already = PendingEvent(
                PLATFORM,
                "run_succeeded",
                "The run succeeded. Another run had already made its changes.",
                RunSucceededData(outcome=Outcome.NOTHING_TO_WRITE.value),
            )
            return Moved(
                Succeeded(self.run_id, Outcome.NOTHING_TO_WRITE, (), self.unread), (already,)
            )
        return Moved(
            Succeeded(self.run_id, Outcome.WRITTEN, written, self.unread),
            (*(write_done(w) for w in fresh), _run_written(len(written))),
        )

    def fail(self, failure: Failure) -> Moved[Failed]:
        resume = ResumeAct(self.proposal_id, self.approval_id, self.attempt + 1, self.unread)
        return Moved(
            Failed(self.run_id, Stage.ACTING, failure, resume),
            (run_failed(Stage.ACTING, failure),),
        )


@dataclass(frozen=True)
class AwaitingApproval:
    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId
    summary: str = ""
    unread: tuple[str, ...] = ()

    def approve(self, now: datetime) -> Moved[Acting]:
        state = Acting(
            self.run_id,
            self.proposal_id,
            self.approval_id,
            1,
            None,
            deadline(Acting, now),
            self.unread,
        )
        return Moved(state, (_leg_dispatched(Leg.ACT, 1),))

    def woken(self, execution: N8nExecutionId, now: datetime) -> Moved[Acting]:
        """n8n took the yes. The write's deadline starts now, not at the decision, so an n8n
        outage while it waits does not use it up."""
        acting = Acting(
            self.run_id,
            self.proposal_id,
            self.approval_id,
            1,
            execution,
            deadline(Acting, now),
            self.unread,
        )
        return Moved(acting, (_resumed(execution, "took the yes and carries on"),))

    def lose(self, why: str) -> Moved[Lost]:
        lost = PendingEvent(
            PLATFORM,
            "run_lost",
            f"Approved, but n8n lost the run, because {sentence(why)} Nothing was written.",
            RunLostData(approval_id=self.approval_id, why=why),
        )
        return Moved(Lost(self.run_id, self.proposal_id, self.approval_id, self.unread), (lost,))

    def expire(self) -> Moved[Expired]:
        expired = PendingEvent(
            PLATFORM, "run_expired", NO_ANSWER, RunExpiredData(approval_id=self.approval_id)
        )
        return Moved(
            Expired(self.run_id, self.proposal_id, self.approval_id, self.unread), (expired,)
        )

    def reject(
        self, by: UserId, by_display: str, step: int, reason: str | None = None
    ) -> Moved[Rejected]:
        because = f" Reason: {sentence(reason)}" if reason else ""
        rejected = PendingEvent(
            PLATFORM,
            "run_rejected",
            f"{by_display} declined the request. Nothing was written.{because}",
            RunRejectedData(by=by, step=step, reason=reason),
        )
        return Moved(
            Rejected(self.run_id, self.proposal_id, self.approval_id, by, step, self.unread),
            (rejected,),
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
    # The software a check couldn't read, by name, for the approval's Not checked. Runs saved
    # before it existed load with none.
    unread: tuple[str, ...] = ()

    def open_approval(
        self, approval_id: ApprovalId, steps: list[ApprovalStepView], link: str
    ) -> Moved[AwaitingApproval]:
        requested = _approval_requested(approval_id, steps, link)
        return Moved(
            AwaitingApproval(self.run_id, self.proposal_id, approval_id, self.summary, self.unread),
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

    def stop_for_test(self) -> Moved[Succeeded]:
        """A test run of a draft ends at the approval gate. Nobody is asked for a yes, so the
        write can never be made (ADR 0044)."""
        return Moved(
            Succeeded(self.run_id, Outcome.TEST_PASSED, (), self.unread),
            (
                _step_started(StepName.ASK_APPROVAL, self.execution, 1),
                step_finished(
                    StepName.ASK_APPROVAL,
                    self.execution,
                    1,
                    "test_passed",
                    "A test run of a draft asks nobody for a yes",
                ),
                _test_passed(),
            ),
        )

    def fail(self, failure: Failure) -> Moved[Failed]:
        return Moved(
            Failed(self.run_id, Stage.PROPOSED, failure, ResumeWork(self.attempt + 1)),
            (run_failed(Stage.PROPOSED, failure),),
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

    def touch(self, now: datetime) -> Working:
        """A run n8n carries stays alive while its nodes keep calling."""
        return replace(self, deadline_at=deadline(Working, now))

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
        unread: tuple[str, ...] = (),
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
                unread,
            ),
            (
                proposed,
                step_finished(
                    StepName.RUN_AGENTS, self.execution, self.try_number, "proposed", summary
                ),
            ),
        )

    def ask(
        self,
        proposal: tuple[ProposalId, Digest, tuple[ActionLine, ...]],
        approval_id: ApprovalId,
        steps: list[ApprovalStepView],
        link: str,
        summary: str,
        left_out: tuple[str, ...] = (),
    ) -> Moved[AwaitingApproval]:
        """Ask for a yes in n8n: the run's proposal is what its blocks proposed, less what was
        already made."""
        return Moved(
            AwaitingApproval(self.run_id, proposal[0], approval_id, summary),
            (
                _workflow_proposed(*proposal, left_out),
                _approval_requested(approval_id, steps, link),
            ),
        )

    def stop_at_gate(
        self,
        proposal: tuple[ProposalId, Digest, tuple[ActionLine, ...]],
        left_out: tuple[str, ...] = (),
    ) -> Moved[Succeeded]:
        """A test run shows what it would ask, asks nobody and writes nothing."""
        return Moved(
            Succeeded(self.run_id, Outcome.TEST_PASSED, ()),
            (_workflow_proposed(*proposal, left_out), _test_passed()),
        )

    def skip(self, waiting: RunId) -> Moved[Skipped]:
        """Another run of the workflow already waits for a yes (ADR 0026)."""
        return Moved(Skipped(self.run_id, waiting), (run_skipped(waiting),))

    def nothing_to_change(self, left_out: tuple[str, ...] = ()) -> Moved[Succeeded]:
        succeeded = PendingEvent(
            PLATFORM,
            "run_succeeded",
            " ".join(("The run succeeded. There was nothing to change.", *left_out)),
            RunSucceededData(outcome=Outcome.NOTHING_TO_WRITE.value),
        )
        return Moved(Succeeded(self.run_id, Outcome.NOTHING_TO_WRITE, ()), (succeeded,))

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
            (run_failed(Stage.WORKING, failure),),
        )


@dataclass(frozen=True)
class Pending:
    run_id: RunId
    attempt: int
    claimant: N8nExecutionId | None
    deadline_at: datetime

    def claim(self, execution: N8nExecutionId) -> Pending:
        return replace(self, claimant=execution)

    def link(self, execution: N8nExecutionId, mode: str, now: datetime) -> Moved[Working]:
        working = working_on(self.run_id, execution, self.attempt, now)
        return Moved(working, (execution_linked(execution, mode),))

    def skip(self, execution: N8nExecutionId, mode: str, waiting: RunId) -> Moved[Skipped]:
        return Moved(
            Skipped(self.run_id, waiting), (execution_linked(execution, mode), run_skipped(waiting))
        )

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
            (run_failed(Stage.PENDING, failure),),
        )


type RunState = (
    Pending
    | Working
    | Proposed
    | AwaitingApproval
    | Acting
    | Succeeded
    | Rejected
    | Failed
    | Skipped
    | Expired
    | Lost
)
type ActiveState = Pending | Working | Proposed | Acting


def unread_in(state: RunState) -> tuple[str, ...]:
    """The software the run's check couldn't read. It is kept from the proposal to the run's end,
    so a decided request still says what its Approver was told."""
    match state:
        case (
            Proposed(unread=unread)
            | AwaitingApproval(unread=unread)
            | Acting(unread=unread)
            | Rejected(unread=unread)
            | Expired(unread=unread)
            | Lost(unread=unread)
            | Succeeded(unread=unread)
            | Failed(resume=ResumeAct(unread=unread))
        ):
            return unread
        case _:
            return ()


STATE_NAMES: Mapping[type[RunState], RunStateName] = {
    Pending: "pending",
    Working: "working",
    Proposed: "proposed",
    AwaitingApproval: "awaiting_approval",
    Acting: "acting",
    Succeeded: "succeeded",
    Rejected: "rejected",
    Failed: "failed",
    Skipped: "skipped",
    Expired: "expired",
    Lost: "lost",
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


def run_created(
    use_case_id: str,
    use_case_version: int,
    use_case_name: str,
    by: Actor,
    trigger: Trigger = "person",
) -> PendingEvent:
    summary = (
        f"{by.display} started a run of the {use_case_name}."
        if trigger == "person"
        else f"{by.display}'s schedule started a check of the {use_case_name}."
    )
    return PendingEvent(
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


def created_events(
    use_case_id: str,
    use_case_version: int,
    use_case_name: str,
    by: Actor,
    attempt: int,
    trigger: Trigger = "person",
) -> tuple[PendingEvent, ...]:
    created = run_created(use_case_id, use_case_version, use_case_name, by, trigger)
    return (created, _leg_dispatched(Leg.WORK, attempt))


def execution_linked(execution: N8nExecutionId, mode: str) -> PendingEvent:
    return PendingEvent(
        WORKFLOW,
        "execution_linked",
        f"n8n execution {execution} is carrying the run ({mode}).",
        ExecutionLinkedData(execution_id=execution, mode=mode),
    )


def _approval_requested(
    approval_id: ApprovalId, steps: list[ApprovalStepView], link: str
) -> PendingEvent:
    return PendingEvent(
        PLATFORM,
        "approval_requested",
        f"Approval requested. Waiting for the {steps[0].label}.",
        ApprovalRequestedData(approval_id=approval_id, steps=steps, link=link),
    )


def _workflow_proposed(
    proposal_id: ProposalId,
    digest: Digest,
    lines: tuple[ActionLine, ...],
    left_out: tuple[str, ...] = (),
) -> PendingEvent:
    count = len(lines)
    proposed = (
        f"The workflow proposed {count} change{'' if count == 1 else 's'}: "
        + "; ".join(line.line for line in lines)
        + "."
    )
    return PendingEvent(
        WORKFLOW,
        "write_action_proposed",
        " ".join((proposed, *left_out)),
        WriteActionProposedData(proposal_id=proposal_id, digest=digest, actions=list(lines)),
    )


def _test_passed() -> PendingEvent:
    return PendingEvent(
        PLATFORM, "run_succeeded", TEST_PASSED, RunSucceededData(outcome=Outcome.TEST_PASSED.value)
    )


def run_skipped(waiting: RunId) -> PendingEvent:
    return PendingEvent(PLATFORM, "run_skipped", SKIPPED, RunSkippedData(waiting_run_id=waiting))


def working_on(run_id: RunId, execution: N8nExecutionId, attempt: int, now: datetime) -> Working:
    return Working(run_id, execution, attempt, 1, deadline(Working, now), now + CALLBACK_LIFETIME)


def linked_events(
    created: PendingEvent, execution: N8nExecutionId, mode: str
) -> tuple[PendingEvent, ...]:
    """A run n8n started itself: on a schedule, or by hand in the editor."""
    return (created, execution_linked(execution, mode))


def skipped_events(
    created: PendingEvent, execution: N8nExecutionId, mode: str, waiting: RunId
) -> tuple[PendingEvent, ...]:
    return (*linked_events(created, execution, mode), run_skipped(waiting))


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
        case (
            AwaitingApproval()
            | Succeeded()
            | Rejected()
            | Failed()
            | Skipped()
            | Expired()
            | Lost()
        ):
            return Caller.OTHER


def holder_of(state: RunState) -> N8nExecutionId | None:
    match state:
        case Pending(claimant=holder) | Acting(claimant=holder):
            return holder
        case Working(execution=holder) | Proposed(execution=holder):
            return holder
        case (
            AwaitingApproval()
            | Succeeded()
            | Rejected()
            | Failed()
            | Skipped()
            | Expired()
            | Lost()
        ):
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
    RefereeRow(
        frozenset(StepName),
        (Failed, Rejected, Skipped, Expired, Lost),
        ANY_CALLER,
        RowVerdict.REPLAY_FALSE,
    ),
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
