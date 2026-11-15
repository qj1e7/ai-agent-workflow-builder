"""The credential sweep, seen from the workflows (ENGINE-PLAN E17, ADR 0045 section 2).

Every minute, and whenever a workflow opens in n8n, the platform deletes every key in n8n it did
not make, makes its own again where they are gone or changed, and puts each key it lent where
the workflow that names it is held. This module says what that means for the workflows: a key
removed from someone's n8n space while they hold a workflow marks that workflow Needs a fix, and
a workflow in the platform's own n8n project that no use case names and that n8n runs with a key
the platform did not make is taken off in n8n. In the platform's project n8n lets a workflow use
every key there is, so that is the only place such a workflow could run with a member's key: one
n8n moved there as its maker's account ended, with the maker's keys, which the platform keeps
but never uses.

Once a day it also plants a key of its own making that it does not record as its own, which the
next sweep must delete within a minute, as the self-test of the whole guard.
"""

import asyncio
import contextlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

import httpx

from platform_api.db import Database
from platform_api.orchestration import (
    KeyRemoved,
    LendRefused,
    ListedWorkflow,
    N8nError,
    credentials_named,
)
from platform_api.shared import UserId

log = logging.getLogger(__name__)

SWEEP_EVERY = timedelta(seconds=60)
KEY_ADDED = "A key was added in n8n while it was open there. The platform removed it."
KEY_CHANGED = "One of the platform's keys was changed in n8n while it was open there."


class Keys(Protocol):
    async def sweep(self) -> list[KeyRemoved]: ...

    async def keep_only(self, held: Iterable[str]) -> None: ...

    async def made(self) -> dict[str, str]: ...

    async def plant(self) -> str | None: ...

    async def lend(
        self, use_case_id: str, project: str, ids: Iterable[str]
    ) -> LendRefused | None: ...

    async def give_back(self, use_case_id: str) -> None: ...

    async def place(self, home: str | None = None) -> list[str]: ...


class Spaces(Protocol):
    async def spaces(self) -> Mapping[str, str]:
        """Each member's own space by n8n's id for the member."""
        ...

    async def platform_project(self) -> str | None: ...

    async def workflows_in(self, project_id: str) -> list[ListedWorkflow]: ...

    async def go_off(self, workflow_id: str) -> None: ...


class People(Protocol):
    async def people_by_n8n_user(self) -> Mapping[str, UserId]: ...


@dataclass(frozen=True)
class KeysSwept:
    removed: tuple[KeyRemoved, ...]
    marked: tuple[str, ...]
    """The use cases a removed key marks Needs a fix."""
    taken_off: tuple[str, ...]
    """The workflows in the platform's project taken off in n8n."""


class KeySweep:
    """Also the key loans Open in n8n and Take back make, so every Open sweeps as the minute
    does."""

    def __init__(self, db: Database, keys: Keys, n8n: Spaces, people: People) -> None:
        self._db = db
        self._keys = keys
        self._n8n = n8n
        self._people = people
        self._lock = asyncio.Lock()

    async def sweep(self) -> KeysSwept:
        async with self._lock:
            await self._keys.keep_only(await self._holding())
            removed = await self._keys.sweep()
            marked = await self._mark(removed)
            taken_off = await self._take_off()
            try:
                await self._keys.plant()
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not plant the credential sweep's daily key: %s", error)
            return KeysSwept(tuple(removed), tuple(marked), tuple(taken_off))

    async def lend(self, use_case_id: str, project: str, ids: Iterable[str]) -> LendRefused | None:
        return await self._keys.lend(use_case_id, project, ids)

    async def give_back(self, use_case_id: str) -> None:
        await self._keys.give_back(use_case_id)

    async def place(self, home: str | None = None) -> list[str]:
        return await self._keys.place(home)

    async def sweep_forever(self, stop: asyncio.Event, every: timedelta = SWEEP_EVERY) -> None:
        while not stop.is_set():
            try:
                await self.sweep()
            except Exception:
                log.exception("the credential sweep failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), every.total_seconds())

    async def _holding(self) -> list[str]:
        """Each use case someone holds, or that is moving in or out of n8n now, whose loans stay."""
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT use_case_id FROM builder.use_cases"
                    " WHERE held_by IS NOT NULL OR n8n_stranded_at IS NOT NULL"
                )
            ).fetchall()
        return [row["use_case_id"] for row in rows]

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
        """Each workflow in the platform's project that no use case names and whose published
        version names a key the platform did not make."""
        home = await self._n8n.platform_project()
        if home is None:
            return []
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT n8n_workflow_id FROM builder.use_cases"
                    " WHERE n8n_workflow_id IS NOT NULL"
                )
            ).fetchall()
        named = {row["n8n_workflow_id"] for row in rows}
        made = await self._keys.made()
        taken: list[str] = []
        for listed in await self._n8n.workflows_in(home):
            workflow = listed.workflow
            if workflow.id in named or listed.live is None:
                continue
            if not credentials_named(listed.live) - made.keys():
                continue
            try:
                await self._n8n.go_off(workflow.id)
            except (N8nError, httpx.HTTPError) as error:
                log.error("could not take %s off in n8n: %s", workflow.id, error)
                continue
            log.warning(
                "took %s off in n8n: it ran with a key the platform did not make", workflow.id
            )
            taken.append(workflow.id)
        return taken
