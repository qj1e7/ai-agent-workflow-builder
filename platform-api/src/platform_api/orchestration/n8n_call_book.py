"""The node-call tables (ENGINE-PLAN 2.4): the starts our API issued, each execution's link to
its run, and each block's one answer, kept by (execution, block)."""

import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import TypeAdapter

from platform_api.db import UnitOfWork, json
from platform_api.orchestration.n8n_calls import (
    START_LIFETIME,
    Answer,
    AskAnswer,
    IssuedStart,
    NodeCall,
    NothingToChange,
    Refused,
    StartKind,
    Waiting,
    WriteAnswer,
)
from platform_api.orchestration.tell import BlockResult, Told
from platform_api.orchestration.write_actions import WriteAction
from platform_api.shared import N8nExecutionId, RunId, new_id

CLAIM_LEASE = timedelta(minutes=2)
"""An agent call gives up after a minute, so a claim older than this was left by a stopped
process, and the next call takes it over."""

type Outcome = Literal["working", "answered", "refused"]

actions_adapter: TypeAdapter[tuple[WriteAction, ...]] = TypeAdapter(tuple[WriteAction, ...])
_write_adapter: TypeAdapter[WriteAnswer] = TypeAdapter(WriteAnswer)


@dataclass(frozen=True)
class CallRow:
    run_id: RunId | None
    kind: str
    content_hash: str
    outcome: Outcome
    call_id: str
    claimed_at: datetime
    status: int | None
    answer: dict[str, Any] | None

    def result(self) -> Answer | AskAnswer | WriteAnswer | Told | Refused:
        assert self.answer is not None
        if self.outcome == "refused":
            assert self.status is not None
            return Refused(self.status, str(self.answer["detail"]))
        return replayed(self.kind, self.answer)


def answer_of(stored: Mapping[str, Any], replayed: bool = False) -> Answer:
    return Answer(tuple(stored["items"]), replayed, bool(stored.get("cut_off", False)))


def replayed(kind: str, stored: Mapping[str, Any]) -> Answer | AskAnswer | WriteAnswer | Told:
    """A block's first answer, given again to a repeat or to a retry of the run."""
    if kind == "ask":
        return _ask_answer(stored)
    if kind == "write":
        return _write_adapter.validate_python(stored)
    if kind == "tell":
        return Told(stored["status"], stored["line"])
    return answer_of(stored, replayed=True)


def _ask_answer(stored: Mapping[str, Any]) -> AskAnswer:
    if stored["status"] == "waiting":
        return Waiting(stored["request_id"])
    return NothingToChange()


def _stored(answer: Answer | AskAnswer | WriteAnswer | Told) -> dict[str, Any]:
    match answer:
        case Answer(items, _, cut_off):
            return {"items": [dict(item) for item in items], "cut_off": cut_off}
        case WriteAnswer():
            return _write_adapter.dump_python(answer, mode="json")
        case Waiting(request_id):
            return {"status": "waiting", "request_id": request_id}
        case NothingToChange():
            return {"status": "nothing_to_change"}
        case Told(status, line):
            return {"status": status, "line": line}


class CallBook:
    """The node-call tables: starts, the execution links and each block's answer."""

    async def hold_execution(self, uow: UnitOfWork, execution: N8nExecutionId) -> None:
        """One call of an execution links it at a time, so two first calls make one run."""
        await uow.conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('n8n-execution:' || %s, 0))",
            (execution,),
        )

    async def call(self, uow: UnitOfWork, call: NodeCall) -> CallRow | None:
        row = await (
            await uow.conn.execute(
                "SELECT run_id, kind, content_hash, outcome, call_id, claimed_at, status, answer "
                "FROM orchestration.node_calls WHERE execution_id = %s AND node_name = %s "
                "FOR UPDATE",
                (call.execution_id, call.node_name),
            )
        ).fetchone()
        if row is None:
            return None
        return CallRow(
            None if row["run_id"] is None else RunId(row["run_id"]),
            row["kind"],
            row["content_hash"],
            row["outcome"],
            row["call_id"],
            row["claimed_at"],
            row["status"],
            row["answer"],
        )

    async def count_again(self, uow: UnitOfWork, call: NodeCall) -> None:
        await uow.conn.execute(
            "UPDATE orchestration.node_calls SET attempts = attempts + 1 "
            "WHERE execution_id = %s AND node_name = %s",
            (call.execution_id, call.node_name),
        )

    async def claim(self, uow: UnitOfWork, call: NodeCall, run_id: RunId) -> str:
        call_id = new_id("call")
        await uow.conn.execute(
            "INSERT INTO orchestration.node_calls (execution_id, node_name, run_id, kind, "
            "content_hash, attempts, outcome, call_id, claimed_at) "
            "VALUES (%s, %s, %s, %s, %s, 1, 'working', %s, %s) "
            "ON CONFLICT (execution_id, node_name) DO UPDATE SET call_id = EXCLUDED.call_id, "
            "claimed_at = EXCLUDED.claimed_at",
            (
                call.execution_id,
                call.node_name,
                run_id,
                call.kind,
                call.content_hash,
                call_id,
                uow.now,
            ),
        )
        return call_id

    async def keep(
        self,
        uow: UnitOfWork,
        call: NodeCall,
        run_id: RunId | None,
        result: Answer | AskAnswer | WriteAnswer | Told | Refused,
        actions: Sequence[Mapping[str, Any]] = (),
        call_id: str | None = None,
    ) -> bool:
        """Keeps a block's one answer or refusal. With call_id, only that claim may keep it: a
        claim that was taken over meanwhile keeps nothing, and False says so."""
        match result:
            case Answer() | Waiting() | NothingToChange() | WriteAnswer() | Told():
                outcome, status, stored = "answered", None, _stored(result)
            case Refused(status, detail):
                outcome, stored = "refused", {"detail": detail}
        if call_id is not None:
            kept = await (
                await uow.conn.execute(
                    "UPDATE orchestration.node_calls SET outcome = %s, status = %s, answer = %s, "
                    "actions = %s, answered_at = %s WHERE call_id = %s AND outcome = 'working' "
                    "RETURNING call_id",
                    (outcome, status, json(stored), json(list(actions)), uow.now, call_id),
                )
            ).fetchone()
            return kept is not None
        await uow.conn.execute(
            "INSERT INTO orchestration.node_calls (execution_id, node_name, run_id, kind, "
            "content_hash, attempts, outcome, call_id, claimed_at, status, answer, actions, "
            "answered_at) VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (execution_id, node_name) DO UPDATE SET run_id = EXCLUDED.run_id, "
            "outcome = EXCLUDED.outcome, status = EXCLUDED.status, answer = EXCLUDED.answer, "
            "actions = EXCLUDED.actions, answered_at = EXCLUDED.answered_at",
            (
                call.execution_id,
                call.node_name,
                run_id,
                call.kind,
                call.content_hash,
                outcome,
                new_id("call"),
                uow.now,
                status,
                json(stored),
                json(list(actions)),
                uow.now,
            ),
        )
        return True

    async def release(self, uow: UnitOfWork, call_id: str) -> None:
        """Lets the next call take the claim over at once, after a failure worth trying again."""
        await uow.conn.execute(
            "UPDATE orchestration.node_calls SET claimed_at = %s "
            "WHERE call_id = %s AND outcome = 'working'",
            (datetime.fromtimestamp(0, UTC), call_id),
        )

    async def settle(self, uow: UnitOfWork, call_id: str, told: Told) -> None:
        """Replaces a Tell's sending with what the flow answered. Its sending, kept before the
        post, is all a repeat of the call ever sees until then, so nothing is sent twice."""
        await uow.conn.execute(
            "UPDATE orchestration.node_calls SET answer = %s, answered_at = %s "
            "WHERE call_id = %s AND outcome = 'answered' AND answer ->> 'status' = 'sending'",
            (json(_stored(told)), uow.now, call_id),
        )

    async def writing(self, uow: UnitOfWork, execution: N8nExecutionId) -> bool:
        """Whether a Make the approved changes block of this execution is still making its
        changes."""
        row = await (
            await uow.conn.execute(
                "SELECT 1 FROM orchestration.node_calls WHERE execution_id = %s "
                "AND kind = 'write' AND outcome = 'working' LIMIT 1",
                (execution,),
            )
        ).fetchone()
        return row is not None

    async def carried_last(self, uow: UnitOfWork, run_id: RunId, execution: N8nExecutionId) -> bool:
        """Whether the run's newest execution is this one, so the one that carried it to its
        end. Only it may still call once the run has succeeded."""
        row = await (
            await uow.conn.execute(
                "SELECT execution_id FROM orchestration.executions WHERE run_id = %s "
                "ORDER BY linked_at DESC LIMIT 1",
                (run_id,),
            )
        ).fetchone()
        return row is not None and row["execution_id"] == execution

    async def results_in_run(self, uow: UnitOfWork, run_id: RunId) -> tuple[BlockResult, ...]:
        """What the run's Read and Agent blocks answered, each block once, in the order they
        first answered. A retry's replayed answer is the same answer again."""
        rows = await (
            await uow.conn.execute(
                "SELECT * FROM (SELECT DISTINCT ON (node_name) node_name, kind, answer, "
                "answered_at FROM orchestration.node_calls WHERE run_id = %s "
                "AND kind IN ('read', 'agent') AND outcome = 'answered' "
                "ORDER BY node_name, answered_at) firsts ORDER BY answered_at, node_name",
                (run_id,),
            )
        ).fetchall()
        return tuple(
            BlockResult(
                row["node_name"],
                row["kind"],
                tuple(row["answer"]["items"]),
                bool(row["answer"].get("cut_off", False)),
            )
            for row in rows
        )

    async def open_executions(self, uow: UnitOfWork) -> dict[str, set[N8nExecutionId]]:
        """The executions that carry a run our API has not closed, by workflow."""
        rows = await (
            await uow.conn.execute(
                "SELECT e.execution_id, e.n8n_workflow_id FROM orchestration.executions e "
                "JOIN orchestration.runs r ON r.run_id = e.run_id "
                "WHERE (r.state = 'Working' AND r.state_data ->> 'execution' = e.execution_id) "
                "OR (r.state = 'Acting' AND r.state_data ->> 'claimant' = e.execution_id)"
            )
        ).fetchall()
        open_: dict[str, set[N8nExecutionId]] = {}
        for row in rows:
            open_.setdefault(row["n8n_workflow_id"], set()).add(N8nExecutionId(row["execution_id"]))
        return open_

    async def answered_in_run(
        self, uow: UnitOfWork, run_id: RunId, call: NodeCall
    ) -> dict[str, Any] | None:
        row = await (
            await uow.conn.execute(
                "SELECT answer FROM orchestration.node_calls WHERE run_id = %s AND "
                "node_name = %s AND kind = %s AND outcome = 'answered' AND execution_id <> %s "
                "ORDER BY answered_at LIMIT 1",
                (run_id, call.node_name, call.kind, call.execution_id),
            )
        ).fetchone()
        return None if row is None else row["answer"]

    async def working_in_run(self, uow: UnitOfWork, run_id: RunId, call: NodeCall) -> bool:
        row = await (
            await uow.conn.execute(
                "SELECT 1 FROM orchestration.node_calls WHERE run_id = %s AND node_name = %s "
                "AND outcome = 'working' AND execution_id <> %s AND claimed_at > %s",
                (run_id, call.node_name, call.execution_id, uow.now - CLAIM_LEASE),
            )
        ).fetchone()
        return row is not None

    async def linked_run(self, uow: UnitOfWork, execution: N8nExecutionId) -> RunId | None:
        row = await (
            await uow.conn.execute(
                "SELECT run_id FROM orchestration.executions WHERE execution_id = %s",
                (execution,),
            )
        ).fetchone()
        return None if row is None else RunId(row["run_id"])

    async def version_of(self, uow: UnitOfWork, execution: N8nExecutionId) -> str | None:
        """The version a linked execution ran. n8n's retry with loadWorkflow false names none of
        its own, and runs its original's (P7)."""
        row = await (
            await uow.conn.execute(
                "SELECT version_id FROM orchestration.executions WHERE execution_id = %s",
                (execution,),
            )
        ).fetchone()
        return None if row is None else row["version_id"]

    async def link(
        self,
        uow: UnitOfWork,
        execution: N8nExecutionId,
        run_id: RunId,
        workflow_id: str,
        mode: str,
        retry_of: N8nExecutionId | None,
        version_id: str | None,
    ) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.executions (execution_id, run_id, n8n_workflow_id, mode, "
            "retry_of, version_id, linked_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (execution, run_id, workflow_id, mode, retry_of, version_id, uow.now),
        )

    async def start(self, uow: UnitOfWork, nonce: str) -> IssuedStart | None:
        row = await (
            await uow.conn.execute(
                "SELECT nonce, run_id, kind, n8n_workflow_id, expires_at, used_by "
                "FROM orchestration.starts WHERE nonce = %s FOR UPDATE",
                (nonce,),
            )
        ).fetchone()
        if row is None:
            return None
        return IssuedStart(
            row["nonce"],
            RunId(row["run_id"]),
            row["kind"],
            row["n8n_workflow_id"],
            row["expires_at"],
            None if row["used_by"] is None else N8nExecutionId(row["used_by"]),
        )

    async def use_start(self, uow: UnitOfWork, nonce: str, execution: N8nExecutionId) -> bool:
        """Marks the start used by this execution. Exactly one execution can."""
        used = await (
            await uow.conn.execute(
                "UPDATE orchestration.starts SET used_at = %s, used_by = %s "
                "WHERE nonce = %s AND used_at IS NULL RETURNING nonce",
                (uow.now, execution, nonce),
            )
        ).fetchone()
        return used is not None

    async def issue_start(
        self, uow: UnitOfWork, run_id: RunId, kind: StartKind, workflow_id: str
    ) -> IssuedStart:
        start = IssuedStart(
            f"start_{secrets.token_hex(16)}",
            run_id,
            kind,
            workflow_id,
            uow.now + START_LIFETIME,
            None,
        )
        await uow.conn.execute(
            "INSERT INTO orchestration.starts (nonce, run_id, kind, n8n_workflow_id, issued_at, "
            "expires_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (start.nonce, run_id, kind, workflow_id, uow.now, start.expires_at),
        )
        return start

    async def proposed(self, uow: UnitOfWork, run_id: RunId) -> tuple[WriteAction, ...]:
        """The run's proposal, which is what its blocks proposed, in the order they answered. A
        replayed answer carries no actions, so nothing is in it twice."""
        rows = await (
            await uow.conn.execute(
                "SELECT actions FROM orchestration.node_calls WHERE run_id = %s "
                "AND outcome = 'answered' ORDER BY answered_at, execution_id, node_name",
                (run_id,),
            )
        ).fetchall()
        return actions_adapter.validate_python(
            [action for row in rows for action in row["actions"]]
        )

    async def found(self, uow: UnitOfWork, run_id: RunId) -> str:
        """What the run's last agent found, for the Approvers."""
        row = await (
            await uow.conn.execute(
                "SELECT answer->'items'->0->>'summary' AS summary FROM orchestration.node_calls "
                "WHERE run_id = %s AND kind = 'agent' AND outcome = 'answered' "
                "ORDER BY answered_at DESC LIMIT 1",
                (run_id,),
            )
        ).fetchone()
        return "" if row is None or row["summary"] is None else str(row["summary"])

    async def started_as_test(self, uow: UnitOfWork, run_id: RunId) -> bool:
        row = await (
            await uow.conn.execute(
                "SELECT 1 FROM orchestration.starts WHERE run_id = %s AND kind = 'test' LIMIT 1",
                (run_id,),
            )
        ).fetchone()
        return row is not None

    async def waiting_run(self, uow: UnitOfWork, use_case_id: str) -> RunId | None:
        """The run of this use case that waits for a yes, if one does (one waiting run per
        workflow, ADR 0026). The lock holds to the end of the transaction, so two runs that ask
        at once see each other."""
        await uow.conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('use-case:' || %s, 0))",
            (use_case_id,),
        )
        row = await (
            await uow.conn.execute(
                "SELECT run_id FROM orchestration.runs WHERE use_case_id = %s "
                "AND state = 'AwaitingApproval' ORDER BY started_at LIMIT 1",
                (use_case_id,),
            )
        ).fetchone()
        return None if row is None else RunId(row["run_id"])
