"""The credential sweep, seen from the workflows (ENGINE-PLAN E17, ADR 0045 section 2).

Every minute, and whenever a workflow opens in n8n or comes back, the platform deletes every key
in n8n it did not make, and makes its own again where they are gone or changed. Its own keys
never leave its project. This module says what that means for the workflows: a key removed from
someone's n8n space while they hold a workflow marks that workflow Needs a fix, and every
workflow in the platform's own n8n project whose published version n8n would run unchecked
(`unchecked`) is taken off in n8n, and marked Needs a fix when a use case names it. In the
platform's project n8n lets a workflow use every key there is, so no such version stays live
there, whoever published it and however it got there. Nothing is deleted.

Once a day it also plants a key of its own making that it does not record as its own, which the
next sweep must delete within a minute, as the self-test of the whole guard.
"""

import asyncio
import contextlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import httpx

from platform_api.db import Database
from platform_api.orchestration import (
    KeyRemoved,
    ListedWorkflow,
    N8nError,
    unchecked,
)
from platform_api.shared import UserId

log = logging.getLogger(__name__)

SWEEP_EVERY = timedelta(seconds=60)
KEY_ADDED = "A key was added in n8n while it was open there. The platform removed it."
KEY_CHANGED = "One of the platform's keys was changed in n8n while it was open there."
TAKEN_OFF = (
    "The version published in n8n has a block the platform can't check, so the platform took it "
    "off in n8n. Open it in n8n, fix it, and publish it again."
)
UNCHECKED_DRAFT = (
    "Its draft in n8n has a block the platform can't check, so no test run starts until it is "
    "fixed in n8n."
)
KEYS_NOT_BACK = (
    "n8n did not take the platform's keys back on this workflow, so it stays held until it does."
)


class Keys(Protocol):
    async def sweep(self) -> list[KeyRemoved]: ...

    async def made(self) -> dict[str, str]: ...

    async def plant(self) -> str | None: ...


class Spaces(Protocol):
    async def spaces(self) -> Mapping[str, str]:
        """Each member's own space by n8n's id for the member."""
        ...

    async def platform_project(self) -> str | None: ...

    async def workflows_in(self, project_id: str) -> list[ListedWorkflow]: ...

    async def kept(self, workflow_id: str, version_id: str) -> dict[str, Any] | None: ...

    async def go_off(self, workflow_id: str) -> None: ...


class People(Protocol):
    async def people_by_n8n_user(self) -> Mapping[str, UserId]: ...


@dataclass(frozen=True)
class KeysSwept:
    removed: tuple[KeyRemoved, ...]
    marked: tuple[str, ...]
    """The use cases a removed key marks Needs a fix."""
    taken_off: tuple[str, ...]
    """The workflows in the platform's project taken off in n8n, each named by a use case marked
    Needs a fix."""


class KeySweep:
    def __init__(self, db: Database, keys: Keys, n8n: Spaces, people: People) -> None:
        self._db = db
        self._keys = keys
        self._n8n = n8n
        self._people = people
        self._lock = asyncio.Lock()

    async def sweep(self) -> KeysSwept:
        async with self._lock:
            removed = await self._keys.sweep()
            marked = await self._mark(removed)
            taken_off = await self._take_off()
            try:
                await self._keys.plant()
            except (N8nError, httpx.HTTPError) as error:
                log.warning("the sweep's daily self-test did not start: %s", type(error).__name__)
            return KeysSwept(tuple(removed), tuple(marked), tuple(taken_off))

    async def made(self) -> dict[str, str]:
        return await self._keys.made()

    async def clear(self) -> list[KeyRemoved]:
        """The sweep of keys alone, marking nothing, for a take-back that holds the workflow's
        row: a mark there would wait on it, so it does not wait for this sweep's lock either. The
        keys' own lock keeps the two from crossing. The hold ends with that take-back anyway."""
        return await self._keys.sweep()

    async def sweep_forever(self, stop: asyncio.Event, every: timedelta = SWEEP_EVERY) -> None:
        while not stop.is_set():
            try:
                await self.sweep()
            except Exception:
                log.exception("the credential sweep failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), every.total_seconds())

    async def _mark(self, removed: Iterable[KeyRemoved]) -> list[str]:
        """Each workflow held by the person in whose n8n space a key was removed."""
        found = [r for r in removed if r.project is not None]
        if not found:
            return []
        owners = {project: user for user, project in (await self._n8n.spaces()).items()}
        people = await self._people.people_by_n8n_user()
        marked: list[str] = []
        async with self._db.transaction("builder") as uow:
            for key in found:
                person = people.get(owners.get(str(key.project), ""))
                if person is None:
                    continue
                rows = await (
                    await uow.conn.execute(
                        "UPDATE builder.use_cases SET n8n_key_finding = %s, n8n_key_found_at = %s"
                        " WHERE held_by = %s RETURNING use_case_id",
                        (KEY_CHANGED if key.changed else KEY_ADDED, uow.now, person),
                    )
                ).fetchall()
                marked += [row["use_case_id"] for row in rows]
        for use_case_id in marked:
            log.warning("a key was removed while %s was held in n8n", use_case_id)
        return marked

    async def _take_off(self) -> list[str]:
        """Each workflow in the platform's project whose published version n8n would run
        unchecked, named by a use case or not, is taken off in n8n. A use case that names it is
        marked Needs a fix. One whose published version n8n can't show counts too."""
        home = await self._n8n.platform_project()
        if home is None:
            return []
        made = await self._keys.made()
        taken: list[str] = []
        for listed in await self._n8n.workflows_in(home):
            workflow = listed.workflow
            if workflow.active_version_id is None:
                continue
            live = listed.live or await self._n8n.kept(workflow.id, workflow.active_version_id)
            if not unchecked(live or {}, made):
                continue
            try:
                await self._n8n.go_off(workflow.id)
            except (N8nError, httpx.HTTPError) as error:
                log.error("could not take %s off in n8n: %s", workflow.id, error)
                continue
            log.warning("took %s off in n8n: it would run a block unchecked", workflow.id)
            taken.append(workflow.id)
        if taken:
            async with self._db.transaction("builder") as uow:
                await uow.conn.execute(
                    "UPDATE builder.use_cases SET n8n_key_finding = %s, n8n_key_found_at = %s"
                    " WHERE n8n_workflow_id = ANY(%s)",
                    (TAKEN_OFF, uow.now, taken),
                )
        return taken
