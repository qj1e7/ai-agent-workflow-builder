"""The troubleshooter's model version (ADR 0032, ADR 0055 section 10), as run monitoring's
CauseFinder. It only reads: the run's record in n8n says which blocks the version that ran has and
where the run stopped, the model key goes from the settings store into the request to the runtime
and nowhere else, and the runtime's answer is kept only when every block it names is one the run
stopped at."""

import logging
from collections.abc import Sequence
from typing import Protocol

from pydantic import ValidationError

from platform_api.db import Database
from platform_api.monitoring import FoundCause, RunFailedData
from platform_api.orchestration.agents import (
    EVENT_SUMMARY_LIMIT,
    MOST_EVENTS,
    STOP_MESSAGE_LIMIT,
    AgentRejected,
    AgentUnavailable,
    CauseFound,
    CauseKept,
    CauseRequest,
    CauseResult,
    ModelProblem,
    StoppedRun,
)
from platform_api.orchestration.n8n_run_view import RunInN8n
from platform_api.orchestration.service import ActiveModel
from platform_api.shared import RunId

log = logging.getLogger(__name__)


class RunRecords(Protocol):
    async def read(self, run_id: RunId) -> RunInN8n | None: ...


class CauseAgents(Protocol):
    async def find_cause(
        self, request: CauseRequest
    ) -> CauseResult | AgentUnavailable | AgentRejected: ...


class RunCauses:
    def __init__(
        self, db: Database, models: ActiveModel, agents: CauseAgents, runs: RunRecords
    ) -> None:
        self._db = db
        self._models = models
        self._agents = agents
        self._runs = runs

    async def find(
        self, run_id: RunId, failure: RunFailedData, events: Sequence[str]
    ) -> FoundCause | None:
        run = await self._runs.read(run_id)
        stopped = [] if run is None else [n for n, s in run.nodes.items() if s == "failed"]
        if run is None or not stopped:
            return None
        async with self._db.transaction("orchestration") as uow:
            model = await self._models.access(uow)
        if model is None:
            return None
        try:
            request = CauseRequest(
                model=model,
                stop=StoppedRun(
                    stage=failure.stage,
                    reason=failure.reason,
                    retryable=failure.retryable,
                    message=failure.message[:STOP_MESSAGE_LIMIT],
                ),
                events=[e[:EVENT_SUMMARY_LIMIT] for e in events[-MOST_EVENTS:]],
                blocks=list(run.nodes),
                stopped_at=stopped,
            )
        except ValidationError:
            log.warning("The run's blocks don't fit a cause request, so no model is asked")
            return None
        return _checked(await self._agents.find_cause(request), stopped)


def _checked(
    reply: CauseResult | AgentUnavailable | AgentRejected, stopped: Sequence[str]
) -> FoundCause | None:
    match reply:
        case CauseFound(cause=cause, failed_part=part) if set(part) <= set(stopped):
            return FoundCause(cause=cause, failed_part=part)
        case CauseFound():
            log.warning("The troubleshooter's model named a block the run didn't stop at")
        case CauseKept(why=why):
            log.info("The troubleshooter's model fell back: %s", why)
        case ModelProblem(reason=reason):
            log.warning("The troubleshooter's model answered with a problem: %s", reason)
        case AgentUnavailable(detail=detail) | AgentRejected(detail=detail):
            log.warning("The troubleshooter's model fell back: %s", detail)
    return None
