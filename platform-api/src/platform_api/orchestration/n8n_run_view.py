"""A run as n8n carried it, for the In n8n tab's canvas (ENGINE-PLAN E7, E8). Each of our blocks'
state comes from the calls it made to our API. Once the run has ended, n8n's own record of its
last execution is read too, which also names n8n's blocks that never call us, such as an IF."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from platform_api.db import Database
from platform_api.shared import N8nExecutionId, RunId

type NodeState = Literal["running", "waiting", "done", "failed"]

ENDED = frozenset({"succeeded", "rejected", "failed", "skipped", "expired", "lost"})

_FROM_N8N: Mapping[str, NodeState] = {
    "success": "done",
    "error": "failed",
    "crashed": "failed",
    "canceled": "failed",
    "waiting": "waiting",
    "running": "running",
}
"""n8n's status for a block's last try, in the canvas's words."""


class ExecutionReads(Protocol):
    async def ran(self, execution_id: N8nExecutionId) -> Mapping[str, str] | None: ...


@dataclass(frozen=True)
class RunInN8n:
    run_id: RunId
    use_case_id: str
    state: str
    execution_id: str | None
    """The run's last execution, which a retry replaces."""
    workflow_id: str | None
    version_id: str | None
    """The n8n version the last execution ran."""
    nodes: Mapping[str, NodeState]
    read_n8n: bool
    """n8n's own record of the ended execution was read."""


def call_state(outcome: str, kind: str, run_state: str) -> NodeState:
    if outcome == "working":
        return "running"
    if outcome == "refused":
        return "failed"
    if kind == "ask" and run_state == "awaiting_approval":
        return "waiting"
    return "done"


class RunsInN8n:
    def __init__(self, db: Database, executions: ExecutionReads | None) -> None:
        self._db = db
        self._executions = executions

    async def read(self, run_id: RunId) -> RunInN8n | None:
        async with self._db.connection("orchestration") as conn:
            run = await (
                await conn.execute(
                    "SELECT use_case_id, state FROM orchestration.runs WHERE run_id = %s",
                    (run_id,),
                )
            ).fetchone()
            if run is None:
                return None
            last = await (
                await conn.execute(
                    "SELECT execution_id, n8n_workflow_id, version_id FROM orchestration.executions"
                    " WHERE run_id = %s ORDER BY linked_at DESC LIMIT 1",
                    (run_id,),
                )
            ).fetchone()
            calls = await (
                await conn.execute(
                    "SELECT node_name, kind, outcome FROM orchestration.node_calls"
                    " WHERE run_id = %s ORDER BY claimed_at",
                    (run_id,),
                )
            ).fetchall()
        state = str(run["state"])
        nodes: dict[str, NodeState] = {
            c["node_name"]: call_state(c["outcome"], c["kind"], state) for c in calls
        }
        read_n8n = False
        if last is not None and state in ENDED and self._executions is not None:
            ran = await self._executions.ran(N8nExecutionId(last["execution_id"]))
            if ran is not None:
                read_n8n = True
                nodes |= {name: _FROM_N8N[s] for name, s in ran.items() if s in _FROM_N8N}
        return RunInN8n(
            run_id,
            str(run["use_case_id"]),
            state,
            None if last is None else str(last["execution_id"]),
            None if last is None else str(last["n8n_workflow_id"]),
            None if last is None or last["version_id"] is None else str(last["version_id"]),
            nodes,
            read_n8n,
        )
