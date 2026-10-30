from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
from platform_api.builder.lifecycle import (
    AlreadyDeleted,
    Deleted,
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
)
from platform_api.builder.models import (
    CardChecked,
    CardDefinition,
    CardList,
    CardRefused,
    CardView,
    CreateAgentUseCase,
    DraftIn,
    DraftList,
    DraftView,
    PlanOut,
    SuggestOut,
    ToolList,
    UnderstandOut,
    UseCaseAgentView,
    UseCaseCreated,
    UseCaseDeleted,
    UseCaseList,
    UseCaseView,
)
from platform_api.builder.planning import (
    NoModelConnected,
    NoPlanner,
    Planning,
    RuntimeNotAnswering,
    plan,
    understand,
)
from platform_api.builder.templates import (
    AGENT_CARDS,
    SOFTWARE_WATCHLIST,
    TEMPLATES,
    suggest_template,
)
from platform_api.builder.views import template_view
from platform_api.builder.watchlist import Watchlist
from platform_api.db import Database, json
from platform_api.orchestration import (
    CardRun,
    CardsTask,
    NotOn,
    RunSpec,
    RunStarted,
    RunStarter,
    SavedSchedule,
    ScheduleBook,
    Task,
    card_bindings,
    cards_policy,
)
from platform_api.shared import Principal, UseCaseId, UserId, new_id

_CURRENT_VERSION = """
    SELECT u.use_case_id, u.owner, u.paused_at, u.paused_by, u.deleted_at, u.deleted_by,
           v.version, v.template, v.name, v.instruction, v.params, v.created_at
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
"""


def _view(
    row: Mapping[str, Any],
    agents: Sequence[PinnedAgent],
    schedule: SavedSchedule | None,
    now: datetime,
) -> UseCaseView:
    template = TEMPLATES[row["template"]]
    on = is_on(lifecycle_of(row))
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
        state="on" if on else "paused",
        next_run_at=schedule.next_run(now) if on and schedule is not None else None,
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
class CardsRefused:
    refused: CardRefused


@dataclass(frozen=True)
class UseCasePaused:
    pass


@dataclass(frozen=True)
class WatchlistStays:
    pass


type Moved = Lifecycle | AlreadyDeleted | TooLate | WatchlistStays
type Move = Callable[[Lifecycle, str, datetime], Moved]


class Builder:
    def __init__(
        self,
        db: Database,
        runs: RunStarter,
        watchlist: Watchlist,
        public_base_url: str,
        planner: Planning | None = None,
    ) -> None:
        self._db = db
        self._runs = runs
        self._watchlist = watchlist
        self._cards = CardLibrary(db)
        self._schedules = ScheduleBook(db)
        self._drafts = Drafts(db)
        self._planner = planner or NoPlanner()
        self.public_base_url = public_base_url

    async def list_use_cases(self) -> UseCaseList:
        """Team-wide by design: one team, two roles, and Approvers need the context.
        Per-team scoping comes with Entra ID, if more teams join."""
        async with self._db.connection("builder") as conn:
            cursor = await conn.execute(
                _CURRENT_VERSION
                + " WHERE u.deleted_at IS NULL ORDER BY u.created_at DESC, u.use_case_id DESC"
            )
            rows = await cursor.fetchall()
        schedules = {saved.use_case_id: saved for saved in await self._schedules.all()}
        return UseCaseList(use_cases=await self._views(rows, schedules))

    async def get_use_case(self, use_case_id: str) -> UseCaseView | None:
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
        return (await self._views([row], schedules))[0]

    async def _views(
        self, rows: Sequence[Mapping[str, Any]], schedules: Mapping[UseCaseId, SavedSchedule]
    ) -> list[UseCaseView]:
        agent_cases = [
            (row["use_case_id"], row["version"])
            for row in rows
            if row["template"] == AGENT_CARDS.key
        ]
        agents = await self._cards.agents_of(agent_cases)
        now = self._db.clock()
        return [
            _view(
                row,
                agents.get((row["use_case_id"], row["version"]), []),
                schedules.get(row["use_case_id"]),
                now,
            )
            for row in rows
        ]

    async def pause_use_case(self, use_case_id: str, principal: Principal) -> UseCaseView | None:
        moved = await self._move(
            use_case_id, lambda state, _, now: pause(state, now, principal.user_id)
        )
        if moved is None or isinstance(moved, AlreadyDeleted):
            return None
        return await self.get_use_case(use_case_id)

    async def resume_use_case(self, use_case_id: str) -> UseCaseView | None:
        moved = await self._move(use_case_id, lambda state, _template, _now: resume(state))
        if moved is None or isinstance(moved, AlreadyDeleted):
            return None
        return await self.get_use_case(use_case_id)

    async def delete_use_case(
        self, use_case_id: str, principal: Principal
    ) -> UseCaseDeleted | WatchlistStays | None:
        def move(state: Lifecycle, template: str, now: datetime) -> Lifecycle | WatchlistStays:
            if template == SOFTWARE_WATCHLIST.key:
                return WatchlistStays()
            return delete(state, now, principal.user_id)

        match await self._move(use_case_id, move):
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

    async def restore_use_case(self, use_case_id: str) -> UseCaseView | TooLate | None:
        match await self._move(use_case_id, lambda state, _, now: restore(state, now)):
            case TooLate() as late:
                return late
            case None:
                return None
            case _:
                return await self.get_use_case(use_case_id)

    async def _move(self, use_case_id: str, move: Move) -> Moved | None:
        async with self._db.transaction("builder") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT u.paused_at, u.paused_by, u.deleted_at, u.deleted_by, v.template"
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
            if isinstance(after, On | Paused | Deleted) and after != before:
                columns = to_columns(after)
                await uow.conn.execute(
                    "UPDATE builder.use_cases SET paused_at = %s, paused_by = %s,"
                    " deleted_at = %s, deleted_by = %s WHERE use_case_id = %s",
                    (
                        columns.paused_at,
                        columns.paused_by,
                        columns.deleted_at,
                        columns.deleted_by,
                        use_case_id,
                    ),
                )
                if comes_on(before, after):
                    # The builder's role cannot write orchestration's schedules, so this is its
                    # own transaction. It commits before the move does: a move that then fails
                    # leaves the workflow off, missing only a slot the tick would have skipped.
                    await self._schedules.use_up_slots_until(UseCaseId(use_case_id), uow.now)
        return after

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

    async def understand(self, text: str) -> UnderstandOut:
        """What the Planner understood of a task, or the starter workflows. Nothing is saved."""
        return await understand(self._planner, text)

    async def create_agent_use_case(
        self, principal: Principal, body: CreateAgentUseCase
    ) -> UseCaseCreated | AgentUseCaseRefused:
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
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version)"
                " VALUES (%s, %s, %s, 1)",
                (use_case_id, principal.user_id, uow.now),
            )
            await uow.conn.execute(
                "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
                " instruction, params, created_at) VALUES (%s, 1, %s, %s, %s, %s, %s)",
                (use_case_id, AGENT_CARDS.key, body.name, body.instruction, json({}), uow.now),
            )
            for position, (card, values) in enumerate(chosen):
                await uow.conn.execute(
                    "INSERT INTO builder.use_case_cards (use_case_id, version, position,"
                    ' card_id, card_version, "values") VALUES (%s, 1, %s, %s, %s, %s)',
                    (use_case_id, position, card.card_id, card.version, json(values)),
                )
        return UseCaseCreated(use_case_id=use_case_id, version=1)

    @staticmethod
    def suggest(text: str) -> SuggestOut:
        template, terms = suggest_template(text)
        return SuggestOut(
            template=None if template is None else template_view(template), matched_terms=terms
        )

    async def run_spec_for(self, use_case_id: UseCaseId) -> RunSpec | None | NothingToCheck:
        view = await self.get_use_case(use_case_id)
        return None if view is None else await self._spec_of(view)

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
        )

    async def check_spec(self, use_case_id: UseCaseId) -> RunSpec | NotOn | None:
        """What the schedule tick asks for. None means nothing to check."""
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT paused_at, paused_by, deleted_at, deleted_by FROM builder.use_cases"
                    " WHERE use_case_id = %s",
                    (use_case_id,),
                )
            ).fetchone()
        if row is None:
            return None
        match lifecycle_of(row):
            case Paused():
                return NotOn("paused")
            case Deleted():
                return NotOn("deleted")
            case On():
                spec = await self.run_spec_for(use_case_id)
                return None if isinstance(spec, NothingToCheck) else spec

    async def start_run(
        self, use_case_id: UseCaseId, principal: Principal, idempotency_key: str
    ) -> RunStarted | None | NothingToCheck | NoModelToRun | UseCasePaused:
        view = await self.get_use_case(use_case_id)
        if view is None:
            return None
        if view.state == "paused":
            return UseCasePaused()
        spec = await self._spec_of(view)
        if isinstance(spec, NothingToCheck):
            return spec
        if isinstance(spec.task, CardsTask) and not await self._planner.has_model():
            return NoModelToRun()
        return await self._runs.start_run(spec, principal, idempotency_key)
