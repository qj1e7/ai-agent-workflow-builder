"""Connection health: whether Jira, GitHub, Teams and the AI model work, and the last result.

A check only reads. It never writes to Jira, GitHub or Teams, and it changes nothing the safety
checker allows. A result holds plain words chosen here, never a system's own error text, and
never a token, so it is safe to store and to show.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol, cast

from platform_api.db import Database, UnitOfWork
from platform_api.orchestration.agents import (
    AgentRejected,
    AgentUnavailable,
    GitHubCheckResult,
    GitHubProblem,
    GitHubWorking,
)
from platform_api.orchestration.jira_rest import JiraReach
from platform_api.orchestration.model_settings import SettingsOff, SettingsState
from platform_api.orchestration.store import ANNOUNCE, SHOW_OUTCOME

log = logging.getLogger(__name__)

type ConnectionId = Literal["jira", "github", "teams", "model"]
type ConnectionState = Literal[
    "working", "needs_attention", "not_answering", "not_set_up", "not_checked"
]

CONNECTION_IDS: Final[tuple[ConnectionId, ...]] = ("jira", "github", "teams", "model")
RECHECK_AFTER: Final = timedelta(hours=1)
"""A scheduled tick checks a connection at most this often, because unauthenticated GitHub allows
60 calls an hour."""
EXPIRY_WARNING: Final = timedelta(days=14)
"""A key that runs out within this long is raised on Home."""
CHECK_DEADLINE_SECONDS: Final = 15.0

TEAMS_NOT_CHECKED: Final = (
    "Not checked yet. Teams is tried when the first approval request is sent."
)
NOT_ANSWERING: Final = "{name} is not answering."
TOKEN_REFUSED: Final = "{name} does not accept the key."
CHECK_FAILED: Final = "The check of {name} did not finish."


@dataclass(frozen=True)
class Reading:
    """What one probe saw."""

    state: ConnectionState
    problem: str | None = None
    expires_at: datetime | None = None
    key_ends_in: str | None = None


class Probe(Protocol):
    async def __call__(self) -> Reading: ...


@dataclass(frozen=True)
class Entry:
    id: ConnectionId
    name: str
    practice: bool
    probe: Probe
    live: bool = False
    """A live connection is read fresh on every view and never stored, because another screen
    owns the fact and a stored copy could disagree with it."""


@dataclass(frozen=True)
class Shown:
    """The result a person is shown, and the one different result waiting for a second to agree."""

    state: ConnectionState
    problem: str | None
    checked_at: datetime
    last_ok_at: datetime | None
    expires_at: datetime | None
    key_ends_in: str | None
    unconfirmed_state: ConnectionState | None = None


def settle(shown: Shown | None, reading: Reading, now: datetime, *, at_once: bool) -> Shown:
    """The new result after one reading. Check now shows what it found. A scheduled check
    changes the state only when two readings in a row agree, so one failed call raises no alarm."""
    last_ok = reading_ok_at(shown, reading, now)
    first_result = shown is not None and shown.state == "not_checked"
    if shown is None or at_once or first_result or reading.state == shown.state:
        return Shown(
            reading.state, reading.problem, now, last_ok, reading.expires_at, reading.key_ends_in
        )
    if shown.unconfirmed_state == reading.state:
        return Shown(
            reading.state, reading.problem, now, last_ok, reading.expires_at, reading.key_ends_in
        )
    return replace(shown, unconfirmed_state=reading.state)


def reading_ok_at(shown: Shown | None, reading: Reading, now: datetime) -> datetime | None:
    if reading.state == "working":
        return now
    return None if shown is None else shown.last_ok_at


def due(shown: Shown | None, now: datetime) -> bool:
    """A tick checks a connection that was never checked, one waiting for a second reading or for
    its first result, and any other after an hour."""
    if shown is None or shown.unconfirmed_state is not None or shown.state == "not_checked":
        return True
    return now - shown.checked_at >= RECHECK_AFTER


@dataclass(frozen=True)
class ConnectionCheck:
    id: ConnectionId
    name: str
    practice: bool
    state: ConnectionState
    checked_at: datetime | None
    """None while nothing has been tried, so no time implies a test happened."""
    last_ok_at: datetime | None
    problem: str | None
    key_ends_in: str | None
    expires_at: datetime | None
    fix: str | None

    def runs_out_soon(self, now: datetime) -> bool:
        return (
            self.state == "working"
            and self.expires_at is not None
            and self.expires_at - now <= EXPIRY_WARNING
        )


def fix_for(entry: Entry, state: ConnectionState, *, expiring: bool) -> str | None:
    match entry.id, state:
        case _, "working":
            return (
                f"Ask whoever set up {entry.name} for a new key before this one runs out."
                if expiring
                else None
            )
        case "model", _:
            return "Add an AI model under Settings, AI model."
        case "teams", "not_answering":
            return "Ask whoever set up the Teams address to check that it still works."
        case _, "needs_attention":
            return f"Ask whoever set up {entry.name} for a new key."
        case _, "not_answering":
            return "Nothing to change yet. Check again in a few minutes."
        case _, "not_set_up":
            return f"Ask whoever set up the platform to connect {entry.name}."
        case _, "not_checked":
            return None


class ConnectionStore:
    async def load_all(self, uow: UnitOfWork) -> dict[ConnectionId, Shown]:
        rows = await (
            await uow.conn.execute("SELECT * FROM orchestration.connection_checks")
        ).fetchall()
        return {cast(ConnectionId, row["connection"]): _shown(row) for row in rows}

    async def lock(self, uow: UnitOfWork, id: ConnectionId) -> Shown | None:
        row = await (
            await uow.conn.execute(
                "SELECT * FROM orchestration.connection_checks WHERE connection = %s FOR UPDATE",
                (id,),
            )
        ).fetchone()
        return None if row is None else _shown(row)

    async def save(self, uow: UnitOfWork, id: ConnectionId, shown: Shown) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.connection_checks (connection, state, problem, "
            "checked_at, last_ok_at, expires_at, key_ends_in, unconfirmed_state) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (connection) DO UPDATE SET state = EXCLUDED.state, "
            "problem = EXCLUDED.problem, checked_at = EXCLUDED.checked_at, "
            "last_ok_at = EXCLUDED.last_ok_at, expires_at = EXCLUDED.expires_at, "
            "key_ends_in = EXCLUDED.key_ends_in, unconfirmed_state = EXCLUDED.unconfirmed_state",
            (
                id,
                shown.state,
                shown.problem,
                shown.checked_at,
                shown.last_ok_at,
                shown.expires_at,
                shown.key_ends_in,
                shown.unconfirmed_state,
            ),
        )


def _shown(row: dict[str, Any]) -> Shown:
    return Shown(
        state=cast(ConnectionState, row["state"]),
        problem=row["problem"],
        checked_at=row["checked_at"],
        last_ok_at=row["last_ok_at"],
        expires_at=row["expires_at"],
        key_ends_in=row["key_ends_in"],
        unconfirmed_state=cast(ConnectionState | None, row["unconfirmed_state"]),
    )


class Connections:
    def __init__(
        self,
        db: Database,
        entries: Sequence[Entry],
        store: ConnectionStore | None = None,
    ) -> None:
        self._db = db
        self._entries: dict[ConnectionId, Entry] = {entry.id: entry for entry in entries}
        self._store = store or ConnectionStore()

    async def view(self) -> list[ConnectionCheck]:
        """Every connection with its last result. One never checked is checked now, once."""
        async with self._db.transaction("orchestration") as uow:
            stored = await self._store.load_all(uow)
        for id, entry in self._entries.items():
            if entry.live:
                stored[id] = await self._live(entry)
            elif id not in stored:
                stored[id] = await self._check(entry, at_once=True)
        now = self._db.clock()
        return [self._present(self._entries[id], stored[id], now) for id in self._entries]

    async def check_now(self, id: str) -> ConnectionCheck | None:
        """Checks one connection and shows what was found. None for a name nobody has."""
        entry = next((e for e in self._entries.values() if e.id == id), None)
        if entry is None:
            return None
        shown = await (self._live(entry) if entry.live else self._check(entry, at_once=True))
        return self._present(entry, shown, self._db.clock())

    async def check_due(self) -> None:
        """The scheduled tick's part: checks what is due, and lets nothing go wrong on the way."""
        async with self._db.transaction("orchestration") as uow:
            stored = await self._store.load_all(uow)
        now = self._db.clock()
        waiting = [e for e in self._entries.values() if not e.live and due(stored.get(e.id), now)]
        await asyncio.gather(*(self._check(e, at_once=False) for e in waiting))

    async def needing_attention(self) -> list[ConnectionCheck]:
        """Connections that do not work, and keys that run out soon. Reads what was stored and
        asks nobody, so a fresh stack shows none until a check found something."""
        async with self._db.transaction("orchestration") as uow:
            stored = await self._store.load_all(uow)
        now = self._db.clock()
        found = [
            self._present(self._entries[id], shown, now)
            for id, shown in stored.items()
            if id in self._entries and not self._entries[id].live
        ]
        trouble = [c for c in found if c.state in ("needs_attention", "not_answering")]
        ending = sorted(
            (c for c in found if c.runs_out_soon(now)),
            key=lambda c: c.expires_at or now,
        )
        order = {id: place for place, id in enumerate(CONNECTION_IDS)}
        return sorted(trouble, key=lambda c: order[c.id]) + ending

    async def _check(self, entry: Entry, *, at_once: bool) -> Shown:
        reading = await self._read(entry)
        async with self._db.transaction("orchestration") as uow:
            shown = settle(await self._store.lock(uow, entry.id), reading, uow.now, at_once=at_once)
            await self._store.save(uow, entry.id, shown)
        return shown

    async def _live(self, entry: Entry) -> Shown:
        reading = await self._read(entry)
        now = self._db.clock()
        return Shown(
            reading.state,
            reading.problem,
            now,
            now if reading.state == "working" else None,
            reading.expires_at,
            reading.key_ends_in,
        )

    async def _read(self, entry: Entry) -> Reading:
        try:
            async with asyncio.timeout(CHECK_DEADLINE_SECONDS):
                return await entry.probe()
        except Exception as error:
            # Only the type is logged, because an error can quote the address or a key.
            log.warning("the check of %s did not finish: %s", entry.id, type(error).__name__)
            return Reading("not_answering", CHECK_FAILED.format(name=entry.name))

    def _present(self, entry: Entry, shown: Shown, now: datetime) -> ConnectionCheck:
        check = ConnectionCheck(
            id=entry.id,
            name=entry.name,
            practice=entry.practice,
            state=shown.state,
            checked_at=None if shown.state == "not_checked" else shown.checked_at,
            last_ok_at=shown.last_ok_at,
            problem=shown.problem,
            key_ends_in=shown.key_ends_in,
            expires_at=shown.expires_at,
            fix=None,
        )
        soon = check.runs_out_soon(now)
        return replace(
            check,
            problem=check.problem or ("The key runs out soon." if soon else None),
            fix=fix_for(entry, shown.state, expiring=soon),
        )


class JiraChecker(Protocol):
    async def check(self) -> JiraReach: ...


class GitHubChecker(Protocol):
    async def check_github(self) -> GitHubCheckResult | AgentUnavailable | AgentRejected: ...


class ModelView(Protocol):
    async def view(self) -> SettingsState: ...


def jira_probe(jira: JiraChecker, name: str, key_ends_in: str | None) -> Probe:
    async def probe() -> Reading:
        match await jira.check():
            case "working":
                return Reading("working", key_ends_in=key_ends_in)
            case "token_refused":
                return Reading(
                    "needs_attention", TOKEN_REFUSED.format(name=name), key_ends_in=key_ends_in
                )
            case "not_answering":
                return Reading("not_answering", NOT_ANSWERING.format(name=name))

    return probe


GITHUB_PROBLEMS: Final[dict[str, tuple[ConnectionState, str]]] = {
    "token_refused": ("needs_attention", "GitHub does not accept the key."),
    "unreachable": ("not_answering", "GitHub is not answering."),
    "unexpected_answer": ("not_answering", "GitHub answered in a way the platform did not expect."),
}


def github_probe(runtime: GitHubChecker) -> Probe:
    async def probe() -> Reading:
        match await runtime.check_github():
            case GitHubWorking(expires_at=expires_at):
                return Reading("working", expires_at=expires_at)
            case GitHubProblem(reason=reason):
                state, problem = GITHUB_PROBLEMS[reason]
                return Reading(state, problem)
            case _:
                return Reading(
                    "not_answering", "The agent runtime did not answer, so GitHub was not checked."
                )

    return probe


def model_probe(models: ModelView) -> Probe:
    async def probe() -> Reading:
        state = await models.view()
        if not state.available:
            return Reading("not_set_up", SettingsOff().message)
        if state.active is None:
            return Reading("not_set_up", "No AI model is turned on.")
        return Reading("working", key_ends_in=state.active.key_hint)

    return probe


def teams_probe(db: Database, *, practice: bool, adapter: str = "teams_workflows") -> Probe:
    """The practice copy always takes a message. A real channel is judged by how the last
    message the outbox tried to send through it went, because a check must not post to a channel.
    Messages the practice copy took say nothing about the real channel, so only a message posted
    through `adapter` counts, and a failed announcement, which was never posted, counts as one."""

    async def probe() -> Reading:
        if practice:
            return Reading("working")
        async with db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT o.status FROM orchestration.outbox o "
                    "LEFT JOIN orchestration.approval_messages m "
                    "ON m.approval_id = o.payload->>'approval_id' "
                    "WHERE o.kind IN (%s, %s) "
                    "AND (o.status IN ('sent', 'given_up') OR "
                    "(o.status = 'pending' AND o.last_error IS NOT NULL)) "
                    "AND (m.adapter = %s OR "
                    "(m.adapter IS NULL AND o.kind = %s AND o.status <> 'sent')) "
                    "ORDER BY o.id DESC LIMIT 1",
                    (ANNOUNCE, SHOW_OUTCOME, adapter, ANNOUNCE),
                )
            ).fetchone()
        if row is None:
            return Reading("not_checked", TEAMS_NOT_CHECKED)
        if row["status"] != "sent":
            return Reading("not_answering", "Teams did not take the last message.")
        return Reading("working")

    return probe
