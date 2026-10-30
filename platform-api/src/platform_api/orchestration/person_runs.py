"""The runs one person has to act on or is waiting on, for Home. The approval rules decide who
may say yes, with the same dry run as the approval page, so Home never offers what the page
would refuse."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from platform_api.orchestration import approvals
from platform_api.orchestration.approvals import (
    ApprovalRequest,
    Decision,
    Open,
    Recorded,
    Refusal,
    Refused,
    Verdict,
    approval_status,
)
from platform_api.orchestration.runs import AwaitingApproval, Failed
from platform_api.orchestration.store import RunRecord
from platform_api.orchestration.write_actions import Proposal
from platform_api.shared import ApprovalId, Principal, Role, RunId, UseCaseId, UserId
from platform_api.wire import FailureReason, FailureStage, Trigger

CHANGES_SHOWN = 3


@dataclass(frozen=True)
class Change:
    connector: str
    operation: str
    title: str | None


@dataclass(frozen=True)
class RunFacts:
    run_id: RunId
    use_case_id: UseCaseId
    use_case_name: str
    started_by: UserId
    trigger: Trigger
    started_at: datetime


@dataclass(frozen=True)
class Ask:
    """A run waiting for a yes that this person may give."""

    run: RunFacts
    approval_id: ApprovalId
    step: int
    steps: int
    step_label: str
    changes: int
    first_changes: tuple[Change, ...]


type Because = Literal["started", "retried", "owns", "decided_earlier"]


@dataclass(frozen=True)
class Waiting:
    """A run waiting for someone else's yes: the person is a party to it, or decided a step."""

    run: RunFacts
    step: int
    steps: int
    because: Because


@dataclass(frozen=True)
class Stopped:
    run: RunFacts
    stopped_at: datetime
    stage: FailureStage
    reason: FailureReason
    retryable: bool
    message: str


@dataclass(frozen=True)
class PersonRuns:
    asks: tuple[Ask, ...]
    waiting: tuple[Waiting, ...]
    stopped: tuple[Stopped, ...]


class OpenRun(Protocol):
    """A run waiting for a yes, or the newest run of its workflow and stopped."""

    @property
    def record(self) -> RunRecord: ...

    @property
    def proposal(self) -> Proposal | None: ...

    @property
    def approval(self) -> ApprovalRequest | None: ...

    @property
    def decisions(self) -> tuple[Decision, ...]: ...


def _facts(record: RunRecord) -> RunFacts:
    return RunFacts(
        run_id=record.run_id,
        use_case_id=record.spec.use_case_id,
        use_case_name=record.spec.use_case_name,
        started_by=record.started_by,
        trigger=record.spec.trigger,
        started_at=record.started_at,
    )


def _changes(proposal: Proposal) -> tuple[Change, ...]:
    return tuple(
        Change(
            connector=action.connector,
            operation=action.operation,
            title=title if isinstance(title := action.fields.get("title"), str) else None,
        )
        for action in proposal.actions[:CHANGES_SHOWN]
    )


def _because(record: RunRecord, viewer: UserId) -> Because:
    if viewer == record.started_by:
        return "started"
    if viewer in record.retried_by:
        return "retried"
    if viewer == record.spec.owner:
        return "owns"
    return "decided_earlier"


def _waiting_or_ask(run: OpenRun, viewer: Principal) -> Ask | Waiting | None:
    request, proposal = run.approval, run.proposal
    assert request is not None and proposal is not None
    status = approval_status(request, run.decisions)
    if not isinstance(status, Open):
        return None
    step = status.next_step
    steps = len(request.policy.steps)
    dry_run = approvals.decide(
        request, run.decisions, viewer, step, Verdict.APPROVE, request.digest, datetime.min
    )
    if isinstance(dry_run, Recorded):
        return Ask(
            run=_facts(run.record),
            approval_id=request.id,
            step=step,
            steps=steps,
            step_label=request.policy.steps[step].label,
            changes=len(proposal.actions),
            first_changes=_changes(proposal),
        )
    decided_a_step = isinstance(dry_run, Refused) and dry_run.reason is Refusal.DECIDED_EARLIER_STEP
    if viewer.user_id in request.parties or decided_a_step:
        return Waiting(_facts(run.record), step, steps, _because(run.record, viewer.user_id))
    return None


def _stopped(record: RunRecord, state: Failed, viewer: Principal) -> Stopped | None:
    parties = {record.started_by, record.spec.owner, *record.retried_by}
    if Role.OPERATOR not in viewer.roles or viewer.user_id not in parties:
        return None
    return Stopped(
        run=_facts(record),
        stopped_at=record.updated_at,
        stage=state.stage.value,
        reason=state.failure.reason.value,
        retryable=state.failure.retryable,
        message=state.failure.message,
    )


def runs_of(runs: Iterable[OpenRun], viewer: Principal) -> PersonRuns:
    """Sorts the open runs, newest first as given, into what the viewer may decide, what waits
    on someone else, and their stopped runs. Only an Operator can retry, so only an Operator
    who started, owns or retried a stopped run sees it."""
    asks: list[Ask] = []
    waiting: list[Waiting] = []
    stopped: list[Stopped] = []
    for run in runs:
        match run.record.state:
            case AwaitingApproval():
                match _waiting_or_ask(run, viewer):
                    case Ask() as ask:
                        asks.append(ask)
                    case Waiting() as wait:
                        waiting.append(wait)
                    case None:
                        pass
            case Failed() as failed:
                if (stop := _stopped(run.record, failed, viewer)) is not None:
                    stopped.append(stop)
            case _:
                pass
    return PersonRuns(tuple(asks), tuple(waiting), tuple(stopped))
