import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from platform_api.db import Connection, Database
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


type ScheduleHold = Literal["owner_removed", "owner_not_an_operator"]
"""Why a schedule starts no run: its owner has left the People list, or is no longer an
Operator."""

_HOLD_WORDS: dict[ScheduleHold, str] = {
    "owner_removed": "has left the People list",
    "owner_not_an_operator": "is no longer an Operator",
}


@dataclass(frozen=True)
class SavedSchedule:
    use_case_id: UseCaseId
    schedule: Schedule
    owner: UserId
    owner_name: str
    saved_at: datetime
    last_slot_started: datetime | None
    owner_roles: frozenset[Role] | None
    """The owner's roles on the People list now. None once they have left it."""

    def slots(self, now: datetime) -> Slots:
        return slots(self.schedule, now)

    def next_run(self, now: datetime) -> datetime | None:
        """The first slot after now, or None while the schedule is held."""
        return None if self.held is not None else self.slots(now).next

    @property
    def starter(self) -> Principal | ScheduleHold:
        """Who starts the schedule's runs: its owner, with the roles they hold now. While the
        owner can no longer run it, why the schedule is held instead. It starts again when the
        owner is an Operator again, or when another Operator saves it and so becomes its owner."""
        if self.owner_roles is None:
            return "owner_removed"
        if Role.OPERATOR not in self.owner_roles:
            return "owner_not_an_operator"
        return Principal(self.owner, self.owner_roles, self.owner_name)

    @property
    def held(self) -> ScheduleHold | None:
        starter = self.starter
        return None if isinstance(starter, Principal) else starter


# Each schedule is read with its owner's entry on the People list as it is now.
_WITH_OWNER = (
    "SELECT s.*, p.is_operator AS owner_is_operator, p.is_approver AS owner_is_approver "
    "FROM {source} s LEFT JOIN orchestration.people p "
    "ON p.id = s.owner_id AND p.removed_at IS NULL"
)
_SCHEDULES = _WITH_OWNER.format(source="orchestration.schedules")


def _owner_roles(row: Mapping[str, Any]) -> frozenset[Role] | None:
    if row["owner_is_operator"] is None:
        return None
    flags = ((Role.OPERATOR, row["owner_is_operator"]), (Role.APPROVER, row["owner_is_approver"]))
    return frozenset(role for role, on in flags if on)


def _saved(row: Mapping[str, Any]) -> SavedSchedule:
    return SavedSchedule(
        UseCaseId(row["use_case_id"]),
        Schedule(row["day"], row["at"], row["time_zone"]),
        UserId(row["owner_id"]),
        row["owner_name"],
        row["saved_at"],
        row["last_slot_started"],
        _owner_roles(row),
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

    async def use_up_slot(self, use_case_id: UseCaseId, slot: datetime) -> None:
        """Remembers the newest slot used up, by a check or by a skip while paused. An older slot
        never moves it back."""
        async with self._db.transaction("orchestration") as uow:
            await _use_up(uow.conn, use_case_id, slot)

    async def use_up_slots_until(self, use_case_id: UseCaseId, now: datetime) -> None:
        """Uses up every slot at or before now, so a workflow back on after missing a slot waits
        for its next one."""
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT day, at, time_zone FROM orchestration.schedules "
                    "WHERE use_case_id = %s FOR UPDATE",
                    (use_case_id,),
                )
            ).fetchone()
            if row is not None:
                schedule = Schedule(row["day"], row["at"], row["time_zone"])
                await _use_up(uow.conn, use_case_id, slots(schedule, now).latest)


async def _use_up(conn: Connection, use_case_id: UseCaseId, slot: datetime) -> None:
    await conn.execute(
        "UPDATE orchestration.schedules SET last_slot_started = %s "
        "WHERE use_case_id = %s AND (last_slot_started IS NULL OR last_slot_started < %s)",
        (slot, use_case_id, slot),
    )


@dataclass(frozen=True)
class NotOn:
    state: Literal["paused", "deleted"]


class CheckSpecs(Protocol):
    """What a scheduled check needs from the use case builder, which orchestration may not
    import. None means there is nothing to check, for example an empty watchlist."""

    async def check_spec(self, use_case_id: UseCaseId) -> RunSpec | NotOn | None: ...


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
        """Starts the slot's run as the schedule owner, with the roles they hold now. A held
        schedule, like a paused workflow, uses its slot up and starts nothing."""
        run_id: RunId | None = None
        starter = saved.starter
        if not isinstance(starter, Principal):
            log.info(
                "skipped the scheduled check of %s, because its owner %s %s",
                saved.use_case_id,
                saved.owner,
                _HOLD_WORDS[starter],
            )
        else:
            match await self._specs.check_spec(saved.use_case_id):
                case RunSpec() as spec:
                    result = await self._runs.start_run(
                        replace(spec, trigger="schedule"),
                        starter,
                        f"schedule:{saved.use_case_id}:{slot.isoformat()}",
                    )
                    run_id = result.run_id if result.created else None
                case NotOn(state):
                    log.info(
                        "skipped the scheduled check of %s, which is %s", saved.use_case_id, state
                    )
                case None:
                    pass
        await self._book.use_up_slot(saved.use_case_id, slot)
        return run_id
