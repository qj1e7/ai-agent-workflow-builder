from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
from platform_api.builder.models import (
    CardChecked,
    CardDefinition,
    CardList,
    CardRefused,
    CardView,
    CreateAgentUseCase,
    CreateUseCase,
    PlanOut,
    SuggestOut,
    ToolList,
    UseCaseAgentView,
    UseCaseCreated,
    UseCaseList,
    UseCaseView,
)
from platform_api.builder.planning import (
    CardPlanner,
    NoModelConnected,
    NoPlanner,
    RuntimeNotAnswering,
    plan,
)
from platform_api.builder.templates import (
    AGENT_CARDS,
    TEMPLATES,
    ParamErrors,
    TemplateNotOffered,
    UnknownTemplate,
    suggest_template,
    validate_params,
)
from platform_api.builder.views import template_view
from platform_api.builder.watchlist import Watchlist
from platform_api.db import Database, json
from platform_api.orchestration import (
    CardRun,
    CardsTask,
    ReleaseTask,
    RunSpec,
    RunStarted,
    RunStarter,
    Task,
    card_bindings,
    cards_policy,
)
from platform_api.shared import Principal, UseCaseId, UserId, new_id

_CURRENT_VERSION = """
    SELECT u.use_case_id, u.owner, v.version, v.template, v.name, v.instruction, v.params,
           v.created_at
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
"""


def _view(row: Mapping[str, Any], agents: Sequence[PinnedAgent]) -> UseCaseView:
    template = TEMPLATES[row["template"]]
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


class Builder:
    def __init__(
        self,
        db: Database,
        runs: RunStarter,
        watchlist: Watchlist,
        public_base_url: str,
        planner: CardPlanner | None = None,
    ) -> None:
        self._db = db
        self._runs = runs
        self._watchlist = watchlist
        self._cards = CardLibrary(db)
        self._planner = planner or NoPlanner()
        self.public_base_url = public_base_url

    async def create_use_case(
        self, principal: Principal, body: CreateUseCase
    ) -> UseCaseCreated | ParamErrors | UnknownTemplate | TemplateNotOffered:
        template = TEMPLATES.get(body.template)
        if template is None:
            return UnknownTemplate(body.template)
        if not template.offered:
            return TemplateNotOffered(template.key)
        checked = validate_params(template, body.params)
        if isinstance(checked, ParamErrors):
            return checked
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
                (
                    use_case_id,
                    template.key,
                    body.name,
                    body.instruction,
                    json(dict(checked.values)),
                    uow.now,
                ),
            )
        return UseCaseCreated(use_case_id=use_case_id, version=1)

    async def list_use_cases(self) -> UseCaseList:
        """Team-wide by design: one team, two roles, and Approvers need the context.
        Per-team scoping comes with Entra ID, if more teams join."""
        async with self._db.connection("builder") as conn:
            cursor = await conn.execute(
                _CURRENT_VERSION + " ORDER BY u.created_at DESC, u.use_case_id DESC"
            )
            rows = await cursor.fetchall()
        return UseCaseList(use_cases=await self._views(rows))

    async def get_use_case(self, use_case_id: str) -> UseCaseView | None:
        async with self._db.connection("builder") as conn:
            cursor = await conn.execute(
                _CURRENT_VERSION + " WHERE u.use_case_id = %s", (use_case_id,)
            )
            row = await cursor.fetchone()
        return None if row is None else (await self._views([row]))[0]

    async def _views(self, rows: Sequence[Mapping[str, Any]]) -> list[UseCaseView]:
        agent_cases = [
            (row["use_case_id"], row["version"])
            for row in rows
            if row["template"] == AGENT_CARDS.key
        ]
        agents = await self._cards.agents_of(agent_cases)
        return [_view(row, agents.get((row["use_case_id"], row["version"]), [])) for row in rows]

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
        """The Room lead's plan for a task. Nothing is saved."""
        library = (await self._cards.list())[:LIBRARY_LIMIT]
        return await plan(self._planner, library, task)

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
        if view is None:
            return None
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
        elif template.offered:
            carried = await self._runs.latest_carry_forward(use_case_id)
            task = ReleaseTask(
                repo=params["repo"],
                tag_pattern=params["tag_pattern"],
                last_known_tag=carried or params.get("last_seen_tag"),
            )
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

    async def check_spec(self, use_case_id: UseCaseId) -> RunSpec | None:
        """What the schedule tick asks for. None means nothing to check."""
        spec = await self.run_spec_for(use_case_id)
        return None if isinstance(spec, NothingToCheck) else spec

    async def start_run(
        self, use_case_id: UseCaseId, principal: Principal, idempotency_key: str
    ) -> RunStarted | None | NothingToCheck | NoModelToRun:
        spec = await self.run_spec_for(use_case_id)
        if spec is None or isinstance(spec, NothingToCheck):
            return spec
        if isinstance(spec.task, CardsTask) and not await self._planner.has_model():
            return NoModelToRun()
        return await self._runs.start_run(spec, principal, idempotency_key)
