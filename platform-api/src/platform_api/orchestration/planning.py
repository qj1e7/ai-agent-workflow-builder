"""The Planner's planning, as the builder sees it: choose saved agents, or draft a new one.

The builder owns the library and the checks. This side owns the model and the runtime, so the
model key goes from the settings store into the request to the runtime and nowhere else.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from platform_api.db import Database
from platform_api.orchestration.agents import (
    AgentRejected,
    AgentUnavailable,
    ChooseRequest,
    ChooseResult,
    DraftRequest,
    DraftResult,
    HttpAgentRuntime,
    LibraryCard,
)
from platform_api.orchestration.service import ActiveModel


@dataclass(frozen=True)
class NoModel:
    """No AI model is connected, so nothing can be planned or run."""


@dataclass(frozen=True)
class RuntimeDown:
    """The agent runtime did not give a usable answer. The detail is for the log, not for people."""

    detail: str


class CardPlanning:
    def __init__(self, db: Database, models: ActiveModel, agents: HttpAgentRuntime) -> None:
        self._db = db
        self._models = models
        self._agents = agents

    async def has_model(self) -> bool:
        async with self._db.transaction("orchestration") as uow:
            return await self._models.access(uow) is not None

    async def choose(
        self, task: str, library: Sequence[LibraryCard]
    ) -> ChooseResult | NoModel | RuntimeDown:
        async with self._db.transaction("orchestration") as uow:
            model = await self._models.access(uow)
        if model is None:
            return NoModel()
        reply = await self._agents.choose(
            ChooseRequest(task=task, library=list(library), model=model)
        )
        if isinstance(reply, AgentUnavailable | AgentRejected):
            return RuntimeDown(reply.detail)
        return reply

    async def draft(self, task: str) -> DraftResult | NoModel | RuntimeDown:
        async with self._db.transaction("orchestration") as uow:
            model = await self._models.access(uow)
        if model is None:
            return NoModel()
        reply = await self._agents.draft(DraftRequest(task=task, model=model))
        if isinstance(reply, AgentUnavailable | AgentRejected):
            return RuntimeDown(reply.detail)
        return reply
