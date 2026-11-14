"""The versions sweep (ENGINE-PLAN 2.5, D5, D7, D9). Every minute, and when the Portal asks, it
looks at each workflow n8n carries. A version published in n8n's editor that our records do not
hold is fetched, graded against what the editor's lists hold now, and kept as a new version
published in n8n, with its publisher matched by the n8n user id we stored for the person, never
guessed. A workflow n8n no longer has is marked deleted in n8n, its open request is cancelled,
and its runs and versions stay.

The sweep holds the use case's row while it looks, as every platform publish does, so a publish
the Portal is making is never taken for one made in n8n.
"""

import asyncio
import contextlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx

from platform_api.builder.versions import Held, Made, Publication, add_version
from platform_api.db import Database, UnitOfWork
from platform_api.orchestration import (
    KnownOptions,
    N8nDrafts,
    N8nError,
    PublishEvent,
    grade,
    publisher_of,
)
from platform_api.shared import UseCaseId, UserId

log = logging.getLogger(__name__)

SWEEP_EVERY = timedelta(seconds=60)
ASKED_GAP = timedelta(seconds=5)
"""A look the Portal asks for within this long of the last one is not made again."""

_OWN = """
    SELECT u.use_case_id, u.current_version, u.n8n_workflow_id, v.n8n_version_id
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
    WHERE u.engine = 'own' AND u.n8n_workflow_id IS NOT NULL AND NOT u.draft
      AND u.deleted_at IS NULL AND u.deleted_in_n8n_at IS NULL
"""


class N8nAccounts(Protocol):
    async def people_by_n8n_user(self) -> Mapping[str, UserId]:
        """Each person the platform made an n8n account for, by that account's user id."""
        ...


class NoN8nAccounts:
    """Nobody has an n8n account the platform made yet (ENGINE-PLAN E7), so no publish in n8n is
    matched to a person, and a run of such a version stops until an Operator matches them."""

    async def people_by_n8n_user(self) -> Mapping[str, UserId]:
        return {}


class OpenRequests(Protocol):
    async def cancel_for_deleted(self, use_case_id: UseCaseId) -> int:
        """Ends the use case's open request as cancelled, with nothing written, and tells its
        Approvers (D7). How many it ended."""
        ...


class Graders(Protocol):
    async def known(self, adding: Mapping[str, Sequence[str]]) -> KnownOptions: ...


@dataclass(frozen=True)
class Found:
    use_case_id: str
    version: int


@dataclass(frozen=True)
class Gone:
    use_case_id: str


def last_activation(version_id: str, timeline: Sequence[PublishEvent]) -> PublishEvent | None:
    activated = [e for e in timeline if e.version_id == version_id and e.event == "activated"]
    if not activated:
        return None
    return max(enumerate(activated), key=lambda pair: (pair[1].at, pair[0]))[1]


class VersionsSweep:
    def __init__(
        self,
        db: Database,
        n8n: N8nDrafts,
        graders: Graders,
        accounts: N8nAccounts,
        requests: OpenRequests | None,
    ) -> None:
        self._db = db
        self._n8n = n8n
        self._graders = graders
        self._accounts = accounts
        self._requests = requests
        self._lock = asyncio.Lock()
        self._last: datetime | None = None

    async def sweep(self, use_case_id: str | None = None) -> list[Found | Gone]:
        """One look at every workflow n8n carries, or at one."""
        async with self._lock:
            self._last = self._db.clock()
            return await self._sweep(use_case_id)

    async def asked(self, use_case_id: str | None = None) -> list[Found | Gone]:
        """A look the Portal asked for, made at most once every few seconds."""
        async with self._lock:
            now = self._db.clock()
            if use_case_id is None and self._last is not None and now - self._last < ASKED_GAP:
                return []
            if use_case_id is None:
                self._last = now
            return await self._sweep(use_case_id)

    async def sweep_forever(self, stop: asyncio.Event, every: timedelta = SWEEP_EVERY) -> None:
        while not stop.is_set():
            try:
                await self.sweep()
            except Exception:
                log.exception("the versions sweep failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), every.total_seconds())

    async def _sweep(self, use_case_id: str | None) -> list[Found | Gone]:
        async with self._db.connection("builder") as conn:
            where = "" if use_case_id is None else " AND u.use_case_id = %s"
            params = () if use_case_id is None else (use_case_id,)
            rows = await (await conn.execute(_OWN + where, params)).fetchall()
        if not rows:
            return []
        known = await self._graders.known({})
        error_workflow = await self._n8n.error_workflow_id()
        found: list[Found | Gone] = []
        for row in rows:
            try:
                seen = await self._look(row["use_case_id"], known, error_workflow)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not look at %s in n8n: %s", row["use_case_id"], error)
                continue
            if seen is None:
                continue
            found.append(seen)
            if isinstance(seen, Gone) and self._requests is not None:
                await self._requests.cancel_for_deleted(UseCaseId(seen.use_case_id))
        return found

    async def _look(
        self, use_case_id: str, known: KnownOptions, error_workflow: str | None
    ) -> Found | Gone | None:
        async with self._db.transaction("builder") as uow:
            mine = _OWN + " AND u.use_case_id = %s FOR UPDATE OF u"
            row = await (await uow.conn.execute(mine, (use_case_id,))).fetchone()
            if row is None:
                return None
            workflow_id = row["n8n_workflow_id"]
            workflow = await self._n8n.look(workflow_id)
            if workflow is None:
                await uow.conn.execute(
                    "UPDATE builder.use_cases SET deleted_in_n8n_at = %s WHERE use_case_id = %s",
                    (uow.now, use_case_id),
                )
                log.warning("n8n no longer has %s, the workflow of %s", workflow_id, use_case_id)
                return Gone(use_case_id)
            live = workflow.active_version_id
            if live is None or live == row["n8n_version_id"]:
                return None
            return await self._keep(uow, row, live, workflow.version_id, known, error_workflow)

    async def _keep(
        self,
        uow: UnitOfWork,
        row: Mapping[str, Any],
        live: str,
        draft: str,
        known: KnownOptions,
        error_workflow: str | None,
    ) -> Found | None:
        """Keeps the version n8n has live as one published in n8n. One the platform published
        itself and has no record of is left alone: its runs stop at their first block, because
        no version on record matches it."""
        use_case_id, workflow_id = row["use_case_id"], row["n8n_workflow_id"]
        timeline = await self._n8n.timeline(workflow_id)
        activated = last_activation(live, timeline)
        if activated is None:
            return None
        if activated.user_id == await self._n8n.platform_user():
            log.warning("n8n has %s of %s live, which the platform has no record of", live, row)
            return None
        document = await self._n8n.kept(workflow_id, live)
        if document is None:
            log.warning("n8n has %s of %s live but did not show it", live, workflow_id)
            return None
        people = await self._accounts.people_by_n8n_user()
        publisher = publisher_of(live, "n8n", None, timeline, people)
        assert publisher is not None
        graded = grade(document, error_workflow, known)
        newest = row["current_version"]
        version = await add_version(
            uow,
            use_case_id,
            newest,
            newest,
            Held(live, document, graded.grade, tuple(f.text for f in graded.findings)),
            Made("published_in_n8n", None, None),
            Publication(publisher.person, "n8n"),
            (),
            draft,
        )
        log.info(
            "version %d of %s was published in n8n by %s and graded %s",
            version,
            use_case_id,
            publisher.person or "someone we don't know",
            graded.grade,
        )
        return Found(use_case_id, version)
