"""The team's agent cards and the agents of each agent use case, in the builder's tables.

Starter cards are in code (cards.py), so a library is the starters plus these rows. A saved card
keeps every version, and a use case pins the version it was made with.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from platform_api.builder.cards import STARTER_CARDS, STARTERS, card_view, sorted_for_library
from platform_api.builder.models import CardDefinition, CardView
from platform_api.db import Database, UnitOfWork, json
from platform_api.shared import Principal, UserId, new_id

_CURRENT = """
    SELECT v.card_id, v.version, v.name, v.purpose, v.good_for, v.inputs, v.blocks, v.approvals,
           c.owner, c.created_at
    FROM builder.cards c
    JOIN builder.card_versions v ON v.card_id = c.card_id AND v.version = c.current_version
"""
_PINNED = """
    SELECT v.card_id, v.version, v.name, v.purpose, v.good_for, v.inputs, v.blocks, v.approvals,
           c.owner, c.created_at
    FROM builder.cards c
    JOIN builder.card_versions v ON v.card_id = c.card_id
"""


@dataclass(frozen=True)
class StarterCard:
    """A starter card cannot be changed. Copy it instead."""


@dataclass(frozen=True)
class NoSuchCard:
    card_id: str


@dataclass(frozen=True)
class PinnedAgent:
    position: int
    card: CardView
    values: Mapping[str, str]


def _card(row: Mapping[str, Any]) -> CardView:
    return card_view(
        card_id=row["card_id"],
        version=row["version"],
        starter=False,
        owner=UserId(row["owner"]),
        created_at=row["created_at"],
        definition=CardDefinition.model_validate(
            {
                "name": row["name"],
                "purpose": row["purpose"],
                "good_for": row["good_for"],
                "inputs": row["inputs"],
                "blocks": row["blocks"],
                "approvals": row["approvals"],
            }
        ),
    )


class CardLibrary:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list(self) -> list[CardView]:
        """Every card at its current version, starters first, then the team's by name."""
        async with self._db.connection("builder") as conn:
            rows = await (await conn.execute(_CURRENT)).fetchall()
        return sorted_for_library(STARTER_CARDS, (_card(row) for row in rows))

    async def get(self, card_id: str) -> CardView | None:
        """The card at its current version."""
        for starter in STARTER_CARDS:
            if starter.card_id == card_id:
                return starter
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(_CURRENT + " WHERE c.card_id = %s", (card_id,))
            ).fetchone()
        return None if row is None else _card(row)

    async def create(self, principal: Principal, definition: CardDefinition) -> CardView:
        """Saves a card that has been through check_card with no problems."""
        card_id = new_id("crd")
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "INSERT INTO builder.cards (card_id, owner, created_at, current_version)"
                " VALUES (%s, %s, %s, 1)",
                (card_id, principal.user_id, uow.now),
            )
            await self._insert_version(uow, card_id, 1, principal, definition)
        return card_view(
            card_id=card_id,
            version=1,
            starter=False,
            owner=principal.user_id,
            created_at=uow.now,
            definition=definition,
        )

    async def update(
        self, principal: Principal, card_id: str, definition: CardDefinition
    ) -> CardView | NoSuchCard | StarterCard:
        """Saves the next version of a card. Use cases made before keep their version."""
        if card_id in {starter.card_id for starter in STARTER_CARDS}:
            return StarterCard()
        async with self._db.transaction("builder") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT owner, created_at, current_version FROM builder.cards"
                    " WHERE card_id = %s FOR UPDATE",
                    (card_id,),
                )
            ).fetchone()
            if row is None:
                return NoSuchCard(card_id)
            version = row["current_version"] + 1
            await self._insert_version(uow, card_id, version, principal, definition)
            await uow.conn.execute(
                "UPDATE builder.cards SET current_version = %s WHERE card_id = %s",
                (version, card_id),
            )
        return card_view(
            card_id=card_id,
            version=version,
            starter=False,
            owner=UserId(row["owner"]),
            created_at=row["created_at"],
            definition=definition,
        )

    @staticmethod
    async def _insert_version(
        uow: UnitOfWork,
        card_id: str,
        version: int,
        principal: Principal,
        definition: CardDefinition,
    ) -> None:
        await uow.conn.execute(
            "INSERT INTO builder.card_versions (card_id, version, name, purpose, good_for,"
            " inputs, blocks, approvals, created_by, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                card_id,
                version,
                definition.name,
                definition.purpose,
                json(definition.good_for),
                json([i.model_dump() for i in definition.inputs]),
                json([b.model_dump() for b in definition.blocks]),
                json([a.model_dump() for a in definition.approvals]),
                principal.user_id,
                uow.now,
            ),
        )

    async def pinned(self, pins: Sequence[tuple[str, int]]) -> dict[tuple[str, int], CardView]:
        """The cards at the versions asked for, whichever are found."""
        found = {pin: STARTERS[pin] for pin in pins if pin in STARTERS}
        saved = [pin for pin in pins if pin not in found]
        if saved:
            async with self._db.connection("builder") as conn:
                rows = await (
                    await conn.execute(
                        _PINNED + " WHERE (v.card_id, v.version) IN"
                        " (SELECT * FROM unnest(%s::text[], %s::int[]))",
                        ([p[0] for p in saved], [p[1] for p in saved]),
                    )
                ).fetchall()
            found.update({(row["card_id"], row["version"]): _card(row) for row in rows})
        return found

    async def agents_of(
        self, use_cases: Sequence[tuple[str, int]]
    ) -> dict[tuple[str, int], list[PinnedAgent]]:
        """The agents of each (use case, version) asked for, in the order they work."""
        if not use_cases:
            return {}
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    'SELECT use_case_id, version, position, card_id, card_version, "values"'
                    " FROM builder.use_case_cards"
                    " WHERE (use_case_id, version) IN"
                    " (SELECT * FROM unnest(%s::text[], %s::int[]))"
                    " ORDER BY use_case_id, version, position",
                    ([u[0] for u in use_cases], [u[1] for u in use_cases]),
                )
            ).fetchall()
        cards = await self.pinned(sorted({(r["card_id"], r["card_version"]) for r in rows}))
        agents: dict[tuple[str, int], list[PinnedAgent]] = {}
        for row in rows:
            card = cards.get((row["card_id"], row["card_version"]))
            if card is None:
                raise LookupError(f"{row['card_id']} version {row['card_version']} is missing")
            agents.setdefault((row["use_case_id"], row["version"]), []).append(
                PinnedAgent(row["position"], card, row["values"])
            )
        return agents
