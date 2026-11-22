"""Staff n8n accounts (ENGINE-PLAN 2.9, D17, M5). The People list decides who has n8n access; the
platform makes and ends each person's n8n account to match, and keeps n8n's user id for it, which
every later match uses. An account is made only while N8N_STAFF_ACCESS is on and the last
bootstrap proved n8n's blocks and guards (ADR 0051), so no staff account exists until it has.

The account follows the flag on its own: each settle reads the list and n8n and does only what
differs, so a settle cut off anywhere is finished by the next. An account is ended only once its
person holds no workflow, and whatever its own space still holds moves to the platform's
project, so nothing is deleted with it. The password-set link is sealed at rest, shown only to
its person at the address people open n8n from, and dropped once used. It is never logged."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from platform_api.db import Database
from platform_api.orchestration.model_settings import KeyBox
from platform_api.orchestration.n8n import N8nApi, N8nError, personal_spaces, platform_project
from platform_api.shared import UserId

log = logging.getLogger(__name__)

SETTLE_EVERY = timedelta(seconds=15)

NO_ACCESS = "Only people with n8n access can open n8n. An admin can add it in Settings."
A_COLLEAGUE = "a colleague"
"""Who someone is when the platform can't name them, as a user id means nothing to anyone."""
APPROVERS_NO_ACCESS = "Approvers can't have n8n access. An Operator with n8n access can open it."


def no_access_words(approver: bool) -> str:
    """No one can add n8n access for an Approver, so they are told who can open it instead."""
    return APPROVERS_NO_ACCESS if approver else NO_ACCESS


OFF = "Opening n8n from here isn't turned on. The person who runs the platform can turn it on."
NOT_READY = (
    "n8n can't be opened from here until its block list is checked again. Your own n8n space "
    "stays, without any of the team's workflows."
)
INVITE_LIFE = timedelta(days=7)
"""n8n's password link never runs out, so an unused one this old is replaced by a new account
and link, shown only to its person."""
NOT_MADE = "Your n8n account isn't made yet. Try again in a minute."
SET_PASSWORD = "Set your n8n password first. The link is on your Settings page."
NO_ADDRESS = (
    "Set your n8n password first. Your link can't be shown until the platform knows n8n's "
    "address. Ask the person who runs the platform to set it."
)


class Quarantine(Protocol):
    async def quarantine(self, project: str, n8n_user_id: str) -> list[str]:
        """Notes the keys in this space, which n8n moves to the platform's project as the account
        ends, so the credential sweep keeps them there unused, never as the platform's."""
        ...


@dataclass(frozen=True)
class StaffGate:
    switched_on: bool
    """N8N_STAFF_ACCESS."""
    ready: bool
    """The last bootstrap was ready, so it proved that n8n loads every built-in block but
    the seven left out, and runs with the guards that keep a workflow's code from n8n's secrets."""

    @property
    def closed(self) -> str | None:
        """Why no staff account is made and nothing opens in n8n now, or None."""
        if not self.switched_on:
            return OFF
        if not self.ready:
            return NOT_READY
        return None


@dataclass(frozen=True)
class NoN8nAccess:
    words: str = NO_ACCESS


@dataclass(frozen=True)
class StaffClosed:
    words: str


@dataclass(frozen=True)
class NotYet:
    words: str


@dataclass(frozen=True)
class CanOpen:
    person: UserId
    n8n_user_id: str


type StaffAccess = NoN8nAccess | StaffClosed | NotYet | CanOpen
"""Whether a person may hold a workflow in n8n now, and the words when not."""

type AccountState = Literal["none", "invited", "ready"]


@dataclass(frozen=True)
class MyN8n:
    """What a person's own Settings page shows about n8n."""

    access: bool
    account: AccountState
    set_password_url: str | None = field(repr=False)
    can_open: bool
    why_not: str | None
    editor_url: str | None


@dataclass(frozen=True)
class _Row:
    id: UserId
    email: str
    access: bool
    on_list: bool
    operator: bool
    approver: bool
    n8n_user_id: str | None
    sealed_invite: str | None
    invited_at: datetime | None

    @property
    def may_hold(self) -> bool:
        """n8n access, on the People list, as an Operator who is no Approver. The table refuses
        any other row with the flag; this is asked again so no Approver opens n8n whatever a row
        says."""
        return self.access and self.on_list and self.operator and not self.approver


@dataclass(frozen=True)
class Made:
    person: UserId


@dataclass(frozen=True)
class Ended:
    person: UserId


@dataclass(frozen=True)
class Accepted:
    person: UserId


@dataclass(frozen=True)
class Reissued:
    person: UserId


type Settled = Made | Ended | Accepted | Reissued


def _ready_or_not(row: _Row, account: AccountState, link_shown: bool) -> NotYet | CanOpen:
    match account:
        case "none":
            return NotYet(NOT_MADE)
        case "invited":
            return NotYet(SET_PASSWORD if link_shown else NO_ADDRESS)
        case "ready":
            assert row.n8n_user_id is not None
            return CanOpen(row.id, row.n8n_user_id)


def _at_editor(link: str, editor_url: str) -> str:
    """n8n's password link at the address people open n8n from. n8n builds the link from its own
    address, which a browser outside the platform's network can't reach. n8n's path goes under
    the editor address's path unless it already starts with it, and the query, which holds the
    token, stays exactly as n8n gave it."""
    n8n, editor = urlsplit(link), urlsplit(editor_url)
    prefix = editor.path.rstrip("/")
    path = n8n.path if n8n.path.startswith(f"{prefix}/") else f"{prefix}{n8n.path}"
    return urlunsplit((editor.scheme, editor.netloc, path, n8n.query, n8n.fragment))


_ROW = (
    "SELECT id, email, n8n_access, removed_at IS NULL AS on_list, is_operator, is_approver,"
    " n8n_user_id, n8n_invite, n8n_invited_at FROM orchestration.people"
)


def _row(row: Mapping[str, Any]) -> _Row:
    return _Row(
        UserId(row["id"]),
        row["email"],
        row["n8n_access"],
        row["on_list"],
        row["is_operator"],
        row["is_approver"],
        row["n8n_user_id"],
        row["n8n_invite"],
        row["n8n_invited_at"],
    )


class StaffAccounts:
    def __init__(
        self,
        db: Database,
        api: N8nApi | None,
        box: KeyBox | None,
        switched_on: bool,
        editor_url: str | None = None,
        keys: Quarantine | None = None,
    ) -> None:
        self._db = db
        self._api = api
        self._box = box
        self._switched_on = switched_on
        self.editor_url = editor_url
        self.keys = keys
        """The platform's keys in n8n, so the keys an ending account leaves are kept unused."""
        self._lock = asyncio.Lock()
        self._nudged = asyncio.Event()

    def nudge(self) -> None:
        """Someone's access changed, or the platform is stopping, so the next settle comes now."""
        self._nudged.set()

    async def gate(self) -> StaffGate:
        async with self._db.connection("orchestration") as conn:
            row = await (
                await conn.execute("SELECT ready FROM orchestration.engine_status WHERE id = 1")
            ).fetchone()
        return StaffGate(self._switched_on, row is not None and bool(row["ready"]))

    async def people_by_n8n_user(self) -> Mapping[str, UserId]:
        """Each person the platform made an n8n account for, by that account's n8n user id."""
        async with self._db.connection("orchestration") as conn:
            rows = await (
                await conn.execute(
                    "SELECT id, n8n_user_id FROM orchestration.people WHERE n8n_user_id IS NOT NULL"
                )
            ).fetchall()
        return {row["n8n_user_id"]: UserId(row["id"]) for row in rows}

    async def makers(self) -> Mapping[str, UserId]:
        """Who made each workflow noted as it left its maker's own space (E15)."""
        async with self._db.connection("orchestration") as conn:
            rows = await (
                await conn.execute("SELECT workflow_id, made_by FROM orchestration.n8n_makers")
            ).fetchall()
        return {row["workflow_id"]: UserId(row["made_by"]) for row in rows}

    async def note_made(
        self, person: UserId, n8n_user_id: str, workflow_ids: Iterable[str]
    ) -> None:
        """Notes that these workflows were made in this person's own space, before they leave
        it. The first maker noted stays."""
        async with self._db.transaction("orchestration") as uow:
            for workflow_id in workflow_ids:
                await uow.conn.execute(
                    "INSERT INTO orchestration.n8n_makers (workflow_id, made_by, n8n_user_id,"
                    " noted_at) VALUES (%s, %s, %s, %s) ON CONFLICT (workflow_id) DO NOTHING",
                    (workflow_id, person, n8n_user_id, uow.now),
                )

    async def forget_made(self, workflow_ids: Iterable[str]) -> None:
        """Drops the notes of workflows still in their maker's own space, where their creator
        names the maker."""
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "DELETE FROM orchestration.n8n_makers WHERE workflow_id = ANY(%s)",
                (list(workflow_ids),),
            )

    async def display_of(self, person: UserId) -> str:
        async with self._db.connection("orchestration") as conn:
            row = await (
                await conn.execute(
                    "SELECT display FROM orchestration.people WHERE id = %s", (person,)
                )
            ).fetchone()
        return A_COLLEAGUE if row is None else str(row["display"])

    async def access(self, person: UserId) -> StaffAccess:
        row = await self._person(person)
        if row is None or not row.may_hold:
            return NoN8nAccess(no_access_words(row is not None and row.approver))
        if (closed := (await self.gate()).closed) is not None:
            return StaffClosed(closed)
        return _ready_or_not(row, await self._account(row), self.editor_url is not None)

    async def login_of(self, person: UserId) -> str | None:
        """The email the person signs in to n8n with, read from n8n by the account's id, since
        its member can change it in their profile and `people.email` then no longer says. None
        without n8n access or an account, and when n8n can't say: never a guess."""
        row = await self._person(person)
        if row is None or not row.may_hold or row.n8n_user_id is None or self._api is None:
            return None
        try:
            user = await self._api.user(row.n8n_user_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read the n8n login of %s: %s", person, type(error).__name__)
            return None
        return None if user is None or not user.email else user.email

    async def mine(self, person: UserId) -> MyN8n:
        row = await self._person(person)
        if row is None or not row.may_hold:
            words = no_access_words(row is not None and row.approver)
            return MyN8n(False, "none", None, False, words, None)
        account = await self._account(row)
        closed = (await self.gate()).closed
        access = (
            StaffClosed(closed)
            if closed is not None
            else _ready_or_not(row, account, self.editor_url is not None)
        )
        opened = None
        if account == "invited" and row.sealed_invite is not None and self._box is not None:
            opened = self._box.open(row.sealed_invite)
        link = (
            None
            if opened is None or self.editor_url is None
            else _at_editor(opened, self.editor_url)
        )
        if isinstance(access, CanOpen):
            return MyN8n(True, account, link, True, None, self.editor_url)
        assert not isinstance(access, NoN8nAccess)
        return MyN8n(True, account, link, False, access.words, None)

    async def settle(self, holds: Callable[[UserId], Awaitable[bool]]) -> list[Settled]:
        """Makes the account of each person who has n8n access and none yet, while the gate is
        open; ends the account of each person who no longer has access and holds nothing; and
        notes each invite that was used."""
        if self._api is None:
            return []
        async with self._lock:
            gate = await self.gate()
            async with self._db.connection("orchestration") as conn:
                rows = [
                    _row(r)
                    for r in await (
                        await conn.execute(
                            _ROW + " WHERE n8n_access OR n8n_user_id IS NOT NULL ORDER BY id"
                        )
                    ).fetchall()
                ]
            done: list[Settled] = []
            for row in rows:
                try:
                    step = await self._settle_one(row, gate, holds)
                except (N8nError, httpx.HTTPError) as error:
                    log.warning("could not settle the n8n account of %s: %s", row.id, error)
                    continue
                if step is not None:
                    done.append(step)
            return done

    async def settle_forever(
        self,
        stop: asyncio.Event,
        before: Callable[[], Awaitable[object]],
        holds: Callable[[UserId], Awaitable[bool]],
        every: timedelta = SETTLE_EVERY,
    ) -> None:
        """`before` takes back whatever someone holds who may hold nothing now, so an account
        whose access ended is free to end."""
        while not stop.is_set():
            self._nudged.clear()
            try:
                await before()
                await self.settle(holds)
            except Exception:
                log.exception("the n8n accounts could not be settled")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._nudged.wait(), every.total_seconds())

    async def _settle_one(
        self, row: _Row, gate: StaffGate, holds: Callable[[UserId], Awaitable[bool]]
    ) -> Settled | None:
        wants = row.may_hold
        if wants and row.n8n_user_id is None and gate.closed is None:
            return await self._make(row)
        if not wants and row.n8n_user_id is not None and not await holds(row.id):
            return await self._end(row)
        if wants and row.sealed_invite is not None:
            match await self._account(row):
                case "ready":
                    return Accepted(row.id)
                case "invited" if self._stale(row) and gate.closed is None:
                    return await self._reissue(row)
                case _:
                    return None
        return None

    def _stale(self, row: _Row) -> bool:
        return row.invited_at is not None and self._db.clock() - row.invited_at >= INVITE_LIFE

    async def _reissue(self, row: _Row) -> Reissued | None:
        """Ends the unused account and makes a new one, so the old link opens nothing."""
        await self._end(row)
        made = await self._make(replace(row, n8n_user_id=None, sealed_invite=None))
        log.info("replaced the unused n8n invite of %s with a new account", row.id)
        return None if made is None else Reissued(row.id)

    async def recheck(self, person: UserId) -> None:
        """Asks n8n whether the person's account is still there, and forgets one n8n no longer
        has, so the next settle makes it again."""
        row = await self._person(person)
        if row is None or row.n8n_user_id is None or self._api is None:
            return
        try:
            user = await self._api.user(row.n8n_user_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read the n8n account of %s: %s", person, error)
            return
        if user is not None:
            return
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.people SET n8n_user_id = NULL, n8n_invite = NULL,"
                " n8n_invited_at = NULL WHERE id = %s AND n8n_user_id = %s",
                (person, row.n8n_user_id),
            )
        log.warning("n8n no longer has the account of %s, so the platform makes it again", person)
        self.nudge()

    async def _make(self, row: _Row) -> Made | None:
        assert self._api is not None and self._box is not None
        invited = await self._api.invite(row.email)
        if invited is None:
            log.warning(
                "n8n made no account for %s, so n8n may already have one with that email. "
                "The platform never takes an account it did not make.",
                row.id,
            )
            return None
        async with self._db.transaction("orchestration") as uow:
            kept = await (
                await uow.conn.execute(
                    "UPDATE orchestration.people SET n8n_user_id = %s, n8n_invite = %s,"
                    " n8n_invited_at = %s WHERE id = %s AND n8n_user_id IS NULL AND n8n_access"
                    " AND removed_at IS NULL RETURNING id",
                    (invited.user_id, self._box.seal(invited.link), uow.now, row.id),
                )
            ).fetchone()
        if kept is None:
            await self._delete(invited.user_id)
            return None
        log.info("made the n8n account of %s", row.id)
        return Made(row.id)

    async def _end(self, row: _Row) -> Ended:
        """Ends the account whatever the note does. A delete n8n refuses raises, and the person
        stays marked for ending, so the next settle tries again."""
        assert row.n8n_user_id is not None
        await self._note_space(row)
        await self._delete(row.n8n_user_id)
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.people SET n8n_user_id = NULL, n8n_invite = NULL,"
                " n8n_invited_at = NULL WHERE id = %s AND n8n_user_id = %s",
                (row.id, row.n8n_user_id),
            )
        log.info("ended the n8n account of %s", row.id)
        return Ended(row.id)

    async def _note_space(self, row: _Row) -> None:
        """n8n moves what the account's own space still holds to the platform's project, and
        keeps no maker for it, so each workflow there is noted as this person's first. Best
        effort: when n8n can't list it, the account ends anyway, and those workflows never wait
        to be set up."""
        assert row.n8n_user_id is not None and self._api is not None
        try:
            space = (await personal_spaces(self._api)).get(row.n8n_user_id)
            if space is None:
                return
            left = await self._api.workflows_in(space)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not note what an ending n8n account made: %s", type(error).__name__)
            return
        await self.note_made(row.id, row.n8n_user_id, [w.workflow.id for w in left])
        if self.keys is None:
            return
        try:
            kept = await self.keys.quarantine(space, row.n8n_user_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not note the keys an ending n8n account left: %s", error)
            return
        if kept:
            log.info("kept %d key(s) an ending n8n account left, unused", len(kept))

    async def _delete(self, n8n_user_id: str) -> None:
        assert self._api is not None
        project = await platform_project(self._db)
        if project is None:
            raise N8nError("no bootstrap has recorded the platform's n8n project yet")
        await self._api.delete_user(n8n_user_id, project)

    async def _account(self, row: _Row) -> AccountState:
        """The account as n8n has it now. An invite still on record is asked about, and its
        link forgotten once used. An account n8n no longer has is forgotten too, so a new one is
        made while access stays."""
        if row.n8n_user_id is None:
            return "none"
        if row.sealed_invite is None or self._api is None:
            return "ready" if row.sealed_invite is None else "invited"
        try:
            user = await self._api.user(row.n8n_user_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read the n8n account of %s: %s", row.id, error)
            return "invited"
        if user is not None and user.pending:
            return "invited"
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.people SET n8n_invite = NULL, n8n_invited_at = NULL,"
                " n8n_user_id = CASE WHEN %s THEN NULL ELSE n8n_user_id END"
                " WHERE id = %s AND n8n_user_id = %s",
                (user is None, row.id, row.n8n_user_id),
            )
        return "none" if user is None else "ready"

    async def _person(self, person: UserId) -> _Row | None:
        async with self._db.connection("orchestration") as conn:
            row = await (await conn.execute(_ROW + " WHERE id = %s", (person,))).fetchone()
        return None if row is None else _row(row)
