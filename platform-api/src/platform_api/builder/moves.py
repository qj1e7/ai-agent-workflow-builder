"""The workflows still on the shared run workflow move to n8n workflows of their own (ENGINE-PLAN
2.6, E10), and the workflows n8n lost with its database are saved there again from the versions
the platform kept (Restore to n8n).

Both follow the watchlist's move (watchlist.move_to_n8n): the records name the new n8n workflow
in a commit of its own before it can run, and only then is it put live, so a move cut off
anywhere leaves nothing in n8n that the next one does not find and remove. Only a workflow the
safety checker grades safe is ever saved, and a workflow with a run that has not ended stays
where it is until the run ends, so nothing that run waits for is lost."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from platform_api.builder.in_n8n import discard
from platform_api.builder.lifecycle import is_on, lifecycle_of
from platform_api.builder.n8n_draft import Checked, DraftRefused, N8nNotReady, NotSafe
from platform_api.builder.templates import AGENT_CARDS
from platform_api.builder.versions import Held, Made, Publication, add_version
from platform_api.builder.watchlist import AlreadyOnN8n, MovedToN8n, WaitsForRun, Watchlist
from platform_api.builder.watchlist import Move as WatchlistMove
from platform_api.db import Connection, Database, UnitOfWork, hold_workflow, json
from platform_api.orchestration import (
    KnownOptions,
    N8nDrafts,
    N8nError,
    OpenRuns,
    SavedDraft,
    SavedSchedule,
    Schedule,
    ScheduleBook,
    ScheduleHold,
    grade,
)
from platform_api.shared import UseCaseId, UserId

log = logging.getLogger(__name__)

MOVES_EVERY = timedelta(seconds=60)
NOT_TAKEN = "n8n did not take the workflow. It runs as before."
NOT_LIVE = "n8n did not turn the workflow on. It runs as before."
NOT_BACK = "n8n did not take the workflow back. The next start tries again."
REFUSED_WORDS = (
    "Not running. It could not move to its own n8n workflow: {finding} Fix that step, or ask for"
    " help."
)
NOT_TAKEN_WORDS = (
    "Not running. n8n did not take it yet, so it can't run on its schedule. The platform tries"
    " again every minute. If this stays, ask for help."
)
"""What the workflow's page says while it cannot move, as nothing ticks its schedule (E10)."""

type LayOut = Callable[
    [str, Mapping[str, Any], Schedule | None], Awaitable[Checked | DraftRefused | N8nNotReady]
]
"""The Planner's layout of a use case's version in use, with this schedule, checked and graded."""
type Known = Callable[[], Awaitable[KnownOptions]]


@dataclass(frozen=True)
class ScheduleHeld:
    """Its schedule's owner can no longer start its runs, so it stays as it is, starting none,
    until an Operator saves the schedule and so becomes its owner."""

    hold: ScheduleHold


type Move = MovedToN8n | AlreadyOnN8n | WaitsForRun | ScheduleHeld | N8nNotReady | DraftRefused


@dataclass(frozen=True)
class Restored:
    workflow_id: str


type Restore = Restored | NotSafe | N8nNotReady

_ROW = """
    SELECT u.use_case_id, u.owner, u.paused_at, u.paused_by, u.deleted_at, u.deleted_by,
           u.draft, u.engine, u.n8n_workflow_id, u.deleted_in_n8n_at, u.current_version,
           u.move_refused, u.restoring_in_n8n, v.template, v.name, v.document, v.grade
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
    WHERE u.use_case_id = %s FOR UPDATE OF u
"""
_LEFT = """
    SELECT u.use_case_id FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
    WHERE u.engine = 'shared_run' AND u.deleted_at IS NULL AND v.template = %s
    ORDER BY u.created_at, u.use_case_id
"""
_OWN = """
    SELECT use_case_id FROM builder.use_cases
    WHERE engine = 'own' AND n8n_workflow_id IS NOT NULL AND deleted_at IS NULL
      AND (deleted_in_n8n_at IS NULL OR deleted_in_n8n_at >= %s)
    ORDER BY created_at, use_case_id
"""


async def _hold(uow: UnitOfWork, use_case_id: str) -> Mapping[str, Any] | None:
    """The use case, locked as a pause or a delete locks it, so a move never crosses either."""
    await hold_workflow(uow.conn, use_case_id, alone=True)
    return await (await uow.conn.execute(_ROW, (use_case_id,))).fetchone()


async def _name_in_n8n(uow: UnitOfWork, use_case_id: str, workflow_id: str | None) -> None:
    await uow.conn.execute(
        "UPDATE builder.use_cases SET n8n_workflow_id = %s WHERE use_case_id = %s",
        (workflow_id, use_case_id),
    )


async def _restoring(uow: UnitOfWork, use_case_id: str, workflow_id: str | None) -> None:
    await uow.conn.execute(
        "UPDATE builder.use_cases SET restoring_in_n8n = %s WHERE use_case_id = %s",
        (workflow_id, use_case_id),
    )


async def _says(uow: UnitOfWork, row: Mapping[str, Any], words: str | None) -> None:
    """Keeps why it cannot move, for its page, and logs a refusal only when it is new."""
    if row["move_refused"] == words:
        return
    if words is not None:
        log.error("%s stays on the shared run workflow: %s", row["use_case_id"], words)
    await uow.conn.execute(
        "UPDATE builder.use_cases SET move_refused = %s WHERE use_case_id = %s",
        (words, row["use_case_id"]),
    )


def refusal_words(refused: DraftRefused | N8nNotReady) -> str:
    match refused:
        case DraftRefused(findings=(first, *_)):
            return REFUSED_WORDS.format(finding=first.text)
        case _:
            return NOT_TAKEN_WORDS


async def _authors(conn: Connection, use_case_id: str, owner: UserId) -> list[UserId]:
    """Everyone whose work its versions are: the person who set it up, then each person who
    changed when it runs, in the order they did."""
    rows = await (
        await conn.execute(
            "SELECT changed_by FROM builder.use_case_version_changes"
            " WHERE use_case_id = %s ORDER BY version",
            (use_case_id,),
        )
    ).fetchall()
    return list(dict.fromkeys([owner, *(UserId(row["changed_by"]) for row in rows)]))


def with_error_workflow(document: Mapping[str, Any], error_workflow: str) -> dict[str, Any]:
    """n8n gives the error workflow a new id when it loads it again, so a kept workflow names
    the one n8n holds now."""
    return {
        **document,
        "settings": {**document.get("settings", {}), "errorWorkflow": error_workflow},
    }


class Moves:
    def __init__(
        self,
        db: Database,
        n8n: N8nDrafts,
        runs: OpenRuns,
        schedules: ScheduleBook,
        lay_out: LayOut,
        known: Known,
        watchlist: Watchlist | None = None,
    ) -> None:
        self._db = db
        self._n8n = n8n
        self._runs = runs
        self._schedules = schedules
        self._lay_out = lay_out
        self._known = known
        self._watchlist = watchlist

    async def left(self) -> list[UseCaseId]:
        """The agent workflows still on the shared run workflow. A deleted one stays there, as it
        never runs; restoring it brings it back here."""
        async with self._db.connection("builder") as conn:
            rows = await (await conn.execute(_LEFT, (AGENT_CARDS.key,))).fetchall()
        return [UseCaseId(row["use_case_id"]) for row in rows]

    async def move_all(self) -> dict[str, Move | WatchlistMove | None]:
        """Every workflow left on the shared run workflow, the watchlist first. One that cannot
        move yet says why, and the next pass asks again."""
        moved: dict[str, Move | WatchlistMove | None] = {}
        if self._watchlist is not None:
            moved["watchlist"] = await self._watchlist.move_to_n8n()
        for use_case_id in await self.left():
            try:
                moved[use_case_id] = await self.move(use_case_id)
            except Exception:
                log.exception("could not move %s to n8n", use_case_id)
        return moved

    async def move_forever(self, stop: asyncio.Event, every: timedelta = MOVES_EVERY) -> None:
        """A workflow that waited for its run moves within a pass of the run ending. The first
        pass waits, as the platform moved everything it could as it started."""
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), every.total_seconds())
            if stop.is_set():
                return
            try:
                for use_case_id, move in (await self.move_all()).items():
                    if not isinstance(move, AlreadyOnN8n | WaitsForRun):
                        log.info("the move of %s to n8n: %s", use_case_id, move)
            except Exception:
                log.exception("the moves to n8n failed")

    async def move(self, use_case_id: str) -> Move | None:
        """Puts an agent workflow on an n8n workflow of its own, laid out from its version in use
        with its schedule in the Schedule Trigger, as a new version. Asking again changes
        nothing. None when there is no such agent workflow to move."""
        async with self._db.transaction("builder") as uow:
            row = await _hold(uow, use_case_id)
            if row is None or row["deleted_at"] is not None or row["template"] != AGENT_CARDS.key:
                return None
            if row["engine"] == "own":
                return AlreadyOnN8n()
            if (open_run := await self._runs.open_run(UseCaseId(use_case_id))) is not None:
                log.info("%s moves to n8n once run %s ends", use_case_id, open_run)
                await _says(uow, row, None)
                return WaitsForRun(open_run)
            saved = await self._schedules.get(UseCaseId(use_case_id))
            if saved is not None and saved.held is not None:
                await _says(uow, row, None)
                return ScheduleHeld(saved.held)
            if row["n8n_workflow_id"] is not None:
                await discard(self._n8n, row["n8n_workflow_id"])
            laid = await self._lay_out(use_case_id, row, None if saved is None else saved.schedule)
            if not isinstance(laid, Checked):
                await _says(uow, row, refusal_words(laid))
                return laid
            try:
                draft = await self._n8n.save_draft(laid.document)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not take the workflow of %s: %s", use_case_id, error)
                await _says(uow, row, NOT_TAKEN_WORDS)
                return N8nNotReady(NOT_TAKEN)
            await _name_in_n8n(uow, use_case_id, draft.workflow_id)
        async with self._db.transaction("builder") as uow:
            row = await _hold(uow, use_case_id)
            if row is None or row["engine"] == "own" or row["n8n_workflow_id"] != draft.workflow_id:
                return AlreadyOnN8n()
            if row["deleted_at"] is not None:
                await discard(self._n8n, draft.workflow_id)
                await _name_in_n8n(uow, use_case_id, None)
                return None
            live = is_on(lifecycle_of(row))
            try:
                if live:
                    await self._n8n.go_live(draft.workflow_id, draft.version_id)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not turn the workflow of %s on: %s", use_case_id, error)
                await discard(self._n8n, draft.workflow_id)
                await _name_in_n8n(uow, use_case_id, None)
                await _says(uow, row, NOT_TAKEN_WORDS)
                return N8nNotReady(NOT_LIVE)
            version = await _record(uow, row, draft, laid, live, saved)
        log.info(
            "%s runs as n8n workflow %s from version %d", use_case_id, draft.workflow_id, version
        )
        return MovedToN8n(draft.workflow_id, version)

    async def restore_all(self, asked_at: datetime) -> dict[str, Restore]:
        """After n8n lost its database: each workflow n8n no longer holds is saved there again
        from the version in use, as the platform kept it (ENGINE-PLAN 7, n8n's database lost).
        One marked deleted in n8n since the ask is among them: an older sweep took the loss for
        a deletion. One marked before it was deleted by a person, and stays deleted."""
        async with self._db.connection("builder") as conn:
            rows = await (await conn.execute(_OWN, (asked_at,))).fetchall()
        restored: dict[str, Restore] = {}
        for row in rows:
            try:
                done = await self.restore(row["use_case_id"])
            except Exception:
                log.exception("could not restore %s to n8n", row["use_case_id"])
                done = N8nNotReady(NOT_BACK)
            if done is not None:
                restored[row["use_case_id"]] = done
        return restored

    async def restore(self, use_case_id: str) -> Restore | None:
        """Saves the version in use again as a new n8n workflow, under the move's rules: only when
        it grades safe now, inactive until the records name it, then live when it is on. None
        when n8n still holds the workflow. A restore cut off after the save leaves its workflow
        named as restoring, and the next one removes it and saves again."""
        async with self._db.transaction("builder") as uow:
            row = await _hold(uow, use_case_id)
            if row is None or row["engine"] != "own" or row["deleted_at"] is not None:
                return None
            if row["restoring_in_n8n"] is not None:
                await discard(self._n8n, row["restoring_in_n8n"])
                await _restoring(uow, use_case_id, None)
            lost = row["n8n_workflow_id"]
            try:
                if await self._n8n.look(lost) is not None:
                    return None
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not look for %s in n8n: %s", use_case_id, error)
                return N8nNotReady(NOT_BACK)
            error_workflow = await self._n8n.error_workflow_id()
            if error_workflow is None:
                return N8nNotReady("n8n is not ready yet: its error workflow is not loaded.")
            if row["grade"] != "safe" or row["document"] is None:
                log.error("%s is not restored to n8n: its version in use is not safe", use_case_id)
                return NotSafe()
            document = with_error_workflow(row["document"], error_workflow)
            graded = grade(document, error_workflow, await self._known())
            if graded.grade != "safe":
                log.error("%s is not restored to n8n: %s", use_case_id, graded.findings)
                return NotSafe()
            try:
                draft = await self._n8n.save_draft(document)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not take %s back: %s", use_case_id, error)
                return N8nNotReady(NOT_BACK)
            await _restoring(uow, use_case_id, draft.workflow_id)
        async with self._db.transaction("builder") as uow:
            row = await _hold(uow, use_case_id)
            if row is None or row["restoring_in_n8n"] != draft.workflow_id:
                return None
            try:
                if is_on(lifecycle_of(row)):
                    await self._n8n.go_live(draft.workflow_id, draft.version_id)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not turn %s on again: %s", use_case_id, error)
                await discard(self._n8n, draft.workflow_id)
                await _restoring(uow, use_case_id, None)
                return N8nNotReady(NOT_BACK)
            await _keep_restored(uow, use_case_id, row["current_version"], draft)
        log.info("%s is back in n8n as workflow %s", use_case_id, draft.workflow_id)
        return Restored(draft.workflow_id)

    async def restore_if_asked(self) -> Sequence[Restore]:
        """Bootstrap asks for a restore when it found n8n empty and set it up again. The ask is
        answered once every workflow is back or cannot be, so a workflow n8n could not take yet
        is tried again at the next start."""
        async with self._db.connection("builder") as conn:
            asked = await (
                await conn.execute("SELECT asked_at FROM builder.n8n_restore WHERE id = 1")
            ).fetchone()
        if asked is None:
            return ()
        restored = await self.restore_all(asked["asked_at"])
        if not any(isinstance(done, N8nNotReady) for done in restored.values()):
            async with self._db.transaction("builder") as uow:
                await uow.conn.execute(
                    "DELETE FROM builder.n8n_restore WHERE asked_at = %s", (asked["asked_at"],)
                )
        return list(restored.values())


async def _record(
    uow: UnitOfWork,
    row: Mapping[str, Any],
    draft: SavedDraft,
    laid: Checked,
    live: bool,
    saved: SavedSchedule | None,
) -> int:
    """The moved version's publisher is whoever started its scheduled runs on the shared run
    workflow: the schedule's owner, else the person who set it up (D5). Everyone else whose work
    its versions are joins its runs, so none of them can approve them either. One not live has
    no publisher until someone puts it live, so all of them are its earlier authors."""
    use_case_id = row["use_case_id"]
    owner = UserId(row["owner"])
    publisher = owner if saved is None else saved.owner
    authors = [*await _authors(uow.conn, use_case_id, owner), publisher]
    also = [Publication(p, "portal") for p in dict.fromkeys(authors) if not live or p != publisher]
    version = await add_version(
        uow,
        use_case_id,
        row["current_version"],
        row["current_version"],
        Held(draft.version_id, draft.document, laid.graded.grade),
        Made("moved_to_n8n", None, None),
        Publication(publisher, "portal") if live else None,
        also,
        draft.version_id,
    )
    await uow.conn.execute(
        "UPDATE builder.use_cases SET engine = 'own', move_refused = NULL WHERE use_case_id = %s",
        (use_case_id,),
    )
    return version


async def _keep_restored(
    uow: UnitOfWork, use_case_id: str, version: int, draft: SavedDraft
) -> None:
    """The version in use now names the workflow n8n holds for it, which n8n has again, so it
    is no longer marked deleted there. Its publisher and earlier authors stay, because it is the
    same workflow: only the error workflow's id changed."""
    await uow.conn.execute(
        "UPDATE builder.use_cases SET n8n_workflow_id = %s, n8n_draft_id = %s,"
        " restoring_in_n8n = NULL, deleted_in_n8n_at = NULL WHERE use_case_id = %s",
        (draft.workflow_id, draft.version_id, use_case_id),
    )
    await uow.conn.execute(
        "UPDATE builder.use_case_versions SET n8n_version_id = %s, document = %s"
        " WHERE use_case_id = %s AND version = %s",
        (draft.version_id, json(draft.document), use_case_id, version),
    )
