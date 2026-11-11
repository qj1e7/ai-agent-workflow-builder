from dataclasses import dataclass
from datetime import datetime

from platform_api.orchestration.runs import Rejected, Succeeded, state_name
from platform_api.orchestration.service import RunDetail
from platform_api.orchestration.spec import WatchlistTask
from platform_api.shared import RunId, UserId
from platform_api.wire import RunState

CREATE_TICKET = "create_ticket"


@dataclass(frozen=True)
class RunGist:
    """What another context may say about a run in a line: when it started, how it stands, how
    many writes it proposed or made, and who declined it."""

    run_id: RunId
    state: RunState
    started_at: datetime
    test: bool
    """A person started it by hand to try the workflow. A check of the watchlist is never a test."""
    declined_by: UserId | None
    written: int
    proposed: int
    tickets: bool
    """True when every write counted in `written` or `proposed` is a ticket, and there is one."""


def gist_of(detail: RunDetail) -> RunGist:
    record = detail.record
    state = record.state
    written = state.written if isinstance(state, Succeeded) else ()
    proposed = () if detail.proposal is None else detail.proposal.actions
    counted = written or proposed
    return RunGist(
        run_id=record.run_id,
        state=state_name(state),
        started_at=record.started_at,
        test=record.spec.trigger == "person" and not isinstance(record.spec.task, WatchlistTask),
        declined_by=state.by if isinstance(state, Rejected) else None,
        written=len(written),
        proposed=len(proposed),
        tickets=len(counted) > 0 and all(w.operation == CREATE_TICKET for w in counted),
    )
