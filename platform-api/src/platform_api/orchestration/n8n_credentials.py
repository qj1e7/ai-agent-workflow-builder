"""The platform's own keys in n8n, and the credential sweep (ADR 0045, ENGINE-PLAN E16, E17).

n8n's own blocks for an outside system run with a key from n8n's credential store. Only the
platform makes one, in its own n8n project, from what Key Vault holds, and only a key the system
itself shows can do no more than read or post. Before making it, the platform asks the system
what the key may do, against a list of what reading or posting needs, so anything unknown is a
refusal. After making it, n8n's own connection test must pass. Each key has a fixed id, so a key
made again keeps every workflow that names it working. A key never leaves the platform's project:
a workflow that names one opens in a member's space without it (ADR 0045, as amended).

A key is the platform's while n8n holds it exactly as the platform made it: with the id, the type
and the made and changed times n8n gave the platform's own create, in the platform's project. The
record is never moved on from what n8n says later. A key that differs in any of these was
changed, moved, or deleted and made again by someone else, and is deleted and made anew.

The sweep lists every key in n8n as its owner, every minute and whenever a workflow opens in n8n
or comes back from one, and deletes each one the platform did not make, a member's own above
all: n8n's allow list is by node type, so with the Slack type on it, a member could run a draft
by hand with another operation and a key of their own, which no grade sees. The one kind it
keeps is a member's key that n8n moved into the platform's project as the member's account ended,
which the platform noted then and never treats as its own (quarantined).

Teams, Outlook and Gmail have no key. n8n's Teams block posts to a channel only with a person's
own sign-in, which the platform cannot hold (n8n 2.42.6: "app-only Graph supports only migration
import"). n8n's Gmail block asks Google for the right to change mail, so a key that can only send
does not work with it. n8n rewrites an Outlook app key each time it gets a token from Microsoft,
so the sweep could not tell such a key changed in n8n from one n8n refreshed.
"""

import base64
import hashlib
import json
import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

import httpx

from platform_api.db import Database
from platform_api.orchestration.n8n import N8nCredential, N8nError, platform_project
from platform_api.orchestration.platform_keys import KEYS, KeySpec
from platform_api.settings import KeySystem, N8nKey

log = logging.getLogger(__name__)

PLANTED_KIND = "slackApi"
PLANTED_NAME = "Platform self-test: a key the platform did not make"
TEST_EVERY = timedelta(days=1)
GONE_WITHIN = timedelta(minutes=2)
"""The sweep runs every minute, so a planted key is gone within one, and a second covers a slow
look."""
ASK_SECONDS = 15.0
ASK_AGAIN = timedelta(hours=1)
"""A refused key is asked about again this often, since its account's rights can change while
Key Vault holds the same secret."""


@dataclass(frozen=True)
class Scoped:
    """The system shows the key can do no more than its class: read, or post."""


@dataclass(frozen=True)
class KeyRefused:
    words: str


type Probed = Scoped | KeyRefused


JIRA_READS = frozenset(
    {
        "BROWSE_PROJECTS",
        "VIEW_READONLY_WORKFLOW",
        "VIEW_DEV_TOOLS",
        "VIEW_VOTERS_AND_WATCHERS",
        "USER_PICKER",
    }
)
"""The Jira permissions a key that only reads may hold: browsing projects and issues, and seeing
their workflows, development links, voters, watchers and users. Every other permission Jira
lists, one it adds later included, must be one the account does not have."""
GITHUB_READS = frozenset(
    {
        "",
        "read:org",
        "read:user",
        "user:email",
        "read:project",
        "read:packages",
        "read:discussion",
        "read:audit_log",
        "read:gpg_key",
        "read:public_key",
        "read:ssh_signing_key",
        "read:enterprise",
    }
)
"""A classic GitHub token's scopes that only read. No scope at all reads public repositories.
Any other scope, one GitHub adds later included, is a refusal."""
SLACK_POSTS = frozenset(
    {
        "chat:write",
        "chat:write.public",
        "channels:read",
        "groups:read",
        "im:read",
        "mpim:read",
        "users:read",
        "team:read",
    }
)
"""A Slack bot's scopes that post, and read the lists n8n's editor offers to post to. chat:write
also lets the bot edit or delete its own messages, which ADR 0045 accepts and records. Any other
scope is a refusal."""


def _scopes(response: httpx.Response) -> set[str] | None:
    """The scopes a GitHub or Slack token has, as each says them in X-OAuth-Scopes. None when the
    answer does not say."""
    raw = response.headers.get("x-oauth-scopes")
    if raw is None:
        return None
    return {scope.strip() for scope in raw.split(",")}


async def _ask_jira(http: httpx.AsyncClient, key: N8nKey) -> Probed:
    """Jira lists every permission it has; the account must hold none but JIRA_READS."""
    if key.kind == "jiraSoftwareCloudApi":
        auth = base64.b64encode(f"{key.data['email']}:{key.data['apiToken']}".encode()).decode()
        header = f"Basic {auth}"
    else:
        header = f"Bearer {key.data['personalAccessToken']}"
    headers = {"Authorization": header, "Accept": "application/json"}
    listed = await http.get(f"{key.asks}/rest/api/2/permissions", headers=headers)
    names = _jira_permissions(listed)
    if names is None:
        return KeyRefused(f"Jira did not list its permissions: it answered {listed.status_code}.")
    held = await http.get(
        f"{key.asks}/rest/api/2/mypermissions",
        params={"permissions": ",".join(sorted(names))},
        headers=headers,
    )
    answers = _jira_permissions(held)
    if answers is None:
        return KeyRefused(f"Jira did not say what the key may do: it answered {held.status_code}.")
    for name in sorted(set(names) - JIRA_READS):
        said = answers.get(name)
        if not isinstance(said, dict):
            return KeyRefused(f"Jira did not say whether the key may {name}.")
        if cast(Mapping[str, Any], said).get("havePermission") is not False:
            return KeyRefused(
                f"The Jira key can do more than read ({name}). Use an account that can only browse."
            )
    return Scoped()


def _jira_permissions(response: httpx.Response) -> dict[str, Any] | None:
    """Jira's permissions by name, as both its lists answer them. None for an answer that holds
    none, which is never a pass."""
    if response.status_code != 200:
        return None
    said = cast(Mapping[str, Any], response.json()).get("permissions")
    return cast(dict[str, Any], said) if isinstance(said, dict) and said else None


async def _ask_github(http: httpx.AsyncClient, key: N8nKey) -> Probed:
    response = await http.get(
        f"{key.asks}/user", headers={"Authorization": f"token {key.data['accessToken']}"}
    )
    if response.status_code != 200:
        return KeyRefused(f"GitHub did not take the key: it answered {response.status_code}.")
    scopes = _scopes(response)
    if scopes is None:
        return KeyRefused(
            "GitHub does not say what this key may do, as for a fine-grained token or an app. "
            "Use a classic token with read scopes only, or none."
        )
    if more := sorted(scopes - GITHUB_READS):
        return KeyRefused(f"The GitHub key can do more than read ({', '.join(more)}).")
    return Scoped()


async def _ask_slack(http: httpx.AsyncClient, key: N8nKey) -> Probed:
    response = await http.post(
        f"{key.asks}/auth.test", headers={"Authorization": f"Bearer {key.data['accessToken']}"}
    )
    answer: Mapping[str, Any] = (
        cast(Mapping[str, Any], response.json()) if response.status_code == 200 else {}
    )
    if answer.get("ok") is not True:
        return KeyRefused(
            f"Slack did not take the key: {answer.get('error', response.status_code)}."
        )
    scopes = _scopes(response)
    if scopes is None:
        return KeyRefused("Slack did not say what the key may do.")
    if more := sorted(scopes - SLACK_POSTS):
        return KeyRefused(f"The Slack key can do more than post ({', '.join(more)}).")
    return Scoped()


PROBES: Mapping[KeySystem, Callable[[httpx.AsyncClient, N8nKey], Awaitable[Probed]]] = {
    "jira": _ask_jira,
    "github": _ask_github,
    "slack": _ask_slack,
}


async def probe(system: KeySystem, key: N8nKey, http: httpx.AsyncClient) -> Probed:
    """What the system says the key may do. Anything but a clear "only read" or "only post" is a
    refusal, a system that does not answer included."""
    try:
        return await PROBES[system](http, key)
    except (httpx.HTTPError, ValueError, KeyError) as error:
        return KeyRefused(
            f"The platform could not ask {KEYS[system].said} what the key may do: {error}."
        )


def fingerprint(kind: str, data: Mapping[str, str], salt: str) -> str:
    """Says whether Key Vault holds new data for a key, without keeping the secret."""
    body = json.dumps({"kind": kind, "data": dict(data)}, sort_keys=True)
    return f"{salt}:{hashlib.sha256((salt + body).encode()).hexdigest()}"


def _same(kind: str, data: Mapping[str, str], kept: str | None) -> bool:
    if kept is None or ":" not in kept:
        return False
    salt = kept.partition(":")[0]
    return secrets.compare_digest(fingerprint(kind, data, salt), kept)


@dataclass(frozen=True)
class KeyRemoved:
    """A key the sweep deleted."""

    id: str
    project: str | None
    """Where it sat, so the platform can say whose space a key was added in."""
    changed: bool
    """It was one of the platform's own keys, changed, moved, or made again by someone else."""


@dataclass(frozen=True)
class KeyState:
    system: KeySystem
    made: bool
    refused: str | None


class KeyApi(Protocol):
    async def credentials(self) -> list[N8nCredential]: ...

    async def create_credential(
        self, credential_id: str, name: str, kind: str, data: Mapping[str, str], project_id: str
    ) -> N8nCredential: ...

    async def test_credential(self, credential_id: str) -> tuple[bool, str]: ...

    async def delete_credential(self, credential_id: str) -> None: ...


_MADE = (
    "SELECT id, system, kind, fingerprint, n8n_created_at, n8n_updated_at, refused, checked_at"
    " FROM orchestration.n8n_keys"
)


class PlatformKeys:
    """The platform's keys in n8n, and the sweep of every other key."""

    def __init__(
        self,
        db: Database,
        api: KeyApi | None,
        keys: Mapping[KeySystem, N8nKey],
        http: httpx.AsyncClient | None = None,
        home: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        self._db = db
        self._api = api
        self._keys = dict(keys)
        self._http = http or httpx.AsyncClient(timeout=ASK_SECONDS)
        self._home = home or (lambda: platform_project(db))

    async def close(self) -> None:
        await self._http.aclose()

    async def made(self) -> dict[str, str]:
        """Each key the platform made and n8n holds as it was made, by id, with its n8n credential
        type. Only these pass the checker."""
        async with self._db.connection("orchestration") as conn:
            rows = await (
                await conn.execute(_MADE + " WHERE refused IS NULL AND n8n_created_at IS NOT NULL")
            ).fetchall()
        return {row["id"]: row["kind"] for row in rows}

    async def states(self) -> list[KeyState]:
        async with self._db.connection("orchestration") as conn:
            rows = await (await conn.execute(_MADE + " ORDER BY system")).fetchall()
        return [
            KeyState(
                row["system"],
                row["refused"] is None and row["n8n_created_at"] is not None,
                row["refused"],
            )
            for row in rows
        ]

    async def sweep(self) -> list[KeyRemoved]:
        """One look at every key in n8n: deletes each the platform did not make, or no longer
        holds as it made it, then makes again each of its own that is gone."""
        if self._api is None:
            return []
        home = await self._home()
        if home is None:
            log.warning("no bootstrap has recorded the platform's n8n project, so no key is swept")
            return []
        listed = await self._api.credentials()
        removed = await self._remove_foreign(listed, home)
        gone = {r.id for r in removed}
        await self._ensure(home, [c for c in listed if c.id not in gone])
        return removed

    async def _remove_foreign(self, listed: Sequence[N8nCredential], home: str) -> list[KeyRemoved]:
        assert self._api is not None
        async with self._db.connection("orchestration") as conn:
            ours = {r["id"]: r for r in await (await conn.execute(_MADE)).fetchall()}
            quarantined = {
                row["key_id"]
                for row in await (
                    await conn.execute("SELECT key_id FROM orchestration.n8n_quarantined_keys")
                ).fetchall()
            }
        removed: list[KeyRemoved] = []
        for credential in listed:
            record = ours.get(credential.id)
            if record is not None and _vouched(record, credential, home):
                continue
            if credential.id in quarantined and credential.project == home:
                continue
            await self._api.delete_credential(credential.id)
            changed = record is not None and record["n8n_created_at"] is not None
            removed.append(KeyRemoved(credential.id, credential.project, changed))
            log.warning(
                "deleted %s key %s from n8n project %s",
                "a changed platform" if changed else "a",
                credential.id,
                credential.project,
            )
        async with self._db.transaction("orchestration") as uow:
            for gone in removed:
                if gone.changed:
                    await uow.conn.execute(
                        "UPDATE orchestration.n8n_keys SET n8n_created_at = NULL,"
                        " n8n_updated_at = NULL, fingerprint = NULL WHERE id = %s",
                        (gone.id,),
                    )
                await uow.conn.execute(
                    "UPDATE orchestration.n8n_key_tests SET gone_at = coalesce(gone_at, %s)"
                    " WHERE key_id = %s",
                    (uow.now, gone.id),
                )
        return removed

    async def _ensure(self, home: str, listed: Sequence[N8nCredential]) -> None:
        """Makes each configured key n8n does not hold, and makes anew one Key Vault holds new
        data for. A key no longer configured is deleted."""
        assert self._api is not None
        held = {c.id for c in listed}
        async with self._db.connection("orchestration") as conn:
            ours = {r["system"]: r for r in await (await conn.execute(_MADE)).fetchall()}
        for system, spec in KEYS.items():
            key = self._keys.get(system)
            record = ours.get(system)
            if key is None:
                if spec.id in held and record is not None:
                    await self._api.delete_credential(spec.id)
                if record is not None:
                    await self._forget(system)
                continue
            present = (
                spec.id in held and record is not None and record["n8n_created_at"] is not None
            )
            if record is not None and _same(key.kind, key.data, record["fingerprint"]):
                if present:
                    continue
                asked_lately = self._db.clock() - record["checked_at"] < ASK_AGAIN
                if record["refused"] is not None and asked_lately:
                    continue
            try:
                if spec.id in held:
                    await self._api.delete_credential(spec.id)
                await self._make(spec, key, home)
            except (N8nError, httpx.HTTPError) as error:
                log.warning("could not make the platform's %s key in n8n: %s", spec.said, error)

    async def _make(self, spec: KeySpec, key: N8nKey, home: str) -> None:
        """Asks the system first, then makes the key, then has n8n test it. A key that fails
        either check is not left in n8n. What n8n answers this create is the record, for good."""
        assert self._api is not None
        print_ = fingerprint(key.kind, key.data, secrets.token_hex(8))
        asked = await probe(spec.system, key, self._http)
        if isinstance(asked, KeyRefused):
            await self._refuse(spec, key, print_, asked.words)
            return
        made = await self._api.create_credential(spec.id, spec.name, key.kind, key.data, home)
        works, said = await self._api.test_credential(spec.id)
        if not works:
            await self._api.delete_credential(spec.id)
            words = f"n8n could not connect with the {spec.said} key: {said}"
            await self._refuse(spec, key, print_, words)
            return
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.n8n_keys (id, system, kind, fingerprint,"
                " n8n_created_at, n8n_updated_at, refused, checked_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, NULL, %s) ON CONFLICT (id) DO UPDATE SET"
                " system = EXCLUDED.system, kind = EXCLUDED.kind,"
                " fingerprint = EXCLUDED.fingerprint, n8n_created_at = EXCLUDED.n8n_created_at,"
                " n8n_updated_at = EXCLUDED.n8n_updated_at, refused = NULL,"
                " checked_at = EXCLUDED.checked_at",
                (spec.id, spec.system, key.kind, print_, made.created_at, made.updated_at, uow.now),
            )
        log.info("made the platform's %s key in n8n, which can only %s", spec.said, spec.on)

    async def _refuse(self, spec: KeySpec, key: N8nKey, print_: str, words: str) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.n8n_keys (id, system, kind, fingerprint,"
                " n8n_created_at, n8n_updated_at, refused, checked_at)"
                " VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s) ON CONFLICT (id) DO UPDATE SET"
                " kind = EXCLUDED.kind, fingerprint = EXCLUDED.fingerprint,"
                " n8n_created_at = NULL, n8n_updated_at = NULL, refused = EXCLUDED.refused,"
                " checked_at = EXCLUDED.checked_at",
                (spec.id, spec.system, key.kind, print_, words, uow.now),
            )
        log.warning("the platform made no %s key in n8n: %s", spec.said, words)

    async def _forget(self, system: KeySystem) -> None:
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "DELETE FROM orchestration.n8n_keys WHERE system = %s", (system,)
            )

    async def quarantine(self, project: str, n8n_user_id: str) -> list[str]:
        """Notes each key in a member's space, just before their account ends and n8n moves the
        space's keys to the platform's project. They stay there unused, never as the platform's,
        and the sweep leaves them only while they sit there."""
        if self._api is None:
            return []
        made = await self.made()
        found = [
            c.id for c in await self._api.credentials() if c.project == project and c.id not in made
        ]
        async with self._db.transaction("orchestration") as uow:
            for key in found:
                await uow.conn.execute(
                    "INSERT INTO orchestration.n8n_quarantined_keys (key_id, n8n_user_id,"
                    " quarantined_at) VALUES (%s, %s, %s) ON CONFLICT (key_id) DO NOTHING",
                    (key, n8n_user_id, uow.now),
                )
        return found

    async def plant(self) -> str | None:
        """The daily self-test: a key the platform does not record as its own, in its own
        project, which the next sweep must delete within a minute. None when one was planted
        within the day."""
        if self._api is None:
            return None
        home = await self._home()
        if home is None:
            return None
        async with self._db.connection("orchestration") as conn:
            last = await (
                await conn.execute("SELECT max(planted_at) AS at FROM orchestration.n8n_key_tests")
            ).fetchone()
        if (
            last is not None
            and last["at"] is not None
            and self._db.clock() - last["at"] < TEST_EVERY
        ):
            return None
        key = f"wab-test-{secrets.token_hex(4)}"
        data = {"accessToken": f"not-a-key-{secrets.token_hex(8)}"}
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(
                "INSERT INTO orchestration.n8n_key_tests (key_id, planted_at) VALUES (%s, %s)",
                (key, uow.now),
            )
        await self._api.create_credential(key, PLANTED_NAME, PLANTED_KIND, data, home)
        log.info("planted key %s for the credential sweep's daily self-test", key)
        return key

    async def tested(self) -> tuple[bool, str]:
        """The /healthz/ready line: whether the last planted key was gone within GONE_WITHIN."""
        async with self._db.connection("orchestration") as conn:
            row = await (
                await conn.execute(
                    "SELECT planted_at, gone_at FROM orchestration.n8n_key_tests"
                    " ORDER BY planted_at DESC LIMIT 1"
                )
            ).fetchone()
        now = self._db.clock()
        return key_test_line(None if row is None else (row["planted_at"], row["gone_at"]), now)


def key_test_line(last: tuple[datetime, datetime | None] | None, now: datetime) -> tuple[bool, str]:
    if last is None:
        return False, "no key has been planted yet. The sweep plants one a day"
    planted, gone = last
    if gone is not None and gone - planted <= GONE_WITHIN:
        if now - planted > TEST_EVERY + timedelta(hours=2):
            return False, f"no key has been planted since {planted.isoformat()}"
        return True, f"the key planted at {planted.isoformat()} was removed within a minute"
    if gone is not None:
        return (
            False,
            f"the key planted at {planted.isoformat()} was removed late, at {gone.isoformat()}",
        )
    if now - planted <= GONE_WITHIN:
        return True, f"a key was planted at {planted.isoformat()}, and the sweep is due"
    return False, (
        f"the key planted at {planted.isoformat()} is still in n8n, so a key a member adds may "
        "stay too"
    )


def _vouched(record: Mapping[str, Any], credential: N8nCredential, home: str) -> bool:
    """n8n holds the key as the platform made it: made then, changed by nothing since, and in
    the platform's project, which it never leaves."""
    return (
        record["refused"] is None
        and record["n8n_created_at"] == credential.created_at
        and record["n8n_updated_at"] == credential.updated_at
        and record["kind"] == credential.kind
        and credential.project == home
    )


def credentials_named(document: Mapping[str, Any] | None) -> set[str]:
    """Every key id a workflow's blocks name."""
    found: set[str] = set()
    for node in cast(list[object], (document or {}).get("nodes") or []):
        if not isinstance(node, dict):
            continue
        named = cast(Mapping[str, Any], node).get("credentials")
        if not isinstance(named, dict):
            continue
        for ref in cast(Mapping[str, Any], named).values():
            if isinstance(ref, dict) and isinstance(
                key := cast(Mapping[str, Any], ref).get("id"), str
            ):
                found.add(key)
    return found
