"""Workflows made in n8n (ENGINE-PLAN E15, ADR 0027, D13). A person with n8n access may build a
workflow from our blocks in their own n8n space. The platform knows nothing of it until an
Operator with n8n access sets it up from Workflows, which registers it as a workflow the platform
runs.

What waits to be set up is read from n8n each time, never kept: every workflow in the own space of
a person the platform made an n8n account for, and every workflow n8n moved to the platform's
project when its maker's account ended, which the platform noted then. A workflow a use case
names, deleted ones included, is never offered. Its maker is the person whose space it sits in,
matched by the n8n user id the platform stored for them, never by a name or an email.

Setting one up moves it to the platform's project first, read back as every move is, puts right
there what is the platform's to set and never its maker's (ADR 0051, Fixed for you), and then
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
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field

from platform_api.builder.layout import FixedForYou, fixed_for_you
from platform_api.builder.models import UseCaseCreated
from platform_api.builder.n8n_draft import blocks_of
from platform_api.builder.n8n_holds import HoldRefused
from platform_api.builder.sweep import grading_mark
from platform_api.builder.templates import AGENT_CARDS
from platform_api.builder.versions import Publication, authors_json
from platform_api.db import Connection, Database, hold_workflow, json
from platform_api.orchestration import (
    CanOpen,
    ChangedInN8n,
    Finding,
    Grade,
    Graded,
    KnownOptions,
    ListedWorkflow,
    N8nError,
    N8nWorkflow,
    NoN8nAccess,
    StaffAccess,
    Written,
    attach_keys,
    grade,
    unchecked,
)
from platform_api.shared import TEAM_TIME_ZONE, Principal, UserId, new_id
from platform_api.wire import WireIn, WireModel

log = logging.getLogger(__name__)

SET_UP_ALREADY = "This workflow is set up already."
NOT_LOADED = "n8n is not ready yet: its error workflow is not loaded."
NOT_READ = "n8n did not show the workflow. Nothing is set up. Try again."
REPLACES_DRAFT = (
    "Set up starts from the published version, so changes saved in n8n since then are dropped."
)
NO_START_ADDED = (
    "Set up can't add Start from the Portal, as no schedule that is on starts a block, so Run "
    "now can't start it."
)
NOT_FIXED = "n8n did not keep the platform's settings on it, so it is not set up. Try again."
CHANGED_AS_SET_UP = (
    "It changed in n8n while it was being set up, and it no longer passes the check, so it went "
    "back to its maker's n8n space. Fix it there first."
)
FIX_IN_N8N = (
    "Fix it in n8n first. It isn't published there, and only a workflow that passes the check "
    "can be turned on."
)
FIX_N8N_BLOCKS = (
    "Fix it in n8n first. n8n runs its own blocks as they are, whatever the check says, and one "
    "of them does not pass it."
)
"""For a workflow whose finding n8n would act on without the platform: one of n8n's own blocks
that is off, posts to a place an expression picks, or names a key the platform did not make. In
the platform's project n8n lets a workflow use every key there is, so such a workflow is never
moved there (ADR 0045, ENGINE-PLAN E16)."""


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
    fixed_for_you: list[str] = Field(
        description="What Set up puts right that is the platform's to set, never its maker's: "
        "its error workflow, its time zone, its kept test runs and progress, and Start from the "
        'Portal. Each is words that follow "Set up also". The grade and findings are of the '
        "workflow once these are put right."
    )
    set_up_notes: list[str] = Field(
        description="What else to know before pressing Set up, in words to show: that it drops "
        "changes saved in n8n since the version n8n runs, or that it can't add Start from the "
        "Portal."
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

    async def change(
        self, workflow_id: str, expected_version_id: str, document: Mapping[str, Any], live: bool
    ) -> Written | ChangedInN8n: ...

    async def home(self, workflow_id: str) -> str | None: ...

    async def own_workflow_ids(self) -> set[str]:
        """The platform's own n8n workflows, as bootstrap recorded them, which never wait to be
        set up: the error workflow, the self-test, and its copy in a member's space (M4)."""
        ...


class Makers(Protocol):
    async def access(self, person: UserId) -> StaffAccess: ...

    async def people_by_n8n_user(self) -> Mapping[str, UserId]: ...

    async def makers(self) -> Mapping[str, UserId]: ...

    async def note_made(
        self, person: UserId, n8n_user_id: str, workflow_ids: Iterable[str]
    ) -> None: ...

    async def forget_made(self, workflow_ids: Iterable[str]) -> None: ...

    async def display_of(self, person: UserId) -> str: ...


class Mover(Protocol):
    async def take_in(self, workflow_id: str) -> HoldRefused | None: ...

    async def send_back(self, workflow_id: str, project_id: str) -> HoldRefused | None: ...


class Graders(Protocol):
    async def known(self, adding: Mapping[str, Iterable[str]]) -> KnownOptions: ...


@dataclass(frozen=True)
class Maker:
    person: UserId
    n8n_user_id: str | None
    """The account whose own space holds it now. None for one n8n moved to the platform's
    project as that account ended, whose maker was noted then."""
    space: str
    """The project it was listed in, where it goes back to when its set-up is refused."""


@dataclass(frozen=True)
class Candidate:
    listed: ListedWorkflow
    maker: Maker
    fixed: FixedForYou
    """The version n8n runs, or its draft while nothing is published, as Set up leaves it."""
    graded: Graded
    draft: tuple[Finding, ...] = ()
    """What n8n would run unchecked in the draft of one that is published, once the platform's
    keys are back on it. A test run runs the draft."""

    @property
    def published(self) -> bool:
        return self.listed.workflow.active_version_id is not None

    @property
    def runs_anyway(self) -> bool:
        return bool(self.draft) or any(finding.runs_anyway for finding in self.graded.findings)

    @property
    def why_not(self) -> str | None:
        if self.runs_anyway:
            return FIX_N8N_BLOCKS
        return None if self.published or self.graded.grade == "safe" else FIX_IN_N8N

    @property
    def notes(self) -> list[str]:
        """Set up writes its fixes onto the version n8n runs, so a draft saved since is dropped."""
        workflow = self.listed.workflow
        edited = self.published and workflow.version_id != workflow.active_version_id
        return [
            *([REPLACES_DRAFT] if edited and self.fixed.fixed else []),
            *([NO_START_ADDED] if self.fixed.no_start else []),
        ]

    def view(self, closed: str | None = None) -> MadeInN8nView:
        """`closed` says why nothing can be set up now, whatever its grade."""
        workflow = self.listed.workflow
        why_not = closed or self.why_not
        return MadeInN8nView(
            workflow_id=workflow.id,
            name=str(workflow.document.get("name") or workflow.id),
            made_by=self.maker.person,
            published=self.published,
            grade=self.graded.grade,
            findings=[
                *(f.text for f in self.graded.findings),
                *(f"In its draft: {f.text}" for f in self.draft),
            ],
            fixed_for_you=list(self.fixed.fixed),
            set_up_notes=self.notes,
            can_set_up=why_not is None,
            why_not=why_not,
        )


def _candidate(
    listed: ListedWorkflow,
    maker: Maker,
    workflow: N8nWorkflow,
    document: dict[str, Any],
    error_workflow: str | None,
    zone: str,
    known: KnownOptions,
) -> Candidate:
    """Graded as Set up leaves it, so what is the platform's to put right is never a finding."""
    fixed = fixed_for_you(document, workflow.id, error_workflow, zone)
    graded = grade(fixed.document, error_workflow, zone, known)
    return Candidate(listed, maker, fixed, graded, _draft(workflow, known))


def _closed(access: StaffAccess) -> HoldRefused | None:
    if isinstance(access, CanOpen):
        return None
    return HoldRefused(403 if isinstance(access, NoN8nAccess) else 409, access.words)


class MadeInN8n:
    def __init__(
        self,
        db: Database,
        n8n: Spaces,
        staff: Makers,
        mover: Mover,
        graders: Graders,
        time_zone: ZoneInfo = TEAM_TIME_ZONE,
    ) -> None:
        self._db = db
        self._zone = time_zone.key
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
                await self._forget_unless_in(workflow_id, maker)
                return refused
            try:
                held = await self._held(workflow_id)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not read %s after its move: %s", workflow_id, error)
                held = None
            if held is None:
                return HoldRefused(503, NOT_READ)
            workflow, document = held
            moved = _candidate(
                candidate.listed, maker, workflow, document, error_workflow, self._zone, known
            )
            if moved.why_not is None and moved.fixed.fixed:
                fixed = await self._put_right(workflow, moved.fixed)
                if isinstance(fixed, HoldRefused):
                    return fixed
                workflow, document = fixed
                moved = _candidate(
                    candidate.listed, maker, workflow, document, error_workflow, self._zone, known
                )
                if moved.fixed.fixed:
                    return HoldRefused(503, NOT_FIXED)
            if moved.why_not is not None:
                await self._give_back(workflow_id, maker)
                return HoldRefused(409, CHANGED_AS_SET_UP)
            graded = moved.graded
            use_case_id = new_id("uc")
            made_by = await self._staff.display_of(maker.person)
            await _insert(
                uow.conn,
                use_case_id,
                workflow,
                document,
                graded,
                grading_mark(error_workflow, self._zone),
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

    async def _put_right(
        self, workflow: N8nWorkflow, fixed: FixedForYou
    ) -> tuple[N8nWorkflow, dict[str, Any]] | HoldRefused:
        """Writes what Set up puts right in n8n, in the platform's project now, and publishes it
        when the workflow is published, so the version n8n runs is the one the platform registers.
        What n8n holds then, or why not: the workflow stays there with its maker noted, so asking
        again finishes."""
        live = workflow.active_version_id is not None
        try:
            written = await self._n8n.change(workflow.id, workflow.version_id, fixed.document, live)
            held = None if isinstance(written, ChangedInN8n) else await self._held(workflow.id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not put right what %s needs in n8n: %s", workflow.id, error)
            held = None
        return HoldRefused(503, NOT_FIXED) if held is None else held

    async def _give_back(self, workflow_id: str, maker: Maker) -> None:
        """A draft changed to fail the check while it moved can't be set up, so it goes back to
        the space it came from, where its maker can fix it."""
        if maker.n8n_user_id is None:
            return
        refused = await self._mover.send_back(workflow_id, maker.space)
        if refused is not None:
            log.error("could not move %s back to its maker: %s", workflow_id, refused.words)
        await self._forget_unless_in(workflow_id, maker)

    async def _forget_unless_in(self, workflow_id: str, maker: Maker) -> None:
        """The maker note is for a workflow in the platform's project. One still in its maker's
        own space is found there by its creator, so its note goes. When n8n can't say where it
        is, the note stays."""
        if maker.n8n_user_id is None:
            return
        try:
            where = await self._n8n.home(workflow_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read where %s sits: %s", workflow_id, error)
            return
        if where == maker.space:
            await self._staff.forget_made([workflow_id])

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
        named = {row["n8n_workflow_id"] for row in rows} | await self._n8n.own_workflow_ids()
        found: dict[str, Candidate] = {}
        for listed, maker in await self._made():
            workflow = listed.workflow
            if workflow.id in named or workflow.id in found:
                continue
            document = await self._document(listed)
            if document is None:
                continue
            found[workflow.id] = _candidate(
                listed, maker, workflow, document, error_workflow, self._zone, known
            )
        return found

    async def _made(self) -> list[tuple[ListedWorkflow, Maker]]:
        people = await self._staff.people_by_n8n_user()
        made: list[tuple[ListedWorkflow, Maker]] = []
        for n8n_user, space in (await self._n8n.spaces()).items():
            person = people.get(n8n_user)
            if person is None:
                continue
            for listed in await self._listed(space):
                made.append((listed, Maker(person, n8n_user, space)))
        home = await self._n8n.platform_project()
        noted = await self._staff.makers()
        if home is not None and noted:
            for listed in await self._listed(home):
                maker = noted.get(listed.workflow.id)
                if maker is not None:
                    made.append((listed, Maker(maker, None, home)))
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


def _draft(workflow: N8nWorkflow, known: KnownOptions) -> tuple[Finding, ...]:
    """The draft of a published workflow is not what the grade read, and a test run runs it. It
    is checked as it will be once the platform's keys are back on it."""
    if workflow.active_version_id is None:
        return ()
    return unchecked(attach_keys(workflow.document, known.keys), known.keys)


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
            str(workflow.document.get("name") or workflow.id),
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
