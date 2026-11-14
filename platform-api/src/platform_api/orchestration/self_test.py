"""The daily self-test (ENGINE-PLAN 2.8, ADR 0027).

n8n's own schedule runs the platform's self-test workflow once a day. Our API refuses its Read on
purpose, so the execution fails and n8n's error workflow reports it through Report a failure,
the same way it reports a run that failed. Each self-test is one row: when its Read reached our
API, and when the error workflow's report of it arrived. A self-test is never a run, so no run
fails, nothing is announced, and no Approver hears of it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from platform_api.db import UnitOfWork
from platform_api.shared import N8nExecutionId

STALE_AFTER = timedelta(hours=26)
"""A day between self-tests, and two hours more for a slow start or a deploy at that hour."""


@dataclass(frozen=True)
class SelfTestsSeen:
    last_arrived: datetime | None
    """When the newest report of a self-test arrived."""
    last_unreported: datetime | None
    """When the newest self-test whose report has not arrived reached our API."""


class SelfTests:
    async def sent(self, uow: UnitOfWork, execution: N8nExecutionId, workflow_id: str) -> None:
        """The self-test's Read reached our API, which refuses it on purpose."""
        await uow.conn.execute(
            "INSERT INTO orchestration.self_tests (execution_id, workflow_id, sent_at) "
            "VALUES (%s, %s, %s) ON CONFLICT (execution_id) DO NOTHING",
            (execution, workflow_id, uow.now),
        )

    async def arrived(self, uow: UnitOfWork, execution: N8nExecutionId, workflow_id: str) -> None:
        """The error workflow reported the self-test's failure. A repeated report keeps the first
        arrival."""
        await uow.conn.execute(
            "INSERT INTO orchestration.self_tests (execution_id, workflow_id, arrived_at) "
            "VALUES (%s, %s, %s) ON CONFLICT (execution_id) DO UPDATE "
            "SET arrived_at = coalesce(self_tests.arrived_at, EXCLUDED.arrived_at)",
            (execution, workflow_id, uow.now),
        )

    async def seen(self, uow: UnitOfWork) -> SelfTestsSeen:
        row = await (
            await uow.conn.execute(
                "SELECT max(arrived_at) AS arrived, "
                "max(sent_at) FILTER (WHERE arrived_at IS NULL) AS unreported "
                "FROM orchestration.self_tests"
            )
        ).fetchone()
        assert row is not None
        return SelfTestsSeen(row["arrived"], row["unreported"])


def ready_line(seen: SelfTestsSeen, now: datetime) -> tuple[bool, str]:
    """Whether a self-test's report arrived within STALE_AFTER, and what that says about the
    error workflow, in plain words."""
    arrived, unreported = seen.last_arrived, seen.last_unreported
    if arrived is not None and now - arrived <= STALE_AFTER:
        return True, f"the error workflow reported the daily self-test at {arrived.isoformat()}"
    if unreported is not None and (arrived is None or unreported > arrived):
        return False, (
            "the error workflow did not report: the daily self-test failed on purpose at "
            f"{unreported.isoformat()}, and no report of it reached the platform. A run that "
            "fails before any of its blocks calls the platform may not show in the Portal"
        )
    if arrived is not None:
        return False, (
            f"no self-test has reached the platform since {arrived.isoformat()}: n8n did not "
            "run it, or the error workflow did not report"
        )
    return False, "no self-test has reached the platform yet. n8n runs it once a day"
