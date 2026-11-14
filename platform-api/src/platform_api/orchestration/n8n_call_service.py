"""Answers our node pack's calls (ENGINE-PLAN 2.3 and 2.4): links each n8n execution to a run on
its first call, then answers each block once.

A block's first answer is kept by (execution, block), so n8n's retryOnFail gets that same answer,
a refusal included, and nothing runs twice. A retry execution of the same run gets the answer an
earlier execution already had for that block, so a retry never runs an agent or adds an action
twice. Each call that finds the run working moves its deadline on.
"""

import asyncio
import contextlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from platform_api.db import Database, UnitOfWork
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
from platform_api.orchestration.dispatch import HeldWait, Sealer
from platform_api.orchestration.n8n_call_book import (
    CLAIM_LEASE,
    CallBook,
    actions_adapter,
    answer_of,
    replayed,
)
from platform_api.orchestration.n8n_calls import (
    ANOTHER_EXECUTION,
    BUSY,
    CANNOT_SEAL,
    CHANGED_CALL,
    DENIED,
    GITHUB_RELEASES,
    NO_EXECUTION,
    NO_TELL_FLOW,
    NOT_FAILED,
    NOT_OUR_ERROR_WORKFLOW,
    NOT_OURS,
    NOTHING_READ,
    READ_LIMIT,
    START_TOO_LATE,
    START_USED,
    TEST_RUN_STOPS,
    AgentCall,
    AgentToRun,
    Answer,
    Answered,
    AskAnswer,
    AskCall,
    ByRetry,
    ByStart,
    CallResult,
    CannotRun,
    Carry,
    FailedExecution,
    Finished,
    IssuedStart,
    N8nFailures,
    N8nReads,
    N8nSwitch,
    NewRun,
    NodeCall,
    NodeCatalog,
    NodeOption,
    NothingToChange,
    OptionKind,
    OwnWorkflow,
    ProposeCall,
    ReadCall,
    ReadFailed,
    Refused,
    SourceReads,
    StopRun,
    StopStart,
    TellCall,
    TheRequest,
    TryLater,
    Waiting,
    WorkflowFacts,
    WriteCall,
    admit_write,
    after_write,
    decide_link,
    fail_by_report,
    failure_words,
    rejoin,
    run_stopped,
    unknown,
    write_answer,
)
from platform_api.orchestration.runs import (
    Acting,
    AwaitingApproval,
    Expired,
    Failed,
    Failure,
    FailureReason,
    Lost,
    Moved,
    Pending,
    Rejected,
    RunState,
    Skipped,
    Succeeded,
    Working,
    linked_events,
    run_created,
    skipped_events,
    state_name,
    working_on,
    write_done,
)
from platform_api.orchestration.service import (
    DENIED_ON_THE_WIRE,
    ActiveModel,
    ActivityLogPort,
    CallbackMinter,
    approval_link,
    enqueue_announcement,
    request_for,
    steps_view,
    write_denied,
)
from platform_api.orchestration.spec import CardsTask
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.tell import (
    NOTHING_TO_REPORT,
    REACH,
    SENDING_LINE,
    NotConfirmed,
    Reach,
    TellMessage,
    TellOutlet,
    Told,
    compose,
    ending_of,
    not_confirmed_line,
    sent_line,
    something_to_report,
    told_event,
    would_have_line,
)
from platform_api.orchestration.watch import Unusable
from platform_api.orchestration.watch_store import WatchStore
from platform_api.orchestration.write_actions import (
    AuthorizedWrite,
    Carried,
    Deny,
    Proposal,
    Sites,
    UnboundIntent,
    WriteAction,
    WriteGateway,
    WritingRun,
    at_sites,
    check,
    describe,
    digest,
    made_subjects,
    still_to_make,
    subject_key,
)
from platform_api.shared import (
    TEAM_TIME_ZONE,
    N8nExecutionId,
    ProposalId,
    RunId,
    TaskId,
    UserId,
    new_id,
)

log = logging.getLogger(__name__)

SWEEP_EVERY = timedelta(seconds=5)
"""How often the sweep reads how each open run's execution ended, so a run that ended with no
call or report saying so shows its end within seconds (ENGINE-PLAN 2.3.3 and 2.8)."""


@dataclass(frozen=True)
class Admitted:
    run_id: RunId
    call_id: str
    task_id: TaskId
    record: RunRecord


@dataclass(frozen=True)
class Writing:
    """A write the safety checker allowed, claimed by this call."""

    run_id: RunId
    call_id: str
    write: AuthorizedWrite


@dataclass(frozen=True)
class Done:
    answer: Answer
    actions: tuple[Mapping[str, Any], ...] = ()
    events: tuple[AgentEvent, ...] = ()


@dataclass(frozen=True)
class Stopped:
    failure: Failure
    events: tuple[AgentEvent, ...] = ()


@dataclass(frozen=True)
class Asking:
    """Ask for a yes, done in the finishing transaction, under the run's lock."""

    resume_url: str


@dataclass(frozen=True)
class FailedRun:
    run_id: RunId


@dataclass(frozen=True)
class LeftAsIs:
    detail: str


type FailureResult = FailedRun | LeftAsIs | Refused | TryLater


@dataclass(frozen=True)
class Kept:
    """An answer the block's own work already kept, as a Tell keeps each of its answers."""

    answer: Told | Refused


type Work = Done | Stopped | Asking | Kept | Refused | TryLater


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
        box: Sealer | None = None,
        time_zone: ZoneInfo = TEAM_TIME_ZONE,
        gateway: WriteGateway | None = None,
        tells: TellOutlet | None = None,
        failures: N8nFailures | None = None,
        switch: N8nSwitch | None = None,
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
        self._box = box
        self._time_zone = time_zone
        self._gateway = gateway
        self._tells = tells
        self._failures = failures
        self._switch = switch
        self._store = Store()
        self._watch = WatchStore()
        self._book = CallBook()

    async def options(self, kind: OptionKind, of: Mapping[str, str]) -> list[NodeOption]:
        return await self._catalog.options(kind, of)

    async def report(self, reporter: N8nExecutionId, failed: N8nExecutionId) -> FailureResult:
        """Report a failure, from the error workflow (ENGINE-PLAN 2.8). Nothing in the report is
        taken as said: the reporter must be an execution of our error workflow, and the failed
        block and its words come from n8n's own record of a failed execution. While n8n cannot
        be read, every report is refused."""
        if self._failures is None:
            return NOT_OUR_ERROR_WORKFLOW
        ours = await self._failures.error_workflow_id()
        facts = await self._n8n.execution(reporter)
        if not ours or facts is None or facts.workflow_id != ours:
            return NOT_OUR_ERROR_WORKFLOW
        found = await self._failures.failure(failed)
        if found is None:
            return NOT_FAILED
        return await self._fail_run(found)

    async def _fail_run(self, failed: FailedExecution) -> FailureResult:
        """Fails the run a failed execution carried, with the node's words (ENGINE-PLAN 2.3.9 and
        2.8). An execution none of whose blocks had called is linked first, as its first call
        would have linked it, so the Portal shows the run that stopped."""
        execution = failed.execution_id
        async with self._db.transaction("orchestration") as uow:
            await self._book.hold_execution(uow, execution)
            run_id = await self._book.linked_run(uow, execution) or await self._book.claimed_run(
                uow, execution
            )
            if run_id is None:
                match await self._link(uow, execution):
                    case TryLater() as later:
                        return later
                    case Refused(detail=detail):
                        return LeftAsIs(detail)
                    case linked:
                        run_id = linked
            record = await self._store.load_run(uow, run_id, lock=True)
            assert record is not None
            read = await self._book.results_in_run(uow, run_id)
            words = failure_words(failed, read_anything=bool(read))
            failure = Failure(FailureReason.WORKFLOW_NODE_ERROR, words, retryable=True)
            writing = await self._book.writing(uow, execution)
            moved = fail_by_report(record.state, execution, failure, writing)
            if moved is None and writing and isinstance(record.state, Acting):
                return LeftAsIs("Its changes are being made, so the write's own outcome decides.")
            if moved is None:
                return LeftAsIs(f"The run is {state_name(record.state)}, so it stays as it is.")
            await self._commit(uow, record, moved)
            await self._store.cancel_outbox(uow, run_id)
        return FailedRun(run_id)

    async def sweep(self) -> list[RunId]:
        """Settles each open run whose execution n8n says ended, for an end no call or report
        brought: a failure fails it with the block's words, and an execution that ran to its end
        without asking for a yes closes it, since nothing waits for a change (ENGINE-PLAN 2.3.3
        and 2.8). A run that has ended is not open, so it is never settled twice."""
        if self._failures is None:
            return []
        async with self._db.transaction("orchestration") as uow:
            open_ = await self._book.open_executions(uow)
        settled: list[RunId] = []
        for execution in open_:
            match await self._failures.ended(execution):
                case FailedExecution() as found:
                    result = await self._fail_run(found)
                    run_id = result.run_id if isinstance(result, FailedRun) else None
                case Finished():
                    run_id = await self._close(execution)
                case None:
                    run_id = None
            if run_id is not None:
                settled.append(run_id)
        return settled

    async def _close(self, execution: N8nExecutionId) -> RunId | None:
        """A run whose execution n8n ran to its end while the run was still working never asked
        for a yes, so it had nothing to change: a Tell-only workflow, or a branch that ended at
        Nothing to change. A test run n8n finished before any of its blocks called passed: it
        reached no yes and wrote nothing."""
        async with self._db.transaction("orchestration") as uow:
            await self._book.hold_execution(uow, execution)
            run_id = await self._book.linked_run(uow, execution) or await self._book.claimed_run(
                uow, execution
            )
            record = None if run_id is None else await self._store.load_run(uow, run_id, lock=True)
            if record is None:
                return None
            match record.state:
                case Working(execution=live) as working if live == execution:
                    moved = working.nothing_to_change()
                case Pending(claimant=claimant) as pending if claimant == execution:
                    moved = pending.passed_test()
                case _:
                    return None
            await self._commit(uow, record, moved)
            await self._store.cancel_outbox(uow, record.run_id)
            return record.run_id

    async def sweep_forever(self, stop: asyncio.Event, every: timedelta = SWEEP_EVERY) -> None:
        while not stop.is_set():
            try:
                await self.sweep()
            except Exception:
                log.exception("the failure sweep failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), every.total_seconds())

    async def call(self, call: NodeCall) -> CallResult:
        if isinstance(call.work, WriteCall):
            return await self._write(call)
        async with self._db.transaction("orchestration") as uow:
            admitted = await self._admit(uow, call)
        if admitted == NOT_OURS:
            await self._take_off_if_deleted(call.execution_id)
        if not isinstance(admitted, Admitted):
            return admitted
        work = await self._work(admitted, call)
        async with self._db.transaction("orchestration") as uow:
            return await self._finish(uow, admitted, call, work)

    async def _take_off_if_deleted(self, execution: N8nExecutionId) -> None:
        """A deleted use case whose workflow n8n still runs, because the delete could not take it
        off then, is taken off now, so it stops starting runs our API refuses."""
        facts = await self._n8n.execution(execution)
        if self._switch is None or facts is None:
            return
        if not await self._workflows.deleted(facts.workflow_id):
            return
        try:
            await self._switch.go_off(facts.workflow_id)
        except Exception as error:
            log.warning(
                "could not take deleted workflow %s off in n8n: %s", facts.workflow_id, error
            )

    async def _admit(self, uow: UnitOfWork, call: NodeCall) -> Admitted | CallResult:
        linked = await self._linked_run(uow, call)
        if not isinstance(linked, str):
            return linked
        run_id = linked
        record = await self._store.load_run(uow, run_id, lock=True)
        assert record is not None
        match record.state:
            case Skipped():
                skipped = NothingToChange() if call.kind == "ask" else Answer(())
                await self._book.keep(uow, call, run_id, skipped)
                return skipped
            case Working(execution=live) if live == call.execution_id:
                record = await self._touch_record(uow, record)
            case Succeeded() | Rejected() | Expired() if call.kind == "tell":
                if not await self._book.carried_last(uow, run_id, call.execution_id):
                    return await self._refuse(uow, call, run_id, ANOTHER_EXECUTION)
            case Working():
                return await self._refuse(uow, call, run_id, ANOTHER_EXECUTION)
            case Failed(failure=failure):
                return await self._refuse(uow, call, run_id, run_stopped(failure.message))
            case _:
                why = f"it is {state_name(record.state)}, not working."
                return await self._refuse(uow, call, run_id, run_stopped(why))
        earlier = await self._book.answered_in_run(uow, run_id, call)
        if earlier is not None:
            answer = replayed(call.kind, earlier)
            await self._book.keep(uow, call, run_id, answer)
            return answer
        if await self._book.working_in_run(uow, run_id, call):
            return BUSY
        call_id = await self._book.claim(uow, call, run_id)
        return Admitted(run_id, call_id, TaskId(f"{run_id}/{call_id}"), record)

    async def _linked_run(self, uow: UnitOfWork, call: NodeCall) -> RunId | CallResult:
        """The run a block's call is for, linking its execution on the first call. A call this
        block already had an answer or a refusal for gets that same one again."""
        await self._book.hold_execution(uow, call.execution_id)
        row = await self._book.call(uow, call)
        if row is not None and (row.kind, row.content_hash) != (call.kind, call.content_hash):
            return CHANGED_CALL
        if row is not None:
            await self._book.count_again(uow, call)
        if row is not None and row.outcome != "working":
            if row.run_id is not None:
                await self._touch(uow, row.run_id, call.execution_id)
            return row.result()
        if row is not None and row.claimed_at > uow.now - CLAIM_LEASE:
            return BUSY
        run_id = await self._book.linked_run(uow, call.execution_id)
        if run_id is None:
            linked = await self._link(uow, call.execution_id)
            if isinstance(linked, TryLater):
                return linked
            if isinstance(linked, Refused):
                run_id = await self._book.linked_run(uow, call.execution_id)
                return await self._refuse(uow, call, run_id, linked)
            run_id = linked
        if (refused := await self._catalog.unknown_in(call.work)) is not None:
            return await self._refuse(uow, call, run_id, refused)
        return run_id

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

    async def _link(self, uow: UnitOfWork, execution: N8nExecutionId) -> RunId | Refused | TryLater:
        facts = await self._n8n.execution(execution)
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
        link = decide_link(facts, retried, start, own.holder, version, uow.now, own.on)

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
                    await self._new_run(uow, own, started_by, trigger, execution, facts.mode)
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
        execution: N8nExecutionId,
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
            state = working_on(run_id, execution, 1, uow.now)
            events = linked_events(created, execution, mode)
        else:
            state = Skipped(run_id, waiting)
            events = skipped_events(created, execution, mode, waiting)
        record = RunRecord(run_id, spec, started_by, uow.now, uow.now, 1, state, (), None)
        await self._store.insert_run(uow, record, f"n8n:{execution}")
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
            case AskCall(resume_url):
                return Asking(resume_url)
            case WriteCall():
                raise AssertionError("a write is carried by _write, never by _work")
            case TellCall() as tell:
                return await self._tell(admitted, call, tell)
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
        record = admitted.record
        task = record.spec.task
        pinned = (
            next((run.card for run in task.agents if run.card.id == agent), None)
            if isinstance(task, CardsTask)
            else None
        )
        match await self._workflows.agent_run(agent, inputs, pinned):
            case None:
                return unknown("agent", agent)
            case CannotRun(detail):
                return Refused(422, detail)
            case AgentToRun(card_run, release_of):
                pass
        release = None if release_of is None else await self._newest_release(release_of)
        if isinstance(release, TryLater):
            return release
        async with self._db.transaction("orchestration") as uow:
            model = None if self._models is None else await self._models.access(uow)
            last_start = await self._store.last_finished_start(
                uow, record.spec.use_case_id, record.run_id
            )
        # The last run's own day in the team's zone, as the old engine tells the agent, so a card
        # that searches since its last run leaves no gap.
        last_run_on = None if last_start is None else last_start.astimezone(self._time_zone).date()
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
            carry_forward=CarryForward(last_run_on=last_run_on),
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
                found: dict[str, Any] = {
                    "summary": output.summary,
                    "findings": [f.model_dump(mode="json") for f in output.findings],
                }
                subject = None if release is None else f"{release_of}@{release}"
                actions = _recorded(at_sites(bound, self._sites), subject)
                if release_of is not None:
                    found |= {"newer": bool(actions), "version": release}
                return Done(Answer((found,)), actions, tuple(events))

    async def _newest_release(self, repo: str) -> str | None | TryLater:
        """Read by our API, not taken from the agent's words, so it can key the change across
        runs. None when the repository has no release the tag rule counts."""
        read = await self._sources.read(GITHUB_RELEASES, repo, None)
        if isinstance(read, ReadFailed):
            return TryLater(read.detail)
        newest = read[0].get("id") if read else None
        return newest if isinstance(newest, str) else None

    async def _tell(self, admitted: Admitted, call: NodeCall, tell: TellCall) -> Kept | TryLater:
        """A notice under the Tell rule (ENGINE-PLAN 2.3.12, D19): composed from what the run
        read, with what the gateway made after a yes once the run has succeeded, and sent
        nowhere in a test run. A Tell keeps each of its answers here, a refusal too."""
        record = admitted.record
        ending = ending_of(record.state)
        async with self._db.transaction("orchestration") as uow:
            results = await self._book.results_in_run(uow, record.run_id)
            test = record.spec.stops_at_gate or await self._book.started_as_test(uow, record.run_id)
        if not results:
            return await self._keep_tell(admitted, call, NOTHING_READ)
        if self._tells is None:
            return await self._keep_tell(admitted, call, NO_TELL_FLOW)
        reach = REACH[tell.where]
        if tell.what == "only_when_something_to_report" and not something_to_report(
            results, ending.made
        ):
            return await self._keep_tell(
                admitted, call, Told("nothing_to_report", NOTHING_TO_REPORT)
            )
        setup = self._tells.setup
        if test:
            line = would_have_line(reach, setup.channel)
            return await self._keep_tell(admitted, call, Told("would_have_sent", line))
        message = compose(record.spec.use_case_name, results, reach, setup, record.run_id, ending)
        return await self._send(admitted, call, self._tells, message, reach)

    async def _keep_tell(
        self, admitted: Admitted, call: NodeCall, answer: Told | Refused
    ) -> Kept | TryLater:
        async with self._db.transaction("orchestration") as uow:
            kept = await self._book.keep(
                uow, call, admitted.run_id, answer, call_id=admitted.call_id
            )
            if kept and isinstance(answer, Told):
                await self._note_told(uow, admitted.run_id, call.node_name, answer)
        return Kept(answer) if kept else BUSY

    async def _note_told(self, uow: UnitOfWork, run_id: RunId, block: str, told: Told) -> None:
        event = told_event(block, told)
        if event is not None:
            await self._activity.append(uow, run_id, [event])

    async def _send(
        self,
        admitted: Admitted,
        call: NodeCall,
        outlet: TellOutlet,
        message: TellMessage,
        reach: Reach,
    ) -> Kept | TryLater:
        """Keeps the Tell as sending before the post, so a flow that posted and then answered 5xx,
        or a stop mid-post, is never posted again: a repeat gets "sending, not confirmed"."""
        sending = Told("sending", SENDING_LINE)
        async with self._db.transaction("orchestration") as uow:
            kept = await self._book.keep(
                uow, call, admitted.run_id, sending, call_id=admitted.call_id
            )
        if not kept:
            return BUSY
        try:
            await outlet.send(admitted.run_id, call.node_name, message)
            told = Told("sent", sent_line(reach, outlet.setup.channel))
        except NotConfirmed as why:
            told = Told("not_confirmed", not_confirmed_line(str(why)))
        async with self._db.transaction("orchestration") as uow:
            if await self._book.settle(uow, admitted.call_id, told):
                await self._note_told(uow, admitted.run_id, call.node_name, told)
        return Kept(told)

    async def _finish(
        self, uow: UnitOfWork, admitted: Admitted, call: NodeCall, work: Work
    ) -> CallResult:
        record = await self._store.load_run(uow, admitted.run_id, lock=True)
        assert record is not None
        if isinstance(work, TryLater):
            await self._book.release(uow, admitted.call_id)
            return work
        if isinstance(work, Kept):
            return work.answer
        events = work.events if isinstance(work, Done | Stopped) else ()
        if events:
            await self._activity.ingest_agent_events(uow, admitted.run_id, admitted.task_id, events)
        state = record.state
        if not (isinstance(state, Working) and state.execution == call.execution_id):
            why = run_stopped(f"it moved on while this block worked: it is {state_name(state)}.")
            await self._book.keep(uow, call, admitted.run_id, why, call_id=admitted.call_id)
            return why
        match work:
            case Asking(resume_url):
                return await self._ask(uow, record, admitted, call, resume_url)
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
                    answer, actions = answer_of(earlier, replayed=True), ()
                if not await self._book.keep(
                    uow, call, admitted.run_id, answer, actions, call_id=admitted.call_id
                ):
                    return BUSY
                return answer

    async def _ask(
        self, uow: UnitOfWork, record: RunRecord, admitted: Admitted, call: NodeCall, url: str
    ) -> CallResult:
        """Asks for a yes on the run's proposal, held in n8n (ENGINE-PLAN 2.3.4). With nothing
        proposed, the block leaves by Nothing to change. A test run stops here and asks nobody."""
        working = record.state
        assert isinstance(working, Working)
        actions, left_out = await self._still_to_make(uow, record)
        proposal = Proposal(ProposalId(new_id("prp")), record.run_id, actions, digest(actions))
        shown = (proposal.id, proposal.digest, tuple(describe(action) for action in actions))
        test = record.spec.stops_at_gate or await self._book.started_as_test(uow, record.run_id)
        request = None
        result: AskAnswer | Refused
        moved: Moved[Any]
        if not actions:
            result, moved = NothingToChange(), working.nothing_to_change(left_out)
        elif test:
            result, moved = TEST_RUN_STOPS, working.stop_at_gate(shown, left_out)
        elif self._box is None:
            failure = Failure(FailureReason.SAFETY_DENIED, CANNOT_SEAL, retryable=False)
            result, moved = run_stopped(CANNOT_SEAL), working.fail(failure)
        elif (waiting := await self._book.waiting_run(uow, record.spec.use_case_id)) is not None:
            result, moved = NothingToChange(), working.skip(waiting)
        else:
            request = request_for(record, proposal, uow.now, self._time_zone)
            summary = await self._book.found(uow, record.run_id)
            steps = steps_view(request, ())
            result = Waiting(request.id)
            link = approval_link(request.id)
            moved = working.ask(shown, request.id, steps, link, summary, left_out)
        if not await self._book.keep(uow, call, record.run_id, result, call_id=admitted.call_id):
            return BUSY
        if actions:
            await self._store.insert_proposal(uow, proposal)
        if request is not None and self._box is not None:
            held = HeldWait(call.execution_id, self._box.seal(url))
            await self._store.insert_approval(uow, request, held)
        record = await self._commit(uow, record, moved)
        if isinstance(moved.state, AwaitingApproval) and request is not None:
            await enqueue_announcement(
                uow, self._store, record, request, proposal, moved.state.summary, self._sites
            )
        return result

    async def _still_to_make(
        self, uow: UnitOfWork, record: RunRecord
    ) -> tuple[tuple[WriteAction, ...], tuple[str, ...]]:
        """What the run's blocks proposed, less each change whose subject is made already, so the
        Approvers see only what will be made (ENGINE-PLAN 2.3.8)."""
        proposed = await self._book.proposed(uow, record.run_id)
        use_case = record.spec.use_case_id
        subjects = {subject_key(use_case, a.subject) for a in proposed if a.subject is not None}
        return still_to_make(use_case, proposed, await made_subjects(uow, subjects))

    async def _write(self, call: NodeCall) -> CallResult:
        """Make the approved changes (ENGINE-PLAN 2.3.8). The gateway makes the run's own approved
        proposal, checked against our records as it is made. The call says nothing about what."""
        if self._gateway is None:
            return TryLater("This platform has no write gateway, so it makes no changes.")
        async with self._db.transaction("orchestration") as uow:
            admitted = await self._admit_write(uow, call, self._gateway)
        if not isinstance(admitted, Writing):
            return admitted
        carried = await self._gateway.execute(admitted.write)
        async with self._db.transaction("orchestration") as uow:
            return await self._finish_write(uow, admitted, call, carried)

    async def _admit_write(
        self, uow: UnitOfWork, call: NodeCall, gateway: WriteGateway
    ) -> Writing | CallResult:
        linked = await self._linked_run(uow, call)
        if not isinstance(linked, str):
            return linked
        run_id = linked
        record = await self._store.load_run(uow, run_id, lock=True)
        assert record is not None
        held = await self._the_request(uow, record.state)
        match admit_write(record.state, call.execution_id, held, uow.now):
            case Refused() as refused:
                return await self._refuse(uow, call, run_id, refused)
            case StopRun(refused, moved):
                await self._commit(uow, record, moved)
                await self._store.cancel_outbox(uow, run_id)
                return await self._refuse(uow, call, run_id, refused)
            case Answered(answer):
                await self._book.keep(uow, call, run_id, answer)
                return answer
            case Carry(acting, took_yes):
                if took_yes is not None:
                    record = await self._commit(uow, record, took_yes)
        assert held is not None
        proposal = await self._store.load_proposal(uow, acting.proposal_id)
        assert proposal is not None
        test = record.spec.stops_at_gate or await self._book.started_as_test(uow, run_id)
        verdict = check(
            acting,
            WritingRun(record.spec.use_case_id, test),
            proposal,
            held.request,
            held.decisions,
            gateway.registry,
            gateway.sites,
        )
        match verdict:
            case Deny(reason):
                words = DENIED[reason]
                failure = Failure(FailureReason.SAFETY_DENIED, words, retryable=False)
                denied = write_denied(DENIED_ON_THE_WIRE[reason], words)
                await self._commit(uow, record, acting.fail(failure).preceded_by(denied))
                await self._store.cancel_outbox(uow, run_id)
                return await self._refuse(uow, call, run_id, Refused(403, words))
            case AuthorizedWrite() as write:
                return Writing(run_id, await self._book.claim(uow, call, run_id), write)

    async def _the_request(self, uow: UnitOfWork, state: RunState) -> TheRequest | None:
        match state:
            case (
                AwaitingApproval(approval_id=approval_id)
                | Acting(approval_id=approval_id)
                | Lost(approval_id=approval_id)
            ):
                pass
            case _:
                return None
        request = await self._store.load_approval(uow, approval_id)
        assert request is not None
        decisions = tuple(await self._store.load_decisions(uow, approval_id))
        held = await self._store.held_wait(uow, approval_id)
        return TheRequest(request, decisions, None if held is None else held.execution_id)

    async def _finish_write(
        self, uow: UnitOfWork, writing: Writing, call: NodeCall, carried: Carried
    ) -> CallResult:
        """Keeps the answer and moves the run. What this try made is logged even when the run
        moved on meanwhile, such as past its deadline."""
        record = await self._store.load_run(uow, writing.run_id, lock=True)
        assert record is not None
        answer = write_answer(carried)
        if not await self._book.keep(uow, call, writing.run_id, answer, call_id=writing.call_id):
            await self._activity.append(uow, writing.run_id, [write_done(w) for w in carried.fresh])
            return BUSY
        match record.state:
            case Acting(claimant=claimant) as acting if claimant == call.execution_id:
                await self._commit(uow, record, after_write(acting, carried))
                if carried.failure is not None:
                    await self._store.cancel_outbox(uow, writing.run_id)
            case _:
                await self._activity.append(
                    uow, writing.run_id, [write_done(w) for w in carried.fresh]
                )
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
    about = tuple(replace(action, subject=subject) for action in actions)
    return tuple(actions_adapter.dump_python(about, mode="json"))
