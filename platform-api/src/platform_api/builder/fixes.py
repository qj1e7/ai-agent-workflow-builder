"""Fix it for me (ADR 0055, PR 6): the start of a fix, the fixed version it stores, its set-up
approval and Turn back on.

The start. An Operator asks for a fix on a stopped run of a drafted workflow, set up from the
revision an Approver approved and still the version in use. platform-api writes the fix's start in
the run's log itself, as the coordinator, with who asked from the session, never from a caller.
Only once the log took it does it mint the fix's token, for the same deadline, and ask the agent
runtime to run the coordinator. Only one fix runs for a workflow at a time.

The store. The coordinator hands in a fixed version, which is stored under the fix's id, once:
asking again with the same version answers the same. It is stored only while the fix runs, with
no setting changed, the change inside the blocks where the run stopped, the checker's pass, and a
simulation platform-api ran itself that every scenario passed. A stored version waits for a yes
only once the fix's proposal names it, so a store that came back late, after the coordinator
gave up on it, never waits for a yes. The next start for the workflow drops it.

The approval. A proposal the log took opens a set-up approval for the stored version, keyed by
the fix's id, as ADR 0055 amends ADR 0051: whatever its flags, it needs an Approver's yes. The
person who asked, the person who answered its question, and every author of the stopped version
are its parties, and none of them may give it. The approval page shows code's evidence: the
change, the cause, each scenario's grade and code's checks. The AI's rewording of the report is
help for the reader, never the check. A new version of the workflow drops a fix that waits.

Turn back on. Only after the yes. The fixed version goes into n8n as the workflow's draft, beside
the version in use, and the one real test run tries it: it stops at the yes and writes nothing
(ADR 0044). Only once it passed does the fixed version go live. A no leaves the fix off.

A hand-back. A fix never changes a setting. When the fix was handed back and the blocks where the
run stopped hold a place only a person fills, such as a repository or a Jira project, the fix
asks for it, one question at a time, as a drafted workflow does. The answer makes the fixed
version, which needs the same yes and the same test run."""

import asyncio
import hashlib
import json as plain_json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal, LiteralString, Protocol, cast

from pydantic import Field, ValidationError

from platform_api.builder.drafted_settings import (
    PLACEHOLDER,
    SettingNow,
    Source,
    Unread,
    asking,
    read_answer,
    settings_of,
    with_answer,
)
from platform_api.builder.drafted_views import (
    FixChangeView,
    FixCheckView,
    FixEvidenceView,
    FixScenarioView,
)
from platform_api.builder.drafted_workflows import (
    DraftedWorkflows,
    FixApproval,
    FixLaid,
    NotFound,
    Refused,
    SetUpPlan,
)
from platform_api.builder.explain import TooLongToSmooth, Wordings, to_smooth, view_of
from platform_api.builder.fix_parts import MOST_CALLS, FixRevisionOut, ModelCall, fix_token
from platform_api.builder.versions import authors_from
from platform_api.builder.workflow_report import WorkflowReport
from platform_api.db import Connection, Database, hold_workflow, json
from platform_api.monitoring import (
    ActivityEvent,
    FixData,
    FixDecidedData,
    FixHandedBackData,
    FixHandoffData,
    FixOutcomeData,
    FixProposedData,
    FixRefused,
    FixStartedData,
    FixTriedData,
    RunCreatedData,
    cause_words,
    current_failure,
    explain_failure,
    inside_the_workflow,
    stop_kind,
)
from platform_api.monitoring import RunFailedData as StopData
from platform_api.orchestration import (
    EVENT_SUMMARY_LIMIT,
    GITHUB_RELEASES,
    MOST_EVENTS,
    STOP_MESSAGE_LIMIT,
    TYPE_OF,
    AgentRejected,
    AgentUnavailable,
    Approved,
    ApprovedSetUp,
    CauseFound,
    Closed,
    Declined,
    Ended,
    ExplainReworded,
    FixAccepted,
    FixAsked,
    FixStartRequest,
    ModelAccess,
    RunInN8n,
    SetUpApprovals,
    SetUpAsk,
    SetUpState,
    StoppedRun,
    WorkflowPlan,
    workflow_digest,
)
from platform_api.shared import ApprovalId, Digest, Principal, RunId, UserId, new_id
from platform_api.wire import FixOffer, WireIn, WireModel

log = logging.getLogger(__name__)

FIX_TIME_LIMIT: Final = timedelta(minutes=20)
WORK_EVERY: Final = timedelta(seconds=5)
ASKED_KINDS: Final = frozenset({"repository", "jira_project"})
"""The places a hand-back asks a person for: a fix never changes them (ADR 0055, PR 4)."""
SHOWN_LIMIT: Final = 200
CALL_COLUMNS: Final[Mapping[ModelCall, LiteralString]] = {
    "writer": "writer_calls",
    "explainer": "explainer_calls",
}

# The words people see. Each is listed under "Words to confirm" in the pull request.
OFF: Final = "Fix it for me is off here."
NO_MODEL: Final = "Fix it for me needs an AI model, and none is connected yet."
NOT_STOPPED: Final = "This run isn't stopped, so there's nothing to fix."
NOT_IN_THE_WORKFLOW: Final = (
    "The cause isn't in the workflow's own settings or wiring, so a fix can't help."
)
CANT_TELL_OFFER: Final = "The platform couldn't tell whether a fix can start. Try again soon."
MODEL_CHECK_FOR: Final = timedelta(seconds=30)
"""A read of the run asks whether a model is set at most this often, and never opens its key."""
NOT_DRAFTED: Final = "Fix it for me works only for a workflow drafted here, as it was approved."
CANT_TELL: Final = "The platform can't tell where the run stopped, so it can't be fixed."
NEWER: Final = (
    "The workflow has a newer version since this run, so there's nothing to fix in this run."
)
IN_N8N: Final = "It's open in n8n, so it can't be fixed now."
BUSY: Final = "A fix for this workflow is already under way."
DRAFTING: Final = "Drafting a fix. Nothing changes until an Approver says yes."
WAITING: Final = "Waiting for a yes. Nothing changes until an Approver says yes."
APPROVED: Final = (
    "An Approver said yes. Turn it back on to try the fix with a test run, which writes nothing."
)
TESTING: Final = "Trying the fix with a test run, which writes nothing."
ON: Final = "The fix passed its test run, so the workflow is back on with it."
ON_PAUSED: Final = (
    "The fix passed its test run and is saved. The workflow stays paused, so the fix runs once "
    "someone resumes it."
)
READ_LIST: Final = (
    "Once it is turned back on, {places} joins the team's list of repositories any workflow may "
    "read."
)
REPLAY_THE_STOP: Final = "replay_the_stop"
"""The coordinator's own replay of the stop (agent_runtime.fixing.replay.REPLAY)."""
READ_BLOCK: Final = TYPE_OF["read"]
TRY_LEASE: Final = timedelta(minutes=5)
"""A press of Turn back on whose test run hasn't started by then was cut off, and is freed."""
TEST_FAILED: Final = (
    "The test run didn't pass, so the fix wasn't turned on. The workflow stays as it was."
)
HANDED_BACK: Final = "I couldn't fix this. Here's the cause and what I tried."
"""The team lead's own words (ADR 0055, section 5)."""
DECLINED: Final = "An Approver said no, so the fix stays off. The workflow stays as it was."
EXPIRED: Final = "Nobody said yes in time, so the fix stays off. The workflow stays as it was."
STALE: Final = "The workflow changed since, so this fix was dropped. Ask for a fix again."
NEVER_PROPOSED: Final = "This fix ended before it was handed in, so it was dropped."
YES_FIRST: Final = "It needs an Approver's yes first."
FLAGGED: Final = (
    "It has a flag under today's rules, so it can't be approved now. Ask for a fix again."
)
ACCESS: Final = (
    "It changes who can use a system, so a fix needs two Approvers. That comes in a later step."
)
ENDED: Final = "The fix ended, so nothing was stored."
UNPROVEN: Final = "No simulation here passed every scenario on this version, so it wasn't stored."
SETTING: Final = "A fix can't change a setting."
OUTSIDE: Final = "The change reaches past the blocks where the run stopped, so it wasn't stored."
UNSAFE: Final = "It doesn't pass the safety check, so it wasn't stored."
NOT_READY: Final = "n8n isn't ready, so nothing was stored. Try again."
NOT_THE_STORED: Final = "The proposal isn't the version stored for this fix."
NO_QUESTION: Final = "There's no question to answer for this fix."
IN_SHORT: Final = "A fix for a run that stopped. Nothing changes until an Approver says yes."
FIX_NAME: Final = "a fix for {name}"
"""How the Teams card names it: "Alice asks to set up a fix for Release check."."""
CHECK_WORDS: Final[Mapping[str, str]] = {
    "inside_the_failed_part": "The change stays inside the blocks where the run stopped.",
    "every_scenario_passed": "Every scenario passed on practice systems.",
    "safety_check": "It passes the safety check.",
    "settings_unchanged": "No setting a person filled changed.",
}
DROPPED_WORDS: Final[Mapping[str, str]] = {
    "declined": DECLINED,
    "expired": EXPIRED,
    "stale": STALE,
    "never_proposed": NEVER_PROPOSED,
}

type FixState = Literal[
    "drafting",
    "waiting",
    "approved",
    "testing",
    "on",
    "test_failed",
    "handed_back",
    "declined",
    "dropped",
]
type TriedResult = Literal["turned_on", "kept_paused", "test_failed", "not_put_live"]
BUSY_STATES: Final[frozenset[FixState]] = frozenset({"drafting", "waiting", "approved", "testing"})
STATE_WORDS: Final[Mapping[FixState, str]] = {
    "drafting": DRAFTING,
    "waiting": WAITING,
    "approved": APPROVED,
    "testing": TESTING,
    "on": ON,
    "test_failed": TEST_FAILED,
    "handed_back": HANDED_BACK,
    "declined": DECLINED,
}


# What the routes answer


class FixChoiceView(WireModel):
    value: str
    label: str


class FixQuestionView(WireModel):
    """The one setting a handed-back fix asks a person for, in code's fixed words."""

    setting: str
    key: str = Field(description="The short words before the question, as GitHub or Jira.")
    words: str
    choices: list[FixChoiceView]
    typed: str | None = Field(description="The words on the button that opens a box to type in.")
    waits: str | None = Field(description="Why it can't be answered now.")


class FixView(WireModel):
    fix_id: str
    run_id: str
    use_case_id: str
    name: str = Field(description="The workflow's name.")
    state: FixState
    said: str = Field(description="The state in code's own words.")
    asked_by: str
    asked_by_name: str
    ends_by: datetime = Field(description="When the coordinator stops, at most 20 minutes in.")
    approval_id: str | None = Field(description="Its set-up approval, once it waits for a yes.")
    question: FixQuestionView | None = Field(
        description="The setting a handed-back fix asks for, which a fix never changes itself."
    )
    can_turn_back_on: bool = Field(description="An Approver said yes, and it isn't tried yet.")


class FixAnswerIn(WireIn):
    setting: str = Field(min_length=1, max_length=120)
    choice: str | None = Field(default=None, max_length=200)
    typed: str | None = Field(default=None, min_length=1, max_length=200)


class NotStored(Exception):
    """Why a fixed version or a proposal of it was refused, with the status the route answers."""

    def __init__(self, words: str, status: int = 422) -> None:
        super().__init__(words)
        self.words = words
        self.status = status


@dataclass(frozen=True)
class FixTrying:
    """The test run of a fixed version, and n8n's draft that holds it."""

    run_id: str
    draft: str


@dataclass(frozen=True)
class FixLive:
    """The fix went in as the workflow's version in use. A workflow an Operator paused stays
    paused, so the fix runs once someone resumes it."""

    paused: bool


@dataclass(frozen=True)
class FixSettings:
    on: bool
    """FIX_MODEL: off, nobody can start a fix."""
    signing_key: str = field(repr=False)
    platform_url: str
    """platform-api's own address, where the coordinator's calls go."""


# What the fixes reach


class FixActivity(Protocol):
    async def note_fix(self, run_id: RunId, data: FixData) -> FixRefused | None: ...

    async def note_fix_outcome(self, run_id: RunId, data: FixOutcomeData) -> FixRefused | None: ...

    async def read_after(self, run_id: RunId, after: int) -> list[ActivityEvent]: ...


class RunRecords(Protocol):
    async def read(self, run_id: RunId) -> RunInN8n | None: ...


class FixModels(Protocol):
    async def access(self) -> ModelAccess | None: ...


class FixRuntime(Protocol):
    async def start_fix(
        self, request: FixStartRequest
    ) -> FixAccepted | AgentUnavailable | AgentRejected: ...


class FixTries(Protocol):
    """The builder's test run of a fixed version, and turning the workflow back on with it. Each
    acts only while `stopped_version` is still the version in use, checked under the workflow's
    lock in the same transaction, and answers STALE otherwise."""

    async def try_fixed(
        self, use_case_id: str, document: dict[str, Any], by: Principal, stopped_version: int
    ) -> FixTrying | str: ...

    async def tried_outcome(self, run_id: str) -> Literal["passed", "failed"] | None: ...

    async def put_live(
        self,
        use_case_id: str,
        trying: FixTrying,
        document: dict[str, Any],
        by: UserId,
        authors: frozenset[UserId],
        stopped_version: int,
    ) -> FixLive | str: ...


# One fix, as it is kept


@dataclass(frozen=True)
class _Ready:
    """What a start has read and checked before it writes anything."""

    events: Sequence[Any]
    created: RunCreatedData
    failure: Any
    model: ModelAccess | None
    set_up: SetUpPlan
    stopped_at: list[str]


@dataclass(frozen=True)
class FixRow:
    fix_id: str
    run_id: RunId
    use_case_id: str
    drafted_id: str
    name: str
    stopped_version: int
    stopped_at: tuple[str, ...]
    stop: StoppedRun
    asked_by: UserId
    asked_by_name: str
    started_at: datetime
    ends_by: datetime
    plan: WorkflowPlan | None
    document: dict[str, Any] | None
    digest: str | None
    version: int | None
    cause: CauseFound | None
    made_by: Literal["fix_drafter", "answer"] | None
    answered_by: UserId | None
    stored_at: datetime | None
    proposed_at: datetime | None
    approval_id: str | None
    handed_back_at: datetime | None
    approved_at: datetime | None
    dropped_at: datetime | None
    dropped_why: str | None
    simulated: dict[str, dict[str, dict[str, Any]]]
    test_run_id: str | None
    test_draft: str | None
    testing_by: UserId | None
    testing_at: datetime | None
    turned_on_at: datetime | None
    test_failed_at: datetime | None
    turn_on_problem: str | None
    stays_paused: bool


def fix_state(row: FixRow, now: datetime) -> FixState:
    """One state for each fix, from what was kept: the same words everywhere."""
    if row.dropped_why == "declined":
        return "declined"
    if row.dropped_at is not None:
        return "dropped"
    if row.turned_on_at is not None:
        return "on"
    if row.test_failed_at is not None:
        return "test_failed"
    if row.testing_at is not None:
        return "testing"
    if row.approved_at is not None:
        return "approved"
    if row.proposed_at is not None:
        return "waiting"
    if row.handed_back_at is not None or now >= row.ends_by:
        return "handed_back"
    return "drafting"


def said(row: FixRow, state: FixState) -> str:
    if state == "dropped":
        return DROPPED_WORDS.get(row.dropped_why or "", STALE)
    if state == "test_failed" and row.turn_on_problem:
        return row.turn_on_problem
    if state == "on" and row.stays_paused:
        return ON_PAUSED
    return STATE_WORDS[state]


def plan_key(plan: WorkflowPlan) -> str:
    """The key a simulation of this plan is kept under, the same for the same plan."""
    return hashlib.sha256(plan.model_dump_json().encode()).hexdigest()


def proven(results: Mapping[str, Mapping[str, Any]] | None) -> bool:
    """Every scenario that applies passed, the coordinator's replay of the stop among them."""
    found = results or {}
    applied = [r for r in found.values() if r.get("verdict") != "not_tried"]
    replayed = found.get(REPLAY_THE_STOP, {}).get("verdict") == "passed"
    return replayed and all(r.get("verdict") == "passed" for r in applied)


def _reads(plan: WorkflowPlan) -> set[str]:
    """The repositories the plan's Read blocks read, with each setting's value put in."""
    resolved = _resolved(plan)
    return {
        str(resolved[block.name].get("place"))
        for block in plan.blocks
        if block.type == READ_BLOCK
        and resolved[block.name].get("source") == GITHUB_RELEASES
        and isinstance(resolved[block.name].get("place"), str)
    }


def _read_list(stopped: WorkflowPlan, fixed: WorkflowPlan) -> str | None:
    """What the fixed version adds to the team's read list once it is tried, in code's words."""
    added = sorted(_reads(fixed) - _reads(stopped))
    if not added:
        return None
    return READ_LIST.format(places=" and ".join(f"“{place}”" for place in added))


def settings_kept(stopped: WorkflowPlan, fixed: WorkflowPlan) -> bool:
    """Every setting as it was: its id, kind, value and mark, where it says it fills, and each
    placeholder at the same block and parameter path. A fix that moves a placeholder elsewhere,
    and writes a value where it stood, changes a setting a person filled."""

    def kept(plan: WorkflowPlan) -> object:
        settings = sorted(
            (s.id, s.kind, s.value, s.mark, sorted((f.block, f.parameter) for f in s.fills))
            for s in plan.settings
        )
        placed = sorted(
            (block.name, path, found)
            for block in plan.blocks
            for path, value in _leaves(block.parameters).items()
            if isinstance(value, str)
            for found in PLACEHOLDER.findall(value)
        )
        return settings, placed

    return kept(stopped) == kept(fixed)


def _leaves(value: object, path: str = "") -> dict[str, object]:
    if isinstance(value, dict) and value:
        found: dict[str, object] = {}
        for key, inner in cast(dict[str, object], value).items():
            found |= _leaves(inner, f"{path}.{key}" if path else key)
        return found
    return {path: value}


def _resolved(plan: WorkflowPlan) -> dict[str, dict[str, object]]:
    """Each block's parameters, with each setting's value where its placeholder stands."""
    values = {s.id: s.value for s in plan.settings if s.value is not None}

    def filled(value: object) -> object:
        if isinstance(value, str):
            return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), value)
        return value

    return {
        block.name: {path: filled(v) for path, v in _leaves(block.parameters).items()}
        for block in plan.blocks
    }


def _shown(value: object) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else plain_json.dumps(value, ensure_ascii=False)
    return text if len(text) <= SHOWN_LIMIT else text[: SHOWN_LIMIT - 1] + "…"


def changes_between(stopped: WorkflowPlan, fixed: WorkflowPlan) -> list[FixChangeView]:
    """Each value the fix changed, block by block, as the run reads it."""
    before, after = _resolved(stopped), _resolved(fixed)
    changes: list[FixChangeView] = []
    for block in [b.name for b in fixed.blocks]:
        was, now = before.get(block, {}), after.get(block, {})
        for path in sorted(set(was) | set(now)):
            if was.get(path) != now.get(path):
                changes.append(
                    FixChangeView(
                        block=block,
                        parameter=path,
                        before=_shown(was.get(path)),
                        after=_shown(now.get(path)),
                    )
                )
    return changes


def changed_blocks(stopped: WorkflowPlan, fixed: WorkflowPlan) -> set[str]:
    """The blocks whose values differ, and any block one plan has that the other lacks."""
    before, after = _resolved(stopped), _resolved(fixed)
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


def same_shape(stopped: WorkflowPlan, fixed: WorkflowPlan) -> bool:
    """The same name, the same blocks of the same types and versions, and the same wires: a fix
    changes only values inside blocks, as the runtime's scope check holds it to."""

    def shape(plan: WorkflowPlan) -> object:
        blocks = sorted((b.name, b.type, str(b.version)) for b in plan.blocks)
        wires = sorted(
            plain_json.dumps(w.model_dump(mode="json"), sort_keys=True) for w in plan.wires
        )
        return plan.name, blocks, wires

    return shape(stopped) == shape(fixed)


# The service


class Fixes:
    def __init__(
        self,
        db: Database,
        activity: FixActivity,
        records: RunRecords,
        drafted: DraftedWorkflows,
        approvals: SetUpApprovals,
        runtime: FixRuntime,
        models: FixModels,
        tries: FixTries,
        settings: FixSettings,
        wordings: Wordings | None = None,
    ) -> None:
        self._db = db
        self._log = activity
        self._records = records
        self._drafted = drafted
        self._approvals = approvals
        self._runtime = runtime
        self._models = models
        self._tries = tries
        self.settings = settings
        self._wordings = wordings
        self._wake = asyncio.Event()
        self._model_seen: tuple[datetime, bool] | None = None

    # The start

    async def start(self, run_id: RunId, asker: Principal) -> FixView | Refused | NotFound:
        """Starts a fix on a stopped run for an Operator, whom the route checked."""
        ready = await self._preflight(run_id, for_offer=False)
        if not isinstance(ready, _Ready):
            return ready
        model = ready.model
        assert model is not None
        events, created, failure, set_up, stopped_at = (
            ready.events,
            ready.created,
            ready.failure,
            ready.set_up,
            ready.stopped_at,
        )
        facts = await self._drafted.drafter_facts()
        await self.reconcile(created.use_case_id)
        stop = StoppedRun(
            stage=failure.data.stage,
            reason=failure.data.reason,
            retryable=failure.data.retryable,
            message=failure.data.message[:STOP_MESSAGE_LIMIT],
        )
        begun = await self._begin(run_id, created, set_up, stopped_at, stop, asker)
        if not isinstance(begun, FixRow):
            return begun
        # The log took the start, so the token may be minted, for the same deadline.
        token = fix_token(self.settings.signing_key, run_id, begun.fix_id, begun.ends_by)
        asked = FixStartRequest(
            run_id=run_id,
            request=FixAsked(
                fix_id=begun.fix_id,
                asked_by=asker.user_id,
                asked_by_name=begun.asked_by_name,
                ends_by=begun.ends_by,
                stop=stop,
                version=set_up.plan,
                stopped_at=stopped_at,
            ),
            events=[e.summary[:EVENT_SUMMARY_LIMIT] for e in events][-MOST_EVENTS:],
            facts=facts,
            model=model,
            platform_url=self.settings.platform_url,
            token=token,
        )
        answer = await self._runtime.start_fix(asked)
        if not isinstance(answer, FixAccepted):
            log.warning("fix %s: the runtime didn't take it: %s", begun.fix_id, answer.detail)
            await self.note_fix(run_id, FixHandedBackData(fix_id=begun.fix_id, why="gave_up"))
        log.info("%s asked for fix %s on %s", asker.user_id, begun.fix_id, run_id)
        return await self._viewed(begun.fix_id)

    async def offer(self, run_id: RunId) -> FixOffer:
        """Whether a fix could start on this stopped run now, in the words start would refuse
        with. It reads only, so it writes no event and keeps no row."""
        try:
            return await self._offer(run_id)
        except Exception:
            log.warning("fix offer for %s: couldn't be worked out", run_id, exc_info=True)
            return FixOffer(can=False, why_not=CANT_TELL_OFFER)

    async def _offer(self, run_id: RunId) -> FixOffer:
        ready = await self._preflight(run_id, for_offer=True)
        if isinstance(ready, NotFound):
            return FixOffer(can=False, why_not=NOT_STOPPED)
        if isinstance(ready, Refused):
            return FixOffer(can=False, why_not=ready.words)
        async with self._db.connection("builder") as conn:
            refused = await self._workflow_refusal(
                conn, ready.created, ready.set_up, self._db.clock()
            )
        if refused is None:
            return FixOffer(can=True, why_not=None)
        return FixOffer(
            can=False, why_not=NOT_STOPPED if isinstance(refused, NotFound) else refused.words
        )

    async def _model_is_set(self) -> bool:
        """Whether a model is connected, asked afresh at most every half minute. The run is read
        every few seconds, and opening the saved key each time is more than a read needs."""
        now = self._db.clock()
        if self._model_seen is not None and now - self._model_seen[0] < MODEL_CHECK_FOR:
            return self._model_seen[1]
        is_set = await self._models.access() is not None
        # Only a yes is kept, so connecting a model shows at once.
        self._model_seen = (now, True) if is_set else None
        return is_set

    async def _preflight(self, run_id: RunId, *, for_offer: bool) -> _Ready | Refused | NotFound:
        """The checks a start makes before it writes anything. A read of the offer makes the
        same ones, and never opens the model's key."""
        if not self.settings.on:
            return Refused(OFF)
        events = await self._log.read_after(run_id, 0)
        created = next((e.data for e in events if isinstance(e.data, RunCreatedData)), None)
        if created is None:
            return NotFound()
        failure = current_failure(events)
        if failure is None:
            return Refused(NOT_STOPPED)
        if not inside_the_workflow(failure.data):
            return Refused(NOT_IN_THE_WORKFLOW)
        if for_offer:
            if not await self._model_is_set():
                return Refused(NO_MODEL)
            model = None
        else:
            model = await self._models.access()
            if model is None:
                return Refused(NO_MODEL)
        set_up = await self._drafted.set_up_plan(created.use_case_id)
        if set_up is None:
            return Refused(NOT_DRAFTED)
        record = await self._records.read(run_id)
        nodes: Mapping[str, str] = {} if record is None else record.nodes
        stopped_at = [name for name, state in nodes.items() if state == "failed"]
        if not stopped_at or not set(stopped_at) <= {b.name for b in set_up.plan.blocks}:
            return Refused(CANT_TELL)
        return _Ready(events, created, failure, model, set_up, stopped_at)

    async def _workflow_refusal(
        self, conn: Any, created: RunCreatedData, set_up: SetUpPlan, now: datetime
    ) -> Refused | NotFound | None:
        """Why the workflow itself can't take a fix now: gone, changed since the run, held in n8n,
        not as it was approved, or already has one under way."""
        use_case_id = created.use_case_id
        workflow = await (
            await conn.execute(
                "SELECT current_version, held_by, deleted_at FROM builder.use_cases"
                " WHERE use_case_id = %s",
                (use_case_id,),
            )
        ).fetchone()
        if workflow is None or workflow["deleted_at"] is not None:
            return NotFound()
        if workflow["current_version"] != created.use_case_version:
            return Refused(NEWER)
        if workflow["held_by"] is not None:
            return Refused(IN_N8N)
        ran = await (
            await conn.execute(
                "SELECT document FROM builder.use_case_versions"
                " WHERE use_case_id = %s AND version = %s",
                (use_case_id, created.use_case_version),
            )
        ).fetchone()
        if ran is None or ran["document"] is None:
            return Refused(NOT_DRAFTED)
        if workflow_digest(ran["document"]) != set_up.digest:
            return Refused(NOT_DRAFTED)
        for row in await _rows_of(conn, use_case_id):
            if fix_state(row, now) in BUSY_STATES:
                return Refused(BUSY)
        return None

    async def _begin(
        self,
        run_id: RunId,
        created: RunCreatedData,
        set_up: SetUpPlan,
        stopped_at: Sequence[str],
        stop: StoppedRun,
        asker: Principal,
    ) -> FixRow | Refused | NotFound:
        """Writes the fix's start in the log and keeps the fix, one workflow at a time: under
        the workflow's fix lock, so two asks can't both start one. A start the platform then
        couldn't keep is ended in the log at once, so it never holds the run for 20 minutes."""
        started: list[str] = []
        try:
            return await self._begin_once(run_id, created, set_up, stopped_at, stop, asker, started)
        except Exception:
            for fix_id in started:
                log.warning("fix %s: kept no row for its start, so it ends now", fix_id)
                await self._log.note_fix(run_id, FixHandedBackData(fix_id=fix_id, why="gave_up"))
            raise

    async def _begin_once(
        self,
        run_id: RunId,
        created: RunCreatedData,
        set_up: SetUpPlan,
        stopped_at: Sequence[str],
        stop: StoppedRun,
        asker: Principal,
        started: list[str],
    ) -> FixRow | Refused | NotFound:
        use_case_id = created.use_case_id
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"fix:{use_case_id}", alone=True)
            refused_now = await self._workflow_refusal(uow.conn, created, set_up, uow.now)
            if refused_now is not None:
                return refused_now
            fix_id = new_id("fix")
            ends_by = uow.now + FIX_TIME_LIMIT
            name = _shown_name(asker)
            refused = await self._log.note_fix(
                run_id,
                FixStartedData(
                    fix_id=fix_id, asked_by=asker.user_id, asked_by_name=name, ends_by=ends_by
                ),
            )
            if refused is not None:
                return Refused(NOT_STOPPED if refused.why == "not_stopped" else BUSY)
            started.append(fix_id)
            await uow.conn.execute(
                "INSERT INTO builder.fixes (fix_id, run_id, use_case_id, drafted_id, name,"
                " stopped_version, stopped_at, stop, asked_by, asked_by_name, started_at, ends_by)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    fix_id,
                    run_id,
                    use_case_id,
                    set_up.drafted_id,
                    set_up.plan.name,
                    created.use_case_version,
                    list(stopped_at),
                    json(stop.model_dump(mode="json")),
                    asker.user_id,
                    name,
                    uow.now,
                    ends_by,
                ),
            )
            row = await _row(uow.conn, fix_id)
        assert row is not None
        return row

    # What the coordinator's routes reach

    async def note_fix(self, run_id: RunId, data: FixData) -> FixRefused | None:
        """One event of the fix on the stopped run, under the log's rules, never its start. A
        proposal must name the version stored for the fix. Once the log took it, the version
        waits for a set-up approval. A hand-back the log took is kept, so the fix's state agrees
        with the log."""
        if isinstance(data, FixStartedData):
            raise NotStored("The platform writes a fix's start.")
        if isinstance(data, FixProposedData):
            stored = await self._row(data.fix_id)
            if (
                stored is None
                or stored.run_id != run_id
                or stored.made_by != "fix_drafter"
                or stored.digest is None
                or (stored.version, named_digest(stored.digest)) != (data.version, data.digest)
            ):
                raise NotStored(NOT_THE_STORED)
        refused = await self._log.note_fix(run_id, data)
        if refused is not None:
            return refused
        if isinstance(data, FixProposedData):
            await self._mark(data.fix_id, "proposed_at = coalesce(proposed_at, %(now)s)")
            row = await self._row(data.fix_id)
            assert row is not None
            await self._send(row)
        elif isinstance(data, FixHandedBackData):
            await self._mark(data.fix_id, "handed_back_at = coalesce(handed_back_at, %(now)s)")
        return None

    async def store(
        self, run_id: RunId, fix_id: str, plan: WorkflowPlan, cause: CauseFound
    ) -> FixRevisionOut:
        """The fixed version, stored under the fix's id once, or NotStored with why."""
        row = await self._row(fix_id)
        if row is None or row.run_id != run_id:
            raise NotStored(ENDED, 409)
        set_up = await self._drafted.set_up_plan(row.use_case_id)
        if set_up is None:
            raise NotStored(ENDED, 409)
        if not settings_kept(set_up.plan, plan):
            raise NotStored(SETTING)
        part = set(cause.failed_part)
        if (
            not part <= set(row.stopped_at)
            or not same_shape(set_up.plan, plan)
            or not changed_blocks(set_up.plan, plan) <= part
        ):
            raise NotStored(OUTSIDE)
        laid = await self._drafted.fix_laid(row.drafted_id, plan, set_up.sources)
        if laid is None:
            raise NotStored(NOT_READY, 503)
        if laid.grade != "safe" or laid.changes_access:
            raise NotStored(UNSAFE)
        digest = workflow_digest(laid.document)
        async with self._db.transaction("builder") as uow:
            locked = await _row(uow.conn, fix_id, lock=True)
            assert locked is not None
            if locked.stored_at is not None and locked.digest == digest:
                assert locked.version is not None
                return FixRevisionOut(version=locked.version, digest=named_digest(digest))
            if locked.proposed_at is not None or fix_state(locked, uow.now) != "drafting":
                raise NotStored(ENDED, 409)
            if not proven(locked.simulated.get(plan_key(plan))):
                raise NotStored(UNPROVEN, 409)
            version = locked.stopped_version + 1
            await uow.conn.execute(
                "UPDATE builder.fixes SET plan = %s, document = %s, digest = %s, version = %s,"
                " cause = %s, made_by = 'fix_drafter', stored_at = %s WHERE fix_id = %s",
                (
                    json(plan.model_dump(mode="json")),
                    json(laid.document),
                    digest,
                    version,
                    json(cause.model_dump(mode="json")),
                    uow.now,
                    fix_id,
                ),
            )
        log.info("fix %s: stored version %d", fix_id, version)
        return FixRevisionOut(version=version, digest=named_digest(digest))

    async def take_call(self, fix_id: str, kind: ModelCall) -> bool:
        column = CALL_COLUMNS[kind]
        async with self._db.transaction("builder") as uow:
            taken = await (
                await uow.conn.execute(
                    f"UPDATE builder.fixes SET {column} = {column} + 1"
                    f" WHERE fix_id = %s AND {column} < %s RETURNING fix_id",
                    (fix_id, MOST_CALLS[kind]),
                )
            ).fetchone()
        return taken is not None

    async def simulated_on(
        self, fix_id: str, plan: WorkflowPlan, results: Mapping[str, Any]
    ) -> None:
        """Keeps a simulation platform-api ran, each scenario's latest grade on the plan."""
        key = plan_key(plan)
        async with self._db.transaction("builder") as uow:
            row = await _row(uow.conn, fix_id, lock=True)
            if row is None:
                return
            kept = {**row.simulated.get(key, {}), **results}
            await uow.conn.execute(
                "UPDATE builder.fixes SET simulated = simulated || %s WHERE fix_id = %s",
                (json({key: kept}), fix_id),
            )

    # What people see and do

    async def view(self, fix_id: str) -> FixView | NotFound:
        row = await self._settled(fix_id)
        return NotFound() if row is None else await self._view_of(row)

    async def turn_back_on(self, fix_id: str, by: Principal) -> FixView | Refused | NotFound:
        """Only after an Approver's yes to the stored version: the one real test run tries it,
        and the worker turns the workflow back on only once it passed. Asking again answers the
        fix as it stands."""
        row = await self._settled(fix_id)
        if row is None:
            return NotFound()
        state = fix_state(row, self._db.clock())
        if state in ("testing", "on"):
            return await self._view_of(row)
        if state != "approved":
            return Refused(YES_FIRST if state in ("drafting", "waiting") else said(row, state))
        assert row.document is not None
        approval = await self._approvals.get(ApprovalId(row.approval_id or ""))
        if (
            approval is None
            or not isinstance(approval.status, Approved)
            or approval.request.digest != row.digest
        ):
            return Refused(YES_FIRST)
        async with self._db.transaction("builder") as uow:
            claimed = await (
                await uow.conn.execute(
                    "UPDATE builder.fixes SET testing_at = %s, testing_by = %s"
                    " WHERE fix_id = %s AND testing_at IS NULL RETURNING fix_id",
                    (uow.now, by.user_id, fix_id),
                )
            ).fetchone()
        if claimed is None:
            return await self._viewed(fix_id)
        try:
            trying = await self._tries.try_fixed(
                row.use_case_id, row.document, by, row.stopped_version
            )
        except Exception:
            # A press the builder broke on frees the fix, so it never stays "testing" with no
            # test run, and holds no other fix back.
            await self._mark(fix_id, "testing_at = NULL, testing_by = NULL")
            raise
        if isinstance(trying, str):
            await self._mark(fix_id, "testing_at = NULL, testing_by = NULL")
            if trying == STALE:
                await self._approvals.replace_waiting(fix_id)
                await self._drop(fix_id, "stale")
            return Refused(trying)
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.fixes SET test_run_id = %s, test_draft = %s WHERE fix_id = %s",
                (trying.run_id, trying.draft, fix_id),
            )
        log.info("%s turns fix %s back on, with test run %s", by.user_id, fix_id, trying.run_id)
        self._wake.set()
        return await self._viewed(fix_id)

    async def answer(
        self, fix_id: str, person: Principal, answer: FixAnswerIn
    ) -> FixView | Refused | NotFound:
        """The setting a handed-back fix asked for, which code puts in the stopped version with
        no model. The fixed version it makes needs the same yes and the same test run, and the
        person who answered is a party to it."""
        row = await self._settled(fix_id)
        if row is None:
            return NotFound()
        if (answer.choice is None) == (answer.typed is None):
            return Refused(NO_QUESTION)
        set_up = await self._drafted.set_up_plan(row.use_case_id)
        asked = None if set_up is None else await self._question(row, set_up)
        if set_up is None or asked is None or asked.id != answer.setting:
            return Refused(NO_QUESTION)
        if await self._stale(row):
            await self._drop(fix_id, "stale")
            return Refused(STALE)
        facts = await self._drafted.drafter_facts()
        read = read_answer(asked, facts, choice=answer.choice, typed=answer.typed)
        if isinstance(read, Unread):
            return Refused(read.words)
        plan = with_answer(set_up.plan, asked.id, read.value, "filled")
        sources = {
            **set_up.sources,
            asked.id: Source(
                read.value, "chose" if answer.choice is not None else "typed", person.user_id
            ),
        }
        laid = await self._drafted.fix_laid(row.drafted_id, plan, sources)
        if laid is None:
            return Refused(NOT_READY)
        if laid.grade != "safe" or laid.changes_access:
            return Refused(UNSAFE)
        async with self._db.transaction("builder") as uow:
            locked = await _row(uow.conn, fix_id, lock=True)
            assert locked is not None
            if fix_state(locked, uow.now) != "handed_back" or locked.stored_at is not None:
                return Refused(NO_QUESTION)
            await uow.conn.execute(
                "UPDATE builder.fixes SET plan = %s, document = %s, digest = %s, version = %s,"
                " made_by = 'answer', answered_by = %s, stored_at = %s, proposed_at = %s"
                " WHERE fix_id = %s",
                (
                    json(plan.model_dump(mode="json")),
                    json(laid.document),
                    workflow_digest(laid.document),
                    locked.stopped_version + 1,
                    person.user_id,
                    uow.now,
                    uow.now,
                    fix_id,
                ),
            )
        stored = await self._row(fix_id)
        assert stored is not None
        await self._send(stored)
        log.info("%s answered %s for fix %s", person.user_id, asked.id, fix_id)
        return await self._viewed(fix_id)

    # The set-up approval's fix side

    def owns(self, drafted_id: str) -> bool:
        return drafted_id.startswith("fix_")

    async def approval(
        self, state: SetUpState, viewer: Principal, reworded: bool
    ) -> FixApproval | None:
        row = await self._settled(state.request.drafted_id)
        set_up = None if row is None else await self._drafted.set_up_plan(row.use_case_id)
        if row is None or set_up is None or row.plan is None or row.document is None:
            return None
        laid = await self._laid(row, set_up)
        if laid is None:
            return None
        smoothed = await self._reworded(laid.report) if reworded else None
        return FixApproval(
            name=row.name,
            use_case_id=row.use_case_id,
            report=view_of(laid.report, row.use_case_id, row.name, None, False, smoothed),
            held=await self._held(row, laid),
            fix=await self._evidence(row, set_up, laid),
        )

    async def held_now(self, state: SetUpState) -> str | None:
        """Why a yes can't be taken on the fix today: it ended or went stale, or today's rules
        find a flag in it or a change to someone's access."""
        row = await self._settled(state.request.drafted_id)
        set_up = None if row is None else await self._drafted.set_up_plan(row.use_case_id)
        if row is None or set_up is None:
            return STALE
        laid = await self._laid(row, set_up)
        return NOT_READY if laid is None else await self._held(row, laid)

    async def approved(self, approved: ApprovedSetUp) -> None:
        """The yes came. Nothing is set up: Turn back on tries the fix with its test run. The
        run's log gets the yes with the Approver."""
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.fixes SET approved_at = coalesce(approved_at, %s)"
                " WHERE fix_id = %s AND digest = %s AND approval_id = %s AND dropped_at IS NULL",
                (uow.now, approved.drafted_id, approved.digest, approved.approval_id),
            )
        row = await self._row(approved.drafted_id)
        if row is not None and row.approved_at is not None:
            await self._note_decision(row)

    async def _note_decision(self, row: FixRow) -> None:
        """The Approver's yes or no on the run's log, once (ADR 0055, section 8)."""
        state = (
            None
            if row.approval_id is None
            else await self._approvals.get(ApprovalId(row.approval_id))
        )
        if state is None or not state.decisions:
            return
        if not isinstance(state.status, Approved | Declined):
            return
        decision = state.decisions[-1]
        names = await self._approvals.names([decision.by])
        verdict: Literal["approved", "declined"] = (
            "approved" if isinstance(state.status, Approved) else "declined"
        )
        data = FixDecidedData(
            fix_id=row.fix_id,
            approval_id=state.request.id,
            verdict=verdict,
            by=decision.by,
            by_name=_name_shown(names.get(decision.by), decision.by),
            reason=decision.reason if verdict == "declined" else None,
        )
        refused = await self._log.note_fix_outcome(row.run_id, data)
        if refused is not None:
            log.warning("fix %s: the log took no decision (%s)", row.fix_id, refused.why)

    async def _note_tried(self, row: FixRow, result: TriedResult) -> None:
        """How the test run went, with the approval and its Approver, on the run's log, once."""
        state = (
            None
            if row.approval_id is None
            else await self._approvals.get(ApprovalId(row.approval_id))
        )
        if state is None or not state.decisions:
            return
        approver = state.decisions[-1].by
        names = await self._approvals.names([approver])
        data = FixTriedData(
            fix_id=row.fix_id,
            approval_id=state.request.id,
            approved_by=approver,
            approved_by_name=_name_shown(names.get(approver), approver),
            pressed_by=row.testing_by or row.asked_by,
            result=result,
            test_run_id=row.test_run_id,
        )
        refused = await self._log.note_fix_outcome(row.run_id, data)
        if refused is not None:
            log.warning("fix %s: the log took no test run (%s)", row.fix_id, refused.why)

    # The worker

    async def reconcile(self, use_case_id: str) -> None:
        """Settles every fix of the workflow that hasn't ended: drops a stored version nobody
        proposed once its fix ended, opens an approval a proposal never got, and drops a fix
        that was declined, expired or went stale."""
        async with self._db.connection("builder") as conn:
            rows = await _rows_of(conn, use_case_id)
        for row in rows:
            await self._settle(row)

    async def work_once(self) -> None:
        """Settles each fix still open, and turns a fix back on once its test run passed."""
        async with self._db.connection("builder") as conn:
            ids = [
                str(r["fix_id"])
                for r in await (
                    await conn.execute(
                        "SELECT fix_id FROM builder.fixes WHERE dropped_at IS NULL"
                        " AND turned_on_at IS NULL AND test_failed_at IS NULL"
                        " AND (stored_at IS NOT NULL OR proposed_at IS NOT NULL)"
                        " ORDER BY started_at"
                    )
                ).fetchall()
            ]
        for fix_id in ids:
            try:
                await self._work_on(fix_id)
            except Exception:
                log.exception("fix %s: the worker failed", fix_id)

    async def work_forever(self, stop: asyncio.Event, every: timedelta = WORK_EVERY) -> None:
        while not stop.is_set():
            await self.work_once()
            self._wake.clear()
            waits = [asyncio.ensure_future(stop.wait()), asyncio.ensure_future(self._wake.wait())]
            await asyncio.wait(
                waits, timeout=every.total_seconds(), return_when=asyncio.FIRST_COMPLETED
            )
            for waiting in waits:
                waiting.cancel()

    async def _work_on(self, fix_id: str) -> None:
        row = await self._settled(fix_id)
        if row is None or row.test_run_id is None or row.turned_on_at is not None:
            return
        if row.test_failed_at is not None or row.dropped_at is not None:
            return
        outcome = await self._tries.tried_outcome(row.test_run_id)
        if outcome is None:
            return
        if outcome == "failed":
            await self._mark(fix_id, "test_failed_at = %(now)s")
            await self._note_tried(row, "test_failed")
            log.info("fix %s: its test run didn't pass, so it stays off", fix_id)
            return
        assert row.document is not None and row.test_draft is not None
        put = await self._tries.put_live(
            row.use_case_id,
            FixTrying(row.test_run_id, row.test_draft),
            row.document,
            row.testing_by or row.asked_by,
            await self._parties(row),
            row.stopped_version,
        )
        if put == STALE:
            await self._drop(fix_id, "stale")
            await self._note_tried(row, "not_put_live")
            return
        if isinstance(put, str):
            async with self._db.transaction("builder") as uow:
                await uow.conn.execute(
                    "UPDATE builder.fixes SET test_failed_at = %s, turn_on_problem = %s"
                    " WHERE fix_id = %s",
                    (uow.now, put, fix_id),
                )
            await self._note_tried(row, "not_put_live")
            return
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.fixes SET turned_on_at = %s, stays_paused = %s WHERE fix_id = %s",
                (uow.now, put.paused, fix_id),
            )
        await self._note_tried(row, "kept_paused" if put.paused else "turned_on")
        log.info("fix %s: its test run passed, and it is the version in use", fix_id)

    # Inside

    async def _row(self, fix_id: str) -> FixRow | None:
        async with self._db.connection("builder") as conn:
            return await _row(conn, fix_id)

    async def _mark(self, fix_id: str, assignments: LiteralString) -> None:
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                f"UPDATE builder.fixes SET {assignments} WHERE fix_id = %(fix_id)s",
                {"now": uow.now, "fix_id": fix_id},
            )

    async def _drop(self, fix_id: str, why: str) -> None:
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.fixes SET dropped_at = %s, dropped_why = %s"
                " WHERE fix_id = %s AND dropped_at IS NULL",
                (uow.now, why, fix_id),
            )
        log.info("fix %s: dropped (%s)", fix_id, why)

    async def _settled(self, fix_id: str) -> FixRow | None:
        row = await self._row(fix_id)
        return None if row is None else await self._settle(row)

    async def _settle(self, row: FixRow) -> FixRow:
        """The fix as it stands now, with what its approval and the workflow say."""
        now = self._db.clock()
        if row.dropped_at is not None or row.turned_on_at is not None:
            return row
        if row.test_failed_at is not None:
            return row
        if row.stored_at is not None and row.proposed_at is None:
            if fix_state(row, now) == "handed_back":
                await self._drop(row.fix_id, "never_proposed")
            return await self._reread(row)
        if row.proposed_at is not None and row.approval_id is None:
            await self._send(row)
            row = await self._reread(row)
        if row.approval_id is None:
            return row
        if (
            row.testing_at is not None
            and row.test_run_id is None
            and now - row.testing_at > (TRY_LEASE)
        ):
            # A press cut off before its test run began, as by a restart: free it.
            await self._mark(row.fix_id, "testing_at = NULL, testing_by = NULL")
            row = await self._reread(row)
        approval = await self._approvals.get(ApprovalId(row.approval_id or ""))
        status = None if approval is None else approval.status
        if isinstance(status, Declined):
            await self._drop(row.fix_id, "declined")
            await self._note_decision(row)
        elif isinstance(status, Closed):
            await self._drop(row.fix_id, "expired" if status.ended is Ended.EXPIRED else "stale")
        elif row.testing_at is None and await self._stale(row):
            await self._approvals.replace_waiting(row.fix_id)
            await self._drop(row.fix_id, "stale")
        elif isinstance(status, Approved) and row.approved_at is None:
            await self._mark(row.fix_id, "approved_at = %(now)s")
            await self._note_decision(row)
        return await self._reread(row)

    async def _reread(self, row: FixRow) -> FixRow:
        again = await self._row(row.fix_id)
        assert again is not None
        return again

    async def _stale(self, row: FixRow) -> bool:
        """A new version of the workflow came since the fix was asked for, or it's gone."""
        async with self._db.connection("builder") as conn:
            workflow = await (
                await conn.execute(
                    "SELECT current_version, deleted_at FROM builder.use_cases"
                    " WHERE use_case_id = %s",
                    (row.use_case_id,),
                )
            ).fetchone()
        return (
            workflow is None
            or workflow["deleted_at"] is not None
            or workflow["current_version"] != row.stopped_version
        )

    async def _send(self, row: FixRow) -> None:
        """The stored version's set-up approval. Sending it again while it waits answers the
        same request, so a proposal the log took twice opens one."""
        assert row.version is not None and row.digest is not None
        request = await self._approvals.send(
            SetUpAsk(
                drafted_id=row.fix_id,
                revision=row.version,
                digest=Digest(row.digest),
                name=FIX_NAME.format(name=row.name),
                in_short=IN_SHORT,
                parties=await self._parties(row),
                sent_by=row.answered_by or row.asked_by,
            )
        )
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.fixes SET approval_id = %s WHERE fix_id = %s",
                (request.id, row.fix_id),
            )

    async def _parties(self, row: FixRow) -> frozenset[UserId]:
        """The person who asked, the person who answered, and every author and the publisher
        of the stopped version: none of them may approve the fix."""
        async with self._db.connection("builder") as conn:
            version = await (
                await conn.execute(
                    "SELECT also, published_by FROM builder.use_case_versions"
                    " WHERE use_case_id = %s AND version = %s",
                    (row.use_case_id, row.stopped_version),
                )
            ).fetchone()
        authors: set[UserId] = {row.asked_by}
        if row.answered_by is not None:
            authors.add(row.answered_by)
        if version is not None:
            authors |= {a.by for a in authors_from(version["also"]) if a.by is not None}
            if version["published_by"] is not None:
                authors.add(UserId(version["published_by"]))
        return frozenset(authors)

    async def _laid(self, row: FixRow, set_up: SetUpPlan) -> FixLaid | None:
        assert row.plan is not None and row.document is not None
        return await self._drafted.fix_laid(
            row.drafted_id, row.plan, await self._sources(row, set_up), row.document
        )

    async def _sources(self, row: FixRow, set_up: SetUpPlan) -> dict[str, Source]:
        if row.made_by != "answer" or row.plan is None or row.answered_by is None:
            return dict(set_up.sources)
        given = {s.id: s for s in row.plan.settings}
        changed = {
            k: Source(given[k].value or "", "typed", row.answered_by)
            for k in given
            if k in set_up.sources and set_up.sources[k].value != given[k].value
        }
        return {**set_up.sources, **changed}

    async def _held(self, row: FixRow, laid: FixLaid) -> str | None:
        state = fix_state(row, self._db.clock())
        if state in ("declined", "dropped"):
            return said(row, state)
        if laid.report.flags:
            return FLAGGED
        if laid.changes_access:
            return ACCESS
        return None

    async def _evidence(self, row: FixRow, set_up: SetUpPlan, laid: FixLaid) -> FixEvidenceView:
        assert row.plan is not None
        drafter = row.made_by == "fix_drafter"
        cause = row.cause
        part = list(cause.failed_part) if cause is not None else list(row.stopped_at)
        changed = changed_blocks(set_up.plan, row.plan)
        results = row.simulated.get(plan_key(row.plan), {}) if drafter else {}
        checks = [("inside_the_failed_part", changed <= set(part))]
        if drafter:
            checks.append(("every_scenario_passed", proven(results)))
        checks.append(("safety_check", laid.grade == "safe"))
        if drafter:
            checks.append(("settings_unchanged", settings_kept(set_up.plan, row.plan)))
        names = await self._approvals.names(
            [row.asked_by, *([row.answered_by] if row.answered_by else [])]
        )
        return FixEvidenceView(
            fix_id=row.fix_id,
            run_id=row.run_id,
            use_case_id=row.use_case_id,
            asked_by=names.get(row.asked_by, row.asked_by_name),
            made_by="fix_drafter" if drafter else "person",
            answered_by=None if row.answered_by is None else names.get(row.answered_by),
            cause=self._cause_words(row),
            failed_part=part,
            changes=changes_between(set_up.plan, row.plan),
            read_list=_read_list(set_up.plan, row.plan),
            scenarios=[
                FixScenarioView(
                    name=name,
                    kind=r.get("kind"),
                    verdict=r.get("verdict", "not_tried"),
                    step=r.get("step"),
                    why=r.get("why"),
                )
                for name, r in results.items()
            ],
            checks=[
                FixCheckView.model_validate(
                    {"check": check, "passed": passed, "words": CHECK_WORDS[check]}
                )
                for check, passed in checks
            ],
        )

    def _cause_words(self, row: FixRow) -> str | None:
        """The cause in code's words: the confirmed cause, else the rule table's."""
        cause = row.cause
        if cause is not None:
            kind = stop_kind(cause.failure_kind, row.stop.message)
            return cause_words(cause.failed_part, cause.system, kind, cause.detail)
        stopped = StopData.model_validate(row.stop.model_dump())
        return explain_failure(stopped).likely_cause

    async def _reworded(self, report: WorkflowReport) -> str | None:
        """The AI's rewording of code's in-short, which passed every check: help, never the
        check. None without the model, or when anything goes wrong."""
        asked = to_smooth(report)
        if self._wordings is None or isinstance(asked, TooLongToSmooth):
            return None
        answer = await self._wordings.reword(asked)
        return answer.text if isinstance(answer, ExplainReworded) else None

    async def _question(self, row: FixRow, set_up: SetUpPlan) -> SettingNow | None:
        """The one place a handed-back fix asks for: one only a person fills, in the blocks the
        cause named, else where the run stopped."""
        if fix_state(row, self._db.clock()) != "handed_back" or row.stored_at is not None:
            return None
        part = await self._failed_part(row)
        settings = settings_of(set_up.plan, set_up.sources)
        for planned in set_up.plan.settings:
            if planned.kind in ASKED_KINDS and any(p.block in part for p in planned.fills):
                return next(s for s in settings if s.id == planned.id)
        return None

    async def _failed_part(self, row: FixRow) -> set[str]:
        confirmed = [
            e.data.blocks
            for e in await self._log.read_after(row.run_id, 0)
            if isinstance(e.data, FixHandoffData)
            and e.data.fix_id == row.fix_id
            and e.data.to == "troubleshooter"
            and e.data.found == "confirmed"
        ]
        return set(confirmed[-1]) if confirmed else set(row.stopped_at)

    async def _viewed(self, fix_id: str) -> FixView:
        row = await self._settled(fix_id)
        assert row is not None
        return await self._view_of(row)

    async def _view_of(self, row: FixRow) -> FixView:
        state = fix_state(row, self._db.clock())
        question = None
        if state == "handed_back":
            set_up = await self._drafted.set_up_plan(row.use_case_id)
            asked = None if set_up is None else await self._question(row, set_up)
            if asked is not None:
                shown = asking(asked, await self._drafted.drafter_facts())
                question = FixQuestionView(
                    setting=asked.id,
                    key=shown.key,
                    words=shown.words,
                    choices=[FixChoiceView(value=c.value, label=c.label) for c in shown.choices],
                    typed=shown.typed,
                    waits=shown.waits,
                )
        return FixView(
            fix_id=row.fix_id,
            run_id=row.run_id,
            use_case_id=row.use_case_id,
            name=row.name,
            state=state,
            said=said(row, state),
            asked_by=row.asked_by,
            asked_by_name=row.asked_by_name,
            ends_by=row.ends_by,
            approval_id=row.approval_id,
            question=question,
            can_turn_back_on=state == "approved",
        )


def named_digest(digest: str) -> str:
    """A digest as the fix's events name it: the activity log's contract prefixes sha256."""
    return f"sha256:{digest}"


def _shown_name(person: Principal) -> str:
    """The name the log shows for who asked, or their id when the name can't be shown."""
    return _name_shown(person.display, person.user_id)


def _name_shown(name: str | None, person: UserId) -> str:
    """A person's name as the log shows it, or their id when the name can't be shown."""
    shown = (name or person).strip()[:80]
    try:
        FixStartedData(fix_id="fix_0", asked_by=person, asked_by_name=shown, ends_by=_SOME_TIME)
    except ValidationError:
        return person[:80]
    return shown


_SOME_TIME: Final = datetime.fromisoformat("2026-01-01T00:00:00+00:00")

_COLUMNS: Final = (
    "fix_id, run_id, use_case_id, drafted_id, name, stopped_version, stopped_at, stop,"
    " asked_by, asked_by_name, started_at, ends_by, plan, document, digest, version, cause,"
    " made_by, answered_by, stored_at, proposed_at, approval_id, handed_back_at, approved_at,"
    " dropped_at, dropped_why, simulated, test_run_id, test_draft, testing_by, testing_at,"
    " turned_on_at, test_failed_at, turn_on_problem, stays_paused"
)


async def _row(conn: Connection, fix_id: str, lock: bool = False) -> FixRow | None:
    query = f"SELECT {_COLUMNS} FROM builder.fixes WHERE fix_id = %s"
    query += " FOR UPDATE" if lock else ""
    found = await (await conn.execute(query, (fix_id,))).fetchone()
    return None if found is None else _from(found)


async def _rows_of(conn: Connection, use_case_id: str) -> list[FixRow]:
    query = f"SELECT {_COLUMNS} FROM builder.fixes WHERE use_case_id = %s ORDER BY started_at"
    return [_from(r) for r in await (await conn.execute(query, (use_case_id,))).fetchall()]


def _user(value: object) -> UserId | None:
    return None if value is None else UserId(str(value))


def _from(r: Mapping[str, Any]) -> FixRow:
    return FixRow(
        fix_id=str(r["fix_id"]),
        run_id=RunId(r["run_id"]),
        use_case_id=str(r["use_case_id"]),
        drafted_id=str(r["drafted_id"]),
        name=str(r["name"]),
        stopped_version=int(r["stopped_version"]),
        stopped_at=tuple(str(b) for b in r["stopped_at"]),
        stop=StoppedRun.model_validate(r["stop"]),
        asked_by=UserId(r["asked_by"]),
        asked_by_name=str(r["asked_by_name"]),
        started_at=r["started_at"],
        ends_by=r["ends_by"],
        plan=None if r["plan"] is None else WorkflowPlan.model_validate(r["plan"]),
        document=None if r["document"] is None else cast(dict[str, Any], r["document"]),
        digest=r["digest"],
        version=r["version"],
        cause=None if r["cause"] is None else CauseFound.model_validate(r["cause"]),
        made_by=r["made_by"],
        answered_by=_user(r["answered_by"]),
        stored_at=r["stored_at"],
        proposed_at=r["proposed_at"],
        approval_id=r["approval_id"],
        handed_back_at=r["handed_back_at"],
        approved_at=r["approved_at"],
        dropped_at=r["dropped_at"],
        dropped_why=r["dropped_why"],
        simulated=cast(dict[str, dict[str, dict[str, Any]]], r["simulated"] or {}),
        test_run_id=r["test_run_id"],
        test_draft=r["test_draft"],
        testing_by=_user(r["testing_by"]),
        testing_at=r["testing_at"],
        turned_on_at=r["turned_on_at"],
        test_failed_at=r["test_failed_at"],
        turn_on_problem=r["turn_on_problem"],
        stays_paused=bool(r["stays_paused"]),
    )
