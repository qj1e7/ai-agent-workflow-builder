"""Drafted workflows (ADR 0051, build step 6): what the workflow drafter wrote from an Operator's
words, each change as a new revision, laid out and checked by code, sent for a set-up approval,
and set up as a Draft once an Approver approves that exact revision.

Not the set-up card drafts in drafts.py, which an Operator saves to come back to.

The drafter only plans. Code lays each plan out, adds what every layout adds, puts an Ask for a
yes before each write by our blocks, puts the keys on and grades the result (`layout.py`,
`add_yes`, `attach_keys`, `grade`). Code writes the report. In this step a revision is sent only
when no setting is still needed and the check found nothing: approving a flagged workflow, and the
second Approver of a workflow that changes someone's access, come with build step 10.

The words go to the drafter unchanged, and never to a log. Words shaped like a key are refused
before anything is kept or sent."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol, cast
from zoneinfo import ZoneInfo

import httpx
from psycopg.types.json import Jsonb

from platform_api.builder.card_store import CardLibrary
from platform_api.builder.cards import library_card
from platform_api.builder.drafted_in_n8n import NotReadBack, read_back
from platform_api.builder.drafted_settings import (
    NOT_A_CHOICE,
    Answered,
    How,
    SettingNow,
    Source,
    Sources,
    Unread,
    asking,
    never_guessed,
    next_question,
    read_answer,
    settings_of,
    strays,
    with_answer,
)
from platform_api.builder.drafted_views import (
    DraftAnswerIn,
    DraftedApprovalView,
    DraftedInN8nView,
    DraftedSetUpView,
    DraftedState,
    DraftedWorkflowView,
    SetUpApprovalView,
    SetUpDecisionIn,
    report_settings,
    setting_views,
)
from platform_api.builder.explain import view_of
from platform_api.builder.layout import DraftedLayout, lay_out_drafted
from platform_api.builder.n8n_draft import blocks_of
from platform_api.builder.sweep import grading_mark
from platform_api.builder.templates import AGENT_CARDS
from platform_api.builder.versions import Publication, authors_json
from platform_api.builder.workflow_report import (
    KEY_SHAPE,
    Drafted,
    EachRun,
    Team,
    WorkflowReport,
    workflow_report,
)
from platform_api.db import Connection, Database, hold_workflow, json
from platform_api.orchestration import (
    DECLINE_REASONS,
    GITHUB_RELEASES,
    TYPE_OF,
    WATCHLIST_PLACE,
    Approved,
    ApprovedSetUp,
    CanOpen,
    ChannelList,
    Closed,
    Declined,
    DrafterFacts,
    Ended,
    KeyPasted,
    KnownOptions,
    ListedWorkflow,
    ModelProblem,
    N8nError,
    N8nWorkflow,
    NoModel,
    NoN8nAccess,
    NotKeptAsSent,
    Refusal,
    RuntimeDown,
    SavedDraft,
    SetUpApprovals,
    SetUpAsk,
    SetUpDecided,
    SetUpFinished,
    SetUpRefused,
    SetUpState,
    StaffAccess,
    TryAgain,
    Verdict,
    WorkflowDrafted,
    WorkflowDraftResult,
    WorkflowNotDrafted,
    WorkflowPlan,
    add_yes,
    attach_keys,
    block_id,
    grade,
    set_up_link,
    workflow_digest,
)
from platform_api.shared import ApprovalId, Digest, Principal, Role, UserId, new_id

log = logging.getLogger(__name__)

DRAFTING_LIMIT: Final = timedelta(minutes=5)
"""The drafter stops itself in under three minutes. A revision still drafting after this was cut
off, as by a restart, and reads as not drafted."""
PASTED_KEY: Final = KEY_SHAPE
"""Every shape the runtime's masker knows, and the report's, so neither a log nor the records
ever hold a pasted key."""
KEY_PASTED: Final = "Don't paste keys here. An Operator adds keys in Settings."
KEY_IN_N8N: Final = (
    "A block in n8n holds something shaped like a key. Remove it in n8n, then press Done in n8n "
    "again. An Operator adds keys in Settings."
)
COULDNT_DRAFT: Final = "I couldn't draft that."
NO_MODEL: Final = "I couldn't draft that. No AI model is connected yet."
N8N_NOT_READY: Final = "I couldn't draft that. n8n is not ready yet."
PAUSED: Final = "Drafting is paused while the platform updates."
N8N_IMAGE: Final = "n8nio/n8n"
"""The repository of the n8n image the drafter's catalogue names (contracts/n8n/catalogue.json)."""
CHANGED: Final = "Changed since it was approved. Send it for approval again."
NO_LONGER_PASSES: Final = (
    "It no longer passes the safety check, so it isn't set up. Ask for a change to draft it again."
)
NOT_TAKEN: Final = "n8n didn't take it, so it isn't set up yet. Try again."
NO_N8N: Final = "n8n isn't connected, so it can't be set up."
ACCESS_LATER: Final = (
    "It changes who can use a system, so its set-up needs two Approvers. That comes in a later "
    "step."
)
NEWER_BELOW: Final = "A newer revision is below."
SET_UP_ALREADY: Final = "It's set up already. Change it from Workflows."
SETTING_UP: Final = "It's approved, and it's being set up in n8n now."
FLAGGED_NOW: Final = (
    "It has a flag under today's rules, so it can't be approved now. Ask the sender to draft it "
    "again."
)
NEEDED_NOW: Final = "A setting is still needed, so it can't be approved now."
SAME_WORDS_WITHIN: Final = timedelta(minutes=2)
"""The same words from the same Operator within this long are one request asked twice, as a
retried send of the chat would ask it, so they answer the drafted workflow already started."""
STILL_DRAFTING: Final = "It's still drafting."
IN_N8N_NOW: Final = "It's open in n8n. Press Done in n8n first."
NOT_IN_N8N: Final = "It isn't open in n8n."
NO_SUCH_SETTING: Final = "It has no such setting."
NO_SPACE: Final = "n8n did not say where your n8n space is. Nothing changed. Try again."
NOT_OPENED: Final = "n8n didn't take it, so it isn't open in n8n. Try again."
NOT_READ: Final = "n8n didn't show it, so nothing changed. Try again."
GONE_IN_N8N: Final = (
    "n8n no longer has it, so nothing came back from n8n. The revision before stays as it was."
)
KEYS_WAIT: Final = "Waiting for a write key, which comes in a later step."
READ_BACK: Final = "Read back from n8n."
OPEN_IN_N8N: Final = "Open in your own n8n space, without its keys."


def opened_by(name: str, since: datetime, zone: str) -> str:
    return f"{name} has it open in n8n since {since.astimezone(ZoneInfo(zone)):%H:%M}."


def only_the_opener(name: str) -> str:
    return f"Only {name}, who opened it in n8n, can press Done in n8n."


def answer_first(needed: int) -> str:
    return f"Answer {needed} {'question' if needed == 1 else 'questions'} first"


def flags_later(flags: int) -> str:
    return (
        f"It has {flags} {'flag' if flags == 1 else 'flags'}. Sending a workflow with flags for "
        "approval comes in a later step."
    )


@dataclass(frozen=True)
class Refused:
    """409, with the words the card shows."""

    words: str


@dataclass(frozen=True)
class Forbidden:
    """403, with the words the page shows."""

    words: str


@dataclass(frozen=True)
class NotFound:
    pass


@dataclass(frozen=True)
class Unavailable:
    """503, with the words the card shows: n8n didn't do it."""

    words: str


@dataclass(frozen=True)
class Revision:
    number: int
    asked_by: UserId
    words: str
    started_at: datetime
    state: Literal["drafting", "drafted", "not_drafted"]
    plan: WorkflowPlan | None
    document: dict[str, Any] | None
    digest: str | None
    said: str | None
    made_by: Literal["drafter", "answer", "n8n"] = "drafter"
    sources: Sources = field(default_factory=dict[str, Source])
    catalogue: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class InN8n:
    """A drafted workflow open in someone's own n8n space, without its keys."""

    workflow_id: str
    by: UserId
    since: datetime
    revision: int


@dataclass(frozen=True)
class Kept:
    drafted_id: str
    owner: UserId
    use_case_id: str
    set_up_at: datetime | None
    set_up_approval: str | None
    """The set-up approval the set-up, its last try or its last problem, was for."""
    set_up_trying_at: datetime | None
    """When a try of that approval's set-up began to create the workflow in n8n."""
    set_up_n8n_id: str | None
    """The workflow n8n created on that try, recorded as soon as n8n named it."""
    set_up_problem: str | None
    revisions: tuple[Revision, ...]
    in_n8n: InN8n | None = None

    @property
    def newest(self) -> Revision:
        return self.revisions[-1]

    @property
    def card_revision(self) -> int:
        """The newest revision that started a card: an answer's revision stays on its card."""
        return next(r.number for r in reversed(self.revisions) if r.made_by != "answer")

    def revision(self, number: int) -> Revision:
        return next(r for r in self.revisions if r.number == number)

    @property
    def parties(self) -> frozenset[UserId]:
        """Who described it and everyone who asked for a change. The sender joins at send."""
        return frozenset({self.owner, *(r.asked_by for r in self.revisions)})

    def current_plan(self, before: int) -> WorkflowPlan | None:
        """The plan as it stands before a revision: the newest one drafted before it."""
        drafted = [r.plan for r in self.revisions if r.number < before and r.plan is not None]
        return drafted[-1] if drafted else None


class Drafting(Protocol):
    async def draft(
        self, words: str, facts: DrafterFacts, current: WorkflowPlan | None
    ) -> WorkflowDraftResult | NoModel | RuntimeDown: ...


class Facts(Protocol):
    async def known(self, adding: Mapping[str, Sequence[str]]) -> KnownOptions: ...


class Channels(Protocol):
    async def listed(self) -> ChannelList:
        """The Slack channels the platform's key can post in, as "#name", and how old the list
        is."""
        ...


class Staff(Protocol):
    async def access(self, person: UserId) -> StaffAccess: ...


class SettingUp(Protocol):
    """What the set-up and Edit in n8n need of n8n: N8nWorkflows, which reads a workflow back
    after creating it."""

    async def member_project(self, n8n_user_id: str) -> str | None: ...

    async def move(self, workflow_id: str, project_id: str) -> None: ...

    async def remove_for_good(self, workflow_id: str) -> None:
        """Archives it, which unpublishes it, then deletes it with its executions."""
        ...

    async def error_workflow_id(self) -> str | None: ...

    async def n8n_version(self) -> str | None:
        """The n8n version the last bootstrap read from n8n itself, or None before any did."""
        ...

    async def save_draft(
        self,
        document: Mapping[str, Any],
        created: Callable[[str], Awaitable[None]] | None = None,
    ) -> SavedDraft: ...

    async def platform_project(self) -> str | None: ...

    async def workflows_in(self, project_id: str) -> list[ListedWorkflow]: ...

    async def look(self, workflow_id: str) -> N8nWorkflow | None: ...

    async def remove(self, workflow_id: str) -> None: ...


@dataclass(frozen=True)
class Made:
    """A revision code made, and who made it."""

    by: UserId
    words: str
    how: Literal["answer", "n8n"]
    plan: WorkflowPlan
    sources: Sources
    catalogue: str | None
    notes: tuple[str, ...] = ()
    """What came back from n8n that didn't count, in words for the card."""


@dataclass(frozen=True)
class Laid:
    """A plan as code laid it out and graded it, ready to keep as a revision."""

    document: dict[str, Any]
    grade: str
    findings: list[dict[str, Any]]


@dataclass(frozen=True)
class Checked:
    """A revision as code laid it out and checked it, under today's rules."""

    document: dict[str, Any]
    report: WorkflowReport
    changes_access: bool
    settings: tuple[SettingNow, ...] = ()
    names: Mapping[UserId, str] = field(default_factory=dict[UserId, str])


class DraftedWorkflows:
    def __init__(
        self,
        db: Database,
        drafting: Drafting,
        approvals: SetUpApprovals,
        facts: Facts,
        n8n: SettingUp | None,
        public_base_url: str,
        time_zone: str,
        channels: Channels | None = None,
        staff: Staff | None = None,
        editor_url: str | None = None,
    ) -> None:
        self._db = db
        self._drafting = drafting
        self._approvals = approvals
        self._facts = facts
        self._n8n = n8n
        self._public_base_url = public_base_url.rstrip("/")
        self._zone = time_zone
        self._channels = channels
        self._staff = staff
        self._editor_url = None if editor_url is None else editor_url.rstrip("/")
        self._cards = CardLibrary(db)
        self._running: set[asyncio.Task[None]] = set()

    async def start(
        self,
        owner: Principal,
        words: str,
        idempotency_key: str | None = None,
        same_words_within: timedelta | None = None,
    ) -> DraftedWorkflowView | Refused:
        """A new drafted workflow, drafting its first revision now. The same key from the same
        Operator answers the drafted workflow it started, and so do the same words within
        `same_words_within`, for a request with no key of its own."""
        if PASTED_KEY.search(words):
            return Refused(KEY_PASTED)
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"drafted.start:{owner.user_id}",)
            )
            if idempotency_key is not None or same_words_within is not None:
                row = await (
                    await uow.conn.execute(
                        "SELECT d.drafted_id FROM builder.drafted_workflows d"
                        " JOIN builder.drafted_revisions r"
                        " ON r.drafted_id = d.drafted_id AND r.revision = 1"
                        " WHERE d.owner = %s AND (d.idempotency_key = %s"
                        " OR (%s::interval IS NOT NULL AND r.words = %s"
                        " AND d.created_at > %s - %s::interval))"
                        " ORDER BY d.created_at DESC LIMIT 1",
                        (
                            owner.user_id,
                            idempotency_key,
                            same_words_within,
                            words,
                            uow.now,
                            same_words_within,
                        ),
                    )
                ).fetchone()
                if row is not None:
                    drafted_id = str(row["drafted_id"])
                    kept = await _kept(uow.conn, drafted_id)
                    assert kept is not None
                    return await self._view(kept, owner)
            drafted_id = new_id("dw")
            await uow.conn.execute(
                "INSERT INTO builder.drafted_workflows (drafted_id, owner, created_at,"
                " use_case_id, idempotency_key) VALUES (%s, %s, %s, %s, %s)",
                (drafted_id, owner.user_id, uow.now, new_id("uc"), idempotency_key),
            )
            await _begin(uow.conn, drafted_id, 1, owner.user_id, words, uow.now)
        self._draft_in_the_background(drafted_id, 1)
        return await self._viewed(drafted_id, owner)

    async def change(
        self, drafted_id: str, asker: Principal, revision: int, words: str
    ) -> DraftedWorkflowView | Refused | NotFound:
        """A change asked for in the chat: the drafter gets the plan as it stands and the words,
        and its whole new plan is the next revision. A set-up approval still waiting is replaced.
        """
        if PASTED_KEY.search(words):
            return Refused(KEY_PASTED)
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"drafted:{drafted_id}", alone=True)
            kept = await _kept(uow.conn, drafted_id)
            if kept is None:
                return NotFound()
            if kept.set_up_at is not None:
                return Refused(SET_UP_ALREADY)
            if revision != kept.newest.number:
                return Refused(NEWER_BELOW)
            if self._drafting_now(kept.newest):
                return Refused(STILL_DRAFTING)
            if kept.in_n8n is not None:
                return Refused(IN_N8N_NOW)
            state = await self._approvals.latest(drafted_id)
            if state is not None and _holds(kept, state):
                return Refused(SETTING_UP)
            number = kept.newest.number + 1
            await _begin(uow.conn, drafted_id, number, asker.user_id, words, uow.now)
        await self._approvals.replace_waiting(drafted_id)
        self._draft_in_the_background(drafted_id, number)
        return await self._viewed(drafted_id, asker)

    async def view(
        self, drafted_id: str, viewer: Principal | None = None
    ) -> DraftedWorkflowView | None:
        async with self._db.connection("builder") as conn:
            kept = await _kept(conn, drafted_id)
        return None if kept is None else await self._view(kept, viewer)

    async def send(
        self, drafted_id: str, sender: Principal, revision: int
    ) -> DraftedWorkflowView | Refused | NotFound:
        """Sends the revision for a set-up approval, only when nothing is still needed, the
        check found nothing, and it changes nobody's access. Its parties are everyone who
        described it, changed it, answered its questions or sent it."""
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"drafted:{drafted_id}", alone=True)
            kept = await _kept(uow.conn, drafted_id)
            if kept is None:
                return NotFound()
            view = await self._view(kept, sender)
            if revision != kept.newest.number:
                return Refused(NEWER_BELOW)
            if view.state != "draft" or not view.can_send:
                return Refused(view.why_not_send or _not_now(view.state) or COULDNT_DRAFT)
            newest = kept.newest
            assert newest.document is not None and newest.digest is not None
            assert newest.plan is not None and view.report is not None
            if workflow_digest(newest.document) != newest.digest:
                log.error(
                    "drafted %s revision %d no longer matches its digest", drafted_id, revision
                )
                return Refused(COULDNT_DRAFT)
            await self._approvals.send(
                SetUpAsk(
                    drafted_id=drafted_id,
                    revision=newest.number,
                    digest=Digest(newest.digest),
                    name=newest.plan.name,
                    in_short="".join(s.text for s in view.report.in_short),
                    parties=kept.parties | {sender.user_id},
                    sent_by=sender.user_id,
                )
            )
        return await self._viewed(drafted_id, sender)

    async def answer(
        self, drafted_id: str, person: Principal, answer: DraftAnswerIn
    ) -> DraftedWorkflowView | Refused | NotFound:
        """An answer to one of its questions, or a guessed setting changed: code reads it and
        lays out the next revision, with no model. Words shaped like a key are refused before
        anything is kept. The person who answers becomes a party to its set-up approval."""
        if answer.typed is not None and PASTED_KEY.search(answer.typed):
            return Refused(KEY_PASTED)
        if (answer.choice is None) == (answer.typed is None):
            return Refused(NOT_A_CHOICE)
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"drafted:{drafted_id}", alone=True)
            kept = await _kept(uow.conn, drafted_id)
            if kept is None:
                return NotFound()
            if (refused := await self._not_a_draft(kept, person, answer.revision)) is not None:
                return refused
            newest = kept.newest
            assert newest.plan is not None
            setting = next(
                (s for s in settings_of(newest.plan, newest.sources) if s.id == answer.setting),
                None,
            )
            if setting is None:
                return Refused(NO_SUCH_SETTING)
            read = read_answer(
                setting, await self._options(), choice=answer.choice, typed=answer.typed
            )
            if isinstance(read, Unread):
                return Refused(read.words)
            if self._n8n is None or (error_workflow := await self._n8n.error_workflow_id()) is None:
                return Refused(N8N_NOT_READY)
            plan = with_answer(
                newest.plan, setting.id, read.value, "filled" if read.filled else "needed"
            )
            how: How = "chose" if answer.choice is not None else "typed"
            given = {setting.id: Source(read.value, how, person.user_id)} if read.filled else {}
            before = {k: v for k, v in newest.sources.items() if k != setting.id}
            await self._keep(
                uow.conn,
                kept,
                Made(
                    person.user_id,
                    _answered_words(setting, read),
                    "answer",
                    plan,
                    carried(before, plan, given, person.user_id),
                    newest.catalogue,
                ),
                await self._laid(kept, plan, error_workflow),
                uow.now,
            )
        return await self._viewed(drafted_id, person)

    async def open_in_n8n(
        self, drafted_id: str, person: Principal, revision: int
    ) -> DraftedWorkflowView | Refused | Forbidden | NotFound | Unavailable:
        """Puts the newest revision in the person's own n8n space, without its keys, as Open in
        n8n does (ADR 0045, amendment 3). Only an Operator with n8n access may. Nothing else
        changes it until Done in n8n reads it back."""
        if self._staff is None or self._n8n is None:
            return Refused(NO_N8N)
        access = await self._staff.access(person.user_id)
        if not isinstance(access, CanOpen):
            refusal = access.words
            return Forbidden(refusal) if isinstance(access, NoN8nAccess) else Refused(refusal)
        n8n = self._n8n
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"drafted:{drafted_id}", alone=True)
            kept = await _kept(uow.conn, drafted_id)
            if kept is None:
                return NotFound()
            if kept.in_n8n is not None and kept.in_n8n.by == person.user_id:
                return await self._view(kept, person)
            if (refused := await self._not_a_draft(kept, person, revision)) is not None:
                return refused
            newest = kept.newest
            assert newest.document is not None
            try:
                project = await n8n.member_project(access.n8n_user_id)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not list its projects: %s", type(error).__name__)
                project = None
            if project is None:
                return Unavailable(NO_SPACE)
            try:
                saved = await n8n.save_draft(_without_keys(newest.document))
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not take %s: %s", drafted_id, type(error).__name__)
                return Unavailable(NOT_OPENED)
            try:
                await n8n.move(saved.workflow_id, project)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not move %s: %s", drafted_id, type(error).__name__)
                await n8n.remove(saved.workflow_id)
                return Unavailable(NOT_OPENED)
            await uow.conn.execute(
                "UPDATE builder.drafted_workflows SET in_n8n_id = %s, in_n8n_by = %s,"
                " in_n8n_since = %s, in_n8n_revision = %s WHERE drafted_id = %s",
                (saved.workflow_id, person.user_id, uow.now, newest.number, drafted_id),
            )
        log.info("%s opened %s in n8n as %s", person.user_id, drafted_id, saved.workflow_id)
        return await self._viewed(drafted_id, person)

    async def done_in_n8n(
        self, drafted_id: str, person: Principal
    ) -> DraftedWorkflowView | Refused | Forbidden | NotFound | Unavailable:
        """Reads what n8n holds back as a new revision, checked again, and takes it out of the
        person's n8n space. What the plan can't hold comes back as words, and it stays in n8n to
        put right."""
        if self._n8n is None:
            return Refused(NO_N8N)
        n8n = self._n8n
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"drafted:{drafted_id}", alone=True)
            kept = await _kept(uow.conn, drafted_id)
            if kept is None:
                return NotFound()
            held = kept.in_n8n
            if held is None:
                return Refused(NOT_IN_N8N)
            if held.by != person.user_id:
                names = await self._approvals.names([held.by])
                return Forbidden(only_the_opener(names[held.by]))
            try:
                whole = await n8n.look(held.workflow_id)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("n8n did not show %s: %s", held.workflow_id, type(error).__name__)
                return Unavailable(NOT_READ)
            if whole is None:
                await _out_of_n8n(uow.conn, drafted_id)
                return Refused(GONE_IN_N8N)
            if _holds_a_key(whole.document):
                # Never the value, nor where it is: only that the read-back was refused.
                log.warning("refused to read %s back from n8n: it holds a key", drafted_id)
                return Refused(KEY_IN_N8N)
            if (error_workflow := await n8n.error_workflow_id()) is None:
                return Refused(N8N_NOT_READY)
            opened = kept.revision(held.revision)
            assert opened.plan is not None and opened.document is not None
            read = read_back(
                whole.document,
                opened.plan,
                opened.document,
                await self._options(),
                person.user_id,
                self._zone,
            )
            if isinstance(read, NotReadBack):
                return Refused(read.words)
            plan = never_guessed(read.plan)
            await self._keep(
                uow.conn,
                kept,
                Made(
                    person.user_id,
                    READ_BACK,
                    "n8n",
                    plan,
                    carried(opened.sources, plan, read.sources, person.user_id),
                    opened.catalogue,
                    read.notes,
                ),
                await self._laid(kept, plan, error_workflow),
                uow.now,
            )
            await _out_of_n8n(uow.conn, drafted_id)
        try:
            await n8n.remove_for_good(held.workflow_id)
        except (N8nError, httpx.HTTPError) as error:
            # The revision is kept. A copy n8n kept is the person's own, and holds no key.
            log.warning("n8n kept %s after Done in n8n: %s", held.workflow_id, type(error).__name__)
        log.info("%s read %s back from n8n", person.user_id, drafted_id)
        return await self._viewed(drafted_id, person)

    async def _not_a_draft(self, kept: Kept, person: Principal, revision: int) -> Refused | None:
        """Why the newest revision can't be answered or opened in n8n now."""
        if (held := kept.in_n8n) is not None:
            if held.by == person.user_id:
                return Refused(IN_N8N_NOW)
            names = await self._approvals.names([held.by])
            return Refused(opened_by(names[held.by], held.since, self._zone))
        if revision != kept.newest.number:
            return Refused(NEWER_BELOW)
        view = await self._view(kept, person)
        if view.state != "draft":
            return Refused(_not_now(view.state) or COULDNT_DRAFT)
        return None

    async def _keep(
        self, conn: Connection, kept: Kept, made: Made, laid: Laid, now: datetime
    ) -> None:
        """A revision code made, with no model: from an answer or read back from n8n."""
        await conn.execute(
            "INSERT INTO builder.drafted_revisions (drafted_id, revision, asked_by, words,"
            " started_at, state, finished_at, plan, catalogue, document, digest, grade,"
            " findings, made_by, sources, notes)"
            " VALUES (%s, %s, %s, %s, %s, 'drafted', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                kept.drafted_id,
                kept.newest.number + 1,
                made.by,
                made.words,
                now,
                now,
                json(made.plan.model_dump(mode="json")),
                made.catalogue,
                json(laid.document),
                workflow_digest(laid.document),
                laid.grade,
                json(laid.findings),
                made.how,
                _sources_json(made.sources),
                json(list(made.notes)),
            ),
        )

    async def set_up_again(
        self, drafted_id: str, asker: Principal
    ) -> DraftedWorkflowView | Refused | NotFound:
        state = await self._approvals.latest(drafted_id)
        if state is None:
            return NotFound()
        if state.set_up != "failed" or not await self._approvals.set_up_again(state.request.id):
            return Refused("There's nothing to try again.")
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.drafted_workflows SET set_up_problem = NULL"
                " WHERE drafted_id = %s AND set_up_approval = %s",
                (drafted_id, state.request.id),
            )
        log.info("%s asked to set %s up again", asker.user_id, drafted_id)
        return await self._viewed(drafted_id, asker)

    async def approval(self, approval_id: str, viewer: Principal) -> SetUpApprovalView | None:
        state = await self._approvals.get(ApprovalId(approval_id))
        if state is None:
            return None
        async with self._db.connection("builder") as conn:
            kept = await _kept(conn, state.request.drafted_id)
        assert kept is not None
        revision = kept.revision(state.request.revision)
        assert revision.document is not None and revision.plan is not None
        checked = await self._checked(kept, revision, viewer.user_id)
        refusal = await self._approvals.why_not(state, viewer)
        why_not = WHY_NOT[refusal] if refusal is not None else _held_by_today(checked)
        return SetUpApprovalView(
            approval_id=state.request.id,
            drafted_id=kept.drafted_id,
            revision=revision.number,
            name=revision.plan.name,
            digest=state.request.digest,
            approval=_approval_view(state),
            report=view_of(checked.report, kept.use_case_id, revision.plan.name, None, False),
            you_can_decide=why_not is None,
            why_not=why_not,
            decline_reasons=list(DECLINE_REASONS),
            set_up=_set_up_view(kept, state),
        )

    async def decide(
        self, approval_id: str, viewer: Principal, decision: SetUpDecisionIn
    ) -> tuple[SetUpApprovalView, bool] | Forbidden | NotFound:
        """The gate decides. True with a decision recorded now, False with one recorded before."""
        verdict = Verdict.APPROVE if decision.verdict == "approve" else Verdict.DECLINE
        if verdict is Verdict.APPROVE:
            held = await self._held_now(approval_id)
            if isinstance(held, NotFound):
                return held
            if held is not None:
                return Forbidden(held)
        decided = await self._approvals.decide(
            ApprovalId(approval_id), viewer, verdict, Digest(decision.digest), decision.reason
        )
        match decided:
            case SetUpRefused(refusal):
                return Forbidden(WHY_NOT[refusal])
            case SetUpDecided(repeated=repeated):
                view = await self.approval(approval_id, viewer)
                assert view is not None
                return view, not repeated
            case _:
                return NotFound()

    async def set_up(self, approved: ApprovedSetUp) -> SetUpFinished | TryAgain:
        """The approved revision as a Draft in the platform's n8n project (flow step 9): created
        through n8n's API, read back, and kept only when its digest equals the approved one. It
        is the builder's half of the set-up approval, asked once for each approval."""
        async with self._db.transaction("builder") as uow:
            await hold_workflow(uow.conn, f"drafted:{approved.drafted_id}", alone=True)
            kept = await _kept(uow.conn, approved.drafted_id)
            if kept is None or kept.set_up_at is not None:
                return SetUpFinished()
            newest = kept.newest
            if (
                approved.revision != newest.number
                or newest.digest != approved.digest
                or newest.document is None
                or newest.plan is None
                or workflow_digest(newest.document) != approved.digest
            ):
                return await _refused(uow.conn, kept, approved, CHANGED)
            n8n = self._n8n
            if n8n is None:
                return await _refused(uow.conn, kept, approved, NO_N8N)
            error_workflow = await n8n.error_workflow_id()
            if error_workflow is None:
                return TryAgain("n8n's error workflow is not loaded")
            known = await self._known(newest.plan)
            graded = grade(newest.document, error_workflow, self._zone, known)
            if graded.findings:
                return await _refused(uow.conn, kept, approved, NO_LONGER_PASSES)
            try:
                held = await _left_by_an_earlier_try(n8n, kept, approved)
                if held is None:
                    await self._tried(kept.drafted_id, approved, None)

                    async def created(workflow_id: str) -> None:
                        await self._tried(kept.drafted_id, approved, workflow_id)

                    saved = await n8n.save_draft(newest.document, created)
                    held = Held(saved.workflow_id, saved.version_id, _with_pins(saved))
            except NotKeptAsSent:
                return await _refused(uow.conn, kept, approved, CHANGED)
            except (N8nError, httpx.HTTPError) as error:
                return TryAgain(f"n8n did not answer ({type(error).__name__})")
            if workflow_digest(held.document) != approved.digest:
                await n8n.remove(held.workflow_id)
                return await _refused(uow.conn, kept, approved, CHANGED)
            try:
                await _insert_use_case(
                    uow.conn,
                    kept,
                    held.workflow_id,
                    held.version_id,
                    held.document,
                    grading_mark(error_workflow, self._zone),
                    approved,
                    uow.now,
                )
            except Exception:
                await n8n.remove(held.workflow_id)
                raise
        log.info(
            "set up %s revision %d as %s, a draft, on %s's approval %s",
            approved.drafted_id,
            approved.revision,
            kept.use_case_id,
            ", ".join(approved.approvers),
            approved.approval_id,
        )
        return SetUpFinished()

    async def _tried(
        self, drafted_id: str, approved: ApprovedSetUp, workflow_id: str | None
    ) -> None:
        """Kept at once, outside the set-up's own transaction, so a try cut off after n8n
        created the workflow leaves the next try the id to look for."""
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.drafted_workflows SET set_up_approval = %s,"
                " set_up_trying_at = %s, set_up_n8n_id = %s, set_up_problem = NULL"
                " WHERE drafted_id = %s AND set_up_at IS NULL",
                (approved.approval_id, uow.now, workflow_id, drafted_id),
            )

    async def gave_up(self, approved: ApprovedSetUp, detail: str) -> None:
        async with self._db.transaction("builder") as uow:
            await uow.conn.execute(
                "UPDATE builder.drafted_workflows SET set_up_problem = %s, set_up_approval = %s"
                " WHERE drafted_id = %s AND set_up_at IS NULL",
                (NOT_TAKEN, approved.approval_id, approved.drafted_id),
            )

    async def settle(self) -> None:
        """Waits for every draft this process started, as a test or a shutdown does. It waits only
        for drafts still going: an ended one leaves the set in a callback that needs a turn of the
        loop, and gather() on ended drafts gives it none."""
        while going := [task for task in self._running if not task.done()]:
            await asyncio.gather(*going, return_exceptions=True)

    async def draft(self, drafted_id: str, number: int) -> None:
        """Drafts one revision: the drafter plans, and code lays it out and checks it."""
        async with self._db.connection("builder") as conn:
            kept = await _kept(conn, drafted_id)
        if kept is None:
            return
        revision = next(r for r in kept.revisions if r.number == number)
        if revision.state != "drafting":
            return
        if self._n8n is not None and await self._n8n.n8n_version() is None:
            ready = await self._n8n.error_workflow_id() is not None
            await _finish(self._db, drafted_id, number, said=PAUSED if ready else N8N_NOT_READY)
            return
        current = kept.current_plan(number)
        result = await self._drafting.draft(revision.words, await self._facts_for(), current)
        match result:
            case WorkflowDrafted(plan=plan, catalogue=catalogue):
                await self._lay_out(kept, number, plan, catalogue)
            case KeyPasted(message=message) | WorkflowNotDrafted(message=message):
                await _finish(self._db, drafted_id, number, said=message)
            case NoModel():
                await _finish(self._db, drafted_id, number, said=NO_MODEL)
            case RuntimeDown(detail=detail):
                log.warning("the drafter did not answer for %s: %s", drafted_id, detail)
                await _finish(self._db, drafted_id, number, said=COULDNT_DRAFT)
            case ModelProblem(reason=reason):
                log.warning("the drafter's model failed for %s: %s", drafted_id, reason)
                await _finish(self._db, drafted_id, number, said=COULDNT_DRAFT)

    def _draft_in_the_background(self, drafted_id: str, number: int) -> None:
        task = asyncio.create_task(self._draft_safely(drafted_id, number))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def _draft_safely(self, drafted_id: str, number: int) -> None:
        try:
            await self.draft(drafted_id, number)
        except Exception as error:
            # Only the error's type: the words could be in its message.
            log.error("drafting %s failed: %s", drafted_id, type(error).__name__)
            try:
                await _finish(self._db, drafted_id, number, said=COULDNT_DRAFT)
            except Exception as again:
                log.error("could not record that %s failed: %s", drafted_id, type(again).__name__)

    async def _lay_out(self, kept: Kept, number: int, plan: WorkflowPlan, catalogue: str) -> None:
        if self._n8n is None or (error_workflow := await self._n8n.error_workflow_id()) is None:
            await _finish(self._db, kept.drafted_id, number, said=N8N_NOT_READY)
            return
        if not drafts_for(catalogue, await self._n8n.n8n_version()):
            await _finish(self._db, kept.drafted_id, number, said=PAUSED)
            return
        plan = never_guessed(plan)
        laid = await self._laid(kept, plan, error_workflow)
        before = _drafted_before(kept, number)
        await _finish(
            self._db,
            kept.drafted_id,
            number,
            plan=plan,
            catalogue=catalogue,
            document=laid.document,
            grade=laid.grade,
            findings=laid.findings,
            sources=carried(
                {} if before is None else before.sources,
                plan,
                {},
                kept.revision(number).asked_by,
            ),
        )

    async def _laid(self, kept: Kept, plan: WorkflowPlan, error_workflow: str) -> Laid:
        document = await self._check(kept, plan, error_workflow)
        graded = grade(document, error_workflow, self._zone, await self._known(plan))
        findings = [{"rule": f.rule, "block": f.block, "text": f.text} for f in graded.findings]
        return Laid(document, graded.grade, findings)

    async def _check(self, kept: Kept, plan: WorkflowPlan, error_workflow: str) -> dict[str, Any]:
        """Laid out with what every layout adds, then the yes before each write by our blocks,
        then the platform's keys, as Made in n8n's set-up does. Record the run comes with build
        step 10, in lay_out_drafted."""
        laid = lay_out_drafted(
            DraftedLayout(
                kept.use_case_id,
                f"{self._public_base_url}/workflows/{kept.use_case_id}",
                plan,
                error_workflow,
                self._zone,
            ),
            {s.id: s.value for s in plan.settings if s.value is not None},
        )
        known = await self._known(plan)
        return attach_keys(add_yes(laid, kept.use_case_id).document, known.keys)

    async def _checked(
        self,
        kept: Kept,
        revision: Revision,
        viewer: UserId | None = None,
    ) -> Checked:
        """Graded under today's rules, as Explain grades every version, with each setting as
        the builder sees it and where each value came from, in words for this viewer."""
        plan, document = revision.plan, revision.document
        assert plan is not None and document is not None
        error_workflow = None if self._n8n is None else await self._n8n.error_workflow_id()
        known = await self._known(plan)
        cards = {c.card_id: c for c in await self._cards.list()}
        settings = settings_of(plan, revision.sources)
        givers = [s.source.by for s in settings if s.source is not None and s.source.by]
        names = await self._approvals.names(givers) if givers else {}
        report = workflow_report(
            Drafted(
                document,
                cards,
                report_settings(settings, viewer, names),
            ),
            Team(error_workflow, self._zone, known),
        )
        access = any(
            isinstance(write.decides, EachRun) and write.decides.approvers >= 2
            for write in report.approves
        )
        return Checked(dict(document), report, access, settings, names)

    async def _known(self, plan: WorkflowPlan) -> KnownOptions:
        """The team's options, with each repository the plan reads, as a Planner's layout adds
        the one it reads: any public repository's releases may be read."""
        repos = [s.value for s in plan.settings if s.kind == "repository" and s.value]
        return await self._facts.known({GITHUB_RELEASES: repos})

    async def _facts_for(self) -> DrafterFacts:
        options = await self._options()
        cards = await self._cards.list()
        return options.model_copy(
            update={"agent_cards": [library_card(card) for card in cards[:50]]}
        )

    async def _held_now(self, approval_id: str) -> str | None | NotFound:
        """Why a yes would be taken on a revision today's rules wouldn't set up."""
        state = await self._approvals.get(ApprovalId(approval_id))
        if state is None:
            return NotFound()
        async with self._db.connection("builder") as conn:
            kept = await _kept(conn, state.request.drafted_id)
        assert kept is not None
        return _held_by_today(await self._checked(kept, kept.revision(state.request.revision)))

    def _drafting_now(self, revision: Revision) -> bool:
        return revision.state == "drafting" and self._db.clock() - revision.started_at < (
            DRAFTING_LIMIT
        )

    async def _viewed(
        self, drafted_id: str, viewer: Principal | None = None
    ) -> DraftedWorkflowView:
        view = await self.view(drafted_id, viewer)
        assert view is not None
        return view

    async def _view(self, kept: Kept, viewer: Principal | None = None) -> DraftedWorkflowView:
        newest = kept.newest
        state = await self._approvals.latest(kept.drafted_id)
        mine = state if state is not None and state.request.revision == newest.number else None
        replaced = (
            state is not None
            and state.request.revision < newest.number
            and state.request.ended is Ended.CANCELLED
        )
        name = next((r.plan.name for r in reversed(kept.revisions) if r.plan), None)
        base = DraftedWorkflowView(
            drafted_id=kept.drafted_id,
            revision=newest.number,
            card_revision=kept.card_revision,
            made_by=newest.made_by,
            name=name,
            state="drafting",
            words=newest.words,
            said=None,
            started_at=newest.started_at,
            blocks=[],
            report=None,
            needed=0,
            flags=0,
            settings=[],
            question=None,
            notes=[],
            in_n8n=await self._in_n8n_view(kept, viewer),
            can_edit_in_n8n=False,
            can_send=False,
            why_not_send=STILL_DRAFTING,
            replaced_waiting=replaced,
            approval=None if mine is None else _approval_view(mine),
            set_up=None if mine is None else _set_up_view(kept, mine),
        )
        if newest.state == "drafting":
            if self._drafting_now(newest):
                return base
            return base.model_copy(
                update={"state": "not_drafted", "said": COULDNT_DRAFT, "why_not_send": None}
            )
        if newest.state == "not_drafted" or newest.plan is None or newest.document is None:
            return base.model_copy(
                update={"state": "not_drafted", "said": newest.said, "why_not_send": None}
            )
        checked = await self._checked(kept, newest, None if viewer is None else viewer.user_id)
        report = checked.report
        options, listed_at = await self._options_listed()
        asked = [(s, asking(s, options)) for s in checked.settings]
        loose = strays(newest.plan)
        needed = sum(s.mark == "needed" for s, _ in asked) + len(loose)
        answerable = sum(s.mark == "needed" and q.waits is None for s, q in asked)
        waiting = [(s, q) for s, q in asked if s.mark == "needed" and q.waits is not None]
        flags = len(report.flags)
        why = (
            answer_first(answerable)
            if answerable
            else stray_words(loose[0][0])
            if loose
            else flags_later(flags)
            if flags
            else (KEYS_WAIT if waiting[0][0].kind == "key" else waiting[0][1].waits)
            if waiting
            else ACCESS_LATER
            if checked.changes_access
            else None
        )
        lived: DraftedState = "draft"
        if mine is not None:
            match mine.status:
                case Approved() if _holds(kept, mine):
                    lived = "approved"
                case Approved():
                    lived = "draft"
                case Declined():
                    lived = "declined"
                case Closed():
                    lived = "draft"
                case _:
                    lived = "waiting"
        editing = lived == "draft" and kept.in_n8n is None
        question = next_question(checked.settings, options) if editing else None
        if kept.in_n8n is not None:
            why = IN_N8N_NOW
        return base.model_copy(
            update={
                "state": lived,
                "blocks": blocks_of(newest.document),
                "report": view_of(report, kept.use_case_id, newest.plan.name, None, False),
                "needed": needed,
                "flags": flags,
                "settings": setting_views(
                    checked.settings, options, viewer and viewer.user_id, checked.names, listed_at
                ),
                "question": None if question is None else question.id,
                "notes": list(newest.notes),
                "can_edit_in_n8n": editing and await self._may_edit_in_n8n(viewer),
                "can_send": editing and why is None,
                "why_not_send": why if lived == "draft" else _not_now(lived),
            }
        )

    async def _in_n8n_view(self, kept: Kept, viewer: Principal | None) -> DraftedInN8nView | None:
        held = kept.in_n8n
        if held is None:
            return None
        names = await self._approvals.names([held.by])
        yours = viewer is not None and viewer.user_id == held.by
        url = None if self._editor_url is None or not yours else self._link(held.workflow_id)
        return DraftedInN8nView(
            by=held.by,
            by_name=names[held.by],
            since=held.since,
            revision=held.revision,
            editor_url=url,
        )

    def _link(self, workflow_id: str) -> str:
        return f"{self._editor_url}/workflow/{workflow_id}"

    async def _may_edit_in_n8n(self, viewer: Principal | None) -> bool:
        if viewer is None or self._staff is None or self._n8n is None:
            return False
        if Role.OPERATOR not in viewer.roles:
            return False
        return isinstance(await self._staff.access(viewer.user_id), CanOpen)

    async def _options(self) -> DrafterFacts:
        """The team's own data the questions offer, and the drafter may use, without the cards."""
        options, _ = await self._options_listed()
        return options

    async def _options_listed(self) -> tuple[DrafterFacts, str | None]:
        """The team's own data, and when Slack last listed its channels once it stopped
        answering, in the team's time, as 10:05."""
        listed = (
            ChannelList([], None, False)
            if self._channels is None
            else (await self._channels.listed())
        )
        known = await self._facts.known({})
        when = (
            f"{listed.as_of.astimezone(ZoneInfo(self._zone)):%H:%M}"
            if listed.stale and listed.as_of is not None
            else None
        )
        return DrafterFacts(
            jira_projects=_places(known, "jira."),
            confluence_pages=_places(known, "confluence."),
            repositories=sorted(
                known.places.get(GITHUB_RELEASES, frozenset()) - {WATCHLIST_PLACE.id}
            ),
            channels=listed.channels,
        ), when


def _places(known: KnownOptions, prefix: str) -> list[str]:
    return sorted(
        {p for action, places in known.writes.items() if action.startswith(prefix) for p in places}
    )


WHY_NOT: Final[Mapping[Refusal, str]] = {
    Refusal.OWN_WORK: (
        "You can't approve it. You asked for it, changed it, answered its questions or sent it."
    ),
    Refusal.NOT_AN_APPROVER: "Only an Approver can decide a set-up.",
    Refusal.NOT_OPEN: "It's not waiting for a yes any more.",
    Refusal.STALE_DIGEST: "It changed since you opened it. Open it again.",
    Refusal.INVALID_DECISIONS: "Its decisions don't add up, so nobody can decide it.",
    Refusal.WRONG_STEP: "It's not waiting for this step.",
    Refusal.DECIDED_EARLIER_STEP: "You decided an earlier step.",
    Refusal.NOT_ELIGIBLE: "You're not one of the Approvers who can decide it.",
}


def drafts_for(catalogue: str, n8n_version: str | None) -> bool:
    """Whether the drafter's catalogue, named by the n8n image it was made from, describes the
    n8n the platform runs. During an update the two can differ, and a draft could then name a
    block or a parameter the running n8n doesn't have (ADR 0051, section 8)."""
    repository, _, tag = catalogue.partition("@")[0].rpartition(":")
    return n8n_version is not None and repository == N8N_IMAGE and tag == n8n_version


def _answered_words(setting: SettingNow, read: Answered) -> str:
    """The answer, as the revision's words: code's label and the value, never a key's."""
    label = setting.label if setting.block is None else f"{setting.label} {setting.block}"
    return f"{label}: {read.value}"


def _holds_a_key(document: Mapping[str, Any]) -> bool:
    """Whether anything a read-back could keep is shaped like a key: the workflow's name, or any
    string anywhere in a block, its name and parameters, expressions and code included."""
    return any(
        PASTED_KEY.search(text) for text in _strings([document.get("name"), document.get("nodes")])
    )


def _strings(value: object) -> Iterable[str]:
    match value:
        case str():
            yield value
        case dict():
            for key, inner in cast(dict[object, object], value).items():
                yield from _strings(key)
                yield from _strings(inner)
        case list() | tuple():
            for inner in cast(Sequence[object], value):
                yield from _strings(inner)
        case _:
            return


def _without_keys(document: Mapping[str, Any]) -> dict[str, Any]:
    """The document as it opens in a person's own n8n space: no block names a key."""
    copied = deepcopy(dict(document))
    for node in cast(list[dict[str, Any]], copied.get("nodes") or []):
        node.pop("credentials", None)
    return copied


async def _out_of_n8n(conn: Connection, drafted_id: str) -> None:
    await conn.execute(
        "UPDATE builder.drafted_workflows SET in_n8n_id = NULL, in_n8n_by = NULL,"
        " in_n8n_since = NULL, in_n8n_revision = NULL WHERE drafted_id = %s",
        (drafted_id,),
    )


def stray_words(block: str) -> str:
    return (
        f"“{block}” holds a placeholder no setting fills, so it can't be sent. Ask for a change "
        "to draft it again."
    )


def _drafted_before(kept: Kept, number: int) -> Revision | None:
    """The newest revision drafted before this one, whose sources a new revision carries."""
    drafted = [r for r in kept.revisions if r.number < number and r.plan is not None]
    return drafted[-1] if drafted else None


def _not_now(state: DraftedState) -> str | None:
    match state:
        case "waiting":
            return "Waiting for an Approver. You can't approve your own draft."
        case "approved":
            return "Approved."
        case "declined":
            return "Declined. Ask for a change to send it again."
        case "drafting":
            return STILL_DRAFTING
        case _:
            return None


def _approval_view(state: SetUpState) -> DraftedApprovalView:
    request, status = state.request, state.status
    decided = state.decisions[-1] if state.decisions else None
    status_words: Literal["waiting", "approved", "declined", "expired", "replaced"]
    match status:
        case Approved():
            status_words = "approved"
        case Declined():
            status_words = "declined"
        case Closed(ended):
            status_words = "expired" if ended is Ended.EXPIRED else "replaced"
        case _:
            status_words = "waiting"
    return DraftedApprovalView(
        approval_id=request.id,
        link=set_up_link(request.id),
        status=status_words,
        sent_by=state.names.get(request.sent_by, "Someone"),
        sent_at=request.created_at,
        expires_at=request.expires_at,
        decided_by=None if decided is None else state.names.get(decided.by, "Someone"),
        decided_at=None if decided is None else decided.at,
        reason=None if decided is None else decided.reason,
        posted=state.post,
    )


def _problem_of(kept: Kept, state: SetUpState) -> str | None:
    """Why this approval's set-up did not finish. A problem left by an earlier approval is not
    this one's."""
    return kept.set_up_problem if kept.set_up_approval == state.request.id else None


def _holds(kept: Kept, state: SetUpState) -> bool:
    """An approval of the newest revision holds it while its set-up is done or still to come. A
    set-up refused or given up leaves it a draft again, to change or send again, and a yes on an
    older revision holds nothing."""
    if not isinstance(state.status, Approved) or state.request.revision != kept.newest.number:
        return False
    if kept.set_up_at is not None:
        return True
    return _problem_of(kept, state) is None and state.set_up == "waiting"


def _held_by_today(checked: Checked) -> str | None:
    """Why the revision can't be approved under today's rules, which the set-up grades it by."""
    report = checked.report
    if report.flags:
        return FLAGGED_NOW
    if report.needs_an_answer:
        return NEEDED_NOW
    if checked.changes_access:
        return ACCESS_LATER
    return None


def _set_up_view(kept: Kept, state: SetUpState) -> DraftedSetUpView | None:
    if not isinstance(state.status, Approved):
        return None
    if kept.set_up_at is not None:
        return DraftedSetUpView(state="set_up", use_case_id=kept.use_case_id, words=None)
    problem = _problem_of(kept, state)
    if problem is not None:
        retry = problem == NOT_TAKEN
        return DraftedSetUpView(
            state="failed" if retry else "refused", use_case_id=None, words=problem
        )
    if state.set_up == "failed":
        return DraftedSetUpView(state="failed", use_case_id=None, words=NOT_TAKEN)
    return DraftedSetUpView(state="setting_up", use_case_id=None, words=None)


async def _begin(
    conn: Connection, drafted_id: str, number: int, asked_by: UserId, words: str, now: datetime
) -> None:
    await conn.execute(
        "INSERT INTO builder.drafted_revisions (drafted_id, revision, asked_by, words,"
        " started_at, state) VALUES (%s, %s, %s, %s, %s, 'drafting')",
        (drafted_id, number, asked_by, words, now),
    )


async def _finish(
    db: Database,
    drafted_id: str,
    number: int,
    *,
    said: str | None = None,
    plan: WorkflowPlan | None = None,
    catalogue: str | None = None,
    document: dict[str, Any] | None = None,
    grade: str | None = None,
    findings: list[dict[str, Any]] | None = None,
    sources: Sources | None = None,
) -> None:
    drafted = document is not None
    async with db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.drafted_revisions SET state = %s, finished_at = %s, plan = %s,"
            " catalogue = %s, document = %s, digest = %s, grade = %s, findings = %s, said = %s,"
            " sources = %s WHERE drafted_id = %s AND revision = %s AND state = 'drafting'",
            (
                "drafted" if drafted else "not_drafted",
                uow.now,
                None if plan is None else json(plan.model_dump(mode="json")),
                catalogue,
                None if document is None else json(document),
                None if document is None else workflow_digest(document),
                grade,
                None if findings is None else json(findings),
                None if drafted else said or COULDNT_DRAFT,
                _sources_json(sources or {}),
                drafted_id,
                number,
            ),
        )


@dataclass(frozen=True)
class Held:
    """A workflow n8n holds for the approved revision, with its pins, as its digest reads it."""

    workflow_id: str
    version_id: str
    document: dict[str, Any]


def _with_pins(saved: SavedDraft | N8nWorkflow) -> dict[str, Any]:
    return {**saved.document, **({"pinData": saved.pins} if saved.pins else {})}


def _ours(document: Mapping[str, Any], use_case_id: str) -> bool:
    """Laid out for this workflow: its Start from the Portal has the webhook id only this
    workflow's layout gives it."""
    start = block_id(use_case_id, "webhook/start")
    nodes = cast(list[dict[str, Any]], document.get("nodes") or [])
    return any(n.get("type") == TYPE_OF["start"] and n.get("webhookId") == start for n in nodes)


async def _left_by_an_earlier_try(
    n8n: SettingUp, kept: Kept, approved: ApprovedSetUp
) -> Held | None:
    """A try that was cut off after n8n created the workflow leaves it there, under this approval
    or under an earlier one that gave up. The next try takes the id the last try recorded, or,
    when it was cut off before it could record one, the workflow its layout alone could have
    made: Start from the Portal with this workflow's own webhook id. It looks only in the
    platform's own n8n project, never in a member's space. It keeps a draft whose digest is the
    approved one and removes any other, so asking twice, or sending again, never makes two. The
    first try looks for nothing."""
    if kept.set_up_trying_at is None or kept.set_up_at is not None:
        return None
    project = await n8n.platform_project()
    if project is None:
        raise N8nError("the platform's n8n project is not recorded")
    there = [listed.workflow for listed in await n8n.workflows_in(project)]
    recorded = kept.set_up_n8n_id
    left = [
        w
        for w in there
        if (w.id == recorded if recorded is not None else _ours(w.document, kept.use_case_id))
    ]
    kept_one: Held | None = None
    for found in left:
        whole = await n8n.look(found.id)
        if whole is None:
            continue
        document = _with_pins(whole)
        if (
            kept_one is None
            and whole.active_version_id is None
            and workflow_digest(document) == approved.digest
        ):
            kept_one = Held(whole.id, whole.version_id, document)
        else:
            log.warning(
                "removing %s, left in n8n by an earlier set-up of %s", whole.id, kept.drafted_id
            )
            await n8n.remove(whole.id)
    return kept_one


async def _refused(
    conn: Connection, kept: Kept, approved: ApprovedSetUp, words: str
) -> SetUpFinished:
    await conn.execute(
        "UPDATE builder.drafted_workflows SET set_up_problem = %s, set_up_approval = %s"
        " WHERE drafted_id = %s",
        (words, approved.approval_id, kept.drafted_id),
    )
    log.warning("the set-up of %s was refused: %s", kept.drafted_id, words)
    return SetUpFinished()


async def _kept(conn: Connection, drafted_id: str) -> Kept | None:
    row = await (
        await conn.execute(
            "SELECT drafted_id, owner, use_case_id, set_up_at, set_up_approval,"
            " set_up_trying_at, set_up_n8n_id, set_up_problem, in_n8n_id, in_n8n_by,"
            " in_n8n_since, in_n8n_revision FROM builder.drafted_workflows WHERE drafted_id = %s",
            (drafted_id,),
        )
    ).fetchone()
    if row is None:
        return None
    rows = await (
        await conn.execute(
            "SELECT revision, asked_by, words, started_at, state, plan, document, digest, said,"
            " made_by, sources, catalogue, notes"
            " FROM builder.drafted_revisions WHERE drafted_id = %s ORDER BY revision",
            (drafted_id,),
        )
    ).fetchall()
    revisions = tuple(
        Revision(
            int(r["revision"]),
            UserId(r["asked_by"]),
            str(r["words"]),
            r["started_at"],
            r["state"],
            None if r["plan"] is None else WorkflowPlan.model_validate(r["plan"]),
            None if r["document"] is None else cast(dict[str, Any], r["document"]),
            r["digest"],
            r["said"],
            r["made_by"],
            _sources_of(r["sources"]),
            r["catalogue"],
            tuple(str(n) for n in r["notes"] or ()),
        )
        for r in rows
    )
    in_n8n = (
        None
        if row["in_n8n_id"] is None
        else InN8n(
            str(row["in_n8n_id"]),
            UserId(row["in_n8n_by"]),
            row["in_n8n_since"],
            int(row["in_n8n_revision"]),
        )
    )
    return Kept(
        str(row["drafted_id"]),
        UserId(row["owner"]),
        str(row["use_case_id"]),
        row["set_up_at"],
        row["set_up_approval"],
        row["set_up_trying_at"],
        row["set_up_n8n_id"],
        row["set_up_problem"],
        revisions,
        in_n8n,
    )


def _sources_of(held: Mapping[str, Any] | None) -> dict[str, Source]:
    return {
        setting_id: Source(str(s["value"]), s["how"], None if s["by"] is None else UserId(s["by"]))
        for setting_id, s in (held or {}).items()
    }


def _sources_json(sources: Sources) -> Jsonb:
    return json({k: {"value": s.value, "how": s.how, "by": s.by} for k, s in sources.items()})


def carried(
    before: Sources, plan: WorkflowPlan, given: Sources, by: UserId | None
) -> dict[str, Source]:
    """Where each value of a new revision came from: what was just given, else what an earlier
    revision said of the same value, else the words the revision was asked in. The Approvers are
    not the plan's, so they carry as they are."""
    sources: dict[str, Source] = {}
    for setting in plan.settings:
        if setting.mark != "filled" or setting.value is None:
            continue
        was = given.get(setting.id) or before.get(setting.id)
        same = was is not None and was.value == setting.value
        sources[setting.id] = was if same and was else Source(setting.value, "words", by)
    planned = {s.id for s in plan.settings}
    others = {**before, **given}
    return sources | {k: s for k, s in others.items() if k not in planned}


async def _insert_use_case(
    conn: Connection,
    kept: Kept,
    workflow_id: str,
    version_id: str,
    document: dict[str, Any],
    graded_by: str,
    approved: ApprovedSetUp,
    now: datetime,
) -> None:
    """Version 1 is the approved revision as n8n holds it, a Draft that whoever turns it on
    publishes (ADR 0044). Everyone who described it, changed it, answered it or sent it is one of
    its authors, so a run of it is their work too, as Made in n8n's maker's is."""
    newest = kept.newest
    assert newest.plan is not None
    authors = [Publication(p, "portal") for p in sorted(approved.parties)]
    await conn.execute(
        "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version,"
        " left_out, draft, engine, n8n_workflow_id, n8n_draft_id)"
        " VALUES (%s, %s, %s, 1, '{}', true, 'own', %s, %s)",
        (kept.use_case_id, kept.owner, now, workflow_id, version_id),
    )
    await conn.execute(
        "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
        " instruction, params, created_at, n8n_version_id, grade, document, findings,"
        " graded_by, published_by, published_in, also)"
        " VALUES (%s, 1, %s, %s, %s, %s, %s, %s, 'safe', %s, %s, %s, NULL, NULL, %s)",
        (
            kept.use_case_id,
            AGENT_CARDS.key,
            newest.plan.name,
            kept.revisions[0].words,
            json({}),
            now,
            version_id,
            json(document),
            json([]),
            graded_by,
            authors_json(authors),
        ),
    )
    await conn.execute(
        "UPDATE builder.drafted_workflows SET set_up_at = %s, set_up_problem = NULL,"
        " set_up_approval = %s, set_up_revision = %s WHERE drafted_id = %s",
        (now, approved.approval_id, newest.number, kept.drafted_id),
    )
