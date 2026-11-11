"""Each workflow's newest run, for the Workflows rows, the check card and the Planner's facts.

All three read `UseCaseView.last_run`, so one run is never described two ways."""

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from platform_api.builder.models import LastRunView
from platform_api.orchestration import RunDetail, RunGist, gist_of
from platform_api.shared import UseCaseId


class RunHistory(Protocol):
    async def list_runs(self) -> list[RunDetail]: ...


def last_run_view(gist: RunGist) -> LastRunView:
    return LastRunView(
        run_id=gist.run_id,
        state=gist.state,
        at=gist.started_at,
        test=gist.test,
        declined_by=gist.declined_by,
        proposed=gist.proposed,
        written=gist.written,
        tickets=gist.tickets,
    )


def _recency(run: RunDetail) -> tuple[datetime, str]:
    return run.record.started_at, run.record.run_id


def newest_runs(runs: Iterable[RunDetail]) -> dict[UseCaseId, LastRunView]:
    """The newest run of each workflow by its start time, whatever its state. Two runs that
    started together go by run id, as the Portal's lists do."""
    newest: dict[UseCaseId, RunDetail] = {}
    for run in runs:
        seen = newest.get(run.record.spec.use_case_id)
        if seen is None or _recency(run) > _recency(seen):
            newest[run.record.spec.use_case_id] = run
    return {use_case_id: last_run_view(gist_of(run)) for use_case_id, run in newest.items()}
