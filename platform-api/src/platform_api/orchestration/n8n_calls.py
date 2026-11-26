"""What our n8n node pack may ask of our API, and how an n8n execution becomes a run
(ENGINE-PLAN 2.2 to 2.4, ADRs 0026 and 0027).

The node pack's blocks call our API, and our API alone reads, runs agents and proposes. An
execution joins a run on its first call, in the order 2.3 states: a retry joins its original's
run, then a start our API issued links the run it was issued for, then a run started by hand is
the holder's, then a webhook with no start is refused, and only the Schedule Trigger's is a new
run of the version's publisher. The version the execution ran must have passed the safety check
first.

Pure, apart from the ports. The service that runs the calls is in n8n_call_service.py.
"""

import hashlib
import hmac
import json
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from platform_api.monitoring import NOTHING_READ_YET, not_found_words, stop_words
from platform_api.orchestration.agents import CardInput, CardSpec, InputKind
from platform_api.orchestration.approvals import (
    ApprovalRequest,
    Approved,
    Decision,
    approval_status,
)
from platform_api.orchestration.block_sources import source_stop
from platform_api.orchestration.cards import TOOL_RULES
from platform_api.orchestration.runs import (
    NO_ANSWER,
    TEST_PASSED,
    Acting,
    AwaitingApproval,
    Expired,
    Failed,
    Failure,
    FailureReason,
    Lost,
    Moved,
    Outcome,
    Pending,
    Proposed,
    Rejected,
    ResumeAct,
    ResumeWork,
    RunState,
    Skipped,
    Succeeded,
    Working,
    deadline,
    execution_linked,
    holder_of,
    sentence,
    state_name,
    working_on,
    write_done,
)
from platform_api.orchestration.spec import CardRun, RunSpec
from platform_api.orchestration.tell import TellWhat, TellWhere, Told
from platform_api.orchestration.write_actions import (
    ActionResult,
    Carried,
    DenyReason,
    Json,
    Made,
    MadeBefore,
    NotMade,
    describe,
    one_line,
)
from platform_api.shared import JIRA_SITE_CHANGED, ApprovalId, N8nExecutionId, RunId, UserId
from platform_api.wire import Trigger

type NodeKind = Literal["read", "agent", "propose", "ask", "write", "tell"]
type StartKind = Literal["run_now", "test", "retry"]
type OptionKind = Literal["places", "agents", "agent_inputs", "write_actions"]
type Grade = Literal["safe", "writes_refused", "needs_a_fix"]

START_LIFETIME = timedelta(seconds=240)
"""The node allows 60 s of clock skew and at most 300 s, so a start our API signs lives 240 s."""
GITHUB_RELEASES = "github_releases"
READ_LIMIT = 100
"""The most items one Read passes on (ADR 0027, long lists). It says when it stopped there."""


@dataclass(frozen=True)
class NodeOption:
    id: str
    name: str


WATCHLIST_PLACE = NodeOption("watchlist", "Software watchlist")
"""The GitHub releases place that stands for every watched software (D11). Its Read lists the
software the run checks."""
WATCHLIST_CHECKER = NodeOption("watchlist_checker", "Watchlist checker")
"""The platform's own agent that checks every watched software at once and proposes the upgrade
tickets, with the same review as before the move (D11)."""
VERSION_CHECKER_ID = "crd_version_checker"
REPO_INPUT = "GitHub repository"


def release_of(agent: str, inputs: Mapping[str, str]) -> str | None:
    """The repository whose newest release each change the agent proposes is about: the Version
    checker's own. None for any other agent."""
    return inputs.get(REPO_INPUT) if agent == VERSION_CHECKER_ID else None


def release_compared(
    found: Mapping[str, Json], *, newer: bool, version: str | None
) -> dict[str, Json]:
    """The Version checker's answer, as the release check's Newer? block reads it: newer when the
    agent proposed a change, with the newest release our API read, never one from its words. The
    simulation gateway answers the same, so a simulation plays the release check's branch."""
    return {**found, "newer": newer, "version": version}


@dataclass(frozen=True)
class ExecutionFacts:
    """What n8n's own record of an execution says, read on its first call."""

    workflow_id: str
    mode: str
    retry_of: N8nExecutionId | None
    start_nonce: str | None
    """The nonce in the Start from the Portal item, when the execution has one."""
    version_id: str | None
    """n8n's workflowVersionId: the published version, or a draft run by hand. A retry has none
    and runs its original's."""


class N8nReads(Protocol):
    """n8n's records, through its public API with the owner's key."""

    async def execution(self, execution_id: N8nExecutionId) -> ExecutionFacts | None: ...


@dataclass(frozen=True)
class Publisher:
    person: UserId | None
    """None when an n8n user published it whom our People list cannot match (D5)."""


@dataclass(frozen=True)
class RanVersion:
    grade: Grade
    publisher: Publisher | None
    """None for a draft that nobody published, which runs only by hand."""
    also: tuple[Publisher, ...] = ()
    """Every other author of the workflow it runs: whoever published that same n8n version
    before, and the authors of a workflow a roll back, an Undo or the yes put back published
    again. A run of it is their work too (ADR 0026)."""

    @property
    def parties(self) -> tuple[UserId, ...]:
        """Whose work a run of this version is, as far as our People list knows them."""
        everyone = (self.publisher, *self.also)
        return tuple(dict.fromkeys(p.person for p in everyone if p is not None and p.person))

    @property
    def unknown(self) -> bool:
        """Someone our People list can't match published it, or authored what it republishes."""
        return any(p is not None and p.person is None for p in (self.publisher, *self.also))


@dataclass(frozen=True)
class OwnWorkflow:
    """A use case that n8n carries in a workflow of its own."""

    spec: RunSpec
    holder: UserId | None
    """Who has the workflow open in n8n now, if anyone."""
    on: bool = True
    """Turned on, and neither paused nor a draft, so its schedule may start runs. Our records
    decide this, whatever n8n has live."""


@dataclass(frozen=True)
class NothingToRun:
    """A workflow of ours with nothing to run now, such as an empty watchlist. Its slot ends
    quietly: no run is made, and nothing fails in n8n."""

    why: str


@dataclass(frozen=True)
class AgentToRun:
    card_run: CardRun
    release_of: str | None = None
    """A repository whose newest release each change the agent proposes is about. Our API reads
    that release itself and names it as the change's subject, so the same change is never made
    twice across runs (ENGINE-PLAN 2.3.8)."""


@dataclass(frozen=True)
class CannotRun:
    """The agent is known, but the block left out something it needs, such as where its write
    lands. Nothing is filled in for it."""

    detail: str


class WorkflowFacts(Protocol):
    """What node calls need from the use case builder, which orchestration may not import."""

    async def workflow(self, n8n_workflow_id: str) -> OwnWorkflow | NothingToRun | None: ...

    async def version(self, n8n_workflow_id: str, version_id: str) -> RanVersion | None: ...

    async def agents(self) -> Sequence[NodeOption]: ...

    async def agent_inputs(self, agent_id: str) -> Sequence[CardInput]: ...

    async def deleted(self, n8n_workflow_id: str) -> bool:
        """The workflow carries a use case that was deleted."""
        ...

    async def watchlist(self, n8n_workflow_id: str) -> bool:
        """The workflow is the Software watchlist's own."""
        ...

    async def agent_run(
        self, agent_id: str, values: Mapping[str, str], pinned: CardSpec | None = None
    ) -> AgentToRun | CannotRun | None:
        """`pinned` is the card as the use case's version pinned it, which runs in place of the
        card's newest version (ENGINE-PLAN 2.3)."""
        ...


@dataclass(frozen=True)
class ReadFailed:
    """A read with no usable answer this time, as from a source that is down. n8n tries again."""

    detail: str


@dataclass(frozen=True)
class NotFoundAtSource:
    """The source has no such place, as a repository GitHub doesn't have. Trying again finds
    none, so the Read block is refused in words that name the source and the place (ADR 0056)."""

    source: str
    place: str


type ReadItems = Sequence[Mapping[str, Json]]
type SourceRead = ReadItems | ReadFailed | NotFoundAtSource


class SourceReads(Protocol):
    """Where a Read block reads. A source lists only the places the Portal allows."""

    async def places(self, source: str) -> Sequence[NodeOption]: ...

    async def read(self, source: str, place: str, query: str | None) -> SourceRead: ...


class ReadSources:
    """The Read block's sources: each named one answered by its own reader, any other by the
    rest, so the editor's options and the check at run time ask the same reader."""

    def __init__(self, own: Mapping[str, SourceReads], rest: SourceReads) -> None:
        self._own = dict(own)
        self._rest = rest

    async def places(self, source: str) -> Sequence[NodeOption]:
        return await self._own.get(source, self._rest).places(source)

    async def read(self, source: str, place: str, query: str | None) -> SourceRead:
        return await self._own.get(source, self._rest).read(source, place, query)


@dataclass(frozen=True)
class WriteEntry:
    """A write a Propose a change block may name: the registry's connector and operation, and
    the places the Portal allows for it."""

    id: str
    name: str
    connector: str
    operation: str
    target_key: str
    places: tuple[NodeOption, ...] = ()


NODE_WRITES = (
    WriteEntry("jira.create_ticket", "Create a Jira ticket", "jira", "create_ticket", "project"),
)
"""The writes a Propose a change block may name, before the places the Portal allows: the
registry's one ready write. n8n's editor lists them (`getWriteActions`), and so does the block
catalogue the workflow drafter reads (`platform_api.n8n_catalogue`)."""


@dataclass(frozen=True)
class ReadCall:
    source: str
    place: str
    query: str | None


@dataclass(frozen=True)
class AgentCall:
    agent: str
    inputs: Mapping[str, str]


@dataclass(frozen=True)
class ProposeCall:
    action: str
    place: str
    title: str
    body: str
    subject: str | None


@dataclass(frozen=True)
class AskCall:
    resume_url: str
    """$execution.resumeUrl, which n8n signs. It is kept sealed and never shown."""


@dataclass(frozen=True)
class WriteCall:
    """Make the approved changes. It names nothing: the gateway makes the run's own approved
    proposal, from our records alone."""


@dataclass(frozen=True)
class TellCall:
    """A choice of the fixed recipients and of when to tell. It carries no address and no text:
    our API composes the notice from what the run read (the Tell rule)."""

    where: TellWhere
    what: TellWhat


type Work = ReadCall | AgentCall | ProposeCall | AskCall | WriteCall | TellCall

KIND_OF: Mapping[type[Work], NodeKind] = {
    ReadCall: "read",
    AgentCall: "agent",
    ProposeCall: "propose",
    AskCall: "ask",
    WriteCall: "write",
    TellCall: "tell",
}


@dataclass(frozen=True)
class NodeCall:
    execution_id: N8nExecutionId
    node_name: str
    work: Work

    @property
    def kind(self) -> NodeKind:
        return KIND_OF[type(self.work)]

    @property
    def content_hash(self) -> str:
        """What the block asked, so a repeat that asks something else is not taken for it."""
        content = json.dumps(
            {"kind": self.kind, **asdict(self.work)}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass(frozen=True)
class Answer:
    items: tuple[Mapping[str, Json], ...]
    replayed: bool = False
    cut_off: bool = False


@dataclass(frozen=True)
class Waiting:
    """Ask for a yes waits in n8n for this request of ours."""

    request_id: ApprovalId


@dataclass(frozen=True)
class NothingToChange:
    pass


type AskAnswer = Waiting | NothingToChange

type ChangeStatus = Literal["made", "already_made", "not_made"]


@dataclass(frozen=True)
class ChangeResult:
    """One change of the proposal, as Make the approved changes passes it on."""

    change: str
    status: ChangeStatus
    reference: str | None = None
    url: str | None = None
    made_in: RunId | None = None
    """The run that made it first, when that was another run."""
    detail: str | None = None


@dataclass(frozen=True)
class WriteAnswer:
    """`made < of` fails the block with "2 of 3 made", so the error workflow reports the run."""

    made: int
    of: int
    results: tuple[ChangeResult, ...]


@dataclass(frozen=True)
class Refused:
    """A call our API will not do. n8n repeats a refused call with retryOnFail, so a repeat
    from the same execution and block gets this same answer and nothing else happens."""

    status: int
    detail: str


@dataclass(frozen=True)
class TryLater:
    detail: str


type CallResult = Answer | AskAnswer | WriteAnswer | Told | Refused | TryLater


def read_answer(read: SourceRead) -> Answer | Refused | TryLater:
    """What a Read block gets for its source's answer, in a real run and in a simulation alike,
    so the two can't disagree: the items up to READ_LIMIT, a try again, or a refusal in words
    that its stop names the source and the place with (`block_sources.source_stop`)."""
    match read:
        case ReadFailed(detail):
            return TryLater(detail)
        case NotFoundAtSource(source, place):
            return Refused(404, not_found_words(source, place))
        case _:
            return Answer(tuple(read[:READ_LIMIT]), cut_off=len(read) > READ_LIMIT)


NOT_OURS = Refused(403, "This workflow is not one our platform runs.")
SELF_TEST_FAILS = Refused(
    409,
    "The daily self-test fails here on purpose, to prove that n8n's error workflow reports to "
    "the platform. Nothing is wrong.",
)
NOBODY_HOLDS = Refused(403, "Nobody holds this workflow, so nobody may run it by hand.")
VERSION_FAILED = Refused(403, "This version failed the check.")
UNKNOWN_PUBLISHER = Refused(403, "Published by someone we don't know.")
WRITES_REFUSED = Refused(
    403,
    "Writes refused: this version can make a change without approval. Add the approval step back, "
    "or undo the change, in the Portal.",
)
"""A version the safety checker graded anything but safe never asks for a yes and never writes
(ENGINE-PLAN 2.3.11): its ask and its writes are refused, and the run stops."""
DELETED_BEFORE = Refused(403, "This workflow was deleted. Nothing was written.")
"""A run of a deleted workflow never asks and never writes, whatever n8n still does (D7)."""
NOT_ON = Refused(409, "This workflow is not on, so its schedule does not run it.")
START_UNKNOWN = Refused(403, "This start is not one our platform made.")
START_USED = Refused(403, "This start was already used.")
START_OTHER_WORKFLOW = Refused(403, "This start was made for another workflow.")
START_EXPIRED = Refused(403, "This start has expired.")
START_TOO_LATE = Refused(409, "The run this start was made for is no longer waiting to start.")
UNKNOWN_START = Refused(403, "This execution did not start from a trigger our platform knows.")
NO_EXECUTION = TryLater("n8n has no record of this execution yet.")
ANOTHER_EXECUTION = Refused(409, "Another execution of this run is live.")
CHANGED_CALL = Refused(409, "This block already called with other content in this execution.")
BUSY = TryLater("Our platform is still answering this block.")
TEST_RUN_STOPS = Refused(409, TEST_PASSED)
"""A test run ends at Ask for a yes, with no exit taken (ENGINE-PLAN 2.3.3)."""
NO_YES = Refused(403, "No approval for this run.")
TEST_RUN_WRITES_NOTHING = Refused(403, "A test run never writes.")
DENIED: Mapping[DenyReason, str] = {
    DenyReason.RUN_MISMATCH: "This run's records do not match its request.",
    DenyReason.NOT_APPROVED: NO_YES.detail,
    DenyReason.INVALID_DECISIONS: "The decisions on this run's request break the approval rules.",
    DenyReason.DIGEST_MISMATCH: "These are not the changes the Approvers approved.",
    DenyReason.UNREGISTERED_ACTION: "A change is not one our platform can make.",
    DenyReason.TARGET_CHANGED: JIRA_SITE_CHANGED,
    DenyReason.EXPIRED: "The request expired before it was approved.",
    DenyReason.TEST_RUN: TEST_RUN_WRITES_NOTHING.detail,
}
"""What the safety checker's refusal says on the block, and in the run's failure."""
NOT_OUR_ERROR_WORKFLOW = Refused(403, "Only our error workflow may report a failure.")
NOT_FAILED = Refused(409, "n8n does not say this execution failed.")
NOTHING_READ = Refused(403, "A Tell reports only what this run read, and it has read nothing yet.")
NOT_A_WATCHLIST_RUN = Refused(409, "Only the Software watchlist reads and checks the watchlist.")
NO_TELL_FLOW = Refused(409, "This platform has no Tell flow, so it sends no notice.")
CANNOT_SEAL = (
    "This platform cannot keep n8n's resume address safe, because SETTINGS_ENCRYPTION_KEY is not "
    "set."
)


def run_stopped(why: str) -> Refused:
    return Refused(409, f"This run has stopped: {why}")


def unknown(what: str, value: str) -> Refused:
    return Refused(422, f'Our platform does not know the {what} "{value}".')


@dataclass(frozen=True)
class IssuedStart:
    nonce: str
    run_id: RunId
    kind: StartKind
    workflow_id: str
    expires_at: datetime
    used_by: N8nExecutionId | None


def start_signature(
    secret: str, workflow_id: str, webhook_id: str, nonce: str, kind: StartKind, expires: int
) -> str:
    """The X-Wab-Signature the Start from the Portal block checks: HMAC-SHA256 with
    WAB_START_SECRET over its own workflow id and webhook id, the nonce, the kind and the expiry
    in Unix seconds, one per line."""
    message = "\n".join((workflow_id, webhook_id, nonce, kind, str(expires)))
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def check_start(
    start: IssuedStart | None, workflow_id: str, now: datetime
) -> IssuedStart | Refused:
    """A start item is only as good as our own record of it. The block's check is a first
    filter that n8n forgets on a restart, and a test run's item never passes the block."""
    if start is None:
        return START_UNKNOWN
    if start.used_by is not None:
        return START_USED
    if start.workflow_id != workflow_id:
        return START_OTHER_WORKFLOW
    if now > start.expires_at:
        return START_EXPIRED
    return start


def version_problem(version: RanVersion | None) -> Refused | None:
    """A version the sweep has not graded yet counts as failed. A version published by someone we
    can't match stops every run of it, however it started (D5). Writes refused is not a stop:
    the run reads, and its ask and its writes are refused (ENGINE-PLAN 2.3.11)."""
    if version is None or version.grade == "needs_a_fix":
        return VERSION_FAILED
    if version.unknown:
        return UNKNOWN_PUBLISHER
    return None


def refuses_writes(version: RanVersion | None) -> bool:
    """Only a version graded safe may ask for a yes and write."""
    return version is None or version.grade != "safe"


@dataclass(frozen=True)
class NewRun:
    started_by: UserId
    trigger: Trigger
    joined: tuple[UserId, ...] = ()
    """Whose work it also is: the version's publishers."""


@dataclass(frozen=True)
class ByStart:
    start: IssuedStart
    holder: UserId | None
    """The holder joins as a party when the start came through a run by hand in n8n."""
    joined: tuple[UserId, ...] = ()
    """The version's publishers, whose work every run of it is (ADR 0026)."""


@dataclass(frozen=True)
class ByRetry:
    run_id: RunId
    holder: UserId | None


@dataclass(frozen=True)
class StopStart:
    """A start our API issued, for a version that may not run: its pending run stops."""

    start: IssuedStart
    why: Refused


type Link = NewRun | ByStart | ByRetry | StopStart | Refused


def decide_link(
    facts: ExecutionFacts,
    retried_run: RunId | None,
    start: IssuedStart | None,
    holder: UserId | None,
    version: RanVersion | None,
    now: datetime,
    on: bool = True,
) -> Link:
    """Which run an execution belongs to, in 2.3's order. A retry copies its original's start
    item, so its used nonce is expected there. A start item that does not check out is refused,
    never taken as a trigger's run. Run now and our Start from the Portal arrive as webhook, so
    a webhook with no start item is refused: only the Schedule Trigger, trigger, makes a run
    credited to the publisher."""
    problem = version_problem(version)
    joined = () if version is None else version.parties
    if facts.retry_of is not None and retried_run is not None:
        return problem or ByRetry(retried_run, holder)
    if facts.start_nonce is not None:
        match check_start(start, facts.workflow_id, now):
            case Refused() as refused:
                return refused
            case IssuedStart() as checked:
                if problem is not None:
                    return StopStart(checked, problem)
                return ByStart(checked, holder if facts.mode == "manual" else None, joined)
    if facts.mode == "manual":
        if holder is None:
            return NOBODY_HOLDS
        return problem or NewRun(holder, "person", _besides(holder, joined))
    if facts.mode == "trigger":
        if not on:
            return NOT_ON
        if problem is not None:
            return problem
        assert version is not None
        publisher = version.publisher
        if publisher is None or publisher.person is None:
            return UNKNOWN_PUBLISHER
        return NewRun(publisher.person, "schedule", _besides(publisher.person, joined))
    return UNKNOWN_START


def _besides(person: UserId, joined: tuple[UserId, ...]) -> tuple[UserId, ...]:
    return tuple(other for other in joined if other != person)


def rejoin(
    state: RunState, execution: N8nExecutionId, mode: str, now: datetime
) -> Moved[Working] | Moved[Acting] | Refused:
    """A retry of one of the run's executions carries the run on. A stop that cannot be retried
    stays stopped, so a retry never skips the check that stopped it. A retry after a part-done
    write carries the same approved proposal, and makes only what is still to make."""
    match state:
        case Pending() as pending:
            return pending.link(execution, mode, now)
        case Working(attempt=attempt):
            working = working_on(state.run_id, execution, attempt + 1, now)
            return Moved(working, (execution_linked(execution, mode),))
        case Failed(failure=failure, resume=ResumeWork(attempt)) if failure.retryable:
            working = working_on(state.run_id, execution, attempt, now)
            return Moved(working, (execution_linked(execution, mode),))
        case Failed(failure=failure, resume=ResumeAct() as act) if failure.retryable:
            acting = Acting(
                state.run_id,
                act.proposal_id,
                act.approval_id,
                act.attempt,
                execution,
                deadline(Acting, now),
                act.unread,
            )
            return Moved(acting, (execution_linked(execution, mode),))
        case Failed(failure=failure):
            return run_stopped(f"{sentence(failure.message)} It cannot be retried.")
        case _:
            return Refused(409, f"This run cannot take a retry while it is {state_name(state)}.")


MESSAGE_LIMIT = 500


@dataclass(frozen=True)
class FailedExecution:
    """An execution that ended in an error, as Report a failure sends it or the sweep reads it
    from n8n (ENGINE-PLAN 2.8)."""

    execution_id: N8nExecutionId
    facts: ExecutionFacts
    """What it ran, from the same record: n8n no longer reads a failed execution as running."""
    node: str | None
    message: str | None
    block: Mapping[str, Any] | None = None
    """The failed block as the execution ran it, when n8n's record holds it."""


@dataclass(frozen=True)
class Finished:
    """n8n ran the execution to its end."""

    execution_id: N8nExecutionId


type Ended = Finished | FailedExecution


@dataclass(frozen=True)
class PlatformWorkflow:
    """One of the platform's own n8n workflows, as the last bootstrap that was ready recorded
    it."""

    id: str
    project: str | None
    """The project n8n held it in then. None for a record made before projects were kept."""


class N8nSwitch(Protocol):
    """Takes a workflow off in n8n, so none of its triggers runs it."""

    async def go_off(self, workflow_id: str) -> None: ...


class N8nFailures(Protocol):
    """n8n's record of how executions ended. A report is checked against it, and the sweep reads
    it for any end no call or report brought: a failure in a workflow held in a member's project
    or in a run by hand, which reaches no error workflow (P7 Q13 and Q22), and a run that ended
    without asking for a yes."""

    async def platform_workflows(self) -> Mapping[str, PlatformWorkflow]:
        """The platform's own workflows by name, from our records only: the error workflow, the
        only one whose executions may report, and the daily self-test."""
        ...

    async def in_place(self, workflow: PlatformWorkflow) -> bool | TryLater:
        """Whether n8n still holds it in the project bootstrap recorded, so a workflow a member
        made or was handed is never it. TryLater while n8n cannot be read."""
        ...

    async def ended(self, execution_id: N8nExecutionId) -> Ended | None:
        """How the execution ended, from n8n's own record. None while it runs or waits, or when
        n8n cannot be read."""
        ...

    async def failure(self, execution_id: N8nExecutionId) -> FailedExecution | TryLater | None:
        """The node that failed and its error text, from the execution's data. None unless n8n
        has the execution and it ended in an error. TryLater while n8n cannot be read, so the
        block sends the report again: no sweep finds a failure no block linked."""
        ...


def failure_words(failed: FailedExecution, read_anything: bool) -> str:
    """A source that gave no usable answer is named with the block and the likely cause (ADR
    0056). Any other failure is the block and n8n's own words."""
    stop = source_stop(failed.node, failed.block, failed.message)
    if stop is not None:
        words = stop_words(stop)
    else:
        node = f'"{failed.node}"' if failed.node else "A block"
        said = one_line(failed.message or "n8n gave no reason", MESSAGE_LIMIT)
        words = f"{node} failed in n8n: {sentence(said)}"
    return words if read_anything else f"{NOTHING_READ_YET} {words}"


def block_failure(failed: FailedExecution, read_anything: bool) -> Failure:
    """How a failed block fails its run. A place its source doesn't have stops a retry the same
    way, so that run can't be retried, and every screen reads it from this one fact."""
    stop = source_stop(failed.node, failed.block, failed.message)
    retryable = stop is None or stop.delay != "not_found"
    words = failure_words(failed, read_anything)
    return Failure(FailureReason.WORKFLOW_NODE_ERROR, words, retryable=retryable)


def fail_by_report(
    state: RunState, execution: N8nExecutionId, failure: Failure, writing: bool
) -> Moved[Failed] | None:
    """A failed execution fails the run only while it carries the run. A run that has ended
    stays as it ended, so a test run that passed up to the yes is not failed by its stop at the
    gate. A run that moved on, to another execution or to an attempt nobody carries yet, is not
    failed by an earlier attempt's execution. An execution linked in the same call carries the
    run, so a run that stopped before reading is still failed. While the run's changes are being
    made, the write's own outcome decides, so the run never reads failed and retryable then."""
    match state:
        case Acting() if writing:
            return None
        case Pending() | Working() | Proposed() | Acting() if holder_of(state) == execution:
            return state.fail(failure)
        case _:
            return None


WRITE_TARGETS: Mapping[InputKind, str] = {
    rule.target_input: rule.connector
    for rule in TOOL_RULES
    if rule.kind == "write" and rule.target_input is not None and rule.connector is not None
}
"""An agent input of one of these kinds names where a write lands, such as a jira_project for
Jira, so its value must be a place the Portal allows for that connector."""


class NodeCatalog:
    """The one list of what a block may name: the editor's options, and the check at run time
    that refuses anything else (ENGINE-PLAN 2.2)."""

    def __init__(
        self, facts: WorkflowFacts, sources: SourceReads, writes: Sequence[WriteEntry]
    ) -> None:
        self._facts = facts
        self._sources = sources
        self._writes = {entry.id: entry for entry in writes}

    async def options(self, kind: OptionKind, of: Mapping[str, str]) -> list[NodeOption]:
        match kind:
            case "places":
                if "action" in of:
                    entry = self._writes.get(of["action"])
                    return [] if entry is None else list(entry.places)
                source = of.get("source", "")
                listed = list(await self._sources.places(source))
                if source == GITHUB_RELEASES and await self._in_watchlist(of):
                    return [WATCHLIST_PLACE, *listed]
                return listed
            case "agents":
                listed = list(await self._facts.agents())
                return [WATCHLIST_CHECKER, *listed] if await self._in_watchlist(of) else listed
            case "agent_inputs":
                inputs = await self._facts.agent_inputs(of.get("agent", ""))
                return [NodeOption(item.name, item.name) for item in inputs]
            case "write_actions":
                return [NodeOption(entry.id, entry.name) for entry in self._writes.values()]

    async def _in_watchlist(self, of: Mapping[str, str]) -> bool:
        """The editor offers the watchlist's own blocks only in the watchlist's own workflow. A
        block anywhere else would be refused at run time."""
        workflow = of.get("workflow")
        return workflow is not None and await self._facts.watchlist(workflow)

    async def unknown_in(self, work: Work) -> Refused | None:
        """The watchlist's place and checker are the platform's own and always known here. A run
        of any other workflow refuses them when the block asks (NOT_A_WATCHLIST_RUN)."""
        match work:
            case ReadCall(source, place) if (
                source == GITHUB_RELEASES and place == WATCHLIST_PLACE.id
            ):
                pass
            case ReadCall(source, place):
                if not await self._listed(self._sources.places(source), place):
                    return unknown("place", place)
            case AgentCall(agent, inputs) if agent == WATCHLIST_CHECKER.id:
                if inputs:
                    return unknown("input", next(iter(inputs)))
            case AgentCall(agent, inputs):
                if not await self._listed(self._facts.agents(), agent):
                    return unknown("agent", agent)
                inputs_of = await self._facts.agent_inputs(agent)
                kinds: dict[str, InputKind] = {item.name: item.kind for item in inputs_of}
                for name, value in inputs.items():
                    if name not in kinds:
                        return unknown("input", name)
                    connector = WRITE_TARGETS.get(kinds[name])
                    if connector is not None and value not in self._places_for(connector):
                        return unknown("place", value)
            case ProposeCall(action, place):
                entry = self._writes.get(action)
                if entry is None:
                    return unknown("change", action)
                if place not in {option.id for option in entry.places}:
                    return unknown("place", place)
            case AskCall() | WriteCall() | TellCall():
                pass
        return None

    def _places_for(self, connector: str) -> set[str]:
        return {
            place.id
            for entry in self._writes.values()
            if entry.connector == connector
            for place in entry.places
        }

    def write(self, action: str) -> WriteEntry:
        return self._writes[action]

    @staticmethod
    async def _listed(listing: Awaitable[Sequence[NodeOption]], wanted: str) -> bool:
        return wanted in {option.id for option in await listing}


@dataclass(frozen=True)
class TheRequest:
    """Our records of the run's request, which the write reads and never n8n's."""

    request: ApprovalRequest
    decisions: tuple[Decision, ...]
    waiting: N8nExecutionId | None
    """The execution n8n holds the wait in, when n8n holds it."""

    def woke(self, execution: N8nExecutionId) -> bool:
        """This is the execution our records would wake with a yes."""
        approved = isinstance(approval_status(self.request, self.decisions), Approved)
        return approved and self.waiting == execution


@dataclass(frozen=True)
class Carry:
    """The run may make its approved changes now, from this execution."""

    acting: Acting
    took_yes: Moved[Acting] | None
    """How the run takes the yes here, when our record of n8n taking it is missing."""


@dataclass(frozen=True)
class StopRun:
    """A write with no yes in a run that never asked: the run stops (ENGINE-PLAN 2.3.11)."""

    refused: Refused
    moved: Moved[Failed]


@dataclass(frozen=True)
class Answered:
    answer: WriteAnswer


type WriteAdmission = Carry | StopRun | Answered | Refused


def admit_write(
    state: RunState, execution: N8nExecutionId, held: TheRequest | None, now: datetime
) -> WriteAdmission:
    """What a call to make the approved changes may do in this state of its run.

    Only the run's own execution writes: the one the run acts in, or the one our records wait to
    wake with a yes. The second is how a lost wake heals. n8n took the yes, but our record of it
    was lost, or the wake met a 409 and marked the run lost. It holds for a lost run only until
    its request would have expired, because after that a person may already have redone the
    work. Every write still passes check() against the same records.
    """
    match state:
        case Acting(claimant=claimant) as acting if claimant == execution:
            return Carry(acting, None)
        case Acting():
            return ANOTHER_EXECUTION
        case AwaitingApproval() as waiting if held is not None and held.woke(execution):
            took = waiting.woken(execution, now)
            return Carry(took.state, took)
        case Lost() as lost if (
            held is not None
            and held.woke(execution)
            and (held.request.expires_at is None or now <= held.request.expires_at)
        ):
            took = lost.taken(execution, now)
            return Carry(took.state, took)
        case Working() as working:
            failure = Failure(FailureReason.SAFETY_DENIED, NO_YES.detail, retryable=False)
            return StopRun(NO_YES, working.fail(failure))
        case Succeeded(outcome=Outcome.TEST_PASSED):
            return TEST_RUN_WRITES_NOTHING
        case Succeeded(written=written):
            results = tuple(
                ChangeResult(f"{w.operation} on {w.connector}", "made", w.external_reference, w.url)
                for w in written
            )
            return Answered(WriteAnswer(len(results), len(results), results))
        case Failed(failure=failure):
            return run_stopped(failure.message)
        case Rejected():
            return Refused(403, "An Approver said no. Nothing was written.")
        case Expired():
            return Refused(403, NO_ANSWER)
        case Lost():
            return run_stopped("n8n lost it after the approval, and nothing was written.")
        case AwaitingApproval() | Pending() | Proposed() | Skipped():
            return NO_YES


def _change(result: ActionResult) -> ChangeResult:
    match result:
        case Made(action, done):
            return ChangeResult(describe(action).line, "made", done.external_reference, done.url)
        case MadeBefore(action, reference, url, run_id):
            detail = f"Already made in run {run_id}."
            return ChangeResult(
                describe(action).line, "already_made", reference, url, run_id, detail
            )
        case NotMade(action, why):
            return ChangeResult(describe(action).line, "not_made", detail=why)


def write_answer(carried: Carried) -> WriteAnswer:
    return WriteAnswer(
        carried.made, len(carried.results), tuple(_change(r) for r in carried.results)
    )


def after_write(acting: Acting, carried: Carried) -> Moved[Succeeded] | Moved[Failed]:
    """The run once the gateway is done. A part-done write fails the run, retryable when the
    failure was, and says how many were made. What this try made is logged either way."""
    if carried.failure is None:
        return acting.made(carried.written, carried.fresh)
    of = len(carried.results)
    message = f"{carried.made} of {of} made. {sentence(carried.failure.message)}"
    failed = acting.fail(replace(carried.failure, message=message))
    return failed.preceded_by(*(write_done(w) for w in carried.fresh))
