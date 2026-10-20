"""The outbox's retry schedule and the two ports it dispatches through."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from platform_api.orchestration.runs import Leg
from platform_api.shared import ApprovalId, N8nExecutionId, RunId


@dataclass(frozen=True)
class RetryPolicy:
    """Waits between outbox tries, and the short delay before an Operator's retry starts."""

    delays: tuple[timedelta, ...] = (
        timedelta(seconds=2),
        timedelta(seconds=5),
        timedelta(seconds=15),
        timedelta(seconds=30),
        timedelta(seconds=60),
    )
    operator_retry_delay: timedelta = timedelta(seconds=3)
    tick_interval: timedelta = timedelta(seconds=5)

    @property
    def tries(self) -> int:
        return len(self.delays) + 1

    @property
    def dispatch_budget(self) -> timedelta:
        """The longest an outbox row can take before the outbox gives up on it."""
        return sum(self.delays, timedelta()) + self.tick_interval * self.tries


RETRY_POLICY = RetryPolicy()


class DispatchFailure(Exception):
    """The engine or channel did not take the call. The outbox tries again later."""


class WorkflowEngine(Protocol):
    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId: ...


@dataclass(frozen=True)
class ApprovalNotice:
    run_id: RunId
    approval_id: ApprovalId
    use_case_name: str
    summary: str
    link: str


class ApprovalChannel(Protocol):
    @property
    def name(self) -> str: ...

    async def announce(self, notice: ApprovalNotice) -> None: ...
