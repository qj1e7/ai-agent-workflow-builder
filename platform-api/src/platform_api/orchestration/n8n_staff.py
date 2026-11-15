"""Staff n8n accounts (ENGINE-PLAN 2.9, D17, M5). The People list decides who has n8n access; the
platform makes and ends each person's n8n account to match, and keeps n8n's user id for it, which
every later match uses. An account is made only while N8N_STAFF_ACCESS is on and the last
bootstrap proved the node allow list, so no staff account exists while the list is unproven.

The account follows the flag on its own: each settle reads the list and n8n and does only what
differs, so a settle cut off anywhere is finished by the next. An account is ended only once its
person holds no workflow, and whatever its own space still holds moves to the platform's
project, so nothing is deleted with it. The password-set link is sealed at rest, shown only to
its person, and dropped once used. It is never logged."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx

from platform_api.db import Database
from platform_api.orchestration.model_settings import KeyBox
from platform_api.orchestration.n8n import N8nApi, N8nError, personal_spaces, platform_project
from platform_api.shared import UserId

log = logging.getLogger(__name__)

SETTLE_EVERY = timedelta(seconds=15)

NO_ACCESS = "Only people with n8n access can open n8n. An admin can add it in Settings."
OFF = "Opening n8n is coming once the block list is on."
NOT_READY = (
    "n8n can't be opened from here until its block list is checked again. Your own n8n space "
    "stays, without any of the team's workflows."
)
INVITE_LIFE = timedelta(days=7)
"""n8n's password link never runs out, so an unused one this old is replaced by a new account
and link, shown only to its person."""
NOT_MADE = "Your n8n account isn't made yet. Try again in a minute."
SET_PASSWORD = "Set your n8n password first. The link is on your Settings page."


@dataclass(frozen=True)
class StaffGate:
    switched_on: bool
    """N8N_STAFF_ACCESS."""
    ready: bool
    """The last bootstrap proved that n8n loads exactly the class file's node types."""

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


def _ready_or_not(row: _Row, account: AccountState) -> NotYet | CanOpen:
    match account:
        case "none":
            return NotYet(NOT_MADE)
        case "invited":
            return NotYet(SET_PASSWORD)
        case "ready":
            assert row.n8n_user_id is not None
            return CanOpen(row.id, row.n8n_user_id)


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
    ) -> None:
        self._db = db
        self._api = api
        self._box = box
        self._switched_on = switched_on
        self.editor_url = editor_url
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
        return person if row is None else str(row["display"])

    async def access(self, person: UserId) -> StaffAccess:
        row = await self._person(person)
        if row is None or not row.may_hold:
            return NoN8nAccess()
        if (closed := (await self.gate()).closed) is not None:
            return StaffClosed(closed)
        return _ready_or_not(row, await self._account(row))

    async def mine(self, person: UserId) -> MyN8n:
        row = await self._person(person)
        if row is None or not row.may_hold:
            return MyN8n(False, "none", None, False, NO_ACCESS, None)
        account = await self._account(row)
        closed = (await self.gate()).closed
        access = StaffClosed(closed) if closed is not None else _ready_or_not(row, account)
        link = None
        if account == "invited" and row.sealed_invite is not None and self._box is not None:
            link = self._box.open(row.sealed_invite)
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
        """n8n moves what the account's own space still holds to the platform's project, and
        keeps no maker for it, so each workflow there is noted as this person's first."""
        assert row.n8n_user_id is not None and self._api is not None
        space = (await personal_spaces(self._api)).get(row.n8n_user_id)
        if space is not None:
            left = await self._api.workflows_in(space)
            await self.note_made(row.id, row.n8n_user_id, [w.workflow.id for w in left])
        await self._delete(row.n8n_user_id)
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "UPDATE orchestration.people SET n8n_user_id = NULL, n8n_invite = NULL,"
                " n8n_invited_at = NULL WHERE id = %s AND n8n_user_id = %s",
                (row.id, row.n8n_user_id),
            )
        log.info("ended the n8n account of %s", row.id)
        return Ended(row.id)

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
