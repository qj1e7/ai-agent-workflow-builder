"""Each workflow's newest run, for the Workflows rows, the check card and the Planner's facts.

All three read `UseCaseView.last_run`, so one run is never described two ways."""

from collections.abc import Sequence
from typing import Protocol

from platform_api.builder.models import LastRunView
from platform_api.orchestration import RunGist
from platform_api.shared import Principal, UseCaseId


class RunHistory(Protocol):
    async def newest_runs(
        self, use_case_ids: Sequence[UseCaseId], viewer: Principal | None = None
    ) -> dict[UseCaseId, RunGist]: ...


def last_run_view(gist: RunGist) -> LastRunView:
    return LastRunView(
        run_id=gist.run_id,
        state=gist.state,
        at=gist.started_at,
        test=gist.test,
        declined_by=gist.declined_by,
        decline_reason=gist.decline_reason,
        approved_by=list(gist.approved_by),
        proposed=gist.proposed,
        written=gist.written,
        tickets=gist.tickets,
        you_can_decide=gist.you_can_decide,
        retryable=gist.retryable,
        reason=gist.reason,
        outcome=gist.outcome,
    )
