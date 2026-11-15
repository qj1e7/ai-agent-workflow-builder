"""The versions sweep (ENGINE-PLAN 2.5, D5, D7, D9). Every minute, and when the Portal asks, it
looks at each workflow n8n carries. A version published in n8n's editor that our records do not
hold is fetched, graded against what the editor's lists hold now, and kept as a new version
published in n8n, with its publisher matched by the n8n user id we stored for the person, never
guessed. A workflow n8n no longer has is marked deleted in n8n, its open request is cancelled,
and its runs and versions stay.

The sweep holds the use case's row while it looks, as every platform publish does, so a publish
the Portal is making is never taken for one made in n8n.

Each look also grades again the version in use when its grade was made under other rules, or
another error workflow, than the ones in force now, and marks it, so a rule that changed with a
release, such as a block the class file now turns off, shows on every workflow however many looks
that takes (ENGINE-PLAN E11). The grade uses the error workflow the last bootstrap recorded, ready
or not, so a stale safe grade never outlives a bootstrap that failed; with none recorded every
workflow needs a fix, and none of its runs starts.
"""

import asyncio
import contextlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx

from platform_api.builder.moves import RESTORE_ASK_LIVES
from platform_api.builder.versions import (
    Held,
    Made,
    Publication,
    add_version,
    authors_from,
    settings_changed,
)
from platform_api.db import Database, UnitOfWork, json
from platform_api.orchestration import (
    GRADING_RULES,
    Grade,
    Graded,
    KnownOptions,
    N8nDrafts,
    N8nError,
    N8nWorkflow,
    PublishEvent,
    grade,
    publisher_of,
)
from platform_api.shared import UseCaseId, UserId

log = logging.getLogger(__name__)

SWEEP_EVERY = timedelta(seconds=60)
ASKED_GAP = timedelta(seconds=5)
"""A look the Portal asks for within this long of the last one, at the same workflow or at all,
is not made again."""
LOOK_SECONDS = 10.0
"""How long a look at one workflow may hold its row. n8n slower than this is looked at again at
the next sweep, so it never holds up Undo or a schedule save for long."""

_OWN = """
    SELECT u.use_case_id, u.current_version, u.n8n_workflow_id, v.n8n_version_id, v.document,
           v.published_by, v.published_in, v.also, v.grade, v.findings, v.graded_by
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


@dataclass(frozen=True)
class Regraded:
    """The version in use, graded again under the rules in force, with another grade. Its record
    is changed in place, so its publisher, its earlier authors and how it came about stay as
    they were."""

    use_case_id: str
    version: int
    grade: Grade


type Seen = Found | Gone | Regraded


def last_activation(version_id: str, timeline: Sequence[PublishEvent]) -> PublishEvent | None:
    activated = [e for e in timeline if e.version_id == version_id and e.event == "activated"]
    if not activated:
        return None
    return max(enumerate(activated), key=lambda pair: (pair[1].at, pair[0]))[1]


async def _restore_asked(uow: UnitOfWork, workflow_id: str) -> bool:
    """n8n lost this workflow with every other it held, a short while ago, so a person did not
    delete it, and the restore asked for saves it again. One lost after the ask was deleted."""
    row = await (
        await uow.conn.execute(
            "SELECT 1 FROM builder.n8n_restore WHERE %s = ANY(missing) AND asked_at > now() - %s",
            (workflow_id, RESTORE_ASK_LIVES),
        )
    ).fetchone()
    return row is not None


class VersionsSweep:
    def __init__(
        self,
        db: Database,
        n8n: N8nDrafts,
        graders: Graders,
        accounts: N8nAccounts,
        requests: OpenRequests | None,
        team_zone: str,
        look_seconds: float = LOOK_SECONDS,
    ) -> None:
        self._db = db
        self._zone = team_zone
        self._n8n = n8n
        self._graders = graders
        self._accounts = accounts
        self._requests = requests
        self._look_seconds = look_seconds
        self._lock = asyncio.Lock()
        self._last: dict[str | None, datetime] = {}
        """When each workflow, or all of them as None, was last looked at."""

    async def sweep(self, use_case_id: str | None = None) -> list[Seen]:
        """One look at every workflow n8n carries, or at one."""
        async with self._lock:
            self._last[use_case_id] = self._db.clock()
            return await self._sweep(use_case_id)

    async def asked(self, use_case_id: str | None = None) -> list[Seen]:
        """A look the Portal asked for, made at most once every few seconds."""
        async with self._lock:
            now = self._db.clock()
            last = self._last.get(use_case_id)
            if last is not None and now - last < ASKED_GAP:
                return []
            self._last[use_case_id] = now
            return await self._sweep(use_case_id)

    async def sweep_forever(self, stop: asyncio.Event, every: timedelta = SWEEP_EVERY) -> None:
        while not stop.is_set():
            try:
                await self.sweep()
            except Exception:
                log.exception("the versions sweep failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), every.total_seconds())

    async def _sweep(self, use_case_id: str | None) -> list[Seen]:
        async with self._db.connection("builder") as conn:
            where = "" if use_case_id is None else " AND u.use_case_id = %s"
            params = () if use_case_id is None else (use_case_id,)
            rows = await (await conn.execute(_OWN + where, params)).fetchall()
        if not rows:
            return []
        known = await self._graders.known({})
        error_workflow = (
            await self._n8n.error_workflow_id() or await self._n8n.recorded_error_workflow_id()
        )
        mark = f"{GRADING_RULES} {error_workflow} {self._zone}"
        found: list[Seen] = []
        for row in rows:
            try:
                async with asyncio.timeout(self._look_seconds):
                    seen = await self._look(row["use_case_id"], known, error_workflow, mark)
            except (N8nError, httpx.HTTPError, TimeoutError) as error:
                log.warning("could not look at %s in n8n: %s", row["use_case_id"], error)
                continue
            if seen is None:
                continue
            found.append(seen)
            if isinstance(seen, Gone) and self._requests is not None:
                await self._requests.cancel_for_deleted(UseCaseId(seen.use_case_id))
        return found

    async def _look(
        self, use_case_id: str, known: KnownOptions, error_workflow: str | None, mark: str
    ) -> Seen | None:
        async with self._db.transaction("builder") as uow:
            mine = _OWN + " AND u.use_case_id = %s FOR UPDATE OF u"
            row = await (await uow.conn.execute(mine, (use_case_id,))).fetchone()
            if row is None:
                return None
            workflow_id = row["n8n_workflow_id"]
            workflow = await self._n8n.look(workflow_id)
            if workflow is None and await _restore_asked(uow, workflow_id):
                log.info("n8n lost %s, which the restore asked for saves again", workflow_id)
                return None
            if workflow is None:
                await uow.conn.execute(
                    "UPDATE builder.use_cases SET deleted_in_n8n_at = %s WHERE use_case_id = %s",
                    (uow.now, use_case_id),
                )
                log.warning("n8n no longer has %s, the workflow of %s", workflow_id, use_case_id)
                return Gone(use_case_id)
            live = workflow.active_version_id
            if live is not None and live != row["n8n_version_id"]:
                return await self._keep(uow, row, live, workflow.version_id, known, error_workflow)
            if row["document"] is None:
                return None
            kept: dict[str, Any] = row["document"]
            settings: dict[str, Any] = workflow.document.get("settings") or {}
            changed = settings_changed(kept.get("settings"), settings)
            drifted = live is not None and changed is not None
            if not drifted and row["graded_by"] == mark:
                return None
            document = kept if live is None else {**kept, "settings": settings}
            graded = grade(document, error_workflow, self._zone, known)
            if drifted:
                return await self._settings(uow, row, workflow, document, graded)
            return await _regraded(uow, row, graded, mark)

    async def _settings(
        self,
        uow: UnitOfWork,
        row: Mapping[str, Any],
        workflow: N8nWorkflow,
        document: dict[str, Any],
        graded: Graded,
    ) -> Found:
        """n8n runs the live version with the workflow's settings now, which a save in the editor
        changes with no publish. Different settings make a new version of the same workflow,
        graded again, with whose work it was carried on: n8n names nobody for the save."""
        use_case_id, newest = row["use_case_id"], row["current_version"]
        findings = tuple(f.text for f in graded.findings)
        publisher = row["published_in"]
        version = await add_version(
            uow,
            use_case_id,
            newest,
            newest,
            Held(row["n8n_version_id"], document, graded.grade, findings),
            Made("settings_changed_in_n8n", None, None),
            None if publisher is None else Publication(row["published_by"], publisher),
            authors_from(row["also"]),
            workflow.version_id,
        )
        log.info(
            "the settings of %s changed in n8n: version %d graded %s",
            use_case_id,
            version,
            graded.grade,
        )
        return Found(use_case_id, version)

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
        graded = grade(document, error_workflow, self._zone, known)
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


async def _regraded(
    uow: UnitOfWork, row: Mapping[str, Any], graded: Graded, mark: str
) -> Regraded | None:
    findings = [f.text for f in graded.findings]
    use_case_id, version = row["use_case_id"], row["current_version"]
    await uow.conn.execute(
        "UPDATE builder.use_case_versions SET grade = %s, findings = %s, graded_by = %s"
        " WHERE use_case_id = %s AND version = %s",
        (graded.grade, json(findings), mark, use_case_id, version),
    )
    if (graded.grade, findings) == (row["grade"], row["findings"] or []):
        return None
    log.warning(
        "version %d of %s grades %s now, from %s: %s",
        version,
        use_case_id,
        graded.grade,
        row["grade"],
        "; ".join(findings),
    )
    return Regraded(use_case_id, version, graded.grade)
