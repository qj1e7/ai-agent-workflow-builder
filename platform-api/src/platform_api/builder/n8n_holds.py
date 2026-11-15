"""Open in n8n and Take back (ENGINE-PLAN 2.5, 2.9, D14, D15). A workflow sits in one n8n project:
Open in n8n transfers it to the person's own space, where only they see it, and Take back
transfers it to the platform's project. Each move is read back, and a move that lost the
workflow's settings, which carry its error workflow, time zone and saved progress, puts them back
or moves it no further. The platform takes back by itself every workflow held by someone who may
hold none now: whose n8n access ended, or while staff access is off or the allow list unproven."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    attach_keys,
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
    "n8n has not finished moving this workflow, so nothing else changes in it until it is back "
    "where the platform keeps it. Try again in a few minutes."
)
GONE_BEFORE = "n8n no longer has this workflow."
NOT_FINISHED = "n8n did not finish moving the workflow, so it is not set up. Try again in a minute."
MOVE_GRACE = timedelta(minutes=2)
"""How long a move's mark is left to the Open in n8n that set it, before the settle loop moves
the workflow back."""
STRAYS_EVERY = timedelta(minutes=1)
TAKE_IT_BACK = "Take it back to change it here."


def ask_for_it(name: str) -> str:
    """For someone who may not take it back: who can."""
    return f"Ask {name}, or anyone with n8n access, to take it back."


NOT_YOURS = (
    "Only the person who has it open, or someone with n8n access, can take it back. "
    "An admin can add n8n access in Settings."
)


class StaffPort(Protocol):
    async def access(self, person: UserId) -> StaffAccess: ...

    async def display_of(self, person: UserId) -> str: ...

    async def recheck(self, person: UserId) -> None:
        """Asks n8n whether the person's account is still there, and forgets it when not."""
        ...


class Keys(Protocol):
    """The platform's keys in n8n, which never leave its project (ADR 0045, as amended)."""

    async def sweep(self) -> object:
        """The credential sweep, so no key a member added is left anywhere."""
        ...

    async def clear(self) -> object:
        """The same sweep, marking no workflow."""
        ...

    async def made(self) -> dict[str, str]: ...


class N8nMoves(Protocol):
    async def look(self, workflow_id: str) -> N8nWorkflow | None: ...

    async def keep_keys(
        self, workflow_id: str, expected_draft: str, made: Mapping[str, str]
    ) -> Written | ChangedInN8n: ...

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


async def _mark(uow: UnitOfWork, use_case_id: str) -> None:
    await uow.conn.execute(
        "UPDATE builder.use_cases SET n8n_stranded_at = coalesce(n8n_stranded_at, %s)"
        " WHERE use_case_id = %s",
        (uow.now, use_case_id),
    )


async def _unmark(uow: UnitOfWork, use_case_id: str) -> None:
    await uow.conn.execute(
        "UPDATE builder.use_cases SET n8n_stranded_at = NULL WHERE use_case_id = %s",
        (use_case_id,),
    )


async def _strand(uow: UnitOfWork, use_case_id: str) -> HoldRefused:
    await _mark(uow, use_case_id)
    log.error("%s may sit outside the platform's n8n project; release moves it back", use_case_id)
    return HoldRefused(503, STRANDED)


async def let_go(uow: UnitOfWork, use_case_id: str, by: UserId | None) -> None:
    """Ends the hold on record. `by` is who took it back, or None when the platform did."""
    await uow.conn.execute(
        "UPDATE builder.use_cases SET held_by = NULL, held_since = NULL, n8n_stranded_at = NULL,"
        " n8n_key_finding = NULL, n8n_key_found_at = NULL WHERE use_case_id = %s",
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
        keys: Keys | None = None,
    ) -> None:
        self._db = db
        self._n8n = n8n
        self._staff = staff
        self._zone = zone
        self._keys = keys
        self._strays_at: datetime | None = None

    async def holder(self, use_case_id: str) -> Held | None:
        async with self._db.connection("builder") as conn:
            return await held_in(conn, use_case_id)

    async def words(self, held: Held) -> str:
        return held_words(await self._staff.display_of(held.by), held.since, self._zone)

    async def refused_while_held(
        self, conn: Connection, use_case_id: str, actor: UserId
    ) -> HeldInN8n | None:
        """Read with the workflow's row locked, so no Open in n8n crosses the write. A workflow
        a failed move stranded waits too, until it is back. The words tell the actor to take it
        back only when take_back would let them."""
        row = await (await conn.execute(_ROW, (use_case_id,))).fetchone()
        held = None if row is None else held_of(use_case_id, row)
        if held is not None:
            name = await self._staff.display_of(held.by)
            may = actor == held.by or isinstance(await self._staff.access(actor), CanOpen)
            then = TAKE_IT_BACK if may else ask_for_it(name)
            return HeldInN8n(f"{held_words(name, held.since, self._zone)} {then}")
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
        holds changes nothing. The move is marked in its own committed step before n8n moves
        anything, so a hold that fails to save after the move still leaves the mark, and the
        settle loop moves the workflow back."""
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
            if row["n8n_stranded_at"] is not None:
                return HoldRefused(409, STRANDED)
            await _mark(uow, use_case_id)
        workflow_id = str(row["n8n_workflow_id"])
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, use_case_id, alone=True)
            await uow.conn.execute(_ROW + " FOR UPDATE", (use_case_id,))
            try:
                project = await self._n8n.member_project(access.n8n_user_id)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not read n8n's projects: %s", error)
                project = None
            if project is None:
                await _unmark(uow, use_case_id)
                await self._staff.recheck(actor.user_id)
                return HoldRefused(503, NO_SPACE)
            if (refused := await self._swept()) is not None:
                await _unmark(uow, use_case_id)
                return refused
            match await self._move(workflow_id, project):
                case _Stranded():
                    return HoldRefused(503, STRANDED)
                case _Gone():
                    await _unmark(uow, use_case_id)
                    return HoldRefused(409, GONE)
                case HoldRefused() as refused:
                    await _unmark(uow, use_case_id)
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
                case _Moved():
                    await self._keys_back(row["n8n_workflow_id"])
                case _Gone():
                    pass
        await let_go(uow, use_case_id, by)
        log.info("%s took %s back", by or "the platform", use_case_id)
        return None

    async def _swept(self) -> HoldRefused | None:
        """The credential sweep before a workflow opens, so no key a member added waits in
        their space."""
        if self._keys is None:
            return None
        try:
            await self._keys.sweep()
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not sweep n8n's keys before a workflow opens: %s", error)
            return HoldRefused(503, NOT_MOVED)
        return None

    async def _keys_back(self, workflow_id: str) -> None:
        """Before anything runs once it is back: every key a member added goes, and the draft's
        blocks name the platform's key for their system again, whatever the member's editor kept
        or dropped. A version they published is graded with the keys it names, and our first
        block stops its runs while it names a key the platform did not make. What n8n does not
        take now, the next sweep and the next take-back do."""
        if self._keys is None:
            return
        try:
            await self._keys.clear()
            workflow = await self._n8n.look(workflow_id)
            if workflow is None:
                return
            made = await self._keys.made()
            if attach_keys(workflow.document, made) == workflow.document:
                return
            kept = await self._n8n.keep_keys(workflow_id, workflow.version_id, made)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not put the platform's keys back on %s: %s", workflow_id, error)
            return
        if isinstance(kept, ChangedInN8n):
            log.warning("%s changed in n8n as its keys went back on", workflow_id)

    async def take_in(self, workflow_id: str) -> HoldRefused | None:
        """Moves a workflow made in n8n, which no use case names yet, to the platform's project,
        read back as every move is (E15). None once it is there. Moving one already there changes
        nothing."""
        home = await self._n8n.platform_project()
        if home is None:
            return HoldRefused(503, NO_HOME)
        return await self.send_back(workflow_id, home)

    async def send_back(self, workflow_id: str, project_id: str) -> HoldRefused | None:
        """Moves a workflow no use case names to a project, such as back to its maker's space
        when its set-up is refused after the move. None once it is there."""
        match await self._move(workflow_id, project_id):
            case _Moved():
                return None
            case _Gone():
                return HoldRefused(404, GONE_BEFORE)
            case _Stranded():
                return HoldRefused(503, NOT_FINISHED)
            case HoldRefused() as refused:
                return refused

    async def release(self) -> list[str]:
        """Takes back every workflow whose holder may hold none now, and moves back every one a
        move left marked. Once a minute it also asks n8n where each workflow nobody holds sits,
        and marks one found outside the platform's project, so it comes back too."""
        now = self._db.clock()
        if self._strays_at is None or now - self._strays_at >= STRAYS_EVERY:
            self._strays_at = now
            await self._mark_strays()
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT use_case_id FROM builder.use_cases"
                    " WHERE held_by IS NOT NULL OR n8n_stranded_at IS NOT NULL"
                )
            ).fetchall()
        taken: list[str] = []
        for row in rows:
            try:
                if await self._release_one(row["use_case_id"]):
                    taken.append(row["use_case_id"])
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not take %s back from n8n: %s", row["use_case_id"], error)
        return taken

    async def _release_one(self, use_case_id: str) -> bool:
        """Decided again under the workflow's lock, so an Open in n8n in flight is never undone:
        its own mark is left alone for MOVE_GRACE."""
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, use_case_id, alone=True)
            row = await (await uow.conn.execute(_ROW + " FOR UPDATE", (use_case_id,))).fetchone()
            if row is None:
                return False
            held = held_of(use_case_id, row)
            if held is not None and isinstance(await self._staff.access(held.by), CanOpen):
                return False
            marked = row["n8n_stranded_at"]
            if held is None and (marked is None or uow.now - marked < MOVE_GRACE):
                return False
            return await self.back_in(uow, use_case_id, None) is None

    async def _mark_strays(self) -> None:
        home = await self._n8n.platform_project()
        if home is None:
            return
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT use_case_id, n8n_workflow_id FROM builder.use_cases"
                    " WHERE engine = 'own' AND n8n_workflow_id IS NOT NULL AND held_by IS NULL"
                    " AND n8n_stranded_at IS NULL AND deleted_at IS NULL"
                    " AND deleted_in_n8n_at IS NULL"
                )
            ).fetchall()
        for row in rows:
            try:
                where = await self._n8n.home(row["n8n_workflow_id"])
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not read where %s sits: %s", row["n8n_workflow_id"], error)
                continue
            if where is None or where == home:
                continue
            log.error("%s sits outside the platform's n8n project with nobody holding it", row)
            async with self._db.transaction("builder") as uow:
                await uow.conn.execute(
                    "UPDATE builder.use_cases SET n8n_stranded_at = %s"
                    " WHERE use_case_id = %s AND held_by IS NULL AND n8n_stranded_at IS NULL",
                    (uow.now - MOVE_GRACE, row["use_case_id"]),
                )

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
