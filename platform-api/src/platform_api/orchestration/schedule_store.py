from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from platform_api.db import Connection, Database
from platform_api.orchestration.people import roles_from
from platform_api.orchestration.schedule import DEFAULT_AT, DEFAULT_DAY, TIME_ZONE, Schedule
from platform_api.shared import Principal, Role, UseCaseId, UserId

type ScheduleHold = Literal["owner_removed", "owner_not_an_operator"]
"""Why a schedule starts no run: its owner has left the People list, or is no longer an
Operator."""


@dataclass(frozen=True)
class SavedSchedule:
    use_case_id: UseCaseId
    schedule: Schedule
    owner: UserId
    owner_name: str
    saved_at: datetime
    owner_roles: frozenset[Role] | None
    """The owner's roles on the People list now. None once they have left it."""

    @property
    def starter(self) -> Principal | ScheduleHold:
        """Who the schedule's runs are the work of: its owner, with the roles they hold now. While
        the owner can no longer run it, why the schedule is held instead. It is no longer held
        when the owner is an Operator again, or when another Operator saves it and so becomes its
        owner."""
        if self.owner_roles is None:
            return "owner_removed"
        if Role.OPERATOR not in self.owner_roles:
            return "owner_not_an_operator"
        return Principal(self.owner, self.owner_roles, self.owner_name)

    @property
    def held(self) -> ScheduleHold | None:
        starter = self.starter
        return None if isinstance(starter, Principal) else starter


_WITH_OWNER = (
    "SELECT s.*, p.is_operator AS owner_is_operator, p.is_approver AS owner_is_approver "
    "FROM {source} s LEFT JOIN orchestration.people p "
    "ON p.id = s.owner_id AND p.removed_at IS NULL"
)
_SCHEDULES = _WITH_OWNER.format(source="orchestration.schedules")


def _saved(row: Mapping[str, Any]) -> SavedSchedule:
    on_list = row["owner_is_operator"] is not None
    return SavedSchedule(
        UseCaseId(row["use_case_id"]),
        Schedule(row["day"], row["at"], row["time_zone"]),
        UserId(row["owner_id"]),
        row["owner_name"],
        row["saved_at"],
        roles_from(row["owner_is_operator"], row["owner_is_approver"]) if on_list else None,
    )


class ScheduleBook:
    """The schedules kept in our database, one for each watchlist."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, use_case_id: UseCaseId) -> SavedSchedule | None:
        async with self._db.connection("orchestration") as conn:
            row = await (
                await conn.execute(_SCHEDULES + " WHERE s.use_case_id = %s", (use_case_id,))
            ).fetchone()
        return None if row is None else _saved(row)

    async def save(
        self, use_case_id: UseCaseId, schedule: Schedule, owner: Principal
    ) -> SavedSchedule:
        """Saving makes the caller the schedule owner."""
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "WITH saved AS (INSERT INTO orchestration.schedules (use_case_id, day, at, "
                    "time_zone, owner_id, owner_name, saved_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (use_case_id) DO UPDATE SET day = EXCLUDED.day, "
                    "at = EXCLUDED.at, time_zone = EXCLUDED.time_zone, "
                    "owner_id = EXCLUDED.owner_id, owner_name = EXCLUDED.owner_name, "
                    "saved_at = EXCLUDED.saved_at RETURNING *) "
                    + _WITH_OWNER.format(source="saved"),
                    (
                        use_case_id,
                        schedule.day,
                        schedule.at,
                        schedule.time_zone,
                        owner.user_id,
                        owner.display,
                        uow.now,
                    ),
                )
            ).fetchone()
        assert row is not None
        return _saved(row)

    async def save_default(self, use_case_id: UseCaseId, owner: Principal) -> None:
        """Monday 09:00 for a new watchlist. A schedule already there, or one turned off, stays."""
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.schedules (use_case_id, day, at, time_zone, "
                "owner_id, owner_name, saved_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (use_case_id) DO NOTHING",
                (
                    use_case_id,
                    DEFAULT_DAY,
                    DEFAULT_AT,
                    TIME_ZONE,
                    owner.user_id,
                    owner.display,
                    uow.now,
                ),
            )

    async def delete(self, use_case_id: UseCaseId) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "DELETE FROM orchestration.schedules WHERE use_case_id = %s", (use_case_id,)
            )

    async def all(self) -> list[SavedSchedule]:
        async with self._db.connection("orchestration") as conn:
            rows = await (await conn.execute(_SCHEDULES + " ORDER BY s.use_case_id")).fetchall()
        return [_saved(row) for row in rows]


async def schedule_owner(conn: Connection, use_case_id: UseCaseId) -> UserId | None:
    """Who the Portal names as the owner of the use case's schedule, if it has one."""
    row = await (
        await conn.execute(
            "SELECT owner_id FROM orchestration.schedules WHERE use_case_id = %s", (use_case_id,)
        )
    ).fetchone()
    return None if row is None else UserId(row["owner_id"])
