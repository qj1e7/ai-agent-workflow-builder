"""How the simulation gateway answers our blocks in the simulation n8n (ADR 0054, section 3).

There our blocks call the simulation gateway in place of platform-api, through the same router
(n8n_calls_http.py). It answers each block as platform-api does, with ADR 0054's differences:

- A simulated run is kept here, in memory, apart from runs. It is never in Recent runs or the
  activity log, and the gateway has no database.
- Read gets the scenario's answer: recorded items, mock GitHub's releases, or a source that is
  not found or does not answer in time, played at once.
- Agent gets a recorded reply. The gateway calls no model. The Version checker's answer says,
  as platform-api's does, whether it found a newer release, so the release check's Newer?
  block plays.
- Ask for a yes gets the scenario's answer, yes, no or no answer, and asks nobody. The wake goes
  only to the simulation n8n.
- Every write is refused, as the write gateway refuses a test run's write, and the changes it
  would have made are kept for the grader.
- Tell sends nothing.

A simulated run starts from a start the gateway issued for one scenario. An execution's first call
links it to that run by the nonce in its Start from the Portal item, which the gateway reads from
the simulation n8n's own record, as platform-api links a run (ENGINE-PLAN 2.3).
"""

import asyncio
import logging
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol, cast

import httpx
from pydantic import Field, JsonValue

from platform_api.orchestration.cards import BODY_LIMIT, TITLE_LIMIT
from platform_api.orchestration.dispatch import (
    DispatchFailure,
    Gone,
    HeldWait,
    WakeDecision,
    Waker,
)
from platform_api.orchestration.n8n import ExecutionRecord, N8nError
from platform_api.orchestration.n8n_call_service import FailureResult, LeftAsIs
from platform_api.orchestration.n8n_calls import (
    ANOTHER_EXECUTION,
    CHANGED_CALL,
    GITHUB_RELEASES,
    NO_EXECUTION,
    START_EXPIRED,
    START_LIFETIME,
    START_OTHER_WORKFLOW,
    AgentCall,
    Answer,
    AskCall,
    CallResult,
    NodeCall,
    NodeKind,
    NodeOption,
    NotFoundAtSource,
    NothingToChange,
    OptionKind,
    ProposeCall,
    ReadCall,
    ReadFailed,
    Refused,
    SourceRead,
    TellCall,
    TryLater,
    Waiting,
    WriteAnswer,
    WriteCall,
    read_answer,
    release_compared,
    release_of,
)
from platform_api.orchestration.tell import Told
from platform_api.orchestration.write_actions import Json
from platform_api.shared import ApprovalId, N8nExecutionId, new_id
from platform_api.wire import WireIn, WireModel

log = logging.getLogger(__name__)

NEVER_WRITES = Refused(403, "A simulation never writes.")
"""As the write gateway refuses a test run's write (DENIED[DenyReason.TEST_RUN])."""
SENDS_NOTHING = "A simulation sends nothing."
FAILS_NO_RUN = "A simulation fails no run."
NOT_A_SIMULATION = Refused(
    403, "This execution did not start from a start the simulation gateway made."
)
START_UNKNOWN_HERE = Refused(403, "This start is not one the simulation gateway made.")
FORGOTTEN = Refused(409, "The simulation gateway no longer keeps this simulated run.")
TOO_MANY_CALLS = Refused(409, "This simulated run made too many calls, so the gateway stopped it.")
TOO_MUCH = Refused(409, "This simulated run sent too much, so the gateway stopped it.")
N8N_SILENT = TryLater("The simulation n8n did not answer.")
SOURCE_NOT_FOUND = "The place was not found at the source."
"""What a Read of a source the real platform answers with a try again gets for a place not
found, as a Confluence page. Where the real read refuses, as GitHub's, the simulation refuses as
it does (`_not_found`)."""
SOURCE_TIMED_OUT = "The source did not answer in time."
AGENT_TIMED_OUT = "The agent did not answer in time."

RUN_LIMIT = 200
"""The most simulated runs the gateway keeps. A new start forgets the oldest."""
CALL_LIMIT = 1000
"""The most calls one simulated run may make, so a workflow that loops is stopped."""
BYTE_LIMIT = 256 * 1024
"""The most a simulated run's record may hold, as JSON, so a few large calls are stopped too. The
call that crosses it is kept whole."""
HELD_LIMIT = 32 * 1024 * 1024
"""The most every kept run may hold together, as JSON: each one's scenario and record. A new start
or call past it forgets the oldest runs first, as past RUN_LIMIT, but never the run it is for. So
the gateway holds about this much however large the scenarios are, plus the answers it keeps for
repeats, which are made from the scenarios."""
RECORDED_LIMIT = 500
"""The most items a scenario may give one block. A Read passes on READ_LIMIT of them."""
WAKE_DELAY = 1.0
"""Seconds before the wake, so Ask for a yes is waiting in n8n when it arrives."""
WAKE_GAP = 0.5
WAKE_TRIES = 20

type Serve = Literal["recorded", "mock", "not_found", "timeout"]
type Outcome = Literal[
    "answered",
    "waiting",
    "nothing_to_change",
    "would_have_sent",
    "refused",
    "try_again",
    "left_as_is",
]
type Woke = Literal["delivered", "gone", "failed"]

Name = Annotated[str, Field(min_length=1, max_length=200)]


class Change(WireIn):
    """A change a recorded Agent reply proposes, as a Propose a change block names one."""

    action: Name
    place: Name
    title: str = Field(min_length=1, max_length=TITLE_LIMIT)
    body: str = Field(max_length=BODY_LIMIT)
    subject: str | None = Field(default=None, max_length=200)


class BlockAnswer(WireIn):
    """What one block gets in a scenario. A Read takes recorded items, mock GitHub's releases, a
    source that is not found, or one that does not answer in time. An Agent takes a recorded
    reply, with the changes it proposes, or does not answer in time."""

    serve: Serve
    items: list[dict[str, JsonValue]] = Field(
        default_factory=list[dict[str, JsonValue]], max_length=RECORDED_LIMIT
    )
    proposes: list[Change] = Field(default_factory=list[Change], max_length=20)
    gone: list[Name] = Field(
        default_factory=list[str],
        max_length=10,
        description="For a Read, places that answer not found, as a renamed source does.",
    )


class Scenario(WireIn):
    """One situation a workflow should handle, as data (ADR 0054, section 5). PR 5 adds the
    kinds, the templates and the grader. Here it is what the gateway answers."""

    name: str = Field(min_length=1, max_length=80, description="Which scenario, for the grader.")
    blocks: dict[Name, BlockAnswer] = Field(
        default_factory=dict[str, BlockAnswer],
        max_length=100,
        description="By block name, what each Read and Agent block gets.",
    )
    approver: WakeDecision = Field(
        default="yes", description="What Ask for approval gets: yes, no or no answer."
    )


class ProposedChange(WireModel):
    block: str = Field(description="The block that proposed it.")
    action: str
    place: str
    title: str
    body: str
    subject: str | None = None


class CallRecord(WireModel):
    """One call a block made, and what it got."""

    at: datetime
    execution_id: str
    block: str
    kind: NodeKind | Literal["failure"]
    asked: dict[str, JsonValue] = Field(
        description="What the block sent, less n8n's resume address, which carries a signature."
    )
    outcome: Outcome
    status: int = Field(description="The HTTP status the block got.")
    detail: str | None = Field(default=None, description="The words of a refusal or a try again.")
    items: int | None = Field(default=None, description="The items it passed on.")
    replayed: bool = Field(
        default=False, description="A repeat of the block's first call, which got the same answer."
    )


class SimulatedRun(WireModel):
    """What the grader reads for one scenario (ADR 0054, PR 5): the calls in order, what was
    proposed, what Ask for approval got, and how much Make the approved changes would have made."""

    nonce: str
    workflow_id: str
    scenario: str
    issued_at: datetime
    execution_id: str | None = None
    mode: str | None = Field(default=None, description="n8n's mode: manual for a run by hand.")
    calls: list[CallRecord] = Field(default_factory=list[CallRecord])
    proposed: list[ProposedChange] = Field(default_factory=list[ProposedChange])
    approver: WakeDecision | None = Field(
        default=None, description="What Ask for approval got, once it asked with a change proposed."
    )
    woke: Woke | None = Field(default=None, description="Whether the wake reached n8n.")
    would_have_written: int | None = Field(
        default=None,
        description="How many of the changes proposed, from the first, Make the approved changes "
        "would have made when it was refused. None when no write was asked. A count, so the "
        "record holds each change once.",
    )


class ExecutionReads(Protocol):
    """The simulation n8n's records, as N8nApi reads them."""

    async def execution(self, execution_id: str, data: bool = True) -> ExecutionRecord | None: ...


def _not_found(source: str, place: str) -> CallResult:
    """A place not found, played as the real read answers it: for GitHub's releases, the answer
    `read_answer` gives our API's read of a repository GitHub doesn't have."""
    if source == GITHUB_RELEASES:
        return read_answer(NotFoundAtSource("GitHub", place))
    return TryLater(SOURCE_NOT_FOUND)


class ReleaseReads(Protocol):
    async def releases(self, repo: str) -> SourceRead: ...


@dataclass(frozen=True)
class GitHubPlay:
    """What mock GitHub does for one scenario (ADR 0054, PR 5): serve these releases for every
    repository, or its own when None, or answer not found, or take each request and drop the
    connection, which plays a source that is too slow (spike S5). The repositories in `gone`
    answer not found whatever the mode, as a renamed one does (ADR 0055, PR 5)."""

    mode: Literal["ok", "not_found", "drop"]
    releases: tuple[Mapping[str, Json], ...] | None
    gone: tuple[str, ...] = ()


REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class MockGitHub:
    """GitHub's releases from mock GitHub, in the items the Read block passes on."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)

    async def releases(self, repo: str) -> SourceRead:
        if not REPO.match(repo) or ".." in repo:
            return ReadFailed(f'"{repo}" is not a GitHub repository name.')
        try:
            response = await self._client.get(
                f"{self._base_url}/repos/{repo}/releases", params={"per_page": "100"}
            )
        except httpx.HTTPError as error:
            return ReadFailed(f"Mock GitHub did not answer ({type(error).__name__}).")
        if response.status_code == 404:
            return NotFoundAtSource("GitHub", repo)
        if response.status_code != 200:
            return ReadFailed(f"Mock GitHub answered {response.status_code}.")
        found: object = response.json()
        listed = cast(list[object], found) if isinstance(found, list) else []
        items: list[Mapping[str, Json]] = []
        for entry in listed:
            release = cast(dict[str, object], entry) if isinstance(entry, dict) else {}
            tag = release.get("tag_name")
            if not isinstance(tag, str) or release.get("draft") is True:
                continue
            name = release.get("name")
            published = release.get("published_at")
            items.append(
                {
                    "kind": "release",
                    "id": tag,
                    "name": name if isinstance(name, str) and name else tag,
                    "published_at": published if isinstance(published, str) else None,
                }
            )
        return items

    async def play(self, play: GitHubPlay | None) -> None:
        """Steers mock GitHub for one scenario, or sets it back to its own answers with None. A
        simulation runs one scenario at a time, so one setting serves every repository. Setting
        the mode clears each repository's own, so a gone repository is set after it."""
        given = play or GitHubPlay("ok", None)
        served = None if given.releases is None else [dict(r) for r in given.releases]
        steps: list[tuple[str, dict[str, Json]]] = [
            ("/_admin/mode", {"mode": given.mode}),
            ("/_admin/releases", {"releases": cast(Json, served)}),
            *(("/_admin/mode", {"mode": "not_found", "repo": repo}) for repo in given.gone),
        ]
        for path, body in steps:
            answer = await self._client.post(f"{self._base_url}{path}", json=body)
            answer.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()


class Unsealed:
    """A resume address held only in memory, for the length of one wake, needs no sealing."""

    def seal(self, key: str) -> str:
        return key

    def open(self, sealed: str) -> str | None:
        return sealed


def _now() -> datetime:
    return datetime.now(UTC)


class SimulatedCalls:
    """The node calls of the simulation n8n, answered from each simulated run's scenario. It has
    the methods of platform-api's NodeCalls that the router calls."""

    def __init__(
        self,
        executions: ExecutionReads,
        waker: Waker,
        github: ReleaseReads | None,
        *,
        clock: Callable[[], datetime] = _now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        run_limit: int = RUN_LIMIT,
        call_limit: int = CALL_LIMIT,
        byte_limit: int = BYTE_LIMIT,
        held_limit: int = HELD_LIMIT,
    ) -> None:
        self._executions = executions
        self._waker = waker
        self._github = github
        self._clock = clock
        self._sleep = sleep
        self._run_limit = run_limit
        self._call_limit = call_limit
        self._byte_limit = byte_limit
        self._held_limit = held_limit
        self._sizes: dict[str, int] = {}
        """By run, the bytes its record holds."""
        self._scenario_sizes: dict[str, int] = {}
        self._held = 0
        """The bytes every kept run holds, scenarios and records."""
        self._runs: OrderedDict[str, SimulatedRun] = OrderedDict()
        self._scenarios: dict[str, Scenario] = {}
        self._links: dict[N8nExecutionId, str] = {}
        self._kept: dict[tuple[N8nExecutionId, str], tuple[str, CallResult]] = {}
        self._wakes: set[asyncio.Task[None]] = set()

    def start(self, workflow_id: str, scenario: Scenario) -> SimulatedRun:
        """A new simulated run of one workflow, with the nonce its start item must carry."""
        nonce = new_id("sim")
        run = SimulatedRun(
            nonce=nonce, workflow_id=workflow_id, scenario=scenario.name, issued_at=self._clock()
        )
        self._runs[nonce] = run
        self._scenarios[nonce] = scenario
        self._scenario_sizes[nonce] = len(scenario.model_dump_json())
        self._held += self._scenario_sizes[nonce]
        self._make_room(nonce)
        return run

    def run(self, nonce: str) -> SimulatedRun | None:
        return self._runs.get(nonce)

    def forget(self, nonce: str) -> None:
        """Drops a run nobody will read, such as one whose start n8n never ran."""
        if nonce in self._runs:
            self._forget(nonce)

    async def options(self, kind: OptionKind, of: Mapping[str, str]) -> list[NodeOption]:
        """Nobody edits a workflow in the simulation n8n, so its editor lists nothing."""
        return []

    async def report(self, reporter: N8nExecutionId, failed: N8nExecutionId) -> FailureResult:
        """n8n runs no error workflow for a run by hand, so a report is rare here. It is kept on
        the run the failed execution carries, and fails nothing."""
        nonce = self._links.get(failed)
        run = None if nonce is None else self._runs.get(nonce)
        if run is not None and not self._full(run):
            reported = CallRecord(
                at=self._clock(),
                execution_id=reporter,
                block="Report a failure",
                kind="failure",
                asked={"failed_execution_id": failed},
                outcome="left_as_is",
                status=200,
                detail=FAILS_NO_RUN,
            )
            run.calls.append(reported)
            self._count(run, reported)
        return LeftAsIs(FAILS_NO_RUN)

    async def call(self, call: NodeCall) -> CallResult:
        linked = await self._link(call.execution_id)
        if not isinstance(linked, SimulatedRun):
            log.info(
                "refused %s from execution %s: %s", call.kind, call.execution_id, linked.detail
            )
            return linked
        run = linked
        if len(run.calls) >= self._call_limit:
            return TOO_MANY_CALLS
        if self._full(run):
            return TOO_MUCH
        key = (call.execution_id, call.node_name)
        kept = self._kept.get(key)
        if kept is not None and kept[0] != call.content_hash:
            return self._note(run, call, CHANGED_CALL)
        if kept is not None:
            return self._note(run, call, kept[1], replayed=True)
        answer = await self._answer(run, self._scenarios[run.nonce], call)
        if not isinstance(answer, TryLater):
            self._kept[key] = (call.content_hash, answer)
        return self._note(run, call, answer)

    async def settle(self) -> None:
        """Waits for every wake under way."""
        while self._wakes:
            await asyncio.gather(*self._wakes, return_exceptions=True)

    async def close(self) -> None:
        for task in self._wakes:
            task.cancel()
        await asyncio.gather(*self._wakes, return_exceptions=True)

    def _full(self, run: SimulatedRun) -> bool:
        return self._sizes.get(run.nonce, 0) >= self._byte_limit

    def _count(self, run: SimulatedRun, *kept: WireModel) -> None:
        """Counts what the run's record now holds besides, toward its byte limit."""
        added = sum(len(model.model_dump_json()) for model in kept)
        self._sizes[run.nonce] = self._sizes.get(run.nonce, 0) + added
        self._held += added
        self._make_room(run.nonce)

    def _make_room(self, keep: str) -> None:
        """Forgets the oldest runs but `keep` while there are too many, or they hold too much."""
        for nonce in list(self._runs):
            if len(self._runs) <= self._run_limit and self._held <= self._held_limit:
                return
            if nonce != keep:
                self._forget(nonce)

    def _forget(self, nonce: str) -> None:
        run = self._runs.pop(nonce)
        self._scenarios.pop(nonce, None)
        self._held -= self._sizes.pop(nonce, 0) + self._scenario_sizes.pop(nonce, 0)
        if run.execution_id is not None:
            execution = N8nExecutionId(run.execution_id)
            self._links.pop(execution, None)
            for key in [key for key in self._kept if key[0] == execution]:
                del self._kept[key]

    async def _link(self, execution: N8nExecutionId) -> SimulatedRun | Refused | TryLater:
        """The run a start item names, checked as platform-api's check_start checks one."""
        nonce = self._links.get(execution)
        if nonce is not None:
            return self._runs.get(nonce) or FORGOTTEN
        try:
            record = await self._executions.execution(execution)
        except N8nError, httpx.HTTPError:
            return N8N_SILENT
        if record is None:
            return NO_EXECUTION
        if record.start_nonce is None:
            return NOT_A_SIMULATION
        run = self._runs.get(record.start_nonce)
        if run is None:
            return START_UNKNOWN_HERE
        if run.workflow_id != record.workflow_id:
            return START_OTHER_WORKFLOW
        if run.execution_id is not None and run.execution_id != execution:
            return ANOTHER_EXECUTION
        if run.execution_id is None and self._clock() > run.issued_at + START_LIFETIME:
            return START_EXPIRED
        run.execution_id = execution
        run.mode = record.mode
        self._links[execution] = run.nonce
        return run

    async def _answer(self, run: SimulatedRun, scenario: Scenario, call: NodeCall) -> CallResult:
        match call.work:
            case ReadCall(source, place):
                return await self._read(scenario, call.node_name, source, place)
            case AgentCall() as agent:
                return self._agent(run, scenario, call.node_name, agent)
            case ProposeCall(action, place, title, body, subject):
                change = ProposedChange(
                    block=call.node_name,
                    action=action,
                    place=place,
                    title=title,
                    body=body,
                    subject=subject,
                )
                run.proposed.append(change)
                self._count(run, change)
                return Answer(())
            case AskCall(resume_url):
                return self._ask(run, scenario, call.execution_id, resume_url)
            case WriteCall():
                if run.would_have_written is None:
                    run.would_have_written = len(run.proposed)
                return NEVER_WRITES
            case TellCall():
                return Told("would_have_sent", SENDS_NOTHING)

    async def _read(self, scenario: Scenario, block: str, source: str, place: str) -> CallResult:
        given = _given(scenario, block)
        if isinstance(given, Refused):
            return given
        if place in given.gone:
            return _not_found(source, place)
        match given.serve:
            case "recorded":
                return read_answer([cast(Mapping[str, Json], item) for item in given.items])
            case "mock" if source == GITHUB_RELEASES and self._github is not None:
                return read_answer(await self._github.releases(place))
            case "mock":
                return Refused(
                    409, f'Only GitHub releases have a mock. Give "{block}" recorded items.'
                )
            case "not_found":
                return _not_found(source, place)
            case "timeout":
                return TryLater(SOURCE_TIMED_OUT)

    def _agent(
        self, run: SimulatedRun, scenario: Scenario, block: str, agent: AgentCall
    ) -> CallResult:
        """The recorded reply, with what platform-api adds to it: the Version checker's answer
        says whether it found a newer release, as the release check's Newer? block reads it."""
        given = _given(scenario, block)
        if isinstance(given, Refused):
            return given
        match given.serve:
            case "recorded":
                for change in given.proposes:
                    proposed = ProposedChange(block=block, **change.model_dump())
                    run.proposed.append(proposed)
                    self._count(run, proposed)
                items = tuple(cast(Mapping[str, Json], item) for item in given.items)
                repo = release_of(agent.agent, agent.inputs)
                if repo is not None:
                    newer, version = bool(given.proposes), self._newest_read(run, repo)
                    items = tuple(
                        release_compared(item, newer=newer, version=version) for item in items
                    )
                return Answer(items)
            case "timeout":
                return TryLater(AGENT_TIMED_OUT)
            case _:
                return Refused(
                    409, f'A simulation calls no model. Give "{block}" a recorded reply.'
                )

    def _newest_read(self, run: SimulatedRun, repo: str) -> str | None:
        """The newest release the run read from the repository, which platform-api reads again
        for the Version checker. None when the run read none there."""
        for call in reversed(run.calls):
            if call.kind != "read" or call.asked.get("place") != repo:
                continue
            if call.asked.get("source") != GITHUB_RELEASES:
                continue
            kept = self._kept.get((N8nExecutionId(call.execution_id), call.block))
            if kept is not None and isinstance(kept[1], Answer) and kept[1].items:
                newest = kept[1].items[0].get("id")
                return newest if isinstance(newest, str) else None
        return None

    def _ask(
        self, run: SimulatedRun, scenario: Scenario, execution: N8nExecutionId, resume_url: str
    ) -> CallResult:
        """With nothing proposed, the block leaves by Nothing to change, as platform-api's ask
        does. Otherwise it waits, and the scenario's answer wakes it."""
        if not run.proposed:
            return NothingToChange()
        request = ApprovalId(new_id("simapr"))
        run.approver = scenario.approver
        held = HeldWait(execution, resume_url)
        self._spawn(self._wake(run, held, request, scenario.approver))
        return Waiting(request)

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._wakes.add(task)
        task.add_done_callback(self._wakes.discard)

    async def _wake(
        self, run: SimulatedRun, held: HeldWait, request: ApprovalId, decision: WakeDecision
    ) -> None:
        await self._sleep(WAKE_DELAY)
        for _ in range(WAKE_TRIES):
            try:
                answer = await self._waker.wake(held, request, decision)
            except DispatchFailure:
                await self._sleep(WAKE_GAP)
                continue
            run.woke = "gone" if isinstance(answer, Gone) else "delivered"
            return
        run.woke = "failed"
        log.warning("could not wake execution %s with the scenario's answer", held.execution_id)

    def _note(
        self, run: SimulatedRun, call: NodeCall, answer: CallResult, replayed: bool = False
    ) -> CallResult:
        asked = {k: v for k, v in asdict(call.work).items() if k != "resume_url"}
        outcome, status, detail, items = _shown(answer)
        record = CallRecord(
            at=self._clock(),
            execution_id=call.execution_id,
            block=call.node_name,
            kind=call.kind,
            asked=cast(dict[str, JsonValue], asked),
            outcome=outcome,
            status=status,
            detail=detail,
            items=items,
            replayed=replayed,
        )
        run.calls.append(record)
        self._count(run, record)
        return answer


def _given(scenario: Scenario, block: str) -> BlockAnswer | Refused:
    given = scenario.blocks.get(block)
    if given is None:
        return Refused(409, f'The scenario "{scenario.name}" gives "{block}" no answer.')
    return given


def _shown(answer: CallResult) -> tuple[Outcome, int, str | None, int | None]:
    match answer:
        case Answer(items):
            return "answered", 200, None, len(items)
        case Waiting():
            return "waiting", 200, None, None
        case NothingToChange():
            return "nothing_to_change", 200, None, None
        case Told(line=line):
            return "would_have_sent", 200, line, None
        case Refused(status, detail):
            return "refused", status, detail, None
        case TryLater(detail):
            return "try_again", 503, detail, None
        case WriteAnswer():
            raise AssertionError("a simulation never writes")
