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
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from platform_api.orchestration.agents import CardInput, InputKind
from platform_api.orchestration.cards import TOOL_RULES
from platform_api.orchestration.runs import (
    TEST_PASSED,
    Failed,
    Moved,
    Pending,
    ResumeWork,
    RunState,
    Working,
    execution_linked,
    sentence,
    state_name,
    working_on,
)
from platform_api.orchestration.spec import CardRun, RunSpec
from platform_api.orchestration.write_actions import Json
from platform_api.shared import ApprovalId, N8nExecutionId, RunId, UserId
from platform_api.wire import Trigger

type NodeKind = Literal["read", "agent", "propose", "ask"]
type StartKind = Literal["run_now", "test", "retry"]
type OptionKind = Literal["places", "agents", "agent_inputs", "write_actions"]
type Grade = Literal["safe", "writes_refused", "needs_a_fix"]

START_LIFETIME = timedelta(seconds=240)
"""The node allows 60 s of clock skew and at most 300 s, so a start our API signs lives 240 s."""
READ_LIMIT = 100
"""The most items one Read passes on (ADR 0027, long lists). It says when it stopped there."""


@dataclass(frozen=True)
class NodeOption:
    id: str
    name: str


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


@dataclass(frozen=True)
class OwnWorkflow:
    """A use case that n8n carries in a workflow of its own."""

    spec: RunSpec
    holder: UserId | None
    """Who has the workflow open in n8n now, if anyone."""


class WorkflowFacts(Protocol):
    """What node calls need from the use case builder, which orchestration may not import."""

    async def workflow(self, n8n_workflow_id: str) -> OwnWorkflow | None: ...

    async def version(self, n8n_workflow_id: str, version_id: str) -> RanVersion | None: ...

    async def agents(self) -> Sequence[NodeOption]: ...

    async def agent_inputs(self, agent_id: str) -> Sequence[CardInput]: ...

    async def agent_run(self, agent_id: str, values: Mapping[str, str]) -> CardRun | None: ...


@dataclass(frozen=True)
class ReadFailed:
    detail: str


type ReadItems = Sequence[Mapping[str, Json]]


class SourceReads(Protocol):
    """Where a Read block reads. A source lists only the places the Portal allows."""

    async def places(self, source: str) -> Sequence[NodeOption]: ...

    async def read(self, source: str, place: str, query: str | None) -> ReadItems | ReadFailed: ...


@dataclass(frozen=True)
class WriteEntry:
    """A write a Propose a change block may name: the registry's connector and operation, and
    the places the Portal allows for it."""

    id: str
    name: str
    connector: str
    operation: str
    target_key: str
    places: tuple[NodeOption, ...]


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


type Work = ReadCall | AgentCall | ProposeCall | AskCall

KIND_OF: Mapping[type[Work], NodeKind] = {
    ReadCall: "read",
    AgentCall: "agent",
    ProposeCall: "propose",
    AskCall: "ask",
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


@dataclass(frozen=True)
class Refused:
    """A call our API will not do. n8n repeats a refused call with retryOnFail, so a repeat
    from the same execution and block gets this same answer and nothing else happens."""

    status: int
    detail: str


@dataclass(frozen=True)
class TryLater:
    detail: str


type CallResult = Answer | AskAnswer | Refused | TryLater

NOT_OURS = Refused(403, "This workflow is not one our platform runs.")
NOBODY_HOLDS = Refused(403, "Nobody holds this workflow, so nobody may run it by hand.")
VERSION_FAILED = Refused(403, "This version failed the check.")
UNKNOWN_PUBLISHER = Refused(403, "Published by someone we don't know.")
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
    """A version the sweep has not graded yet counts as failed. Writes refused is not a stop:
    the run reads, and the gateway refuses the write for want of a yes (ENGINE-PLAN 2.3.11)."""
    if version is None or version.grade == "needs_a_fix":
        return VERSION_FAILED
    return None


@dataclass(frozen=True)
class NewRun:
    started_by: UserId
    trigger: Trigger


@dataclass(frozen=True)
class ByStart:
    start: IssuedStart
    holder: UserId | None
    """The holder joins as a party when the start came through a run by hand in n8n."""


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
) -> Link:
    """Which run an execution belongs to, in 2.3's order. A retry copies its original's start
    item, so its used nonce is expected there. A start item that does not check out is refused,
    never taken as a trigger's run. Run now and our Start from the Portal arrive as webhook, so
    a webhook with no start item is refused: only the Schedule Trigger, trigger, makes a run
    credited to the publisher."""
    problem = version_problem(version)
    if facts.retry_of is not None and retried_run is not None:
        return problem or ByRetry(retried_run, holder)
    if facts.start_nonce is not None:
        match check_start(start, facts.workflow_id, now):
            case Refused() as refused:
                return refused
            case IssuedStart() as checked:
                if problem is not None:
                    return StopStart(checked, problem)
                return ByStart(checked, holder if facts.mode == "manual" else None)
    if facts.mode == "manual":
        if holder is None:
            return NOBODY_HOLDS
        return problem or NewRun(holder, "person")
    if facts.mode == "trigger":
        if problem is not None:
            return problem
        assert version is not None
        publisher = version.publisher
        if publisher is None or publisher.person is None:
            return UNKNOWN_PUBLISHER
        return NewRun(publisher.person, "schedule")
    return UNKNOWN_START


def rejoin(
    state: RunState, execution: N8nExecutionId, mode: str, now: datetime
) -> Moved[Working] | Refused:
    """A retry of one of the run's executions carries the run on. A stop that cannot be retried
    stays stopped, so a retry never skips the check that stopped it."""
    match state:
        case Pending() as pending:
            return pending.link(execution, mode, now)
        case Working(attempt=attempt):
            working = working_on(state.run_id, execution, attempt + 1, now)
            return Moved(working, (execution_linked(execution, mode),))
        case Failed(failure=failure, resume=ResumeWork(attempt)) if failure.retryable:
            working = working_on(state.run_id, execution, attempt, now)
            return Moved(working, (execution_linked(execution, mode),))
        case Failed(failure=failure):
            return run_stopped(f"{sentence(failure.message)} It cannot be retried.")
        case _:
            return Refused(409, f"This run cannot take a retry while it is {state_name(state)}.")


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
                return list(await self._sources.places(of.get("source", "")))
            case "agents":
                return list(await self._facts.agents())
            case "agent_inputs":
                inputs = await self._facts.agent_inputs(of.get("agent", ""))
                return [NodeOption(item.name, item.name) for item in inputs]
            case "write_actions":
                return [NodeOption(entry.id, entry.name) for entry in self._writes.values()]

    async def unknown_in(self, work: Work) -> Refused | None:
        match work:
            case ReadCall(source, place):
                if not await self._listed(self._sources.places(source), place):
                    return unknown("place", place)
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
            case AskCall():
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
