from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import psycopg
from pydantic import TypeAdapter

from platform_api.db import UnitOfWork, json
from platform_api.orchestration.approvals import ApprovalPolicy, ApprovalRequest, Decision, Verdict
from platform_api.orchestration.runs import (
    Acting,
    AwaitingApproval,
    Failed,
    Leg,
    Pending,
    Proposed,
    Rejected,
    RunState,
    Succeeded,
    Working,
)
from platform_api.orchestration.spec import RunSpec
from platform_api.orchestration.write_actions import Proposal, WriteAction
from platform_api.shared import (
    ApprovalId,
    Digest,
    N8nExecutionId,
    ProposalId,
    RunId,
    UserId,
)

STATE_TYPES: Mapping[str, type[RunState]] = {
    cls.__name__: cls
    for cls in (Pending, Working, Proposed, AwaitingApproval, Acting, Succeeded, Rejected, Failed)
}
_state_adapters: dict[str, TypeAdapter[Any]] = {
    name: TypeAdapter(cls) for name, cls in STATE_TYPES.items()
}
_spec_adapter: TypeAdapter[RunSpec] = TypeAdapter(RunSpec)
_policy_adapter: TypeAdapter[ApprovalPolicy] = TypeAdapter(ApprovalPolicy)
_actions_adapter: TypeAdapter[tuple[WriteAction, ...]] = TypeAdapter(tuple[WriteAction, ...])


def dump_state(state: RunState) -> tuple[str, dict[str, Any]]:
    name = type(state).__name__
    return name, _state_adapters[name].dump_python(state, mode="json")


def load_state(name: str, data: dict[str, Any]) -> RunState:
    return _state_adapters[name].validate_python(data)


@dataclass(frozen=True)
class RunRecord:
    run_id: RunId
    spec: RunSpec
    started_by: UserId
    started_at: datetime
    updated_at: datetime
    version: int
    state: RunState
    retried_by: tuple[UserId, ...]
    carry_forward: str | None


class Stale(Exception): ...


class DecisionConflict(Exception): ...


@dataclass(frozen=True)
class OutboxRow:
    id: int
    run_id: RunId
    kind: str
    payload: dict[str, Any]
    attempt: int


def _deadline_of(state: RunState) -> datetime | None:
    match state:
        case Pending() | Working() | Proposed() | Acting():
            return state.deadline_at
        case AwaitingApproval() | Succeeded() | Rejected() | Failed():
            return None


def _record(row: Mapping[str, Any]) -> RunRecord:
    return RunRecord(
        run_id=RunId(row["run_id"]),
        spec=_spec_adapter.validate_python(row["spec"]),
        started_by=UserId(row["started_by"]),
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        version=int(row["version"]),
        state=load_state(row["state"], row["state_data"]),
        retried_by=tuple(UserId(u) for u in row["retried_by"]),
        carry_forward=row["carry_forward"],
    )


RUN_COLUMNS = (
    "run_id, spec, started_by, started_at, updated_at, version, state, state_data, "
    "retried_by, carry_forward"
)


class Store:
    async def insert_run(
        self, uow: UnitOfWork, record: RunRecord, idempotency_key: str
    ) -> tuple[RunRecord, bool]:
        name, data = dump_state(record.state)
        inserted = await (
            await uow.conn.execute(
                "INSERT INTO orchestration.runs (run_id, use_case_id, idempotency_key, spec, "
                "started_by, started_at, updated_at, version, state, state_data, deadline_at, "
                "retried_by, carry_forward) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (use_case_id, idempotency_key) DO NOTHING RETURNING run_id",
                (
                    record.run_id,
                    record.spec.use_case_id,
                    idempotency_key,
                    json(_spec_adapter.dump_python(record.spec, mode="json")),
                    record.started_by,
                    record.started_at,
                    record.updated_at,
                    record.version,
                    name,
                    json(data),
                    _deadline_of(record.state),
                    json(list(record.retried_by)),
                    record.carry_forward,
                ),
            )
        ).fetchone()
        if inserted is not None:
            return record, True
        existing = await (
            await uow.conn.execute(
                f"SELECT {RUN_COLUMNS} FROM orchestration.runs "
                "WHERE use_case_id = %s AND idempotency_key = %s",
                (record.spec.use_case_id, idempotency_key),
            )
        ).fetchone()
        assert existing is not None
        return _record(existing), False

    async def load_run(
        self, uow: UnitOfWork, run_id: RunId, lock: bool = False
    ) -> RunRecord | None:
        suffix = " FOR UPDATE" if lock else ""
        row = await (
            await uow.conn.execute(
                f"SELECT {RUN_COLUMNS} FROM orchestration.runs WHERE run_id = %s{suffix}",
                (run_id,),
            )
        ).fetchone()
        return None if row is None else _record(row)

    async def save_run(
        self,
        uow: UnitOfWork,
        record: RunRecord,
        state: RunState,
        *,
        retried_by: UserId | None = None,
    ) -> RunRecord:
        name, data = dump_state(state)
        new_retried = record.retried_by + ((retried_by,) if retried_by else ())
        updated = await (
            await uow.conn.execute(
                "UPDATE orchestration.runs SET state = %s, state_data = %s, deadline_at = %s, "
                "updated_at = %s, version = version + 1, retried_by = %s, carry_forward = %s "
                "WHERE run_id = %s AND version = %s RETURNING version",
                (
                    name,
                    json(data),
                    _deadline_of(state),
                    uow.now,
                    json(list(new_retried)),
                    record.carry_forward,
                    record.run_id,
                    record.version,
                ),
            )
        ).fetchone()
        if updated is None:
            raise Stale(record.run_id)
        return replace(
            record,
            state=state,
            version=int(updated["version"]),
            updated_at=uow.now,
            retried_by=new_retried,
        )

    async def list_runs(self, uow: UnitOfWork) -> list[RunRecord]:
        rows = await (
            await uow.conn.execute(
                f"SELECT {RUN_COLUMNS} FROM orchestration.runs "
                "ORDER BY started_at DESC, run_id DESC"
            )
        ).fetchall()
        return [_record(row) for row in rows]

    async def open_runs(self, uow: UnitOfWork) -> list[RunRecord]:
        """Every run waiting for a yes, and each workflow's newest run when it has stopped."""
        rows = await (
            await uow.conn.execute(
                f"SELECT {RUN_COLUMNS} FROM orchestration.runs r "
                "WHERE r.state = 'AwaitingApproval' OR (r.state = 'Failed' AND NOT EXISTS ("
                "SELECT 1 FROM orchestration.runs newer WHERE newer.use_case_id = r.use_case_id "
                "AND (newer.started_at, newer.run_id) > (r.started_at, r.run_id))) "
                "ORDER BY r.started_at DESC, r.run_id DESC"
            )
        ).fetchall()
        return [_record(row) for row in rows]

    async def runs_past_deadline(self, uow: UnitOfWork, now: datetime) -> list[RunId]:
        rows = await (
            await uow.conn.execute(
                "SELECT run_id FROM orchestration.runs WHERE deadline_at IS NOT NULL "
                "AND deadline_at <= %s ORDER BY deadline_at",
                (now,),
            )
        ).fetchall()
        return [RunId(row["run_id"]) for row in rows]

    async def record_leg_attempt(
        self,
        uow: UnitOfWork,
        run_id: RunId,
        leg: Leg,
        attempt: int,
        execution: N8nExecutionId | None,
    ) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.leg_attempts (run_id, leg, attempt, n8n_execution_id, "
            "recorded_at) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, leg, attempt) DO UPDATE SET n8n_execution_id = "
            "coalesce(orchestration.leg_attempts.n8n_execution_id, EXCLUDED.n8n_execution_id)",
            (run_id, leg.value, attempt, execution, uow.now),
        )

    async def run_for_execution(self, uow: UnitOfWork, execution: N8nExecutionId) -> RunId | None:
        row = await (
            await uow.conn.execute(
                "SELECT run_id FROM orchestration.leg_attempts WHERE n8n_execution_id = %s "
                "ORDER BY recorded_at DESC LIMIT 1",
                (execution,),
            )
        ).fetchone()
        return None if row is None else RunId(row["run_id"])

    async def insert_proposal(self, uow: UnitOfWork, proposal: Proposal) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.proposals "
            "(proposal_id, run_id, actions, digest, created_at) VALUES (%s, %s, %s, %s, %s)",
            (
                proposal.id,
                proposal.run_id,
                json(_actions_adapter.dump_python(proposal.actions, mode="json")),
                proposal.digest,
                uow.now,
            ),
        )

    async def load_proposal(self, uow: UnitOfWork, proposal_id: ProposalId) -> Proposal | None:
        return (await self.load_proposals(uow, [proposal_id])).get(proposal_id)

    async def load_proposals(
        self, uow: UnitOfWork, proposal_ids: Collection[ProposalId]
    ) -> dict[ProposalId, Proposal]:
        if not proposal_ids:
            return {}
        rows = await (
            await uow.conn.execute(
                "SELECT proposal_id, run_id, actions, digest FROM orchestration.proposals "
                "WHERE proposal_id = ANY(%s)",
                (list(proposal_ids),),
            )
        ).fetchall()
        return {
            ProposalId(row["proposal_id"]): Proposal(
                ProposalId(row["proposal_id"]),
                RunId(row["run_id"]),
                _actions_adapter.validate_python(row["actions"]),
                Digest(row["digest"]),
            )
            for row in rows
        }

    async def insert_approval(self, uow: UnitOfWork, request: ApprovalRequest) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.approval_requests (approval_id, run_id, proposal_id, "
            "digest, policy, parties, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                request.id,
                request.run_id,
                request.proposal_id,
                request.digest,
                json(_policy_adapter.dump_python(request.policy, mode="json")),
                json(sorted(request.parties)),
                uow.now,
            ),
        )

    async def load_approval(
        self, uow: UnitOfWork, approval_id: ApprovalId
    ) -> ApprovalRequest | None:
        return (await self.load_approvals(uow, [approval_id])).get(approval_id)

    async def load_approvals(
        self, uow: UnitOfWork, approval_ids: Collection[ApprovalId]
    ) -> dict[ApprovalId, ApprovalRequest]:
        if not approval_ids:
            return {}
        rows = await (
            await uow.conn.execute(
                "SELECT approval_id, run_id, proposal_id, digest, policy, parties "
                "FROM orchestration.approval_requests WHERE approval_id = ANY(%s)",
                (list(approval_ids),),
            )
        ).fetchall()
        return {
            ApprovalId(row["approval_id"]): ApprovalRequest(
                ApprovalId(row["approval_id"]),
                RunId(row["run_id"]),
                ProposalId(row["proposal_id"]),
                Digest(row["digest"]),
                _policy_adapter.validate_python(row["policy"]),
                frozenset(UserId(u) for u in row["parties"]),
            )
            for row in rows
        }

    async def insert_decision(self, uow: UnitOfWork, decision: Decision) -> None:
        try:
            await uow.conn.execute(
                "INSERT INTO orchestration.approval_decisions (approval_id, step_index, "
                "decided_by, verdict, seen_digest, decided_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    decision.approval_id,
                    decision.step_index,
                    decision.by,
                    decision.verdict.value,
                    decision.seen_digest,
                    decision.at,
                ),
            )
        except psycopg.errors.UniqueViolation as error:
            raise DecisionConflict(decision.approval_id) from error

    async def load_decisions(
        self, uow: UnitOfWork, approval_id: ApprovalId
    ) -> tuple[Decision, ...]:
        return (await self.load_decisions_for(uow, [approval_id])).get(approval_id, ())

    async def load_decisions_for(
        self, uow: UnitOfWork, approval_ids: Collection[ApprovalId]
    ) -> dict[ApprovalId, tuple[Decision, ...]]:
        """Each approval's decisions in step order. An approval with none is left out."""
        if not approval_ids:
            return {}
        rows = await (
            await uow.conn.execute(
                "SELECT approval_id, step_index, decided_by, verdict, seen_digest, decided_at "
                "FROM orchestration.approval_decisions WHERE approval_id = ANY(%s) "
                "ORDER BY approval_id, step_index",
                (list(approval_ids),),
            )
        ).fetchall()
        decisions: dict[ApprovalId, tuple[Decision, ...]] = {}
        for row in rows:
            decision = Decision(
                ApprovalId(row["approval_id"]),
                int(row["step_index"]),
                UserId(row["decided_by"]),
                Verdict(row["verdict"]),
                Digest(row["seen_digest"]),
                row["decided_at"],
            )
            decisions[decision.approval_id] = (*decisions.get(decision.approval_id, ()), decision)
        return decisions

    async def enqueue(
        self, uow: UnitOfWork, run_id: RunId, kind: str, payload: dict[str, Any], next_at: datetime
    ) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.outbox (run_id, kind, payload, attempt, next_at, status, "
            "created_at) VALUES (%s, %s, %s, 0, %s, 'pending', %s)",
            (run_id, kind, json(payload), next_at, uow.now),
        )

    async def due_outbox(self, uow: UnitOfWork, now: datetime) -> list[OutboxRow]:
        rows = await (
            await uow.conn.execute(
                "SELECT id, run_id, kind, payload, attempt FROM orchestration.outbox "
                "WHERE status = 'pending' AND next_at <= %s ORDER BY next_at, id",
                (now,),
            )
        ).fetchall()
        return [
            OutboxRow(int(r["id"]), RunId(r["run_id"]), r["kind"], r["payload"], int(r["attempt"]))
            for r in rows
        ]

    async def outbox_sent(self, uow: UnitOfWork, row_id: int) -> None:
        await uow.conn.execute(
            "UPDATE orchestration.outbox SET status = 'sent' WHERE id = %s AND status = 'pending'",
            (row_id,),
        )

    async def outbox_retry(
        self, uow: UnitOfWork, row_id: int, next_at: datetime, error: str
    ) -> None:
        await uow.conn.execute(
            "UPDATE orchestration.outbox SET attempt = attempt + 1, next_at = %s, "
            "last_error = %s WHERE id = %s AND status = 'pending'",
            (next_at, error[:500], row_id),
        )

    async def outbox_give_up(self, uow: UnitOfWork, row_id: int, error: str) -> None:
        await uow.conn.execute(
            "UPDATE orchestration.outbox SET status = 'given_up', last_error = %s "
            "WHERE id = %s AND status = 'pending'",
            (error[:500], row_id),
        )

    async def cancel_outbox(self, uow: UnitOfWork, run_id: RunId) -> None:
        await uow.conn.execute(
            "UPDATE orchestration.outbox SET status = 'cancelled' "
            "WHERE run_id = %s AND status = 'pending'",
            (run_id,),
        )

    async def pending_outbox(self, uow: UnitOfWork, run_id: RunId) -> int:
        row = await (
            await uow.conn.execute(
                "SELECT count(*) AS n FROM orchestration.outbox "
                "WHERE run_id = %s AND status = 'pending'",
                (run_id,),
            )
        ).fetchone()
        assert row is not None
        return int(row["n"])
