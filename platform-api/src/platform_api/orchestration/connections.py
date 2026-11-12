"""Connection health: whether Jira, GitHub, Teams and the AI model work, and the last result.

A check only reads. It never writes to Jira, GitHub or Teams, and it changes nothing the safety
checker allows. A result holds plain words chosen here, never a system's own error text, and
never a token, so it is safe to store and to show.

Each result belongs to one identity: the practice copy, or the adapter with a one-way fingerprint
of the address and the key it used. Only results of the identity in use now are read, so a new
address or a new key starts with no history, and no screen shows what another copy found.
"""

import asyncio
import logging
from collections.abc import Awaitable, Mapping, Sequence
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
from platform_api.orchestration.dispatch import (
    PRACTICE,
    ApprovalChannel,
    ApprovalNotice,
    ApprovalOutcome,
    Identity,
    MessageRef,
)
from platform_api.orchestration.jira_rest import JiraReach
from platform_api.orchestration.model_settings import SettingsOff, SettingsState

log = logging.getLogger(__name__)

type ConnectionId = Literal["jira", "github", "teams", "model"]
type Found = Literal["working", "needs_attention", "not_answering", "not_set_up"]
"""What a reading can find, and so the only states a kept result has."""
type ConnectionState = Literal[
    "working", "needs_attention", "not_answering", "not_set_up", "not_checked"
]

CONNECTION_IDS: Final[tuple[ConnectionId, ...]] = ("jira", "github", "teams", "model")
RECHECK_AFTER: Final = timedelta(hours=1)
"""A scheduled tick checks a working connection at most this often. One that does not work is
checked on every tick, so its warning ends soon after it is fixed. Neither spends a limit:
GitHub's rate limit call does not count against it, and Jira's check is one read."""
EXPIRY_WARNING: Final = timedelta(days=14)
"""A key that runs out within this long is raised on Home."""
CHECK_DEADLINE_SECONDS: Final = 15.0

TEAMS_NOT_CHECKED: Final = (
    "Not checked yet. Teams is tried when the first approval request is sent."
)
TEAMS_REFUSED: Final = "Teams did not take the last message."
NOT_ANSWERING: Final = "{name} is not answering."
TOKEN_REFUSED: Final = "{name} does not accept the key."
CHECK_FAILED: Final = "The check of {name} did not finish."


@dataclass(frozen=True)
class Reading:
    """What one probe, or one real use, saw."""

    state: Found
    problem: str | None = None
    expires_at: datetime | None = None
    key_ends_in: str | None = None


class Probe(Protocol):
    async def __call__(self) -> Reading: ...


@dataclass(frozen=True)
class Checked:
    """Asked on Check now and by the tick, and the result kept."""

    probe: Probe


@dataclass(frozen=True)
class ReadFresh:
    """Read on every view and never kept, because another screen owns the fact and a kept copy
    could disagree with it."""

    probe: Probe


@dataclass(frozen=True)
class Observed:
    """Known only from real use, because a check may not post to the channel. Check now and the
    tick try nothing, and `waiting` says so until the first result."""

    waiting: str


type Known = Checked | ReadFresh | Observed


@dataclass(frozen=True)
class Entry:
    id: ConnectionId
    name: str
    identity: Identity
    known: Known

    @property
    def practice(self) -> bool:
        return self.identity == PRACTICE


@dataclass(frozen=True)
class Shown:
    """The result a person is shown, and the one different result waiting for a second to agree."""

    state: Found
    problem: str | None
    checked_at: datetime
    """When the reading that set the state was made."""
    last_ok_at: datetime | None
    expires_at: datetime | None
    key_ends_in: str | None
    unconfirmed_state: Found | None = None


def settle(shown: Shown | None, reading: Reading, now: datetime, *, at_once: bool) -> Shown:
    """The new result after one reading. Check now shows what it found. A scheduled check, or a
    real use, changes the state only when two readings in a row agree, so one failed call raises
    no alarm."""
    last_ok = reading_ok_at(shown, reading, now)
    if shown is None or at_once or reading.state in (shown.state, shown.unconfirmed_state):
        return Shown(
            reading.state, reading.problem, now, last_ok, reading.expires_at, reading.key_ends_in
        )
    return replace(shown, unconfirmed_state=reading.state)


def reading_ok_at(shown: Shown | None, reading: Reading, now: datetime) -> datetime | None:
    if reading.state == "working":
        return now
    return None if shown is None else shown.last_ok_at


def due(shown: Shown | None, now: datetime) -> bool:
    """A tick checks a connection never checked with what it uses now, one that does not work or
    waits for a second reading, and a working one after an hour."""
    if shown is None or shown.state != "working" or shown.unconfirmed_state is not None:
        return True
    return now - shown.checked_at >= RECHECK_AFTER


@dataclass(frozen=True)
class ConnectionCheck:
    id: ConnectionId
    name: str
    practice: bool
    state: ConnectionState
    checked_at: datetime | None
    """None while nothing has been tried with what it uses now, and for one read fresh, which is
    not checked, so no time implies a test happened."""
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
    async def load(
        self, uow: UnitOfWork, identities: Mapping[ConnectionId, Identity]
    ) -> dict[ConnectionId, Shown]:
        """The result kept for each connection's identity now. Other identities' results stay in
        the table, and are read again only if that identity comes back."""
        ids = list(identities)
        rows = await (
            await uow.conn.execute(
                "SELECT c.* FROM orchestration.connection_checks c "
                "JOIN unnest(%s::text[], %s::text[]) AS now (connection, identity) "
                "USING (connection, identity)",
                (ids, [identities[id] for id in ids]),
            )
        ).fetchall()
        return {cast(ConnectionId, row["connection"]): _shown(row) for row in rows}

    async def lock(self, uow: UnitOfWork, id: ConnectionId, identity: Identity) -> Shown | None:
        row = await (
            await uow.conn.execute(
                "SELECT * FROM orchestration.connection_checks "
                "WHERE connection = %s AND identity = %s FOR UPDATE",
                (id, identity),
            )
        ).fetchone()
        return None if row is None else _shown(row)

    async def save(
        self, uow: UnitOfWork, id: ConnectionId, identity: Identity, shown: Shown
    ) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.connection_checks (connection, identity, state, problem, "
            "checked_at, last_ok_at, expires_at, key_ends_in, unconfirmed_state) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (connection, identity) DO UPDATE SET state = EXCLUDED.state, "
            "problem = EXCLUDED.problem, checked_at = EXCLUDED.checked_at, "
            "last_ok_at = EXCLUDED.last_ok_at, expires_at = EXCLUDED.expires_at, "
            "key_ends_in = EXCLUDED.key_ends_in, unconfirmed_state = EXCLUDED.unconfirmed_state",
            (
                id,
                identity,
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
        state=cast(Found, row["state"]),
        problem=row["problem"],
        checked_at=row["checked_at"],
        last_ok_at=row["last_ok_at"],
        expires_at=row["expires_at"],
        key_ends_in=row["key_ends_in"],
        unconfirmed_state=cast(Found | None, row["unconfirmed_state"]),
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
        self._identities: dict[ConnectionId, Identity] = {e.id: e.identity for e in entries}

    async def view(self) -> list[ConnectionCheck]:
        """Every connection with its last result. One the platform checks, and never checked with
        what it uses now, is checked now, once."""
        kept = await self._kept()
        shown: dict[ConnectionId, Shown | None] = {}
        for id, entry in self._entries.items():
            match entry.known:
                case ReadFresh(probe):
                    shown[id] = await self._read_fresh(entry, probe)
                case Checked(probe) if id not in kept:
                    shown[id] = await self._check(entry, probe, at_once=True)
                case _:
                    shown[id] = kept.get(id)
        now = self._db.clock()
        return [self._present(entry, shown[id], now) for id, entry in self._entries.items()]

    async def check_now(self, id: str) -> ConnectionCheck | None:
        """Checks one connection and shows what was found. One known only from real use is shown
        as it is, because a check may not post. None for a name nobody has."""
        entry = next((e for e in self._entries.values() if e.id == id), None)
        if entry is None:
            return None
        match entry.known:
            case Checked(probe):
                shown = await self._check(entry, probe, at_once=True)
            case ReadFresh(probe):
                shown = await self._read_fresh(entry, probe)
            case Observed():
                shown = (await self._kept()).get(entry.id)
        return self._present(entry, shown, self._db.clock())

    async def check_due(self) -> None:
        """The scheduled tick's part: checks what is due, and lets nothing go wrong on the way."""
        kept = await self._kept()
        now = self._db.clock()
        waiting = [
            (entry, entry.known.probe)
            for entry in self._entries.values()
            if isinstance(entry.known, Checked) and due(kept.get(entry.id), now)
        ]
        await asyncio.gather(*(self._check(e, probe, at_once=False) for e, probe in waiting))

    async def needing_attention(self) -> list[ConnectionCheck]:
        """Connections that do not work, and keys that run out soon. A checked connection is read
        from what was stored and asks nobody, so a fresh stack shows none until a check found
        something. The AI model is read from its own settings, as every view reads it, and is
        listed while it is not set up, because nothing that needs it can run."""
        kept = await self._kept()
        now = self._db.clock()
        found: list[ConnectionCheck] = []
        for id, entry in self._entries.items():
            shown = (
                await self._read_fresh(entry, entry.known.probe)
                if isinstance(entry.known, ReadFresh)
                else kept.get(id)
            )
            if shown is not None:
                found.append(self._present(entry, shown, now))
        trouble = [
            c for c in found if c.state in ("needs_attention", "not_answering", "not_set_up")
        ]
        ending = sorted(
            (c for c in found if c.runs_out_soon(now)),
            key=lambda c: c.expires_at or now,
        )
        order = {id: place for place, id in enumerate(CONNECTION_IDS)}
        return sorted(trouble, key=lambda c: order[c.id]) + ending

    async def observe(self, id: ConnectionId, identity: Identity, reading: Reading) -> None:
        """What real use found, such as a post to Teams, kept for the identity that made it. As on
        a tick, a state changes only when two results in a row agree."""
        async with self._db.transaction("orchestration") as uow:
            shown = settle(
                await self._store.lock(uow, id, identity), reading, uow.now, at_once=False
            )
            await self._store.save(uow, id, identity, shown)

    async def _kept(self) -> dict[ConnectionId, Shown]:
        async with self._db.transaction("orchestration") as uow:
            return await self._store.load(uow, self._identities)

    async def _check(self, entry: Entry, probe: Probe, *, at_once: bool) -> Shown:
        reading = await self._read(entry, probe)
        async with self._db.transaction("orchestration") as uow:
            shown = settle(
                await self._store.lock(uow, entry.id, entry.identity),
                reading,
                uow.now,
                at_once=at_once,
            )
            await self._store.save(uow, entry.id, entry.identity, shown)
        return shown

    async def _read_fresh(self, entry: Entry, probe: Probe) -> Shown:
        reading = await self._read(entry, probe)
        now = self._db.clock()
        return Shown(
            reading.state,
            reading.problem,
            now,
            now if reading.state == "working" else None,
            reading.expires_at,
            reading.key_ends_in,
        )

    async def _read(self, entry: Entry, probe: Probe) -> Reading:
        try:
            async with asyncio.timeout(CHECK_DEADLINE_SECONDS):
                return await probe()
        except Exception as error:
            # Only the type is logged, because an error can quote the address or a key.
            log.warning("the check of %s did not finish: %s", entry.id, type(error).__name__)
            return Reading("not_answering", CHECK_FAILED.format(name=entry.name))

    def _present(self, entry: Entry, shown: Shown | None, now: datetime) -> ConnectionCheck:
        if shown is None:
            return ConnectionCheck(
                id=entry.id,
                name=entry.name,
                practice=entry.practice,
                state="not_checked",
                checked_at=None,
                last_ok_at=None,
                problem=entry.known.waiting if isinstance(entry.known, Observed) else None,
                key_ends_in=None,
                expires_at=None,
                fix=None,
            )
        fresh = isinstance(entry.known, ReadFresh)
        check = ConnectionCheck(
            id=entry.id,
            name=entry.name,
            practice=entry.practice,
            state=shown.state,
            checked_at=None if fresh else shown.checked_at,
            last_ok_at=None if fresh else shown.last_ok_at,
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


GITHUB_PROBLEMS: Final[dict[str, tuple[Found, str]]] = {
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


async def practice_teams() -> Reading:
    """The practice copy of Teams always takes a message."""
    return Reading("working")


class WatchedChannel:
    """The approval channel, keeping how each post went as the result of the channel that
    posted it. A real Teams channel is judged by its own posts, and a check never posts."""

    def __init__(self, channel: ApprovalChannel, connections: Connections) -> None:
        self._channel = channel
        self._connections = connections

    @property
    def name(self) -> str:
        return self._channel.name

    @property
    def identity(self) -> Identity:
        return self._channel.identity

    async def announce(self, notice: ApprovalNotice) -> MessageRef:
        return await self._watched(self._channel.announce(notice))

    async def update(self, ref: MessageRef, outcome: ApprovalOutcome) -> None:
        await self._watched(self._channel.update(ref, outcome))

    async def _watched[T](self, post: Awaitable[T]) -> T:
        try:
            result = await post
        except Exception:
            await self._keep(Reading("not_answering", TEAMS_REFUSED))
            raise
        await self._keep(Reading("working"))
        return result

    async def _keep(self, reading: Reading) -> None:
        try:
            await self._connections.observe("teams", self._channel.identity, reading)
        except Exception as error:
            # The post's own result stands either way: a post that went out and then failed its
            # outbox row would be posted again.
            log.warning("the result of a Teams post was not kept: %s", type(error).__name__)
