import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

import httpx

from platform_api.builder.card_store import CardLibrary, NoSuchCard, PinnedAgent, StarterCard
from platform_api.builder.cards import (
    LIBRARY_LIMIT,
    card_spec,
    check_card,
    check_values,
    plan_for_cards,
    tool_list,
)
from platform_api.builder.drafts import Drafts, TooManyDrafts
from platform_api.builder.in_n8n import put_back, write_in_n8n
from platform_api.builder.last_run import RunHistory, last_run_view
from platform_api.builder.layout import REPO_INPUT, LayoutPlan, PlannedAgent, lay_out
from platform_api.builder.lifecycle import (
    AlreadyDeleted,
    Deleted,
    Draft,
    Lifecycle,
    On,
    Paused,
    TooLate,
    delete,
    is_on,
    lifecycle_of,
    pause,
    restore,
    resume,
    to_columns,
    turn_on,
)
from platform_api.builder.models import (
    BuildLineView,
    CardChecked,
    CardDefinition,
    CardList,
    CardRefused,
    CardView,
    CreateAgentUseCase,
    DraftIn,
    DraftList,
    DraftView,
    LastRunView,
    N8nHolderView,
    PlanOut,
    RepublishIn,
    SuggestOut,
    SweepOut,
    ToolList,
    UndoIn,
    UseCaseAgentView,
    UseCaseCreated,
    UseCaseDeleted,
    UseCaseList,
    UseCaseSchedule,
    UseCaseScheduleIn,
    UseCaseState,
    UseCaseView,
    VersionList,
    Via,
)
from platform_api.builder.moves import NOT_MOVED_YET, Moves
from platform_api.builder.n8n_draft import (
    ADDING,
    SAVED,
    Checked,
    DraftRefused,
    N8nNotReady,
    NotSafe,
    blocks_of,
    check_draft,
    read_only_steps,
)
from platform_api.builder.n8n_facts import BuilderWorkflowFacts, MadeKeys, ReleaseReader
from platform_api.builder.n8n_holds import HeldInN8n, Holding
from platform_api.builder.planner import ChangedInN8nReply
from platform_api.builder.planning import (
    CardPlanner,
    NoModelConnected,
    NoPlanner,
    RuntimeNotAnswering,
    plan,
)
from platform_api.builder.sweep import N8nAccounts, NoN8nAccounts, OpenRequests, VersionsSweep
from platform_api.builder.templates import (
    AGENT_CARDS,
    SOFTWARE_WATCHLIST,
    TEMPLATES,
    suggest_template,
)
from platform_api.builder.versions import (
    AlreadyUndone,
    ChangedSince,
    DeletedInN8n,
    Held,
    InUseChanged,
    Made,
    NoSuchVersion,
    NotAScheduleChange,
    NotSafeToPublish,
    Publication,
    Publish,
    ScheduleChange,
    Undo,
    Version,
    add_version,
    authors_of,
    changes_between,
    publish,
    schedule_of,
    undo,
    version_view,
    versions_of,
)
from platform_api.builder.views import template_view
from platform_api.builder.watchlist import Watchlist
from platform_api.db import Connection, Database, UnitOfWork, hold_workflow, json
from platform_api.orchestration import (
    GITHUB_RELEASES,
    TYPE_OF,
    CardRun,
    CardsTask,
    ChangedInN8n,
    Expected,
    Grade,
    Graded,
    N8nDrafts,
    N8nError,
    N8nTarget,
    OpenRuns,
    RunSpec,
    RunStarted,
    RunStarter,
    SavedDraft,
    SavedSchedule,
    Schedule,
    ScheduleBook,
    Task,
    Unreadable,
    WriteEntry,
    Written,
    add_yes,
    card_bindings,
    cards_policy,
    grade,
    next_run,
    read_flow,
    tools_used,
    unchecked,
    write_tools_used,
)
from platform_api.shared import TEAM_TIME_ZONE, Principal, UseCaseId, UserId, new_id

log = logging.getLogger(__name__)

_CURRENT_VERSION = """
    SELECT u.use_case_id, u.owner, u.paused_at, u.paused_by, u.deleted_at, u.deleted_by,
           u.draft, u.left_out, u.engine, u.n8n_workflow_id, u.deleted_in_n8n_at,
           u.move_refused, u.made_in_n8n_by, u.n8n_key_finding, u.held_by, u.held_since,
           v.version,
           v.template, v.name, v.instruction, v.params, v.created_at, v.document,
           v.n8n_version_id, v.grade, v.findings
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
"""

_USE_CASE_ROW = (
    "SELECT current_version, paused_at, paused_by, deleted_at, deleted_by, draft, engine,"
    " n8n_workflow_id, n8n_draft_id, deleted_in_n8n_at FROM builder.use_cases"
    " WHERE use_case_id = %s"
)
_IN_N8N = (
    "SELECT name, document, n8n_version_id FROM builder.use_case_versions"
    " WHERE use_case_id = %s AND version = %s"
)
"""Read once the use case's row is locked. Locking it joined to its version would drop the row
when a save waited on the lock had moved the current version on."""


def _schedule_view(
    row: Mapping[str, Any], saved: SavedSchedule | None, team_zone: str
) -> UseCaseSchedule | None:
    """An own workflow runs when the Schedule Trigger of the version in use says, whatever was
    saved in the Portal: a version published in n8n may have added, changed or taken out its
    schedule. So its day, time and zone are read from that version alone, as its next run is. A
    schedule saved in the Portal names its owner."""
    if _own(row) and row["document"] is not None:
        schedule = schedule_of(row["document"], team_zone)
    else:
        schedule = None if saved is None else saved.schedule
    if schedule is None:
        return None
    return UseCaseSchedule(
        day=schedule.day,
        at=schedule.at,
        time_zone=schedule.time_zone,
        owner_name=None if saved is None else saved.owner_name,
        held=None if saved is None else saved.held,
        held_words=None if saved is None else saved.held_words,
    )


def _own(row: Mapping[str, Any]) -> bool:
    """Carried by an n8n workflow of its own, not the shared run workflow (ENGINE-PLAN 2.6)."""
    return row["engine"] == "own" and row["n8n_workflow_id"] is not None


def _start_webhook(document: Mapping[str, Any] | None) -> str | None:
    """Where Run now is sent: Start from the Portal's webhookId, in a document the checker
    graded before it was stored."""
    for node in cast(list[dict[str, Any]], (document or {}).get("nodes", [])):
        if node.get("type") == TYPE_OF["start"] and not node.get("disabled"):
            hook = node.get("webhookId")
            return hook if isinstance(hook, str) else None
    return None


def _no_start(row: Mapping[str, Any]) -> bool:
    """An own workflow whose version in use has no Start from the Portal, which Run now and a
    test run start. One made in n8n before Set up added it, or one it was taken out of there."""
    return _own(row) and row["document"] is not None and _start_webhook(row["document"]) is None


def _target(row: Mapping[str, Any]) -> N8nTarget | None:
    if not _own(row):
        return None
    return N8nTarget(row["n8n_workflow_id"], _start_webhook(row["document"]))


def _next_run_at(row: Mapping[str, Any], now: datetime, team_zone: str) -> datetime | None:
    """An own workflow runs when n8n's Schedule Trigger fires, to the second n8n adds to it
    (ENGINE-PLAN 2.4). One still on the shared run workflow starts no scheduled run until it
    moves (E10)."""
    if not _own(row):
        return None
    document = row["document"]
    if document is None or row["deleted_in_n8n_at"] is not None:
        return None
    return next_run(document, row["n8n_workflow_id"], now, team_zone)


def _grade(row: Mapping[str, Any]) -> Grade | None:
    """A key the credential sweep removed while someone held the workflow needs a fix too, until
    the hold ends (ENGINE-PLAN E17)."""
    if not _own(row):
        return None
    return "needs_a_fix" if row["n8n_key_finding"] else row["grade"]


def _state(state: Lifecycle) -> UseCaseState:
    """A deleted workflow is never shown, so it has no word of its own."""
    match state:
        case Draft():
            return "draft"
        case On():
            return "on"
        case Paused() | Deleted():
            return "paused"


def _view(
    row: Mapping[str, Any],
    agents: Sequence[PinnedAgent],
    schedule: SavedSchedule | None,
    last_run: LastRunView | None,
    now: datetime,
    team_zone: str,
    moving: bool = False,
    holder: N8nHolderView | None = None,
) -> UseCaseView:
    template = TEMPLATES[row["template"]]
    state = _state(lifecycle_of(row))
    held = schedule is not None and schedule.held is not None
    plan = (
        plan_for_cards([a.card for a in agents]) or read_only_steps(row["document"])
        if template.key == AGENT_CARDS.key
        else template_view(template).blocks
    )
    return UseCaseView(
        use_case_id=row["use_case_id"],
        version=row["version"],
        template=row["template"],
        name=row["name"],
        instruction=row["instruction"],
        params=row["params"],
        owner=UserId(row["owner"]),
        created_at=row["created_at"],
        state=state,
        next_run_at=_next_run_at(row, now, team_zone) if state == "on" and not held else None,
        schedule=_schedule_view(row, schedule, team_zone),
        plan=plan,
        agents=[
            UseCaseAgentView(
                card_id=a.card.card_id,
                card_version=a.card.version,
                name=a.card.name,
                values=dict(a.values),
            )
            for a in agents
        ],
        last_run=last_run,
        left_out=list(row["left_out"]),
        blocks=[] if row["document"] is None else blocks_of(row["document"]),
        grade=_grade(row),
        findings=[
            *(row["findings"] or []),
            *([row["n8n_key_finding"]] if _own(row) and row["n8n_key_finding"] else []),
        ],
        deleted_in_n8n_at=row["deleted_in_n8n_at"],
        moving_to_n8n=moving,
        move_refused=None if _own(row) else row["move_refused"],
        start_refused=NO_START if _no_start(row) else None,
        made_in_n8n_by=row["made_in_n8n_by"],
        held_in_n8n=holder,
    )


@dataclass(frozen=True)
class NothingToCheck:
    """The watchlist has no software, so a check would have nothing to do."""


@dataclass(frozen=True)
class NoModelToRun:
    """An agent use case needs an AI model, and none is connected."""


@dataclass(frozen=True)
class AgentUseCaseRefused:
    """What is wrong with a new agent use case, as (place in the body, message)."""

    errors: tuple[tuple[tuple[str | int, ...], str], ...]


@dataclass(frozen=True)
class InN8n:
    """The draft saved in n8n, and what happened while it was laid out."""

    saved: SavedDraft
    graded: Graded
    log: tuple[BuildLineView, ...]


@dataclass(frozen=True)
class Relaid:
    """A version as n8n holds it after the platform laid it out again."""

    version_id: str
    document: dict[str, Any]
    grade: Grade


type InN8nRefused = N8nNotReady | DraftRefused | ChangedInN8n | HeldInN8n
"""Why a change to an own workflow was not made: n8n did not take it, the checker refused the
layout, someone changed the workflow in n8n since the platform stored it, or someone holds it in
n8n now (D15)."""

type Republished = (
    UseCaseView | NoSuchVersion | InUseChanged | NotSafeToPublish | DeletedInN8n | InN8nRefused
)
"""What a roll back or the yes put back did: the workflow as it is now, or why nothing changed."""


@dataclass(frozen=True)
class CardsRefused:
    refused: CardRefused


@dataclass(frozen=True)
class UseCasePaused:
    pass


@dataclass(frozen=True)
class NotOnYet:
    """A draft runs by hand only as a test run."""


@dataclass(frozen=True)
class NoTestRun:
    """A test run runs the draft in the platform's n8n project, where n8n lets it use every key
    there is. So none starts while the draft is held in someone's space, or has a block n8n
    would run unchecked. The words say why."""

    words: str


NO_START = (
    "It has no Start from the Portal block, so the Portal can't start it. Add the block in n8n."
)
UNCHECKED_TEST = (
    "The draft in n8n has a block the platform can't check: {found} Fix it in n8n, then test it."
)
UNREAD_TEST = "n8n did not show the draft, so no test run started. Try again in a minute."
NOT_SHOWN = "n8n did not show this version, so it stayed off. Try again in a minute."


@dataclass(frozen=True)
class NoStart:
    """Neither Run now nor a test run can start it: it has no Start from the Portal block."""


@dataclass(frozen=True)
class NotMovedYet:
    """It is still on the shared run workflow, whose blocks are off (E11), so a run could only
    fail. The words are what its page says."""

    words: str


@dataclass(frozen=True)
class WatchlistStays:
    pass


@dataclass(frozen=True)
class ScheduleOnSoftwarePage:
    pass


@dataclass(frozen=True)
class ScheduleInN8n:
    """A workflow made in n8n has no plan the Planner could lay it out from again, so when it
    runs is changed in n8n."""


type Moved = Lifecycle | AlreadyDeleted | TooLate | WatchlistStays


@dataclass(frozen=True)
class Recorded:
    """A pause or a resume, kept with who made it and from where, so the record outlives the
    state it changed (AGENTS.md: every agent action is logged with who asked for it)."""

    move: Literal["pause", "resume"]
    by: UserId
    via: Via


async def _record(uow: UnitOfWork, use_case_id: str, recorded: Recorded) -> None:
    await uow.conn.execute(
        "INSERT INTO builder.use_case_moves (use_case_id, move, moved_by, via, moved_at)"
        " VALUES (%s, %s, %s, %s, %s)",
        (use_case_id, recorded.move, recorded.by, recorded.via, uow.now),
    )
    log.info("%s %sd %s via %s", recorded.by, recorded.move, use_case_id, recorded.via)


type Move = Callable[[Lifecycle, str, datetime], Moved]


def _planned(card: CardView, values: Mapping[str, str]) -> PlannedAgent:
    spec = card_spec(card)
    return PlannedAgent(
        card.card_id,
        card.name,
        tuple((item.name, values[item.name]) for item in spec.inputs if item.name in values),
        bool(write_tools_used(tools_used(spec))),
    )


NOT_TAKEN = "n8n did not take the change. Nothing changed. Try again."
DELETED_IN_N8N = (
    "This workflow was deleted in n8n, so it can't run again. Its runs and versions are kept."
)
CHANGED_IN_N8N_SINCE = timedelta(days=1)
"""How long Home lists a version published in n8n."""


@dataclass(frozen=True)
class InUse:
    held: Held
    draft: str
    """n8n's draft after it."""


class Builder:
    def __init__(
        self,
        db: Database,
        runs: RunStarter,
        watchlist: Watchlist,
        public_base_url: str,
        planner: CardPlanner | None = None,
        schedules: ScheduleBook | None = None,
        history: RunHistory | None = None,
        n8n: N8nDrafts | None = None,
        releases: ReleaseReader | None = None,
        writes: Sequence[WriteEntry] = (),
        requests: OpenRequests | None = None,
        accounts: N8nAccounts | None = None,
        open_runs: OpenRuns | None = None,
        holding: Holding | None = None,
        time_zone: ZoneInfo = TEAM_TIME_ZONE,
        keys: MadeKeys | None = None,
    ) -> None:
        self._db = db
        self._zone = time_zone.key
        """The team time zone: a new schedule's, and the one every workflow runs on."""
        self._runs = runs
        self._watchlist = watchlist
        self._cards = CardLibrary(db)
        self._schedules = schedules or ScheduleBook(db)
        self._drafts = Drafts(db)
        self._planner = planner or NoPlanner()
        self._history = history
        self._n8n = n8n
        self.public_base_url = public_base_url
        self.facts = BuilderWorkflowFacts(db, self, releases, writes, keys)
        """What node calls ask of the builder, and what a draft is graded against."""
        self._requests = requests
        self.holding = holding
        """Open in n8n and Take back, for a platform that gives staff n8n accounts."""
        self.sweep = (
            None
            if n8n is None
            else VersionsSweep(
                db, n8n, self.facts, accounts or NoN8nAccounts(), requests, self._zone
            )
        )
        """The versions sweep, for a platform that lays workflows out in n8n."""
        self._open_runs = open_runs
        self.moves = (
            None
            if n8n is None or open_runs is None
            else Moves(
                db,
                n8n,
                open_runs,
                self._schedules,
                self._laid_out_again,
                lambda: self.facts.known({}),
                self._zone,
                watchlist,
            )
        )
        """The moves off the shared run workflow, and Restore to n8n (ENGINE-PLAN 2.6, E10)."""

    async def list_use_cases(self, viewer: Principal | None = None) -> UseCaseList:
        """Team-wide by design: one team, two roles, and Approvers need the context.
        Per-team scoping comes with Entra ID, if more teams join."""
        async with self._db.connection("builder") as conn:
            cursor = await conn.execute(
                _CURRENT_VERSION
                + " WHERE u.deleted_at IS NULL ORDER BY u.created_at DESC, u.use_case_id DESC"
            )
            rows = await cursor.fetchall()
        schedules = {saved.use_case_id: saved for saved in await self._schedules.all()}
        return UseCaseList(use_cases=await self._views(rows, schedules, viewer))

    async def get_use_case(
        self, use_case_id: str, viewer: Principal | None = None
    ) -> UseCaseView | None:
        """None for a deleted use case too: it has left the list until it is restored."""
        async with self._db.connection("builder") as conn:
            cursor = await conn.execute(
                _CURRENT_VERSION + " WHERE u.use_case_id = %s AND u.deleted_at IS NULL",
                (use_case_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        saved = await self._schedules.get(UseCaseId(use_case_id))
        schedules = {} if saved is None else {saved.use_case_id: saved}
        return (await self._views([row], schedules, viewer))[0]

    async def _views(
        self,
        rows: Sequence[Mapping[str, Any]],
        schedules: Mapping[UseCaseId, SavedSchedule],
        viewer: Principal | None,
    ) -> list[UseCaseView]:
        agent_cases = [
            (row["use_case_id"], row["version"])
            for row in rows
            if row["template"] == AGENT_CARDS.key
        ]
        agents = await self._cards.agents_of(agent_cases)
        newest = (
            {}
            if self._history is None
            else await self._history.newest_runs(
                [UseCaseId(row["use_case_id"]) for row in rows], viewer
            )
        )
        now = self._db.clock()
        moving = await self._moving(rows)
        holders = {row["use_case_id"]: await self._holder(row) for row in rows if row["held_by"]}
        return [
            _view(
                row,
                agents.get((row["use_case_id"], row["version"]), []),
                schedules.get(row["use_case_id"]),
                last_run_view(gist) if (gist := newest.get(row["use_case_id"])) else None,
                now,
                self._zone,
                row["use_case_id"] in moving,
                holders.get(row["use_case_id"]),
            )
            for row in rows
        ]

    async def _holder(self, row: Mapping[str, Any]) -> N8nHolderView:
        by = UserId(row["held_by"])
        name = by if self.holding is None else await self.holding.name_of(by)
        return N8nHolderView(id=by, name=name, since=row["held_since"])

    async def _moving(self, rows: Sequence[Mapping[str, Any]]) -> set[str]:
        """The workflows still on the shared run workflow only because a run has not ended."""
        if self.moves is None or self._open_runs is None:
            return set()
        shared = [row["use_case_id"] for row in rows if row["engine"] == "shared_run"]
        return {
            use_case_id
            for use_case_id in shared
            if await self._open_runs.open_run(UseCaseId(use_case_id)) is not None
        }

    async def pause_use_case(
        self, use_case_id: str, principal: Principal, via: Via = "page"
    ) -> UseCaseView | N8nNotReady | NotSafe | HeldInN8n | None:
        moved = await self._move(
            use_case_id,
            lambda state, _, now: pause(state, now, principal.user_id),
            principal.user_id,
            Recorded("pause", principal.user_id, via),
        )
        return await self._after(use_case_id, principal, moved)

    async def resume_use_case(
        self, use_case_id: str, principal: Principal, via: Via = "page"
    ) -> UseCaseView | N8nNotReady | NotSafe | HeldInN8n | None:
        moved = await self._move(
            use_case_id,
            lambda state, _template, _now: resume(state),
            principal.user_id,
            Recorded("resume", principal.user_id, via),
        )
        return await self._after(use_case_id, principal, moved)

    async def turn_on_use_case(
        self, use_case_id: str, principal: Principal
    ) -> UseCaseView | N8nNotReady | NotSafe | HeldInN8n | None:
        """Publishes a draft's version 1 and turns it on. An own workflow reads On only once n8n
        has every trigger live (ENGINE-PLAN 2.5). Asking again changes nothing."""
        moved = await self._move(
            use_case_id, lambda state, _template, _now: turn_on(state), principal.user_id
        )
        return await self._after(use_case_id, principal, moved)

    async def _after(
        self,
        use_case_id: str,
        principal: Principal,
        moved: Moved | N8nNotReady | NotSafe | HeldInN8n | None,
    ) -> UseCaseView | N8nNotReady | NotSafe | HeldInN8n | None:
        match moved:
            case None | AlreadyDeleted():
                return None
            case N8nNotReady() | NotSafe() | HeldInN8n():
                return moved
            case _:
                return await self.get_use_case(use_case_id, principal)

    async def delete_use_case(
        self, use_case_id: str, principal: Principal
    ) -> UseCaseDeleted | WatchlistStays | N8nNotReady | None:
        def move(state: Lifecycle, template: str, now: datetime) -> Lifecycle | WatchlistStays:
            if template == SOFTWARE_WATCHLIST.key:
                return WatchlistStays()
            return delete(state, now, principal.user_id)

        match await self._move(use_case_id, move, principal.user_id):
            case Deleted() as deleted:
                await self._removed(use_case_id)
                return UseCaseDeleted(
                    use_case_id=use_case_id,
                    deleted_at=deleted.at,
                    restore_until=deleted.restore_until,
                )
            case WatchlistStays() | N8nNotReady() as refused:
                return refused
            case _:
                return None

    async def restore_use_case(
        self, use_case_id: str, principal: Principal
    ) -> UseCaseView | TooLate | N8nNotReady | NotSafe | None:
        moved = await self._move(
            use_case_id, lambda state, _, now: restore(state, now), principal.user_id
        )
        match moved:
            case TooLate() | N8nNotReady() | NotSafe():
                return moved
            case None:
                return None
            case _:
                return await self.get_use_case(use_case_id, principal)

    async def save_schedule(
        self, use_case_id: str, principal: Principal, body: UseCaseScheduleIn
    ) -> UseCaseView | ScheduleOnSoftwarePage | ScheduleInN8n | ChangedSince | InN8nRefused | None:
        """The same save as the watchlist's: the caller becomes the owner, which lifts a hold.
        A new schedule publishes a new version. Saving the same one again publishes none.
        Saving is not a write to Jira or Confluence, so it needs no approval. An own workflow's
        new schedule is saved in n8n first (ENGINE-PLAN 2.5). A save made from a version that
        is no longer in use changes nothing."""
        # Read the workflow before the lock, so the lock holds one connection and no more.
        view = await self.get_use_case(use_case_id, principal)
        if view is None:
            return None
        if view.template == SOFTWARE_WATCHLIST.key:
            return ScheduleOnSoftwarePage()
        if view.made_in_n8n_by is not None:
            return ScheduleInN8n()
        after = Schedule(body.day, body.at, self._zone)
        match await self._publish(
            use_case_id, principal, body.via, lambda _: Publish(after), body.expected_version
        ):
            case None:
                return None
            case (
                N8nNotReady()
                | DraftRefused()
                | ChangedInN8n()
                | ChangedSince()
                | HeldInN8n() as refused
            ):
                return refused
            case _:
                return await self.get_use_case(use_case_id, principal)

    async def list_versions(self, use_case_id: str) -> VersionList | None:
        async with self._db.connection("builder") as conn:
            row = await (await conn.execute(_USE_CASE_ROW, (use_case_id,))).fetchone()
            if row is None:
                return None
            state = lifecycle_of(row)
            if isinstance(state, Draft):
                return VersionList(versions=[])
            if not isinstance(state, On | Paused):
                return None
            versions = await versions_of(conn, use_case_id)
        running = row["current_version"]
        befores = [*versions[1:], None]
        return VersionList(
            versions=[
                version_view(version, running, before)
                for version, before in zip(versions, befores, strict=True)
            ]
        )

    async def undo_version(
        self, use_case_id: str, version: int, principal: Principal, body: UndoIn
    ) -> UseCaseView | NoSuchVersion | NotAScheduleChange | ChangedSince | InN8nRefused | None:
        """Publishes the schedule of the version before `version` again, as a new version.
        Asking again once it is undone answers the same."""
        match await self._publish(use_case_id, principal, body.via, lambda vs: undo(vs, version)):
            case None:
                return None
            case Publish() | AlreadyUndone():
                return await self.get_use_case(use_case_id, principal)
            case refused:
                return refused

    async def _publish(
        self,
        use_case_id: str,
        principal: Principal,
        via: Via,
        decide: Callable[[Sequence[Version]], Undo],
        expected: int | None = None,
    ) -> Undo | InN8nRefused | None:
        """Publishes what `decide` makes of the versions, and saves its schedule. The builder
        cannot write orchestration's schedules, so the schedule is saved in its own transaction,
        before the version's commits. A save that fails leaves no version naming it.

        If the version's commit is lost after the schedule saved, the schedule runs on with no
        version naming it until the change is made again. Whether anything changed is judged
        against the schedule the newest version recorded, so that retry publishes the missing
        version. Version 1 and the watchlist's versions record no schedule, so against them it
        is judged on the live schedule, and the first change after version 1 stays without a
        version if its commit is lost. A draft has published no version, so a change to it
        saves its schedule and publishes none.

        An own workflow is laid out again with the new schedule, checked, and written to n8n
        under the version compare before anything here: live when it is on, as a draft else.
        Each version keeps what n8n holds of it, so what runs is what was checked."""
        async with self._db.transaction("builder") as uow:
            # A delete holds this lock alone, so it waits until the schedule is stored, and a
            # delete that came first is seen here. The row lock puts changes in turn.
            await hold_workflow(uow.conn, use_case_id, alone=False)
            row = await (
                await uow.conn.execute(_USE_CASE_ROW + " FOR UPDATE", (use_case_id,))
            ).fetchone()
            if row is None:
                return None
            state = lifecycle_of(row)
            if not isinstance(state, Draft | On | Paused):
                return None
            if expected is not None and row["current_version"] != expected:
                return ChangedSince()
            draft = isinstance(state, Draft)
            versions = [] if draft else await versions_of(uow.conn, use_case_id)
            decided = decide(versions)
            if not isinstance(decided, Publish):
                return decided
            in_n8n = None
            if _own(row) and self.holding is not None:
                held = await self.holding.refused_while_held(
                    uow.conn, use_case_id, principal.user_id
                )
                if held is not None:
                    return held
            if _own(row):
                version = row["current_version"]
                current = await (await uow.conn.execute(_IN_N8N, (use_case_id, version))).fetchone()
                assert current is not None
                row = {**row, **current}
                in_n8n = await self._schedule_in_n8n(use_case_id, row, decided.after, is_on(state))
                if isinstance(in_n8n, N8nNotReady | DraftRefused | ChangedInN8n | HeldInN8n):
                    return in_n8n
            if draft and in_n8n is not None:
                await _store_in_n8n(uow, use_case_id, row["current_version"], in_n8n)
            if not draft:
                recorded = versions[0].change
                if recorded is None:
                    saved = await self._schedules.get(UseCaseId(use_case_id))
                    before = None if saved is None else saved.schedule
                else:
                    before = recorded.after
                if decided.after != before or decided.undid is not None:
                    change = ScheduleChange(
                        principal.user_id, via, before, decided.after, decided.undid
                    )
                    newest = row["current_version"]
                    await publish(uow, use_case_id, newest, change)
                    if _own(row):
                        await _carry_n8n(uow, use_case_id, newest)
                    if in_n8n is not None:
                        await _store_in_n8n(uow, use_case_id, newest + 1, in_n8n)
                        if is_on(state):
                            await _mark_published(uow, use_case_id, newest + 1, principal.user_id)
            if decided.after is None:
                await self._schedules.delete(UseCaseId(use_case_id))
            else:
                await self._schedules.save(UseCaseId(use_case_id), decided.after, principal)
        return decided

    async def rollback_version(
        self, use_case_id: str, version: int, principal: Principal, body: RepublishIn
    ) -> Republished | None:
        """Puts version `version` back in use as a new version, under the version compare
        (ENGINE-PLAN 2.5). Only a version that passes the safety check now is put back."""

        def back_to(versions: Sequence[Version]) -> tuple[Version, Held] | NoSuchVersion:
            target = next((v for v in versions if v.number == version), None)
            if target is None or target.held is None:
                return NoSuchVersion()
            return target, target.held

        return await self._republish(
            use_case_id,
            principal,
            body,
            back_to,
            lambda v: v.made is not None and v.made.back_to == version,
            lambda by: Made("rolled_back", by, body.via, version),
        )

    async def add_the_yes_back(
        self, use_case_id: str, principal: Principal, body: RepublishIn
    ) -> Republished | None:
        """Puts Ask for a yes back before each write in the version in use, and publishes that
        as a new version under the version compare."""

        def with_yes(versions: Sequence[Version]) -> tuple[Version, Held] | NoSuchVersion:
            current = versions[0]
            if current.held is None:
                return NoSuchVersion()
            added = add_yes(current.held.document, use_case_id)
            if not added.added_before:
                return current, current.held
            return current, Held(current.held.version_id, added.document, current.held.grade)

        return await self._republish(
            use_case_id,
            principal,
            body,
            with_yes,
            lambda v: v.made is not None and v.made.kind == "yes_put_back",
            lambda by: Made("yes_put_back", by, body.via),
        )

    async def _republish(
        self,
        use_case_id: str,
        principal: Principal,
        body: RepublishIn,
        pick: Callable[[Sequence[Version]], tuple[Version, Held] | NoSuchVersion],
        done_already: Callable[[Version], bool],
        made: Callable[[UserId], Made],
    ) -> Republished | None:
        """Puts a workflow in use as a new version: one n8n still holds, published as it is, or
        the one the platform kept, written over the draft. Both under the version compare, and
        only when it grades safe against what the editor's lists hold now. Its source's
        publisher is kept with it, because its runs are their work too (ADR 0026). Asked again
        once done, it answers the same."""
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, use_case_id, alone=True)
            row = await (
                await uow.conn.execute(_USE_CASE_ROW + " FOR UPDATE", (use_case_id,))
            ).fetchone()
            if row is None or not _own(row):
                return None
            state = lifecycle_of(row)
            if not isinstance(state, On | Paused):
                return None
            if row["deleted_in_n8n_at"] is not None:
                return DeletedInN8n()
            if self.holding is not None:
                held = await self.holding.refused_while_held(
                    uow.conn, use_case_id, principal.user_id
                )
                if held is not None:
                    return held
            versions = await versions_of(uow.conn, use_case_id)
            current = versions[0]
            picked = pick(versions)
            if isinstance(picked, NoSuchVersion):
                return picked
            source, held = picked
            stale = body.in_use is not None and body.in_use != current.number
            if stale and not done_already(current):
                return InUseChanged()
            if not stale and held != current.held:
                live = is_on(state)
                put = await self._put_in_use(use_case_id, row, current, source, held, live)
                if not isinstance(put, InUse):
                    return put
                await add_version(
                    uow,
                    use_case_id,
                    current.number,
                    source.number,
                    put.held,
                    made(principal.user_id),
                    Publication(principal.user_id, "portal") if live else None,
                    authors_of(source),
                    put.draft,
                )
        return await self.get_use_case(use_case_id, principal)

    async def _put_in_use(
        self,
        use_case_id: str,
        row: Mapping[str, Any],
        current: Version,
        source: Version,
        held: Held,
        live: bool,
    ) -> InUse | NotSafeToPublish | InN8nRefused:
        """In n8n, under the version compare: live when the workflow is on, else ready to publish
        when it is resumed. n8n's live version and draft must be the ones the platform saw."""
        assert self._n8n is not None and current.held is not None
        error_workflow = await self._n8n.error_workflow_id()
        graded = grade(held.document, error_workflow, self._zone, await self.facts.known({}))
        if graded.grade != "safe":
            return NotSafeToPublish(tuple(f.text for f in graded.findings))
        workflow_id = row["n8n_workflow_id"]
        in_use = current.held.version_id
        expected = Expected(row["n8n_draft_id"] or in_use, in_use if live else None)
        kept = held.version_id if held == source.held else None
        try:
            put = await self._n8n.put_back(workflow_id, expected, held.document, live, held=kept)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("n8n did not put %s in use: %s", use_case_id, error)
            if live:
                await put_back(self._n8n, workflow_id, in_use)
            return N8nNotReady(NOT_TAKEN)
        if isinstance(put, ChangedInN8n):
            return put
        return InUse(Held(put.version_id, put.document, "safe"), put.draft)

    async def _bring_back(
        self, uow: UnitOfWork, use_case_id: str, row: Mapping[str, Any]
    ) -> Mapping[str, Any] | N8nNotReady:
        """A deleted workflow was removed from n8n (D7), or deleted there, so restoring it saves
        the version in use again as a new n8n workflow, from the workflow the platform kept for
        it. n8n has it again, so it is no longer marked deleted in n8n."""
        assert self._n8n is not None
        try:
            if await self._n8n.look(row["n8n_workflow_id"]) is not None:
                return row
            saved = await self._n8n.save_draft(row["document"])
        except (N8nError, httpx.HTTPError) as error:
            log.warning("n8n did not take %s back: %s", use_case_id, error)
            return N8nNotReady(NOT_TAKEN)
        await uow.conn.execute(
            "UPDATE builder.use_cases SET n8n_workflow_id = %s, n8n_draft_id = %s,"
            " deleted_in_n8n_at = NULL WHERE use_case_id = %s",
            (saved.workflow_id, saved.version_id, use_case_id),
        )
        await uow.conn.execute(
            "UPDATE builder.use_case_versions SET n8n_version_id = %s, document = %s"
            " WHERE use_case_id = %s AND version = %s",
            (saved.version_id, json(saved.document), use_case_id, row["current_version"]),
        )
        return {
            **row,
            "n8n_workflow_id": saved.workflow_id,
            "n8n_version_id": saved.version_id,
            "document": saved.document,
            "deleted_in_n8n_at": None,
        }

    async def _removed(self, use_case_id: str) -> None:
        """After a delete (D7): the open request ends cancelled and its Approvers are told, then
        n8n archives the workflow and deletes it with its executions. Deleting again tries each
        step again. A run of a deleted workflow never asks or writes, whatever n8n does."""
        async with self._db.connection("builder") as conn:
            row = await (await conn.execute(_USE_CASE_ROW, (use_case_id,))).fetchone()
        if row is None or not _own(row):
            return
        if self._requests is not None:
            try:
                await self._requests.cancel_for_deleted(UseCaseId(use_case_id))
            except Exception:
                log.exception("could not cancel the open request of deleted %s", use_case_id)
        if self._n8n is None or row["deleted_in_n8n_at"] is not None:
            return
        try:
            await self._n8n.remove_for_good(row["n8n_workflow_id"])
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not remove deleted %s from n8n: %s", use_case_id, error)

    async def sweep_now(self, use_case_id: str | None) -> SweepOut:
        if self.sweep is None:
            return SweepOut(found=0)
        found = await self.sweep.asked(use_case_id)
        return SweepOut(found=len(found))

    async def changed_in_n8n(self, limit: int) -> list[ChangedInN8nReply]:
        """The versions published in n8n, or whose settings changed there, in the last day, newest
        first, with what each changed from the version before it. Names are the caller's to add."""
        since = self._db.clock() - CHANGED_IN_N8N_SINCE
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT v.use_case_id, v.version, v.created_at, v.published_by, v.grade,"
                    " v.findings, v.document, v.name, v.made, u.current_version,"
                    " p.document AS before FROM builder.use_case_versions v"
                    " JOIN builder.use_cases u ON u.use_case_id = v.use_case_id"
                    " LEFT JOIN builder.use_case_versions p"
                    " ON p.use_case_id = v.use_case_id AND p.version = v.version - 1"
                    " WHERE v.made IN ('published_in_n8n', 'settings_changed_in_n8n')"
                    " AND v.created_at > %s"
                    " AND u.deleted_at IS NULL"
                    " ORDER BY v.created_at DESC, v.use_case_id, v.version DESC LIMIT %s",
                    (since, limit),
                )
            ).fetchall()
        return [
            ChangedInN8nReply(
                use_case_id=row["use_case_id"],
                name=row["name"],
                version=row["version"],
                made=row["made"],
                by=None
                if row["published_by"] is None or row["made"] != "published_in_n8n"
                else UserId(row["published_by"]),
                by_name=None,
                at=row["created_at"],
                grade=row["grade"],
                changes=changes_between(row["before"], row["document"]),
                findings=list(row["findings"] or []),
                in_use=row["current_version"],
            )
            for row in rows
        ]

    async def _move(
        self, use_case_id: str, move: Move, by: UserId, recorded: Recorded | None = None
    ) -> Moved | N8nNotReady | NotSafe | HeldInN8n | None:
        """An own workflow's n8n state follows the move before it is recorded: on is published
        with every trigger live, anything else is off. The lock is held across n8n's answer, so
        moves of one workflow never cross there either."""
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, use_case_id, alone=True)
            row = await (
                await uow.conn.execute(
                    "SELECT u.paused_at, u.paused_by, u.deleted_at, u.deleted_by, u.draft,"
                    " u.engine, u.n8n_workflow_id, u.current_version, u.deleted_in_n8n_at,"
                    " u.held_by, u.n8n_stranded_at, v.template, v.n8n_version_id, v.grade,"
                    " v.document"
                    " FROM builder.use_cases u JOIN builder.use_case_versions v"
                    " ON v.use_case_id = u.use_case_id AND v.version = u.current_version"
                    " WHERE u.use_case_id = %s FOR UPDATE OF u",
                    (use_case_id,),
                )
            ).fetchone()
            if row is None:
                return None
            before = lifecycle_of(row)
            after = move(before, row["template"], uow.now)
            if isinstance(after, Draft | On | Paused | Deleted) and after != before:
                away = row["held_by"] is not None or row["n8n_stranded_at"] is not None
                if _own(row) and away and self.holding is not None:
                    if isinstance(after, Deleted):
                        # Back in the platform's project first, so a delete n8n does not finish
                        # never leaves the workflow in a member's space with no hold on record.
                        refused = await self.holding.back_in(uow, use_case_id, by)
                        if refused is not None:
                            return N8nNotReady(refused.words)
                    elif is_on(after):
                        return await self.holding.refused_while_held(uow.conn, use_case_id, by)
                if _own(row) and isinstance(before, Deleted) and not isinstance(after, Deleted):
                    back = await self._bring_back(uow, use_case_id, row)
                    if isinstance(back, N8nNotReady):
                        return back
                    row = back
                if _own(row) and is_on(after) != is_on(before):
                    if (refused := await self._follow_in_n8n(row, after)) is not None:
                        return refused
                    if is_on(after):
                        await _mark_published(uow, use_case_id, row["current_version"], by)
                columns = to_columns(after)
                await uow.conn.execute(
                    "UPDATE builder.use_cases SET paused_at = %s, paused_by = %s,"
                    " deleted_at = %s, deleted_by = %s, draft = %s WHERE use_case_id = %s",
                    (
                        columns.paused_at,
                        columns.paused_by,
                        columns.deleted_at,
                        columns.deleted_by,
                        columns.draft,
                        use_case_id,
                    ),
                )
                if recorded is not None:
                    await _record(uow, use_case_id, recorded)
        return after

    async def _schedule_in_n8n(
        self, use_case_id: str, row: Mapping[str, Any], schedule: Schedule | None, live: bool
    ) -> Relaid | InN8nRefused | None:
        """The workflow laid out again with this schedule, and saved in n8n over the version the
        platform stored. None when n8n already holds that layout."""
        laid = await self._laid_out_again(use_case_id, row, schedule)
        if not isinstance(laid, Checked):
            return laid
        if laid.document == row["document"]:
            return None
        assert self._n8n is not None
        if row["deleted_in_n8n_at"] is not None:
            return N8nNotReady(DELETED_IN_N8N)
        if row["n8n_version_id"] is None:
            return N8nNotReady("This version is not saved in n8n, so it cannot be changed there.")
        expected = row["n8n_draft_id"] or row["n8n_version_id"]
        written = await write_in_n8n(
            self._n8n, row["n8n_workflow_id"], expected, row["n8n_version_id"], laid.document, live
        )
        if not isinstance(written, Written):
            return written
        return Relaid(written.version_id, written.document, laid.graded.grade)

    async def _laid_out_again(
        self, use_case_id: str, row: Mapping[str, Any], schedule: Schedule | None
    ) -> Checked | DraftRefused | N8nNotReady:
        version = row["current_version"]
        pinned = (await self._cards.agents_of([(use_case_id, version)])).get(
            (use_case_id, version), []
        )
        chosen = [(agent.card, agent.values) for agent in pinned]
        return await self._laid_out(use_case_id, row["name"], schedule, chosen)

    async def _unchecked_in_n8n(
        self, workflow_id: str, version_id: str
    ) -> NotSafe | N8nNotReady | None:
        """The version as n8n holds it, checked again now, just before it goes live: the keys the
        platform holds may have changed since it was graded. One n8n can't show stays off."""
        assert self._n8n is not None
        try:
            version = await self._n8n.kept(workflow_id, version_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read %s before it goes live: %s", workflow_id, error)
            version = None
        if version is None:
            return N8nNotReady(NOT_SHOWN)
        return NotSafe() if unchecked(version, (await self.facts.known({})).keys) else None

    async def _follow_in_n8n(
        self, row: Mapping[str, Any], after: Lifecycle
    ) -> N8nNotReady | NotSafe | None:
        """Puts the version on live in n8n, or takes the workflow off. A delete takes it off as
        best it can: a deleted use case's runs are refused at their first call whatever n8n
        does. A publish that did not finish is taken off again, so n8n never runs what the
        records say is off."""
        workflow_id = row["n8n_workflow_id"]
        version_id = row["n8n_version_id"]
        if self._n8n is None:
            return N8nNotReady("This platform is not connected to n8n.")
        if is_on(after) and row["deleted_in_n8n_at"] is not None:
            return N8nNotReady(DELETED_IN_N8N)
        if is_on(after) and version_id is None:
            return N8nNotReady("This version is not saved in n8n. Change when it runs to save it.")
        if is_on(after) and row["grade"] != "safe":
            return NotSafe()
        if is_on(after) and (refused := await self._unchecked_in_n8n(workflow_id, version_id)):
            return refused
        try:
            if is_on(after):
                await self._n8n.go_live(workflow_id, version_id)
            else:
                await self._n8n.go_off(workflow_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("n8n did not follow the move of %s: %s", workflow_id, error)
            if isinstance(after, Deleted):
                return None
            if is_on(after):
                await self._take_off(workflow_id)
                return N8nNotReady("n8n did not turn it on in time. Nothing changed. Try again.")
            return N8nNotReady("n8n did not take it off. Nothing changed. Try again.")
        return None

    async def _take_off(self, workflow_id: str) -> None:
        assert self._n8n is not None
        try:
            await self._n8n.go_off(workflow_id)
        except (N8nError, httpx.HTTPError) as error:
            log.error("could not take %s off again in n8n: %s", workflow_id, error)

    async def save_draft(
        self, principal: Principal, draft_id: str, draft: DraftIn
    ) -> DraftView | TooManyDrafts:
        return await self._drafts.save(principal.user_id, draft_id, draft)

    async def list_drafts(self, principal: Principal) -> DraftList:
        return DraftList(drafts=await self._drafts.list(principal.user_id))

    async def delete_draft(self, principal: Principal, draft_id: str) -> bool:
        return await self._drafts.delete(principal.user_id, draft_id)

    @staticmethod
    def tools() -> ToolList:
        return tool_list()

    @staticmethod
    def check_card(card: CardDefinition) -> CardChecked:
        return check_card(card)

    async def list_cards(self) -> CardList:
        return CardList(cards=await self._cards.list())

    async def get_card(self, card_id: str) -> CardView | None:
        return await self._cards.get(card_id)

    async def create_card(
        self, principal: Principal, card: CardDefinition
    ) -> CardView | CardsRefused:
        checked = check_card(card)
        if checked.problems:
            return CardsRefused(CardRefused(problems=checked.problems))
        return await self._cards.create(principal, checked.card)

    async def update_card(
        self, principal: Principal, card_id: str, card: CardDefinition
    ) -> CardView | CardsRefused | NoSuchCard | StarterCard:
        checked = check_card(card)
        if checked.problems:
            return CardsRefused(CardRefused(problems=checked.problems))
        return await self._cards.update(principal, card_id, checked.card)

    async def plan(self, task: str) -> PlanOut | NoModelConnected | RuntimeNotAnswering:
        """The Planner's plan for a task. Nothing is saved."""
        library = (await self._cards.list())[:LIBRARY_LIMIT]
        return await plan(self._planner, library, task)

    async def create_agent_use_case(
        self, principal: Principal, body: CreateAgentUseCase
    ) -> UseCaseCreated | AgentUseCaseRefused | DraftRefused | N8nNotReady:
        """Where this platform lays workflows out in n8n, a new use case is born on its own n8n
        workflow, saved there as a draft (ENGINE-PLAN 2.5). The draft is saved before any row
        here, so a failure in n8n sets nothing up."""
        errors: list[tuple[tuple[str | int, ...], str]] = []
        chosen: list[tuple[CardView, dict[str, str]]] = []
        for index, agent in enumerate(body.agents):
            where = ("body", "agents", index)
            card = await self._cards.get(agent.card_id)
            if card is None:
                errors.append(((*where, "card_id"), "No such agent."))
                continue
            if any(card.card_id == other.card_id for other, _ in chosen):
                errors.append(((*where, "card_id"), "This agent is already in the list."))
                continue
            clean, problems = check_values(card, agent.values)
            errors.extend(((*where, "values", name), message) for name, message in problems)
            chosen.append((card, clean))
        if errors:
            return AgentUseCaseRefused(tuple(errors))
        use_case_id = new_id("uc")
        drafted = None
        if self._n8n is not None:
            drafted = await self._draft_in_n8n(self._n8n, use_case_id, body, chosen)
            if isinstance(drafted, DraftRefused | N8nNotReady):
                return drafted
        try:
            await self._insert_agent_use_case(use_case_id, principal, body, chosen, drafted)
        except Exception:
            if self._n8n is not None and drafted is not None:
                await self._n8n.remove(drafted.saved.workflow_id)
            raise
        if body.schedule is not None:
            try:
                await self._schedules.save(
                    UseCaseId(use_case_id),
                    Schedule(body.schedule.day, body.schedule.at, self._zone),
                    principal,
                )
            except Exception:
                await self.delete_use_case(use_case_id, principal)
                raise
        if drafted is None:
            return UseCaseCreated(use_case_id=use_case_id, version=1)
        if body.on:
            # Born a draft in n8n, and on only once n8n has every trigger live. When n8n does not
            # turn it on, it stays a draft and its page says so.
            await self.turn_on_use_case(use_case_id, principal)
        return UseCaseCreated(
            use_case_id=use_case_id,
            version=1,
            n8n_workflow_id=drafted.saved.workflow_id,
            grade=drafted.graded.grade,
            build_log=list(drafted.log),
            blocks=blocks_of(drafted.saved.document),
        )

    async def _draft_in_n8n(
        self,
        n8n: N8nDrafts,
        use_case_id: str,
        body: CreateAgentUseCase,
        chosen: Sequence[tuple[CardView, Mapping[str, str]]],
    ) -> InN8n | DraftRefused | N8nNotReady:
        clock = self._db.clock
        started = BuildLineView(at=clock(), kind="status", text=ADDING)
        schedule = (
            None
            if body.schedule is None
            else Schedule(body.schedule.day, body.schedule.at, self._zone)
        )
        checked = await self._laid_out(use_case_id, body.name, schedule, chosen)
        if not isinstance(checked, Checked):
            return checked
        at = clock()
        lines = [BuildLineView(at=at, kind=kind, text=text) for kind, text in checked.lines]
        try:
            saved = await n8n.save_draft(checked.document)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("n8n did not take the draft of %s: %s", use_case_id, error)
            return N8nNotReady("n8n did not take the draft. Try again in a minute.")
        done = BuildLineView(at=clock(), kind="status", text=SAVED)
        return InN8n(saved, checked.graded, (started, *lines, done))

    async def _laid_out(
        self,
        use_case_id: str,
        name: str,
        schedule: Schedule | None,
        chosen: Sequence[tuple[CardView, Mapping[str, str]]],
    ) -> Checked | DraftRefused | N8nNotReady:
        """The use case laid out as its own n8n workflow, with the yes put in and graded."""
        assert self._n8n is not None
        error_workflow = await self._n8n.error_workflow_id()
        if error_workflow is None:
            return N8nNotReady("n8n is not ready yet: its error workflow is not loaded.")
        plan = LayoutPlan(
            use_case_id,
            name,
            f"{self.public_base_url}/workflows/{use_case_id}",
            schedule,
            tuple(_planned(card, values) for card, values in chosen),
            error_workflow,
            self._zone,
        )
        repos = [values[REPO_INPUT] for _, values in chosen if REPO_INPUT in values]
        known = await self.facts.known({GITHUB_RELEASES: repos})
        checked = check_draft(lay_out(plan), use_case_id, error_workflow, self._zone, known)
        if isinstance(checked, DraftRefused):
            log.error("the safety checker refused the layout of %s: %s", use_case_id, checked)
        return checked

    async def _insert_agent_use_case(
        self,
        use_case_id: str,
        principal: Principal,
        body: CreateAgentUseCase,
        chosen: Sequence[tuple[CardView, Mapping[str, str]]],
        drafted: InN8n | None,
    ) -> None:
        engine = "shared_run" if drafted is None else "own"
        workflow_id = None if drafted is None else drafted.saved.workflow_id
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version,"
                " left_out, draft, engine, n8n_workflow_id) VALUES (%s, %s, %s, 1, %s, %s, %s, %s)",
                (
                    use_case_id,
                    principal.user_id,
                    uow.now,
                    body.left_out,
                    drafted is not None or not body.on,
                    engine,
                    workflow_id,
                ),
            )
            await uow.conn.execute(
                "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
                " instruction, params, created_at, n8n_version_id, grade, document)"
                " VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    use_case_id,
                    AGENT_CARDS.key,
                    body.name,
                    body.instruction,
                    json({}),
                    uow.now,
                    None if drafted is None else drafted.saved.version_id,
                    None if drafted is None else drafted.graded.grade,
                    None if drafted is None else json(drafted.saved.document),
                ),
            )
            for position, (card, values) in enumerate(chosen):
                await uow.conn.execute(
                    "INSERT INTO builder.use_case_cards (use_case_id, version, position,"
                    ' card_id, card_version, "values") VALUES (%s, 1, %s, %s, %s, %s)',
                    (use_case_id, position, card.card_id, card.version, json(dict(values))),
                )

    @staticmethod
    def suggest(text: str) -> SuggestOut:
        template, terms = suggest_template(text)
        return SuggestOut(
            template=None if template is None else template_view(template), matched_terms=terms
        )

    async def run_spec_for(self, use_case_id: UseCaseId) -> RunSpec | None | NothingToCheck:
        view = await self.get_use_case(use_case_id)
        return None if view is None else await self._spec_of(view)

    async def _target(self, use_case_id: str) -> N8nTarget | None:
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(_CURRENT_VERSION + " WHERE u.use_case_id = %s", (use_case_id,))
            ).fetchone()
        return None if row is None else _target(row)

    async def _spec_of(self, view: UseCaseView) -> RunSpec | NothingToCheck:
        use_case_id = UseCaseId(view.use_case_id)
        template = TEMPLATES[view.template]
        params = view.params
        task: Task
        policy = template.approval_policy
        if template.key == AGENT_CARDS.key:
            pinned = (await self._cards.agents_of([(use_case_id, view.version)])).get(
                (use_case_id, view.version), []
            )
            named = await self._named_in_n8n(use_case_id, {a.card.card_id for a in pinned})
            chosen = [*((a.card, dict(a.values)) for a in pinned), *named]
            task = CardsTask(tuple(_bound(card, values) for card, values in chosen))
            asked = max((x.approvers for card, _ in chosen for x in card.approvals), default=1)
            policy = cards_policy([card_spec(card) for card, _ in chosen], asked)
        else:
            listed = await self._watchlist.task_for(use_case_id, view.version)
            if listed is None:
                return NothingToCheck()
            task = listed
        return RunSpec(
            use_case_id=use_case_id,
            use_case_version=view.version,
            use_case_name=view.name,
            owner=view.owner,
            workflow=template.workflow,
            instruction=view.instruction,
            task=task,
            bindings=template.bindings_for(params),
            approval_policy=policy,
            n8n=await self._target(use_case_id),
        )

    async def _named_in_n8n(
        self, use_case_id: str, pinned: set[str]
    ) -> list[tuple[CardView, dict[str, str]]]:
        """The cards the Agent blocks of its own n8n workflow name beyond the pinned ones, with
        each block's values, as a workflow made or changed in n8n may hold. Each runs its newest
        version with those values, so what it may read and the Approvers it asks for count too.
        The checker graded the values against the places the platform allows."""
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(_CURRENT_VERSION + " WHERE u.use_case_id = %s", (use_case_id,))
            ).fetchone()
        if row is None or row["document"] is None:
            return []
        try:
            flow = read_flow(row["document"])
        except Unreadable:
            return []
        found: list[tuple[CardView, dict[str, str]]] = []
        for block in flow.of_kind("agent"):
            card_id = str(block.parameters.get("agent"))
            card = None if card_id in pinned else await self._cards.get(card_id)
            if card is not None:
                found.append((card, _agent_values(block.parameters)))
        return found

    async def start_run(
        self,
        use_case_id: UseCaseId,
        principal: Principal,
        idempotency_key: str,
        test: bool = False,
    ) -> (
        RunStarted
        | None
        | NothingToCheck
        | NoModelToRun
        | UseCasePaused
        | NotOnYet
        | NotMovedYet
        | NoTestRun
        | NoStart
    ):
        """A test run of a draft stops at the approval gate (ADR 0044). Whether it is a draft
        is read under the lock, so a draft turned on since runs as any test run does. A test run
        runs the n8n draft, so it starts only when nobody holds it and n8n would run nothing in
        it unchecked."""
        view = await self.get_use_case(use_case_id)
        # Its first run after a run that held it back runs on its own n8n workflow. Read it again
        # whatever the move answers, since a move may also have landed meanwhile.
        if view is not None and view.template == SOFTWARE_WATCHLIST.key:
            await self._watchlist.move_to_n8n()
            view = await self.get_use_case(use_case_id)
        elif (
            view is not None and self.moves is not None and await self._target(use_case_id) is None
        ):
            await self.moves.move(use_case_id)
            view = await self.get_use_case(use_case_id)
        if view is None:
            return None
        if view.state == "paused":
            return UseCasePaused()
        if view.state == "draft" and not test:
            return NotOnYet()
        spec = await self._spec_of(view)
        if isinstance(spec, NothingToCheck):
            return spec
        if spec.n8n is None and self.moves is not None:
            # The shared run workflow is made of blocks the allow list turns off (E11).
            return NotMovedYet(view.move_refused or NOT_MOVED_YET)
        if view.start_refused is not None:
            return NoStart()
        spec = replace(spec, test=test)
        if test and spec.n8n is not None:
            checked = await self._checked_draft(use_case_id, spec.n8n)
            if isinstance(checked, NoTestRun):
                return checked
            spec = replace(spec, n8n=replace(spec.n8n, draft_version=checked))
        if isinstance(spec.task, CardsTask) and not await self._planner.has_model():
            return NoModelToRun()
        async with self._db.transaction("builder") as uow:
            # Read the state again under the lock, on this one connection, and hold the lock
            # until the run is inserted, so a pause or delete can't land in between (#56).
            await hold_workflow(uow.conn, use_case_id, alone=False)
            if test and self.holding is not None:
                held = await self.holding.refused_while_held(
                    uow.conn, use_case_id, principal.user_id
                )
                if held is not None:
                    return NoTestRun(held.words)
            match await _lifecycle_now(uow.conn, use_case_id):
                case None | Deleted():
                    return None
                case Paused():
                    return UseCasePaused()
                case Draft() if not test:
                    return NotOnYet()
                case Draft():
                    trial = replace(spec, stops_at_gate=True)
                    return await self._runs.start_run(trial, principal, idempotency_key)
                case On():
                    return await self._runs.start_run(spec, principal, idempotency_key)

    async def _checked_draft(self, use_case_id: str, target: N8nTarget) -> NoTestRun | str:
        """The version id of the draft a test run would run, once n8n would run nothing in it
        unchecked. The run is then held to that draft."""
        if self._n8n is None:
            return NoTestRun(UNREAD_TEST)
        try:
            draft = await self._n8n.look(target.workflow_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read the draft of %s before a test run: %s", use_case_id, error)
            return NoTestRun(UNREAD_TEST)
        if draft is None:
            return NoTestRun(UNREAD_TEST)
        found = unchecked(draft.document, (await self.facts.known({})).keys)
        if found:
            return NoTestRun(UNCHECKED_TEST.format(found=found[0].text))
        return draft.version_id


def _bound(card: CardView, values: Mapping[str, str]) -> CardRun:
    """A block that names no place for a write the card makes binds none, so its run is refused
    at the write, never sent to a default place."""
    spec = card_spec(card)
    try:
        return CardRun(spec, dict(values), card_bindings(spec, values))
    except ValueError:
        return CardRun(spec, dict(values), {})


def _agent_values(parameters: Mapping[str, Any]) -> dict[str, str]:
    """An Agent block's values, as its fixed collection of inputs holds them."""
    inputs = parameters.get("inputs")
    rows = cast(dict[str, Any], inputs).get("input") if isinstance(inputs, dict) else None
    listed = cast(list[object], rows) if isinstance(rows, list) else []
    return {
        str(row["name"]): str(row["value"])
        for row in (cast(dict[str, Any], r) for r in listed if isinstance(r, dict))
        if "name" in row and isinstance(row.get("value"), str)
    }


async def _store_in_n8n(uow: UnitOfWork, use_case_id: str, version: int, relaid: Relaid) -> None:
    """A layout the Planner made again from the plan, which nobody can edit in n8n, so it has
    no earlier authors and grades safe."""
    await uow.conn.execute(
        "UPDATE builder.use_case_versions SET n8n_version_id = %s, document = %s, grade = %s,"
        " published_by = NULL, published_in = NULL, also = '[]'::jsonb, findings = NULL"
        " WHERE use_case_id = %s AND version = %s",
        (relaid.version_id, json(relaid.document), relaid.grade, use_case_id, version),
    )
    await uow.conn.execute(
        "UPDATE builder.use_cases SET n8n_draft_id = %s WHERE use_case_id = %s",
        (relaid.version_id, use_case_id),
    )


async def _carry_n8n(uow: UnitOfWork, use_case_id: str, newest: int) -> None:
    """The version after `newest` holds what n8n holds until a new layout replaces it, with
    every author of that workflow and the checker's words for it."""
    await uow.conn.execute(
        "UPDATE builder.use_case_versions n SET n8n_version_id = o.n8n_version_id,"
        " document = o.document, grade = o.grade, published_by = o.published_by,"
        " published_in = o.published_in, also = o.also, findings = o.findings"
        " FROM builder.use_case_versions o"
        " WHERE n.use_case_id = %s AND n.version = %s AND o.use_case_id = n.use_case_id"
        " AND o.version = %s",
        (use_case_id, newest + 1, newest),
    )


async def _mark_published(uow: UnitOfWork, use_case_id: str, version: int, by: UserId) -> None:
    """The person who put a version live from the Portal is its publisher, whose scheduled runs
    are their work and who can never approve them (D5). A version keeps its first publisher."""
    await uow.conn.execute(
        "UPDATE builder.use_case_versions SET published_by = %s, published_in = 'portal'"
        " WHERE use_case_id = %s AND version = %s AND published_in IS NULL",
        (by, use_case_id, version),
    )


async def _lifecycle_now(conn: Connection, use_case_id: str) -> Lifecycle | None:
    row = await (
        await conn.execute(
            "SELECT paused_at, paused_by, deleted_at, deleted_by, draft FROM builder.use_cases"
            " WHERE use_case_id = %s",
            (use_case_id,),
        )
    ).fetchone()
    return None if row is None else lifecycle_of(row)
