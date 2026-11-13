"""Answers our node pack's calls (ENGINE-PLAN 2.3 and 2.4): links each n8n execution to a run on
its first call, then answers each block once.

A block's first answer is kept by (execution, block), so n8n's retryOnFail gets that same answer,
a refusal included, and nothing runs twice. A retry execution of the same run gets the answer an
earlier execution already had for that block, so a retry never runs an agent or adds an action
twice. Each call that finds the run working moves its deadline on.
"""

import logging
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from platform_api.db import Database, UnitOfWork, json
from platform_api.monitoring import AgentEvent, user_actor
from platform_api.orchestration.agents import (
    AgentRejected,
    AgentRuntime,
    AgentUnavailable,
    Callback,
    CardsInputs,
    CardToRun,
    CarryForward,
    TaskFailed,
    TaskFinished,
    TaskRequest,
)
from platform_api.orchestration.cards import ReviewedCards, bind_cards, review_cards
from platform_api.orchestration.n8n_calls import (
    ANOTHER_EXECUTION,
    BUSY,
    NO_EXECUTION,
    NOT_OURS,
    READ_LIMIT,
    START_LIFETIME,
    START_TOO_LATE,
    START_USED,
    AgentCall,
    Answer,
    ByRetry,
    ByStart,
    CallResult,
    IssuedStart,
    N8nReads,
    NewRun,
    NodeCall,
    NodeCatalog,
    NodeOption,
    OptionKind,
    OwnWorkflow,
    ProposeCall,
    ReadCall,
    ReadFailed,
    Refused,
    SourceReads,
    StartKind,
    StopStart,
    TryLater,
    WorkflowFacts,
    decide_link,
    rejoin,
    run_stopped,
    start_signature,
    unknown,
)
from platform_api.orchestration.runs import (
    Failed,
    Failure,
    FailureReason,
    Moved,
    Pending,
    RunState,
    Skipped,
    Working,
    linked_events,
    run_created,
    skipped_events,
    state_name,
    working_on,
)
from platform_api.orchestration.service import ActiveModel, ActivityLogPort, CallbackMinter
from platform_api.orchestration.spec import CardsTask
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.watch import Unusable
from platform_api.orchestration.watch_store import WatchStore
from platform_api.orchestration.write_actions import (
    Sites,
    UnboundIntent,
    WriteAction,
    at_sites,
)
from platform_api.shared import TEAM_TIME_ZONE, N8nExecutionId, RunId, TaskId, UserId, new_id

log = logging.getLogger(__name__)

CLAIM_LEASE = timedelta(minutes=2)
"""An agent call gives up after a minute, so a claim older than this was left by a stopped
process, and the next call takes it over."""

type Outcome = Literal["working", "answered", "refused"]

_actions_adapter: TypeAdapter[tuple[WriteAction, ...]] = TypeAdapter(tuple[WriteAction, ...])


@dataclass(frozen=True)
class CallRow:
    run_id: RunId | None
    outcome: Outcome
    call_id: str
    claimed_at: datetime
    status: int | None
    answer: dict[str, Any] | None

    def result(self) -> Answer | Refused:
        assert self.answer is not None
        if self.outcome == "refused":
            assert self.status is not None
            return Refused(self.status, str(self.answer["detail"]))
        return _answer(self.answer, replayed=True)


@dataclass(frozen=True)
class SignedStart:
    """What the Portal's start sends to the trigger: the body, and its X-Wab-Signature."""

    body: Mapping[str, str | int]
    signature: str


@dataclass(frozen=True)
class Admitted:
    run_id: RunId
    call_id: str
    task_id: TaskId
    record: RunRecord


@dataclass(frozen=True)
class Done:
    answer: Answer
    actions: tuple[Mapping[str, Any], ...] = ()
    events: tuple[AgentEvent, ...] = ()


@dataclass(frozen=True)
class Stopped:
    failure: Failure
    events: tuple[AgentEvent, ...] = ()


type Work = Done | Stopped | Refused | TryLater


def _answer(stored: Mapping[str, Any], replayed: bool = False) -> Answer:
    return Answer(tuple(stored["items"]), replayed, bool(stored.get("cut_off", False)))


def _stored(answer: Answer) -> dict[str, Any]:
    return {"items": [dict(item) for item in answer.items], "cut_off": answer.cut_off}


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
                "UPDATE orchestration.node_calls SET attempts = attempts + 1 "
                "WHERE execution_id = %s AND node_name = %s "
                "RETURNING run_id, outcome, call_id, claimed_at, status, answer",
                (call.execution_id, call.node_name),
            )
        ).fetchone()
        if row is None:
            return None
        return CallRow(
            None if row["run_id"] is None else RunId(row["run_id"]),
            row["outcome"],
            row["call_id"],
            row["claimed_at"],
            row["status"],
            row["answer"],
        )

    async def claim(self, uow: UnitOfWork, call: NodeCall, run_id: RunId) -> str:
        call_id = new_id("call")
        await uow.conn.execute(
            "INSERT INTO orchestration.node_calls (execution_id, node_name, run_id, kind, "
            "attempts, outcome, call_id, claimed_at) VALUES (%s, %s, %s, %s, 1, 'working', %s, %s)"
            " ON CONFLICT (execution_id, node_name) DO UPDATE SET call_id = EXCLUDED.call_id, "
            "claimed_at = EXCLUDED.claimed_at",
            (call.execution_id, call.node_name, run_id, call.kind, call_id, uow.now),
        )
        return call_id

    async def keep(
        self,
        uow: UnitOfWork,
        call: NodeCall,
        run_id: RunId | None,
        result: Answer | Refused,
        actions: Sequence[Mapping[str, Any]] = (),
        call_id: str | None = None,
    ) -> bool:
        """Keeps a block's one answer or refusal. With call_id, only that claim may keep it: a
        claim that was taken over meanwhile keeps nothing, and False says so."""
        match result:
            case Answer():
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
            "attempts, outcome, call_id, claimed_at, status, answer, actions, answered_at) "
            "VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (execution_id, node_name) DO UPDATE SET run_id = EXCLUDED.run_id, "
            "outcome = EXCLUDED.outcome, status = EXCLUDED.status, answer = EXCLUDED.answer, "
            "actions = EXCLUDED.actions, answered_at = EXCLUDED.answered_at",
            (
                call.execution_id,
                call.node_name,
                run_id,
                call.kind,
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

    async def waiting_run(self, uow: UnitOfWork, use_case_id: str) -> RunId | None:
        """The run of this use case that waits for a yes, if one does (one waiting run per
        workflow, ADR 0026)."""
        row = await (
            await uow.conn.execute(
                "SELECT run_id FROM orchestration.runs WHERE use_case_id = %s "
                "AND state = 'AwaitingApproval' ORDER BY started_at LIMIT 1",
                (use_case_id,),
            )
        ).fetchone()
        return None if row is None else RunId(row["run_id"])


class NodeCalls:
    def __init__(
        self,
        db: Database,
        activity: ActivityLogPort,
        agents: AgentRuntime,
        mint_callback: CallbackMinter,
        catalog: NodeCatalog,
        workflows: WorkflowFacts,
        n8n: N8nReads,
        sources: SourceReads,
        sites: Sites,
        models: ActiveModel | None = None,
        *,
        start_secret: str | None = None,
        time_zone: ZoneInfo = TEAM_TIME_ZONE,
    ) -> None:
        self._db = db
        self._activity = activity
        self._agents = agents
        self._mint_callback = mint_callback
        self._catalog = catalog
        self._workflows = workflows
        self._n8n = n8n
        self._sources = sources
        self._sites = sites
        self._models = models
        self._start_secret = start_secret
        self._time_zone = time_zone
        self._store = Store()
        self._watch = WatchStore()
        self._book = CallBook()

    async def options(self, kind: OptionKind, of: Mapping[str, str]) -> list[NodeOption]:
        return await self._catalog.options(kind, of)

    async def issue_start(
        self, run_id: RunId, kind: StartKind, workflow_id: str, webhook_id: str
    ) -> SignedStart:
        """A start for one pending run of one workflow, signed for that workflow's trigger."""
        if self._start_secret is None:
            raise RuntimeError("WAB_START_SECRET is not set, so no start can be signed.")
        async with self._db.transaction("orchestration") as uow:
            start = await self._book.issue_start(uow, run_id, kind, workflow_id)
        expires = int(start.expires_at.timestamp())
        signature = start_signature(
            self._start_secret, workflow_id, webhook_id, start.nonce, kind, expires
        )
        return SignedStart({"nonce": start.nonce, "kind": kind, "expires": expires}, signature)

    async def call(self, call: NodeCall) -> CallResult:
        async with self._db.transaction("orchestration") as uow:
            admitted = await self._admit(uow, call)
        if not isinstance(admitted, Admitted):
            return admitted
        work = await self._work(admitted, call)
        async with self._db.transaction("orchestration") as uow:
            return await self._finish(uow, admitted, call, work)

    async def _admit(self, uow: UnitOfWork, call: NodeCall) -> Admitted | CallResult:
        await self._book.hold_execution(uow, call.execution_id)
        row = await self._book.call(uow, call)
        if row is not None and row.outcome != "working":
            if row.run_id is not None:
                await self._touch(uow, row.run_id, call.execution_id)
            return row.result()
        if row is not None and row.claimed_at > uow.now - CLAIM_LEASE:
            return BUSY
        run_id = await self._book.linked_run(uow, call.execution_id)
        if (refused := await self._catalog.unknown_in(call.work)) is not None:
            return await self._refuse(uow, call, run_id, refused)
        if run_id is None:
            linked = await self._link(uow, call)
            if isinstance(linked, TryLater):
                return linked
            if isinstance(linked, Refused):
                run_id = await self._book.linked_run(uow, call.execution_id)
                return await self._refuse(uow, call, run_id, linked)
            run_id = linked
        record = await self._store.load_run(uow, run_id, lock=True)
        assert record is not None
        match record.state:
            case Skipped():
                await self._book.keep(uow, call, run_id, Answer(()))
                return Answer(())
            case Working(execution=live) if live == call.execution_id:
                pass
            case Working():
                return await self._refuse(uow, call, run_id, ANOTHER_EXECUTION)
            case Failed(failure=failure):
                return await self._refuse(uow, call, run_id, run_stopped(failure.message))
            case _:
                why = f"it is {state_name(record.state)}, not working."
                return await self._refuse(uow, call, run_id, run_stopped(why))
        record = await self._touch_record(uow, record)
        earlier = await self._book.answered_in_run(uow, run_id, call)
        if earlier is not None:
            answer = _answer(earlier, replayed=True)
            await self._book.keep(uow, call, run_id, answer)
            return answer
        if await self._book.working_in_run(uow, run_id, call):
            return BUSY
        call_id = await self._book.claim(uow, call, run_id)
        return Admitted(run_id, call_id, TaskId(f"{run_id}/{call_id}"), record)

    async def _refuse(
        self, uow: UnitOfWork, call: NodeCall, run_id: RunId | None, refused: Refused
    ) -> Refused:
        log.info(
            "refused %s call %r of n8n execution %s: %s",
            call.kind,
            call.node_name,
            call.execution_id,
            refused.detail,
        )
        await self._book.keep(uow, call, run_id, refused)
        return refused

    async def _link(self, uow: UnitOfWork, call: NodeCall) -> RunId | Refused | TryLater:
        facts = await self._n8n.execution(call.execution_id)
        if facts is None:
            return NO_EXECUTION
        own = await self._workflows.workflow(facts.workflow_id)
        if own is None:
            return NOT_OURS
        retried, version_id = None, facts.version_id
        if facts.retry_of is not None:
            retried = await self._book.linked_run(uow, facts.retry_of)
            version_id = version_id or await self._book.version_of(uow, facts.retry_of)
        start = None
        if facts.start_nonce is not None:
            start = await self._book.start(uow, facts.start_nonce)
        version = None
        if version_id is not None:
            version = await self._workflows.version(facts.workflow_id, version_id)
        link = decide_link(facts, retried, start, own.holder, version, uow.now)
        execution = call.execution_id

        async def linked(run_id: RunId) -> RunId:
            await self._book.link(
                uow,
                execution,
                run_id,
                facts.workflow_id,
                facts.mode,
                facts.retry_of,
                version_id,
            )
            return run_id

        match link:
            case Refused():
                return link
            case NewRun(started_by, trigger):
                return await linked(
                    await self._new_run(uow, own, started_by, trigger, call, facts.mode)
                )
            case StopStart(issued, why):
                record = await self._pending_for(uow, issued, execution)
                if isinstance(record, Refused):
                    return record
                assert isinstance(record.state, Pending)
                failure = Failure(FailureReason.SAFETY_DENIED, why.detail, retryable=False)
                await self._commit(uow, record, record.state.fail(failure))
                await self._store.cancel_outbox(uow, record.run_id)
                await linked(record.run_id)
                return why
            case ByStart(issued, holder):
                record = await self._pending_for(uow, issued, execution)
                if isinstance(record, Refused):
                    return record
                pending = record.state
                assert isinstance(pending, Pending)
                waiting = None
                if issued.kind != "test":
                    waiting = await self._book.waiting_run(uow, record.spec.use_case_id)
                moved = (
                    pending.link(execution, facts.mode, uow.now)
                    if waiting is None
                    else pending.skip(execution, facts.mode, waiting)
                )
                await self._commit(uow, record, moved, joined_by=holder)
                return await linked(record.run_id)
            case ByRetry(run_id, holder):
                record = await self._store.load_run(uow, run_id, lock=True)
                assert record is not None
                match rejoin(record.state, execution, facts.mode, uow.now):
                    case Refused() as refused:
                        return refused
                    case Moved() as moved:
                        await self._commit(uow, record, moved, joined_by=holder)
                        return await linked(run_id)

    async def _pending_for(
        self, uow: UnitOfWork, issued: IssuedStart, execution: N8nExecutionId
    ) -> RunRecord | Refused:
        """The run a start was issued for, while it still waits to start. The start is used up
        either way, so it never starts anything twice."""
        if not await self._book.use_start(uow, issued.nonce, execution):
            return START_USED
        record = await self._store.load_run(uow, issued.run_id, lock=True)
        assert record is not None
        return record if isinstance(record.state, Pending) else START_TOO_LATE

    async def _new_run(
        self,
        uow: UnitOfWork,
        own: OwnWorkflow,
        started_by: UserId,
        trigger: Literal["person", "schedule"],
        call: NodeCall,
        mode: str,
    ) -> RunId:
        spec = replace(own.spec, trigger=trigger)
        names = await self._store.names(uow, [started_by])
        created = run_created(
            spec.use_case_id,
            spec.use_case_version,
            spec.use_case_name,
            user_actor(started_by, names[started_by]),
            trigger,
        )
        run_id = RunId(new_id("run"))
        waiting = await self._book.waiting_run(uow, spec.use_case_id)
        state: RunState
        if waiting is None:
            state = working_on(run_id, call.execution_id, 1, uow.now)
            events = linked_events(created, call.execution_id, mode)
        else:
            state = Skipped(run_id, waiting)
            events = skipped_events(created, call.execution_id, mode, waiting)
        record = RunRecord(run_id, spec, started_by, uow.now, uow.now, 1, state, (), None)
        await self._store.insert_run(uow, record, f"n8n:{call.execution_id}")
        await self._activity.append(uow, run_id, events)
        return run_id

    async def _touch(self, uow: UnitOfWork, run_id: RunId, execution: N8nExecutionId) -> None:
        record = await self._store.load_run(uow, run_id, lock=True)
        if record is None:
            return
        match record.state:
            case Working(execution=live) if live == execution:
                await self._touch_record(uow, record)
            case _:
                pass

    async def _touch_record(self, uow: UnitOfWork, record: RunRecord) -> RunRecord:
        assert isinstance(record.state, Working)
        return await self._store.save_run(uow, record, record.state.touch(uow.now))

    async def _work(self, admitted: Admitted, call: NodeCall) -> Work:
        match call.work:
            case ReadCall(source, place, query):
                read = await self._sources.read(source, place, query)
                if isinstance(read, ReadFailed):
                    return TryLater(read.detail)
                items = tuple(read[:READ_LIMIT])
                return Done(Answer(items, cut_off=len(read) > READ_LIMIT))
            case AgentCall(agent, inputs):
                return await self._run_agent(admitted, agent, inputs)
            case ProposeCall(action, place, title, body, subject):
                entry = self._catalog.write(action)
                proposed = WriteAction(
                    entry.connector,
                    entry.operation,
                    {entry.target_key: place},
                    {"title": title, "body": body},
                )
                return Done(Answer(()), _recorded(at_sites((proposed,), self._sites), subject))

    async def _run_agent(self, admitted: Admitted, agent: str, inputs: Mapping[str, str]) -> Work:
        card_run = await self._workflows.agent_run(agent, inputs)
        if card_run is None:
            return unknown("agent", agent)
        model = None
        if self._models is not None:
            async with self._db.transaction("orchestration") as uow:
                model = await self._models.access(uow)
        record = admitted.record
        assert isinstance(record.state, Working)
        url, token = self._mint_callback(
            admitted.run_id, admitted.task_id, record.state.callback_expires_at
        )
        request = TaskRequest(
            task_id=admitted.task_id,
            run_id=admitted.run_id,
            instruction=record.spec.instruction,
            inputs=CardsInputs(
                agents=[CardToRun(card=card_run.card, values=dict(card_run.values))]
            ),
            carry_forward=CarryForward(),
            time_zone=self._time_zone.key,
            callback=Callback(url=url, token=token),
            model=model,
        )
        match await self._agents.run_task(request):
            case AgentUnavailable(detail):
                return TryLater(detail)
            case AgentRejected(detail):
                return Stopped(Failure(FailureReason.AGENT_ERROR, detail, retryable=False))
            case TaskFailed(error=error, events=events):
                detail = f"{error.type}: {error.message}"
                failure = Failure(FailureReason.AGENT_ERROR, detail, retryable=error.retryable)
                return Stopped(failure, tuple(events))
            case TaskFinished(output=output, events=events):
                task = CardsTask((card_run,))
                match review_cards(task, output.proposed):
                    case Unusable(detail):
                        failure = Failure(FailureReason.AGENT_ERROR, detail, retryable=False)
                        return Stopped(failure, tuple(events))
                    case ReviewedCards() as reviewed:
                        bound = bind_cards(task, reviewed)
                if isinstance(bound, UnboundIntent):
                    detail = f"No connector is bound for {', '.join(bound.kinds)}"
                    failure = Failure(FailureReason.UNBOUND_INTENT, detail, retryable=False)
                    return Stopped(failure, tuple(events))
                found = {
                    "summary": output.summary,
                    "findings": [f.model_dump(mode="json") for f in output.findings],
                }
                actions = _recorded(at_sites(bound, self._sites), None)
                return Done(Answer((found,)), actions, tuple(events))

    async def _finish(
        self, uow: UnitOfWork, admitted: Admitted, call: NodeCall, work: Work
    ) -> CallResult:
        record = await self._store.load_run(uow, admitted.run_id, lock=True)
        assert record is not None
        if isinstance(work, TryLater):
            await self._book.release(uow, admitted.call_id)
            return work
        events = work.events if isinstance(work, Done | Stopped) else ()
        if events:
            await self._activity.ingest_agent_events(uow, admitted.run_id, admitted.task_id, events)
        state = record.state
        if not (isinstance(state, Working) and state.execution == call.execution_id):
            why = run_stopped(f"it moved on while this block worked: it is {state_name(state)}.")
            await self._book.keep(uow, call, admitted.run_id, why, call_id=admitted.call_id)
            return why
        match work:
            case Refused():
                await self._book.keep(uow, call, admitted.run_id, work, call_id=admitted.call_id)
                return work
            case Stopped(failure):
                stopped = run_stopped(failure.message)
                if not await self._book.keep(
                    uow, call, admitted.run_id, stopped, call_id=admitted.call_id
                ):
                    return BUSY
                await self._commit(uow, record, state.fail(failure))
                await self._store.cancel_outbox(uow, admitted.run_id)
                return stopped
            case Done(answer, actions):
                earlier = await self._book.answered_in_run(uow, admitted.run_id, call)
                if earlier is not None:
                    answer, actions = _answer(earlier, replayed=True), ()
                if not await self._book.keep(
                    uow, call, admitted.run_id, answer, actions, call_id=admitted.call_id
                ):
                    return BUSY
                return answer

    async def _commit(
        self,
        uow: UnitOfWork,
        record: RunRecord,
        moved: Moved[Any],
        *,
        joined_by: UserId | None = None,
    ) -> RunRecord:
        saved = await self._store.save_run(uow, record, moved.state, joined_by=joined_by)
        await self._activity.append(uow, record.run_id, moved.events)
        await self._watch.run_moved(uow, record, moved.state)
        return saved


def _recorded(actions: Sequence[WriteAction], subject: str | None) -> tuple[Mapping[str, Any], ...]:
    """The actions a block adds to the run's proposal, each with what it is about, so a later
    change is never made twice for one subject (ENGINE-PLAN 2.3.8)."""
    dumped = _actions_adapter.dump_python(tuple(actions), mode="json")
    return tuple({**action, "subject": subject} for action in dumped)
