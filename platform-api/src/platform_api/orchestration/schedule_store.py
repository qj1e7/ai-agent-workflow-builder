import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from platform_api.db import Database
from platform_api.orchestration.schedule import (
    DEFAULT_AT,
    DEFAULT_DAY,
    TIME_ZONE,
    Schedule,
    Slots,
    due_slot,
    slots,
)
from platform_api.orchestration.spec import RunSpec, RunStarter
from platform_api.shared import Principal, Role, RunId, UseCaseId, UserId

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedSchedule:
    use_case_id: UseCaseId
    schedule: Schedule
    owner: UserId
    owner_name: str
    saved_at: datetime
    last_slot_started: datetime | None

    def slots(self, now: datetime) -> Slots:
        return slots(self.schedule, now)

    @property
    def principal(self) -> Principal:
        """The schedule owner as the person who starts its checks."""
        return Principal(self.owner, frozenset({Role.OPERATOR}), self.owner_name)


def _saved(row: Mapping[str, Any]) -> SavedSchedule:
    return SavedSchedule(
        UseCaseId(row["use_case_id"]),
        Schedule(row["day"], row["at"], row["time_zone"]),
        UserId(row["owner_id"]),
        row["owner_name"],
        row["saved_at"],
        row["last_slot_started"],
    )


class ScheduleBook:
    """The schedules kept in our database, one for each watchlist."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, use_case_id: UseCaseId) -> SavedSchedule | None:
        async with self._db.connection("orchestration") as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM orchestration.schedules WHERE use_case_id = %s", (use_case_id,)
                )
            ).fetchone()
        return None if row is None else _saved(row)

    async def save(
        self, use_case_id: UseCaseId, schedule: Schedule, owner: Principal
    ) -> SavedSchedule:
        """Saving makes the caller the schedule owner."""
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "INSERT INTO orchestration.schedules (use_case_id, day, at, time_zone, "
                    "owner_id, owner_name, saved_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (use_case_id) DO UPDATE SET day = EXCLUDED.day, "
                    "at = EXCLUDED.at, time_zone = EXCLUDED.time_zone, "
                    "owner_id = EXCLUDED.owner_id, owner_name = EXCLUDED.owner_name, "
                    "saved_at = EXCLUDED.saved_at RETURNING *",
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
            rows = await (
                await conn.execute("SELECT * FROM orchestration.schedules ORDER BY use_case_id")
            ).fetchall()
        return [_saved(row) for row in rows]

    async def record_slot(self, use_case_id: UseCaseId, slot: datetime) -> None:
        """Remembers the newest slot started. An older slot never moves it back."""
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.schedules SET last_slot_started = %s "
                "WHERE use_case_id = %s AND (last_slot_started IS NULL OR last_slot_started < %s)",
                (slot, use_case_id, slot),
            )


class CheckSpecs(Protocol):
    """What a scheduled check needs from the use case builder, which orchestration may not
    import. None means there is nothing to check, for example an empty watchlist."""

    async def check_spec(self, use_case_id: UseCaseId) -> RunSpec | None: ...


class ScheduleTicker:
    def __init__(self, db: Database, book: ScheduleBook, specs: CheckSpecs, runs: RunStarter):
        self._db = db
        self._book = book
        self._specs = specs
        self._runs = runs

    async def tick(self) -> list[RunId]:
        """Starts one check for each schedule that is due and answers the runs it started.

        A repeated tick finds the slot already started, and the idempotency key stops a tick
        that died between starting the run and recording the slot from starting it twice."""
        now = self._db.clock()
        started: list[RunId] = []
        for saved in await self._book.all():
            slot = due_slot(saved.schedule, saved.saved_at, saved.last_slot_started, now)
            if slot is None:
                continue
            try:
                run_id = await self._start(saved, slot)
            except Exception:
                log.exception("could not start the scheduled check of %s", saved.use_case_id)
                continue
            if run_id is not None:
                started.append(run_id)
        return started

    async def _start(self, saved: SavedSchedule, slot: datetime) -> RunId | None:
        spec = await self._specs.check_spec(saved.use_case_id)
        run_id: RunId | None = None
        if spec is not None:
            result = await self._runs.start_run(
                replace(spec, trigger="schedule"),
                saved.principal,
                f"schedule:{saved.use_case_id}:{slot.isoformat()}",
            )
            run_id = result.run_id if result.created else None
        await self._book.record_slot(saved.use_case_id, slot)
        return run_id
