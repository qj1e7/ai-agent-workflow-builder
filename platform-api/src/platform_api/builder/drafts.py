"""New workflow drafts, each kept for its author alone.

A draft's id is chosen by the Portal and belongs to its author, so two people can use the same
id and never see or change each other's draft.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from platform_api.builder.models import DraftIn, DraftView
from platform_api.db import Database, json
from platform_api.shared import UserId

DRAFTS_EACH = 20


@dataclass(frozen=True)
class TooManyDrafts:
    limit: int


def _view(row: Mapping[str, Any]) -> DraftView:
    return DraftView(
        draft_id=row["draft_id"],
        step=row["step"],
        content=row["content"],
        created_at=row["created_at"],
        saved_at=row["saved_at"],
    )


class Drafts:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(
        self, author: UserId, draft_id: str, draft: DraftIn
    ) -> DraftView | TooManyDrafts:
        """Saving again replaces the draft. A new one is refused once the author has the most."""
        async with self._db.transaction("builder") as uow:
            # Two first saves at once must not both slip under the limit.
            await uow.conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"builder.drafts:{author}",)
            )
            kept = await (
                await uow.conn.execute(
                    "SELECT count(*) AS kept, count(*) FILTER (WHERE draft_id = %s) AS this"
                    " FROM builder.drafts WHERE author = %s",
                    (draft_id, author),
                )
            ).fetchone()
            assert kept is not None
            if kept["this"] == 0 and kept["kept"] >= DRAFTS_EACH:
                return TooManyDrafts(DRAFTS_EACH)
            row = await (
                await uow.conn.execute(
                    "INSERT INTO builder.drafts (author, draft_id, step, content, created_at,"
                    " saved_at) VALUES (%s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (author, draft_id) DO UPDATE SET step = EXCLUDED.step,"
                    " content = EXCLUDED.content, saved_at = EXCLUDED.saved_at RETURNING *",
                    (author, draft_id, draft.step, json(draft.content), uow.now, uow.now),
                )
            ).fetchone()
        assert row is not None
        return _view(row)

    async def list(self, author: UserId) -> list[DraftView]:
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM builder.drafts WHERE author = %s"
                    " ORDER BY saved_at DESC, draft_id",
                    (author,),
                )
            ).fetchall()
        return [_view(row) for row in rows]

    async def delete(self, author: UserId, draft_id: str) -> bool:
        async with self._db.transaction("builder") as uow:
            cursor = await uow.conn.execute(
                "DELETE FROM builder.drafts WHERE author = %s AND draft_id = %s",
                (author, draft_id),
            )
        return cursor.rowcount == 1
