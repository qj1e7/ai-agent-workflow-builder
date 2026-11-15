"""Workflows made in n8n (ENGINE-PLAN E15, ADR 0027, D13). A person with n8n access may build a
workflow from our blocks in their own n8n space. The platform knows nothing of it until an
Operator with n8n access sets it up from Workflows, which registers it as a workflow the platform
runs.

What waits to be set up is read from n8n each time, never kept: every workflow in the own space of
a person the platform made an n8n account for, and every workflow n8n moved to the platform's
project when its maker's account ended, which the platform noted then. A workflow a use case
names, deleted ones included, is never offered. Its maker is the person whose space it sits in,
matched by the n8n user id the platform stored for them, never by a name or an email.

Setting one up moves it to the platform's project first, read back as every move is, and then
registers what n8n holds there, which nobody else can change any more. The safety checker grades
it, and only a safe version asks for a yes and writes (ENGINE-PLAN 2.3.11). One published in n8n
is on at once. One that is not is set up as a draft, and only when it is safe, because only a
safe draft can be turned on. Its maker, and the person who set it up, are parties to every run
of it, so neither can approve one. Any Approver decides its requests."""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx
from pydantic import Field

from platform_api.builder.models import UseCaseCreated
from platform_api.builder.n8n_draft import blocks_of
from platform_api.builder.n8n_holds import HoldRefused
from platform_api.builder.templates import AGENT_CARDS
from platform_api.builder.versions import Publication, authors_json
from platform_api.db import Connection, Database, hold_workflow, json
from platform_api.orchestration import (
    GRADING_RULES,
    CanOpen,
    Grade,
    Graded,
    KnownOptions,
    ListedWorkflow,
    N8nError,
    N8nWorkflow,
    NoN8nAccess,
    StaffAccess,
    grade,
)
from platform_api.shared import Principal, UserId, new_id
from platform_api.wire import WireIn, WireModel

log = logging.getLogger(__name__)

SET_UP_ALREADY = "This workflow is set up already."
NOT_LOADED = "n8n is not ready yet: its error workflow is not loaded."
NOT_READ = "n8n did not show the workflow. Nothing is set up. Try again."
FIX_IN_N8N = (
    "Fix it in n8n first. It isn't published there, and only a workflow that passes the check "
    "can be turned on."
)


class MadeInN8nView(WireModel):
    workflow_id: str
    name: str
    made_by: UserId = Field(
        description="Who made it in n8n: the person whose own n8n space holds it, or held it when "
        "their account ended, matched by the n8n account the platform made for them."
    )
    published: bool = Field(description="Whether it is published in n8n, so it runs there.")
    grade: Grade = Field(
        description="The safety checker's grade of the version n8n runs, or of its draft when "
        "nothing is published. Only a safe version asks for a yes and writes."
    )
    findings: list[str] = Field(
        description="Why it is not safe, in the safety checker's words, one per problem."
    )
    can_set_up: bool
    why_not: str | None = Field(description="Why it can't be set up now, in words to show.")


class MadeInN8nList(WireModel):
    workflows: list[MadeInN8nView]


class SetUpFromN8n(WireIn):
    workflow_id: str = Field(min_length=1, max_length=64)


class Spaces(Protocol):
    async def error_workflow_id(self) -> str | None: ...

    async def spaces(self) -> Mapping[str, str]:
        """Each member's own space by n8n's id for the member."""
        ...

    async def platform_project(self) -> str | None: ...

    async def workflows_in(self, project_id: str) -> list[ListedWorkflow]: ...

    async def look(self, workflow_id: str) -> N8nWorkflow | None: ...

    async def kept(self, workflow_id: str, version_id: str) -> dict[str, Any] | None: ...


class Makers(Protocol):
    async def access(self, person: UserId) -> StaffAccess: ...

    async def people_by_n8n_user(self) -> Mapping[str, UserId]: ...

    async def makers(self) -> Mapping[str, UserId]: ...

    async def note_made(
        self, person: UserId, n8n_user_id: str, workflow_ids: Iterable[str]
    ) -> None: ...

    async def display_of(self, person: UserId) -> str: ...


class Mover(Protocol):
    async def take_in(self, workflow_id: str) -> HoldRefused | None: ...


class Graders(Protocol):
    async def known(self, adding: Mapping[str, Iterable[str]]) -> KnownOptions: ...


@dataclass(frozen=True)
class Maker:
    person: UserId
    n8n_user_id: str | None
    """The account whose own space holds it now. None for one n8n moved to the platform's
    project as that account ended, whose maker was noted then."""


@dataclass(frozen=True)
class Candidate:
    listed: ListedWorkflow
    maker: Maker
    document: dict[str, Any]
    """The version n8n runs, or its draft while nothing is published."""
    graded: Graded

    @property
    def published(self) -> bool:
        return self.listed.workflow.active_version_id is not None

    @property
    def can_set_up(self) -> bool:
        return self.published or self.graded.grade == "safe"

    @property
    def why_not(self) -> str | None:
        return None if self.can_set_up else FIX_IN_N8N

    def view(self, closed: str | None = None) -> MadeInN8nView:
        """`closed` says why nothing can be set up now, whatever its grade."""
        workflow = self.listed.workflow
        why_not = closed or self.why_not
        return MadeInN8nView(
            workflow_id=workflow.id,
            name=str(self.document.get("name") or workflow.document.get("name") or workflow.id),
            made_by=self.maker.person,
            published=self.published,
            grade=self.graded.grade,
            findings=[f.text for f in self.graded.findings],
            can_set_up=why_not is None,
            why_not=why_not,
        )


def _closed(access: StaffAccess) -> HoldRefused | None:
    if isinstance(access, CanOpen):
        return None
    return HoldRefused(403 if isinstance(access, NoN8nAccess) else 409, access.words)


class MadeInN8n:
    def __init__(
        self, db: Database, n8n: Spaces, staff: Makers, mover: Mover, graders: Graders
    ) -> None:
        self._db = db
        self._n8n = n8n
        self._staff = staff
        self._mover = mover
        self._graders = graders

    async def waiting(self, actor: Principal) -> list[MadeInN8nView] | HoldRefused:
        """Every workflow made in n8n that waits to be set up, for a person who may open n8n."""
        if (closed := _closed(await self._staff.access(actor.user_id))) is not None:
            return closed
        error_workflow = await self._n8n.error_workflow_id()
        known = await self._graders.known({})
        found = await self._candidates(error_workflow, known)
        closed = NOT_LOADED if error_workflow is None else None
        return [candidate.view(closed) for candidate in found.values()]

    async def set_up(
        self, workflow_id: str, actor: Principal
    ) -> UseCaseCreated | HoldRefused | None:
        """Registers one workflow made in n8n. None when no such workflow waits to be set up.
        Asking again once it is set up answers that it is."""
        if (closed := _closed(await self._staff.access(actor.user_id))) is not None:
            return closed
        error_workflow = await self._n8n.error_workflow_id()
        if error_workflow is None:
            return HoldRefused(409, NOT_LOADED)
        known = await self._graders.known({})
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"n8n:{workflow_id}", alone=True)
            if await _named(uow.conn, workflow_id):
                return HoldRefused(409, SET_UP_ALREADY)
            candidate = (await self._candidates(error_workflow, known)).get(workflow_id)
            if candidate is None:
                return None
            if candidate.why_not is not None:
                return HoldRefused(409, candidate.why_not)
            maker = candidate.maker
            if maker.n8n_user_id is not None:
                await self._staff.note_made(maker.person, maker.n8n_user_id, [workflow_id])
            if (refused := await self._mover.take_in(workflow_id)) is not None:
                return refused
            try:
                held = await self._held(workflow_id)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not read %s after its move: %s", workflow_id, error)
                held = None
            if held is None:
                return HoldRefused(503, NOT_READ)
            workflow, document = held
            graded = grade(document, error_workflow, known)
            use_case_id = new_id("uc")
            made_by = await self._staff.display_of(maker.person)
            await _insert(
                uow.conn,
                use_case_id,
                workflow,
                document,
                graded,
                f"{GRADING_RULES} {error_workflow}",
                maker.person,
                actor.user_id,
                f"Made in n8n by {made_by}.",
                uow.now,
            )
        on = workflow.active_version_id is not None
        log.info(
            "%s set up %s, made in n8n by %s, as %s, graded %s",
            actor.user_id,
            workflow_id,
            maker.person,
            "on" if on else "a draft",
            graded.grade,
        )
        return UseCaseCreated(
            use_case_id=use_case_id,
            version=1,
            n8n_workflow_id=workflow_id,
            grade=graded.grade,
            blocks=blocks_of(document),
        )

    async def _held(self, workflow_id: str) -> tuple[N8nWorkflow, dict[str, Any]] | None:
        """What n8n holds now, in the platform's project, where nobody else can change it: the
        version it runs, as it runs it, or its draft while nothing is published."""
        workflow = await self._n8n.look(workflow_id)
        if workflow is None:
            return None
        live = workflow.active_version_id
        document = workflow.document if live is None else await self._n8n.kept(workflow_id, live)
        return None if document is None else (workflow, document)

    async def _candidates(
        self, error_workflow: str | None, known: KnownOptions
    ) -> dict[str, Candidate]:
        """Read from n8n each time. A space n8n could not list is left out this time."""
        async with self._db.connection("builder") as conn:
            rows = await (
                await conn.execute(
                    "SELECT n8n_workflow_id FROM builder.use_cases"
                    " WHERE n8n_workflow_id IS NOT NULL"
                )
            ).fetchall()
        named = {row["n8n_workflow_id"] for row in rows}
        found: dict[str, Candidate] = {}
        for listed, maker in await self._made():
            workflow = listed.workflow
            if workflow.id in named or workflow.id in found:
                continue
            document = await self._document(listed)
            if document is None:
                continue
            graded = grade(document, error_workflow, known)
            found[workflow.id] = Candidate(listed, maker, document, graded)
        return found

    async def _made(self) -> list[tuple[ListedWorkflow, Maker]]:
        people = await self._staff.people_by_n8n_user()
        made: list[tuple[ListedWorkflow, Maker]] = []
        for n8n_user, space in (await self._n8n.spaces()).items():
            person = people.get(n8n_user)
            if person is None:
                continue
            for listed in await self._listed(space):
                made.append((listed, Maker(person, n8n_user)))
        home = await self._n8n.platform_project()
        noted = await self._staff.makers()
        if home is not None and noted:
            for listed in await self._listed(home):
                maker = noted.get(listed.workflow.id)
                if maker is not None:
                    made.append((listed, Maker(maker, None)))
        return made

    async def _listed(self, project_id: str) -> list[ListedWorkflow]:
        try:
            return await self._n8n.workflows_in(project_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not list the workflows in n8n project %s: %s", project_id, error)
            return []

    async def _document(self, listed: ListedWorkflow) -> dict[str, Any] | None:
        workflow = listed.workflow
        live = workflow.active_version_id
        if live is None:
            return workflow.document
        if listed.live is not None:
            return listed.live
        try:
            return await self._n8n.kept(workflow.id, live)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read the published version of %s: %s", workflow.id, error)
            return None


async def _named(conn: Connection, workflow_id: str) -> bool:
    row = await (
        await conn.execute(
            "SELECT 1 FROM builder.use_cases WHERE n8n_workflow_id = %s", (workflow_id,)
        )
    ).fetchone()
    return row is not None


async def _insert(
    conn: Connection,
    use_case_id: str,
    workflow: N8nWorkflow,
    document: dict[str, Any],
    graded: Graded,
    graded_by: str,
    maker: UserId,
    actor: UserId,
    instruction: str,
    now: datetime,
) -> None:
    """Version 1 holds what n8n runs. Published in n8n, its maker published it and it is on.
    Otherwise it is a draft whose publisher is whoever turns it on, and its maker joins the
    authors. Whoever set it up joins them too, since that put it in the platform's hands."""
    live = workflow.active_version_id
    publisher = None if live is None else Publication(maker, "n8n")
    also = [Publication(maker, "n8n")] if publisher is None else []
    if actor != maker:
        also.append(Publication(actor, "portal"))
    await conn.execute(
        "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version,"
        " left_out, draft, engine, n8n_workflow_id, n8n_draft_id, made_in_n8n_by)"
        " VALUES (%s, %s, %s, 1, '{}', %s, 'own', %s, %s, %s)",
        (use_case_id, actor, now, live is None, workflow.id, workflow.version_id, maker),
    )
    await conn.execute(
        "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
        " instruction, params, created_at, n8n_version_id, grade, document, findings,"
        " graded_by, published_by, published_in, also)"
        " VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            use_case_id,
            AGENT_CARDS.key,
            str(document.get("name") or workflow.id),
            instruction,
            json({}),
            now,
            live or workflow.version_id,
            graded.grade,
            json(document),
            json([f.text for f in graded.findings]),
            graded_by,
            None if publisher is None else publisher.by,
            None if publisher is None else publisher.where,
            authors_json(also),
        ),
    )
