"""Open in n8n and Take back (ENGINE-PLAN 2.5, 2.9, D14, D15). A workflow sits in one n8n project:
Open in n8n transfers it to the person's own space, where only they see it, and Take back
transfers it to the platform's project. Each move is read back, and a move that lost the
workflow's settings, which carry its error workflow, time zone and saved progress, puts them back
or moves it no further. The platform takes back by itself every workflow held by someone who may
hold none now: whose n8n access ended, or while staff access is off or the allow list unproven."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from platform_api.builder.versions import settings_changed
from platform_api.db import Connection, Database, UnitOfWork, hold_workflow
from platform_api.orchestration import (
    CanOpen,
    ChangedInN8n,
    N8nError,
    N8nWorkflow,
    NoN8nAccess,
    StaffAccess,
    Written,
)
from platform_api.settings import TEAM_TIME_ZONE
from platform_api.shared import Principal, UserId

log = logging.getLogger(__name__)

DRAFT = "Turn it on first. A draft can't be opened in n8n."
NOT_OWN = "This workflow has no n8n workflow of its own yet."
GONE = "This workflow was deleted in n8n, so it can't be opened there."
NO_SPACE = "n8n did not say where your n8n space is. Nothing changed. Try again."
NO_HOME = "No bootstrap has recorded the platform's n8n project yet. Nothing changed."
NOT_MOVED = "n8n did not move the workflow. Nothing changed. Try again."
SETTINGS_LOST = "n8n lost the workflow's settings in the move, so it stayed where it was."
STRANDED = (
    "n8n did not finish moving this workflow, so the platform is moving it back to its own "
    "n8n project. Nothing else changes in it until then. Try again in a minute."
)
TAKE_IT_BACK = "Take it back to change it here."
NOT_YOURS = (
    "Only the person who has it open, or someone with n8n access, can take it back. "
    "An admin can add n8n access in Settings."
)


class StaffPort(Protocol):
    async def access(self, person: UserId) -> StaffAccess: ...

    async def display_of(self, person: UserId) -> str: ...


class N8nMoves(Protocol):
    async def look(self, workflow_id: str) -> N8nWorkflow | None: ...

    async def home(self, workflow_id: str) -> str | None: ...

    async def member_project(self, n8n_user_id: str) -> str | None: ...

    async def platform_project(self) -> str | None: ...

    async def move(self, workflow_id: str, project_id: str) -> None: ...

    async def triggers_live(self, workflow_id: str, version_id: str) -> None:
        """Returns once n8n has this version live with every trigger. Raises N8nError when it
        does not in time."""
        ...

    async def keep_settings(
        self, workflow_id: str, expected_draft: str, settings: Mapping[str, Any]
    ) -> Written | ChangedInN8n: ...


@dataclass(frozen=True)
class Held:
    use_case_id: str
    workflow_id: str
    by: UserId
    since: datetime


@dataclass(frozen=True)
class Free:
    use_case_id: str
    workflow_id: str


@dataclass(frozen=True)
class HoldRefused:
    status: int
    """403 when the person may not, 409 when not now, 503 when n8n did not do it."""
    words: str


@dataclass(frozen=True)
class HeldInN8n:
    """A platform write refused while someone holds the workflow in n8n (D15)."""

    words: str


@dataclass(frozen=True)
class _Moved:
    pass


@dataclass(frozen=True)
class _Stranded:
    """A move that failed and could not be undone: the workflow may sit outside the platform's
    project with nobody holding it."""


@dataclass(frozen=True)
class _Gone:
    """n8n no longer has the workflow, so there is nothing to move."""


type _MoveResult = _Moved | HoldRefused | _Stranded | _Gone

_ROW = (
    "SELECT engine, n8n_workflow_id, draft, deleted_at, deleted_in_n8n_at, held_by, held_since,"
    " n8n_stranded_at FROM builder.use_cases WHERE use_case_id = %s"
)


def held_words(name: str, since: datetime, zone: ZoneInfo = TEAM_TIME_ZONE) -> str:
    return f"{name} has it open in n8n since {since.astimezone(zone):%H:%M}."


async def held_in(conn: Connection, use_case_id: str) -> Held | None:
    row = await (await conn.execute(_ROW, (use_case_id,))).fetchone()
    return None if row is None else held_of(use_case_id, row)


def held_of(use_case_id: str, row: Mapping[str, Any]) -> Held | None:
    if row["held_by"] is None:
        return None
    return Held(use_case_id, row["n8n_workflow_id"], UserId(row["held_by"]), row["held_since"])


async def _strand(uow: UnitOfWork, use_case_id: str) -> HoldRefused:
    await uow.conn.execute(
        "UPDATE builder.use_cases SET n8n_stranded_at = coalesce(n8n_stranded_at, %s)"
        " WHERE use_case_id = %s",
        (uow.now, use_case_id),
    )
    log.error("%s may sit outside the platform's n8n project; release moves it back", use_case_id)
    return HoldRefused(503, STRANDED)


async def let_go(uow: UnitOfWork, use_case_id: str, by: UserId | None) -> None:
    """Ends the hold on record. `by` is who took it back, or None when the platform did."""
    await uow.conn.execute(
        "UPDATE builder.use_cases SET held_by = NULL, held_since = NULL, n8n_stranded_at = NULL"
        " WHERE use_case_id = %s",
        (use_case_id,),
    )
    await uow.conn.execute(
        "UPDATE builder.n8n_holds SET taken_back_by = %s, taken_back_at = %s"
        " WHERE use_case_id = %s AND taken_back_at IS NULL",
        (by, uow.now, use_case_id),
    )


class Holding:
    def __init__(
        self,
        db: Database,
        n8n: N8nMoves,
        staff: StaffPort,
        zone: ZoneInfo = TEAM_TIME_ZONE,
    ) -> None:
        self._db = db
        self._n8n = n8n
        self._staff = staff
        self._zone = zone

    async def holder(self, use_case_id: str) -> Held | None:
        async with self._db.connection("builder") as conn:
            return await held_in(conn, use_case_id)

    async def words(self, held: Held) -> str:
        return held_words(await self._staff.display_of(held.by), held.since, self._zone)

    async def refused_while_held(self, conn: Connection, use_case_id: str) -> HeldInN8n | None:
        """Read with the workflow's row locked, so no Open in n8n crosses the write. A workflow
        a failed move stranded waits too, until it is back."""
        row = await (await conn.execute(_ROW, (use_case_id,))).fetchone()
        held = None if row is None else held_of(use_case_id, row)
        if held is not None:
            return HeldInN8n(f"{await self.words(held)} {TAKE_IT_BACK}")
        if row is not None and row["n8n_stranded_at"] is not None:
            return HeldInN8n(STRANDED)
        return None

    async def holds(self, person: UserId) -> bool:
        async with self._db.connection("builder") as conn:
            row = await (
                await conn.execute(
                    "SELECT 1 FROM builder.use_cases WHERE held_by = %s LIMIT 1", (person,)
                )
            ).fetchone()
        return row is not None

    async def open(self, use_case_id: str, actor: Principal) -> Held | HoldRefused | None:
        """Transfers the workflow to the actor's own n8n space. Opening one the actor already
        holds changes nothing."""
        access = await self._staff.access(actor.user_id)
        if not isinstance(access, CanOpen):
            return HoldRefused(403 if isinstance(access, NoN8nAccess) else 409, access.words)
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, use_case_id, alone=True)
            row = await (await uow.conn.execute(_ROW + " FOR UPDATE", (use_case_id,))).fetchone()
            if row is None or row["deleted_at"] is not None:
                return None
            if (refused := _cannot_open(row)) is not None:
                return refused
            held = held_of(use_case_id, row)
            if held is not None and held.by == actor.user_id:
                return held
            if held is not None:
                return HoldRefused(409, await self.words(held))
            workflow_id = row["n8n_workflow_id"]
            project = await self._n8n.member_project(access.n8n_user_id)
            if project is None:
                return HoldRefused(503, NO_SPACE)
            match await self._move(workflow_id, project):
                case _Stranded():
                    return await _strand(uow, use_case_id)
                case _Gone():
                    return HoldRefused(409, GONE)
                case HoldRefused() as refused:
                    return refused
                case _Moved():
                    pass
            await uow.conn.execute(
                "UPDATE builder.use_cases SET held_by = %s, held_since = %s, n8n_stranded_at = NULL"
                " WHERE use_case_id = %s",
                (actor.user_id, uow.now, use_case_id),
            )
            await uow.conn.execute(
                "INSERT INTO builder.n8n_holds (use_case_id, held_by, opened_at)"
                " VALUES (%s, %s, %s)",
                (use_case_id, actor.user_id, uow.now),
            )
            log.info("%s opened %s in n8n", actor.user_id, use_case_id)
            return Held(use_case_id, workflow_id, actor.user_id, uow.now)

    async def take_back(
        self, use_case_id: str, actor: Principal | None
    ) -> Free | HoldRefused | None:
        """Transfers the workflow back to the platform's project: by the person who holds it,
        by someone with n8n access, or by the platform itself as None. Taking back one nobody
        holds changes nothing."""
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, use_case_id, alone=True)
            row = await (await uow.conn.execute(_ROW + " FOR UPDATE", (use_case_id,))).fetchone()
            if row is None:
                return None
            held = held_of(use_case_id, row)
            if held is None and row["n8n_stranded_at"] is None:
                return Free(use_case_id, row["n8n_workflow_id"])
            if (
                held is not None
                and actor is not None
                and actor.user_id != held.by
                and not isinstance(await self._staff.access(actor.user_id), CanOpen)
            ):
                return HoldRefused(403, NOT_YOURS)
            refused = await self.back_in(uow, use_case_id, None if actor is None else actor.user_id)
            return refused or Free(use_case_id, row["n8n_workflow_id"])

    async def back_in(
        self, uow: UnitOfWork, use_case_id: str, by: UserId | None
    ) -> HoldRefused | None:
        """Takes the workflow back inside the caller's transaction, which holds its row. The hold
        and any strand end only once the workflow is back in the platform's project, or n8n no
        longer has it. Nothing to do when nobody holds it and no move stranded it."""
        row = await (await uow.conn.execute(_ROW, (use_case_id,))).fetchone()
        if row is None:
            return None
        if held_of(use_case_id, row) is None and row["n8n_stranded_at"] is None:
            return None
        if row["deleted_in_n8n_at"] is None:
            home = await self._n8n.platform_project()
            if home is None:
                return HoldRefused(503, NO_HOME)
            match await self._move(row["n8n_workflow_id"], home):
                case _Stranded():
                    return await _strand(uow, use_case_id)
                case HoldRefused() as refused:
                    return refused
                case _Moved() | _Gone():
                    pass
        await let_go(uow, use_case_id, by)
        log.info("%s took %s back", by or "the platform", use_case_id)
        return None

    async def release(self) -> list[str]:
        """Takes back every workflow whose holder may hold none now."""
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT use_case_id, held_by FROM builder.use_cases"
                    " WHERE held_by IS NOT NULL OR n8n_stranded_at IS NOT NULL"
                )
            ).fetchall()
        taken: list[str] = []
        for row in rows:
            holder = row["held_by"]
            if holder is not None and isinstance(await self._staff.access(UserId(holder)), CanOpen):
                continue
            try:
                back = await self.take_back(row["use_case_id"], None)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not take %s back from n8n: %s", row["use_case_id"], error)
                continue
            if isinstance(back, Free):
                taken.append(row["use_case_id"])
        return taken

    async def _move(self, workflow_id: str, project: str) -> _MoveResult:
        """Moves the workflow and reads it back. n8n takes a published workflow off and puts it
        back on as it moves it, so the move waits for every trigger to be live again. A move that
        changed the version n8n runs or the settings puts the settings back, or else moves it
        back where it was."""
        try:
            before = await self._n8n.look(workflow_id)
            if before is None:
                return _Gone()
            was = await self._n8n.home(workflow_id)
            if was == project:
                return _Moved()
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read %s in n8n: %s", workflow_id, error)
            return HoldRefused(503, NOT_MOVED)
        try:
            await self._n8n.move(workflow_id, project)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("n8n did not say whether it moved %s: %s", workflow_id, error)
            try:
                if await self._n8n.home(workflow_id) == was:
                    return HoldRefused(503, NOT_MOVED)
            except N8nError, httpx.HTTPError:
                return _Stranded()
        try:
            if before.active_version_id is not None:
                await self._n8n.triggers_live(workflow_id, before.active_version_id)
            after = await self._n8n.look(workflow_id)
            if after is None or await self._n8n.home(workflow_id) != project:
                return HoldRefused(503, NOT_MOVED)
            if after.active_version_id == before.active_version_id and not settings_changed(
                before.document.get("settings"), after.document.get("settings")
            ):
                return _Moved()
            if await self._kept_settings(workflow_id, before, after):
                return _Moved()
            refused = HoldRefused(503, SETTINGS_LOST)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("n8n moved %s but did not finish: %s", workflow_id, error)
            refused = HoldRefused(503, NOT_MOVED)
        if was is None:
            log.error(
                "n8n moved %s from a project it did not name, so it can't go back", workflow_id
            )
            return _Stranded()
        try:
            await self._n8n.move(workflow_id, was)
        except (N8nError, httpx.HTTPError) as error:
            log.error("could not move %s back to %s: %s", workflow_id, was, error)
            return _Stranded()
        return refused

    async def _kept_settings(
        self, workflow_id: str, before: N8nWorkflow, after: N8nWorkflow
    ) -> bool:
        """Puts back the settings a move lost. A move that changed the version n8n runs is not
        put right here."""
        log.warning("n8n changed %s as it moved it, which the platform puts right", workflow_id)
        if after.active_version_id != before.active_version_id:
            return False
        settings: dict[str, Any] = before.document.get("settings") or {}
        kept = await self._n8n.keep_settings(workflow_id, after.version_id, settings)
        now = await self._n8n.look(workflow_id)
        return (
            isinstance(kept, Written)
            and now is not None
            and not settings_changed(settings, now.document.get("settings"))
        )


def _cannot_open(row: Mapping[str, Any]) -> HoldRefused | None:
    if row["engine"] != "own" or row["n8n_workflow_id"] is None:
        return HoldRefused(409, NOT_OWN)
    if row["deleted_in_n8n_at"] is not None:
        return HoldRefused(409, GONE)
    if row["draft"]:
        return HoldRefused(409, DRAFT)
    return None
