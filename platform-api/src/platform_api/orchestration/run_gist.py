from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from platform_api.monitoring import what_happened
from platform_api.orchestration.approvals import Verdict, why_not
from platform_api.orchestration.runs import (
    AwaitingApproval,
    Failed,
    Rejected,
    Succeeded,
    failed_data,
    state_name,
)
from platform_api.shared import Principal, Role, RunId, UseCaseId, UserId
from platform_api.wire import FailureReason, RunOutcome, RunState

if TYPE_CHECKING:
    from platform_api.orchestration.service import RunDetail

CREATE_TICKET = "create_ticket"


@dataclass(frozen=True)
class Stop:
    """When a stopped run last stopped, the time Needs you gives, and why, in the AI
    troubleshooter's one sentence."""

    at: datetime
    what_happened: str


@dataclass(frozen=True)
class RunGist:
    """What another context may say about a run in a line: when it started, how it stands, how
    many writes it proposed or made, who declined it, and what the asking person may do."""

    run_id: RunId
    use_case_id: UseCaseId
    state: RunState
    started_at: datetime
    test: bool
    """A person started it with Do a test run."""
    declined_by: UserId | None
    decline_reason: str | None
    """Why it was declined, when the Approver gave a reason."""
    approved_by: tuple[UserId, ...]
    """Who said yes to its request, in step order. On a declined run, those before the decline."""
    written: int
    proposed: int
    tickets: bool
    """True when every write counted in `written` or `proposed` is a ticket, and there is one."""
    you_can_decide: bool
    """The asking person may decide the yes this run waits for. False without a person."""
    you_can_open: bool
    """The run stopped and is in the asking person's Needs you: an Operator whose work it is."""
    retryable: bool
    """The run stopped and a retry may start it again."""
    reason: FailureReason | None
    """Why it stopped, for a stopped run."""
    outcome: RunOutcome | None = None
    """How a finished run ended: written, nothing_to_write or test_passed. None until then."""
    stop: Stop | None = None
    """When and why it stopped, for a stopped run."""


def gist_of(detail: RunDetail, viewer: Principal | None) -> RunGist:
    record = detail.record
    state = record.state
    written = state.written if isinstance(state, Succeeded) else ()
    proposed = () if detail.proposal is None else detail.proposal.actions
    counted = written or proposed
    can_decide = (
        viewer is not None
        and isinstance(state, AwaitingApproval)
        and detail.approval is not None
        and why_not(detail.approval, detail.decisions, viewer) is None
    )
    failed = state if isinstance(state, Failed) else None
    can_open = (
        failed is not None
        and viewer is not None
        and Role.OPERATOR in viewer.roles
        and viewer.user_id in record.parties
    )
    decisions = sorted(detail.decisions, key=lambda d: d.step_index)
    reasons = (d.reason for d in decisions if d.reason)
    return RunGist(
        run_id=record.run_id,
        use_case_id=record.spec.use_case_id,
        state=state_name(state),
        started_at=record.started_at,
        test=record.spec.test,
        declined_by=state.by if isinstance(state, Rejected) else None,
        decline_reason=next(reasons, None) if isinstance(state, Rejected) else None,
        approved_by=tuple(d.by for d in decisions if d.verdict is Verdict.APPROVE),
        written=len(written),
        proposed=len(proposed),
        tickets=len(counted) > 0 and all(w.operation == CREATE_TICKET for w in counted),
        you_can_decide=can_decide,
        you_can_open=can_open,
        retryable=failed is not None and failed.failure.retryable,
        reason=None if failed is None else failed.failure.reason.value,
        outcome=state.outcome.value if isinstance(state, Succeeded) else None,
        stop=None
        if failed is None
        else Stop(record.updated_at, what_happened(failed_data(failed.stage, failed.failure))),
    )
