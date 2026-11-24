"""The troubleshooter's model version (ADR 0032, ADR 0055 section 10), as run monitoring's
CauseFinder. It only reads: the run's record in n8n says which blocks the version that ran has and
where the run stopped, the model key goes from the settings store into the request to the runtime
and nowhere else, and the runtime's answer is kept only when every block it names is one the run
stopped at.

The model is asked once for each stop. An answer the model gave, shown or kept back, is remembered
for that stop, so asking again costs nothing. A call that failed or ran out of time is asked again
next time. The runtime gets what is left of the platform's wait, so its calls end before the
platform stops waiting."""

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Final, Protocol

from pydantic import ValidationError

from platform_api.db import Database
from platform_api.monitoring import AskedCause, FoundCause
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

ROUND_TRIP_SECONDS: Final = 1.0
"""Kept back from the runtime's time for the call to it and back."""
LEAST_SECONDS: Final = 2.0
"""With less than this left for the runtime, no model is asked."""
MOST_REMEMBERED: Final = 512

type StopKey = tuple[RunId, int]


class RunRecords(Protocol):
    async def read(self, run_id: RunId) -> RunInN8n | None: ...


class CauseAgents(Protocol):
    async def find_cause(
        self, request: CauseRequest
    ) -> CauseResult | AgentUnavailable | AgentRejected: ...


class RunCauses:
    def __init__(
        self,
        db: Database,
        models: ActiveModel,
        agents: CauseAgents,
        runs: RunRecords,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._models = models
        self._agents = agents
        self._runs = runs
        self._clock = clock
        self._answered: OrderedDict[StopKey, FoundCause | None] = OrderedDict()
        self._asking: dict[StopKey, asyncio.Lock] = {}

    async def find(self, asked: AskedCause) -> FoundCause | None:
        """One question to the model for each stop: a second ask for the same stop waits for the
        first, then reads what it found."""
        deadline = self._clock() + asked.seconds
        key = (asked.run_id, asked.seq)
        lock = self._asking.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                if key in self._answered:
                    self._answered.move_to_end(key)
                    return self._answered[key]
                found, final = await self._ask(asked, deadline)
                if final:
                    self._remember(key, found)
                return found
        finally:
            if not lock.locked() and self._asking.get(key) is lock:
                del self._asking[key]

    def _remember(self, key: StopKey, found: FoundCause | None) -> None:
        self._answered[key] = found
        while len(self._answered) > MOST_REMEMBERED:
            self._answered.popitem(last=False)

    async def _ask(self, asked: AskedCause, deadline: float) -> tuple[FoundCause | None, bool]:
        """The cause to show, and whether the model's answer is final for this stop."""
        run = await self._runs.read(asked.run_id)
        stopped = [] if run is None else [n for n, s in run.nodes.items() if s == "failed"]
        if run is None or not stopped:
            return None, False
        async with self._db.transaction("orchestration") as uow:
            model = await self._models.access(uow)
        left = min(deadline - self._clock() - ROUND_TRIP_SECONDS, 10.0)
        if model is None or left < LEAST_SECONDS:
            return None, False
        failure = asked.failure
        try:
            request = CauseRequest(
                model=model,
                stop=StoppedRun(
                    stage=failure.stage,
                    reason=failure.reason,
                    retryable=failure.retryable,
                    message=failure.message[:STOP_MESSAGE_LIMIT],
                ),
                events=[e[:EVENT_SUMMARY_LIMIT] for e in asked.events[-MOST_EVENTS:]],
                blocks=list(run.nodes),
                stopped_at=stopped,
                within_seconds=left,
            )
        except ValidationError:
            log.warning("The run's blocks don't fit a cause request, so no model is asked")
            return None, False
        return _checked(await self._agents.find_cause(request), stopped)


def _checked(
    reply: CauseResult | AgentUnavailable | AgentRejected, stopped: Sequence[str]
) -> tuple[FoundCause | None, bool]:
    match reply:
        case CauseFound(cause=cause, failed_part=part) if set(part) <= set(stopped):
            return FoundCause(cause=cause, failed_part=part), True
        case CauseFound():
            log.warning("The troubleshooter's model named a block the run didn't stop at")
            return None, True
        case CauseKept(why=why):
            log.info("The troubleshooter's model fell back: %s", why)
            return None, True
        case ModelProblem(reason=reason):
            log.warning("The troubleshooter's model answered with a problem: %s", reason)
        case AgentUnavailable(detail=detail) | AgentRejected(detail=detail):
            log.warning("The troubleshooter's model fell back: %s", detail)
    return None, False
