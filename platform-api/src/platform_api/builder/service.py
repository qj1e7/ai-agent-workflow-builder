import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, cast

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
    comes_on,
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
    PlanOut,
    SuggestOut,
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
from platform_api.builder.n8n_draft import (
    ADDING,
    SAVED,
    Checked,
    DraftRefused,
    N8nNotReady,
    NotSafe,
    blocks_of,
    check_draft,
)
from platform_api.builder.n8n_facts import BuilderWorkflowFacts, ReleaseReader
from platform_api.builder.planning import (
    CardPlanner,
    NoModelConnected,
    NoPlanner,
    RuntimeNotAnswering,
    plan,
)
from platform_api.builder.templates import (
    AGENT_CARDS,
    SOFTWARE_WATCHLIST,
    TEMPLATES,
    suggest_template,
)
from platform_api.builder.versions import (
    AlreadyUndone,
    ChangedSince,
    NoSuchVersion,
    NotAScheduleChange,
    Publish,
    ScheduleChange,
    Undo,
    Version,
    publish,
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
    Grade,
    Graded,
    N8nDrafts,
    N8nError,
    N8nTarget,
    NotOn,
    RunSpec,
    RunStarted,
    RunStarter,
    SavedDraft,
    SavedSchedule,
    Schedule,
    ScheduleBook,
    Task,
    WriteEntry,
    card_bindings,
    cards_policy,
    next_run,
    tools_used,
    write_tools_used,
)
from platform_api.shared import Principal, UseCaseId, UserId, new_id

log = logging.getLogger(__name__)

_CURRENT_VERSION = """
    SELECT u.use_case_id, u.owner, u.paused_at, u.paused_by, u.deleted_at, u.deleted_by,
           u.draft, u.left_out, u.engine, u.n8n_workflow_id, v.version, v.template, v.name,
           v.instruction, v.params, v.created_at, v.document, v.n8n_version_id
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
"""

_USE_CASE_ROW = (
    "SELECT current_version, paused_at, paused_by, deleted_at, deleted_by, draft, engine,"
    " n8n_workflow_id FROM builder.use_cases WHERE use_case_id = %s"
)
_IN_N8N = (
    "SELECT name, document, n8n_version_id FROM builder.use_case_versions"
    " WHERE use_case_id = %s AND version = %s"
)
"""Read once the use case's row is locked. Locking it joined to its version would drop the row
when a save waited on the lock had moved the current version on."""


def _schedule_view(saved: SavedSchedule) -> UseCaseSchedule:
    return UseCaseSchedule(
        day=saved.schedule.day,
        at=saved.schedule.at,
        time_zone=saved.schedule.time_zone,
        owner_name=saved.owner_name,
        held=saved.held,
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


def _target(row: Mapping[str, Any]) -> N8nTarget | None:
    if not _own(row):
        return None
    return N8nTarget(row["n8n_workflow_id"], _start_webhook(row["document"]))


def _next_run_at(
    row: Mapping[str, Any], schedule: SavedSchedule | None, now: datetime
) -> datetime | None:
    """An own workflow runs when n8n's Schedule Trigger fires, to the second n8n adds to it
    (ENGINE-PLAN 2.4). The rest run on the platform's schedule tick."""
    if _own(row):
        document = row["document"]
        return None if document is None else next_run(document, row["n8n_workflow_id"], now)
    return None if schedule is None else schedule.next_run(now)


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
) -> UseCaseView:
    template = TEMPLATES[row["template"]]
    state = _state(lifecycle_of(row))
    plan = (
        plan_for_cards([a.card for a in agents])
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
        next_run_at=_next_run_at(row, schedule, now) if state == "on" else None,
        schedule=None if schedule is None else _schedule_view(schedule),
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


type InN8nRefused = N8nNotReady | DraftRefused | ChangedInN8n
"""Why a change to an own workflow was not made: n8n did not take it, the checker refused the
layout, or someone changed the workflow in n8n since the platform stored it."""


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
class WatchlistStays:
    pass


@dataclass(frozen=True)
class ScheduleOnSoftwarePage:
    pass


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
    ) -> None:
        self._db = db
        self._runs = runs
        self._watchlist = watchlist
        self._cards = CardLibrary(db)
        self._schedules = schedules or ScheduleBook(db)
        self._drafts = Drafts(db)
        self._planner = planner or NoPlanner()
        self._history = history
        self._n8n = n8n
        self.public_base_url = public_base_url
        self.facts = BuilderWorkflowFacts(db, self, releases, writes)
        """What node calls ask of the builder, and what a draft is graded against."""

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
        return [
            _view(
                row,
                agents.get((row["use_case_id"], row["version"]), []),
                schedules.get(row["use_case_id"]),
                last_run_view(gist) if (gist := newest.get(row["use_case_id"])) else None,
                now,
            )
            for row in rows
        ]

    async def pause_use_case(
        self, use_case_id: str, principal: Principal, via: Via = "page"
    ) -> UseCaseView | N8nNotReady | NotSafe | None:
        moved = await self._move(
            use_case_id,
            lambda state, _, now: pause(state, now, principal.user_id),
            principal.user_id,
            Recorded("pause", principal.user_id, via),
        )
        return await self._after(use_case_id, principal, moved)

    async def resume_use_case(
        self, use_case_id: str, principal: Principal, via: Via = "page"
    ) -> UseCaseView | N8nNotReady | NotSafe | None:
        moved = await self._move(
            use_case_id,
            lambda state, _template, _now: resume(state),
            principal.user_id,
            Recorded("resume", principal.user_id, via),
        )
        return await self._after(use_case_id, principal, moved)

    async def turn_on_use_case(
        self, use_case_id: str, principal: Principal
    ) -> UseCaseView | N8nNotReady | NotSafe | None:
        """Publishes a draft's version 1 and turns it on. An own workflow reads On only once n8n
        has every trigger live (ENGINE-PLAN 2.5). Asking again changes nothing."""
        moved = await self._move(
            use_case_id, lambda state, _template, _now: turn_on(state), principal.user_id
        )
        return await self._after(use_case_id, principal, moved)

    async def _after(
        self, use_case_id: str, principal: Principal, moved: Moved | N8nNotReady | NotSafe | None
    ) -> UseCaseView | N8nNotReady | NotSafe | None:
        match moved:
            case None | AlreadyDeleted():
                return None
            case N8nNotReady() | NotSafe():
                return moved
            case _:
                return await self.get_use_case(use_case_id, principal)

    async def delete_use_case(
        self, use_case_id: str, principal: Principal
    ) -> UseCaseDeleted | WatchlistStays | None:
        def move(state: Lifecycle, template: str, now: datetime) -> Lifecycle | WatchlistStays:
            if template == SOFTWARE_WATCHLIST.key:
                return WatchlistStays()
            return delete(state, now, principal.user_id)

        match await self._move(use_case_id, move, principal.user_id):
            case Deleted() as deleted:
                return UseCaseDeleted(
                    use_case_id=use_case_id,
                    deleted_at=deleted.at,
                    restore_until=deleted.restore_until,
                )
            case WatchlistStays() as stays:
                return stays
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
    ) -> UseCaseView | ScheduleOnSoftwarePage | InN8nRefused | None:
        """The same save as the watchlist's: the caller becomes the owner, which lifts a hold.
        A new schedule publishes a new version. Saving the same one again publishes none.
        Saving is not a write to Jira or Confluence, so it needs no approval. An own workflow's
        new schedule is saved in n8n first (ENGINE-PLAN 2.5)."""
        # Read the workflow before the lock, so the lock holds one connection and no more.
        view = await self.get_use_case(use_case_id, principal)
        if view is None:
            return None
        if view.template == SOFTWARE_WATCHLIST.key:
            return ScheduleOnSoftwarePage()
        after = Schedule(body.day, body.at)
        match await self._publish(use_case_id, principal, body.via, lambda _: Publish(after)):
            case None:
                return None
            case N8nNotReady() | DraftRefused() | ChangedInN8n() as refused:
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
        return VersionList(versions=[version_view(version, running) for version in versions])

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
            draft = isinstance(state, Draft)
            versions = [] if draft else await versions_of(uow.conn, use_case_id)
            decided = decide(versions)
            if not isinstance(decided, Publish):
                return decided
            in_n8n = None
            if _own(row):
                version = row["current_version"]
                current = await (await uow.conn.execute(_IN_N8N, (use_case_id, version))).fetchone()
                assert current is not None
                row = {**row, **current}
                in_n8n = await self._schedule_in_n8n(use_case_id, row, decided.after, is_on(state))
                if isinstance(in_n8n, N8nNotReady | DraftRefused | ChangedInN8n):
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

    async def _move(
        self, use_case_id: str, move: Move, by: UserId, recorded: Recorded | None = None
    ) -> Moved | N8nNotReady | NotSafe | None:
        """An own workflow's n8n state follows the move before it is recorded: on is published
        with every trigger live, anything else is off. The lock is held across n8n's answer, so
        moves of one workflow never cross there either."""
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, use_case_id, alone=True)
            row = await (
                await uow.conn.execute(
                    "SELECT u.paused_at, u.paused_by, u.deleted_at, u.deleted_by, u.draft,"
                    " u.engine, u.n8n_workflow_id, u.current_version, v.template, v.n8n_version_id,"
                    " v.grade"
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
                if comes_on(before, after):
                    # The builder's role cannot write orchestration's schedules, so this is its
                    # own transaction. It commits before the move does: a move that then fails
                    # leaves the workflow off, missing only a slot the tick would have skipped.
                    await self._schedules.use_up_slots_until(UseCaseId(use_case_id), uow.now)
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
        expected = row["n8n_version_id"]
        if expected is None:
            return N8nNotReady("This version is not saved in n8n, so it cannot be changed there.")
        try:
            written = await self._n8n.change(row["n8n_workflow_id"], expected, laid.document, live)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("n8n did not take the new schedule of %s: %s", use_case_id, error)
            if live:
                await self._put_back(row["n8n_workflow_id"], expected)
            return N8nNotReady("n8n did not take the change. Nothing changed. Try again.")
        if isinstance(written, ChangedInN8n):
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
        if is_on(after) and version_id is None:
            return N8nNotReady("This version is not saved in n8n. Change when it runs to save it.")
        if is_on(after) and row["grade"] != "safe":
            return NotSafe()
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

    async def _put_back(self, workflow_id: str, version_id: str) -> None:
        """The version the records hold live again, after a change that did not finish."""
        assert self._n8n is not None
        try:
            await self._n8n.go_live(workflow_id, version_id)
        except (N8nError, httpx.HTTPError) as error:
            log.error("could not put %s version %s back in n8n: %s", workflow_id, version_id, error)

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
                    Schedule(body.schedule.day, body.schedule.at),
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
        schedule = None if body.schedule is None else Schedule(body.schedule.day, body.schedule.at)
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
        )
        repos = [values[REPO_INPUT] for _, values in chosen if REPO_INPUT in values]
        known = await self.facts.known({GITHUB_RELEASES: repos})
        checked = check_draft(lay_out(plan), use_case_id, error_workflow, known)
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
            cards = tuple(
                CardRun(
                    card_spec(a.card), dict(a.values), card_bindings(card_spec(a.card), a.values)
                )
                for a in pinned
            )
            task = CardsTask(cards)
            asked = max((x.approvers for a in pinned for x in a.card.approvals), default=1)
            policy = cards_policy([run.card for run in cards], asked)
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

    async def check_spec(self, use_case_id: UseCaseId) -> RunSpec | NotOn | None:
        """What the schedule tick asks for. None means nothing to check. The tick holds the
        workflow's lock around this read and the run insert, so this read does not take it."""
        async with self._db.connection("builder") as conn:
            state = await _lifecycle_now(conn, use_case_id)
        match state:
            case None:
                return None
            case Draft():
                return NotOn("draft")
            case Paused():
                return NotOn("paused")
            case Deleted():
                return NotOn("deleted")
            case On():
                spec = await self.run_spec_for(use_case_id)
                return None if isinstance(spec, NothingToCheck) else spec

    async def start_run(
        self,
        use_case_id: UseCaseId,
        principal: Principal,
        idempotency_key: str,
        test: bool = False,
    ) -> RunStarted | None | NothingToCheck | NoModelToRun | UseCasePaused | NotOnYet:
        """A test run of a draft stops at the approval gate (ADR 0044). Whether it is a draft
        is read under the lock, so a draft turned on since runs as any test run does."""
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
        spec = replace(spec, test=test)
        if isinstance(spec.task, CardsTask) and not await self._planner.has_model():
            return NoModelToRun()
        async with self._db.transaction("builder") as uow:
            # Read the state again under the lock, on this one connection, and hold the lock
            # until the run is inserted, so a pause or delete can't land in between (#56).
            await hold_workflow(uow.conn, use_case_id, alone=False)
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


async def _store_in_n8n(uow: UnitOfWork, use_case_id: str, version: int, relaid: Relaid) -> None:
    await uow.conn.execute(
        "UPDATE builder.use_case_versions SET n8n_version_id = %s, document = %s, grade = %s,"
        " published_by = NULL, published_in = NULL WHERE use_case_id = %s AND version = %s",
        (relaid.version_id, json(relaid.document), relaid.grade, use_case_id, version),
    )


async def _carry_n8n(uow: UnitOfWork, use_case_id: str, newest: int) -> None:
    """The version after `newest` holds what n8n holds until a new layout replaces it."""
    await uow.conn.execute(
        "UPDATE builder.use_case_versions n SET n8n_version_id = o.n8n_version_id,"
        " document = o.document, grade = o.grade, published_by = o.published_by,"
        " published_in = o.published_in FROM builder.use_case_versions o"
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
