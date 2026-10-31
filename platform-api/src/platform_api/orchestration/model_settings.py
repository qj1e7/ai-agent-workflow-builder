import base64
import hashlib
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from platform_api.db import Database, UnitOfWork
from platform_api.orchestration import confirmations
from platform_api.orchestration.agents import (
    AgentRejected,
    AgentUnavailable,
    ConnectRequest,
    ConnectResult,
    ModelAccess,
    ModelProblem,
    ModelStyle,
    ModelTestPassed,
    ModelTestResult,
)
from platform_api.orchestration.service import RolesNow
from platform_api.shared import Principal, Role, UserId, new_id

log = logging.getLogger(__name__)

type Slot = Literal["active", "pending"]
type KnownProviderId = Literal["aisg", "openai", "anthropic", "gemini"]
CHANGES_SHOWN = 20


@dataclass(frozen=True)
class KnownProvider:
    id: KnownProviderId
    name: str
    base_url: str


# Reviewed in PRs, so a model at one of these hosts needs no Approver to confirm it (ADR 0022).
KNOWN_PROVIDERS: tuple[KnownProvider, ...] = (
    KnownProvider("aisg", "AI Singapore gateway", "https://llm-gateway.aisg.sg"),
    KnownProvider("openai", "OpenAI", "https://api.openai.com/v1"),
    KnownProvider("anthropic", "Anthropic", "https://api.anthropic.com"),
    KnownProvider(
        "gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai"
    ),
)


def host_of(base_url: str) -> str:
    return (urlsplit(base_url).hostname or "").lower()


KNOWN_HOSTS = {host_of(p.base_url): p for p in KNOWN_PROVIDERS}


class KeyBox:
    """Seals model keys at rest under a key derived from SETTINGS_ENCRYPTION_KEY."""

    def __init__(self, secret: str) -> None:
        derived = hashlib.sha256(secret.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))

    def seal(self, key: str) -> str:
        return self._fernet.encrypt(key.encode()).decode()

    def open(self, sealed: str) -> str | None:
        try:
            return self._fernet.decrypt(sealed.encode()).decode()
        except InvalidToken:
            return None


@dataclass(frozen=True)
class StoredModel:
    provider: str
    style: ModelStyle
    base_url: str
    model: str
    sealed_key: str
    key_hint: str
    test_seconds: float
    by: UserId
    by_name: str
    at: datetime

    @property
    def digest(self) -> str:
        """Names exactly this entry. An Approver's decision quotes it, as with ADR 0008's digest."""
        seen = "|".join((self.style, self.base_url, self.model, self.key_hint, self.at.isoformat()))
        return "sha256:" + hashlib.sha256(seen.encode()).hexdigest()


@dataclass(frozen=True)
class ModelChange:
    at: datetime
    by: UserId
    summary: str
    confirmed_by: UserId | None = None


@dataclass(frozen=True)
class SettingsState:
    available: bool
    active: StoredModel | None
    pending: StoredModel | None
    changes: list[ModelChange]


@dataclass(frozen=True)
class SettingsOff:
    message: str = "Settings are off until SETTINGS_ENCRYPTION_KEY is set for platform-api."


@dataclass(frozen=True)
class KeyNeeded:
    message: str


@dataclass(frozen=True)
class RuntimeDown:
    message: str = "The agent runtime did not answer, so nothing was checked. Try again shortly."


@dataclass(frozen=True)
class Saved:
    test: ModelTestPassed
    awaiting_confirmation: bool


@dataclass(frozen=True)
class NothingPending:
    pass


@dataclass(frozen=True)
class OwnAddress:
    message: str = "You entered this address, so another Approver must confirm it."


@dataclass(frozen=True)
class PendingChanged:
    message: str = "The waiting address changed after you looked at it. Look again before deciding."


@dataclass(frozen=True)
class NotAnApprover:
    message: str = "Only an Approver can confirm an address. Ask an Approver."


@dataclass(frozen=True)
class NoLongerAnOperator:
    message: str = (
        "You are no longer an Operator, so the new address was not saved. Ask an Operator."
    )


@dataclass(frozen=True)
class AddressDecided:
    confirmed: bool


type ChecksAnswer[T] = T | AgentUnavailable | AgentRejected
type AddressAnswer = (
    AddressDecided | NothingPending | OwnAddress | PendingChanged | NotAnApprover | SettingsOff
)


class ModelChecks(Protocol):
    async def connect_model(self, request: ConnectRequest) -> ChecksAnswer[ConnectResult]: ...

    async def test_model(self, access: ModelAccess) -> ChecksAnswer[ModelTestResult]: ...


class ModelStore:
    async def load(self, uow: UnitOfWork, slot: Slot, lock: bool = False) -> StoredModel | None:
        query = "SELECT * FROM orchestration.model_setting WHERE slot = %s"
        row = await (
            await uow.conn.execute(query + (" FOR UPDATE" if lock else ""), (slot,))
        ).fetchone()
        if row is None:
            return None
        return StoredModel(
            provider=row["provider"],
            style=cast(ModelStyle, row["style"]),
            base_url=row["base_url"],
            model=row["model"],
            sealed_key=row["sealed_key"],
            key_hint=row["key_hint"],
            test_seconds=float(row["test_seconds"]),
            by=UserId(row["saved_by"]),
            by_name=row["saved_by_name"],
            at=row["saved_at"],
        )

    async def put(self, uow: UnitOfWork, slot: Slot, model: StoredModel) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.model_setting (slot, provider, style, base_url, model, "
            "sealed_key, key_hint, test_seconds, saved_by, saved_by_name, saved_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (slot) DO UPDATE SET provider = EXCLUDED.provider, "
            "style = EXCLUDED.style, base_url = EXCLUDED.base_url, model = EXCLUDED.model, "
            "sealed_key = EXCLUDED.sealed_key, key_hint = EXCLUDED.key_hint, "
            "test_seconds = EXCLUDED.test_seconds, saved_by = EXCLUDED.saved_by, "
            "saved_by_name = EXCLUDED.saved_by_name, saved_at = EXCLUDED.saved_at",
            (
                slot,
                model.provider,
                model.style,
                model.base_url,
                model.model,
                model.sealed_key,
                model.key_hint,
                model.test_seconds,
                model.by,
                model.by_name,
                model.at,
            ),
        )

    async def remove(self, uow: UnitOfWork, slot: Slot) -> None:
        await uow.conn.execute("DELETE FROM orchestration.model_setting WHERE slot = %s", (slot,))

    async def confirmed(self, uow: UnitOfWork, host: str) -> bool:
        row = await (
            await uow.conn.execute(
                "SELECT 1 FROM orchestration.model_hosts WHERE host = %s", (host,)
            )
        ).fetchone()
        return row is not None

    async def confirm(self, uow: UnitOfWork, host: str, by: UserId) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.model_hosts (host, confirmed_by, confirmed_at) "
            "VALUES (%s, %s, %s) ON CONFLICT (host) DO NOTHING",
            (host, by, uow.now),
        )

    async def changes(self, uow: UnitOfWork) -> list[ModelChange]:
        return [
            ModelChange(c.at, c.changed_by, c.summary, c.confirmed_by)
            for c in await _history.changes(uow, "model", CHANGES_SHOWN)
        ]


_history = confirmations.ConfirmationStore()


async def _lock_waiting(
    uow: UnitOfWork, store: ModelStore
) -> tuple[confirmations.Confirmation | None, StoredModel | None]:
    waiting = await _history.open_one(
        uow, confirmations.ConfirmationKind.MODEL_ADDRESS, None, lock=True
    )
    return waiting, await store.load(uow, "pending", lock=True)


async def close_address_asked_by(
    uow: UnitOfWork, asker: UserId, asker_name: str, closed_by: UserId, why: str
) -> None:
    """Closes the waiting address if the asker saved it, and deletes its key, when the asker
    leaves the list or stops being an Operator. Nobody then confirms a change whose author is
    gone (#59), as with an Approver request (ADR 0029)."""
    store = ModelStore()
    waiting, _ = await _lock_waiting(uow, store)
    if waiting is None or waiting.asked_by != asker:
        return
    await _history.close(uow, waiting.id, closed_by)
    await store.remove(uow, "pending")
    model, host = waiting.change.get("model"), waiting.change.get("host")
    await _history.record_change(
        uow,
        "model",
        closed_by,
        f"{asker_name}'s request to use {model} at {host} was closed, because {asker_name} "
        f"{why}. Its key was deleted.",
        confirmation_id=waiting.id,
    )


def _address_change(stored: StoredModel) -> dict[str, str]:
    return {
        "host": host_of(stored.base_url),
        "base_url": stored.base_url,
        "model": stored.model,
        "style": stored.style,
        "key_hint": stored.key_hint,
    }


class ModelSettings:
    """The AI model Operators set in the Portal, and the one each run's task carries (ADR 0022)."""

    def __init__(
        self,
        db: Database,
        checks: ModelChecks,
        box: KeyBox | None,
        people: RolesNow | None = None,
    ) -> None:
        self._db = db
        self._checks = checks
        self._box = box
        self._people = people
        self._store = ModelStore()

    async def view(self) -> SettingsState:
        async with self._db.transaction("orchestration") as uow:
            return SettingsState(
                available=self._box is not None,
                active=await self._store.load(uow, "active"),
                pending=await self._store.load(uow, "pending"),
                changes=await self._store.changes(uow),
            )

    async def access(self, uow: UnitOfWork) -> ModelAccess | None:
        if self._box is None:
            return None
        active = await self._store.load(uow, "active")
        if active is None:
            return None
        key = self._box.open(active.sealed_key)
        if key is None:
            log.warning("the saved model key no longer opens, so runs use the template")
            return None
        return ModelAccess(
            style=active.style, base_url=active.base_url, model=active.model, api_key=key
        )

    async def connect(
        self,
        principal: Principal,
        provider_id: KnownProviderId | None,
        base_url: str | None,
        api_key: str | None,
        use_saved_key: bool,
    ) -> ConnectResult | SettingsOff | KeyNeeded | RuntimeDown:
        if self._box is None:
            return SettingsOff()
        url = (
            next(p.base_url for p in KNOWN_PROVIDERS if p.id == provider_id)
            if provider_id
            else base_url or ""
        )
        async with self._db.transaction("orchestration") as uow:
            key = await self._key_for(uow, self._box, url, api_key, use_saved_key)
        if isinstance(key, KeyNeeded):
            return key
        answer = await self._checks.connect_model(ConnectRequest(base_url=url, api_key=key))
        if isinstance(answer, AgentUnavailable | AgentRejected):
            return RuntimeDown()
        return answer

    async def save(
        self,
        principal: Principal,
        style: ModelStyle,
        base_url: str,
        model: str,
        api_key: str | None,
        use_saved_key: bool,
    ) -> Saved | ModelProblem | SettingsOff | KeyNeeded | RuntimeDown | NoLongerAnOperator:
        box = self._box
        if box is None:
            return SettingsOff()
        async with self._db.transaction("orchestration") as uow:
            key = await self._key_for(uow, box, base_url, api_key, use_saved_key)
        if isinstance(key, KeyNeeded):
            return key
        access = ModelAccess(style=style, base_url=base_url, model=model, api_key=key)
        answer = await self._checks.test_model(access)
        if isinstance(answer, AgentUnavailable | AgentRejected):
            return RuntimeDown()
        if isinstance(answer, ModelProblem):
            return answer
        host = host_of(base_url)
        known = KNOWN_HOSTS.get(host)
        async with self._db.transaction("orchestration") as uow:
            stored = StoredModel(
                provider=known.name if known else host,
                style=style,
                base_url=base_url,
                model=model,
                sealed_key=box.seal(key),
                key_hint=key[-2:],
                test_seconds=answer.seconds,
                by=principal.user_id,
                by_name=principal.display,
                at=uow.now,
            )
            if known is None and not await self._store.confirmed(uow, host):
                # The same order as a person leaving, who closes the address they saved (#59):
                # People, then the confirmation, then the pending address. The role is read
                # again here, because the model test above can take seconds.
                await uow.conn.execute(confirmations.LOCK_PEOPLE)
                if self._people is not None:
                    roles = await self._people.roles_now(uow, principal.user_id)
                    if roles is None or Role.OPERATOR not in roles:
                        return NoLongerAnOperator()
                await self._lock_confirmation_then_pending(uow)
                await self._store.put(uow, "pending", stored)
                asked = await _history.ask(
                    uow,
                    confirmations.Confirmation(
                        id=confirmations.ConfirmationId(new_id("cfm")),
                        kind=confirmations.ConfirmationKind.MODEL_ADDRESS,
                        about=None,
                        change=_address_change(stored),
                        digest=stored.digest,
                        asked_by=principal.user_id,
                        asked_at=uow.now,
                    ),
                )
                await _history.record_change(
                    uow,
                    "model",
                    principal.user_id,
                    f"{principal.display} asked to use {model} at {host}. "
                    "An Approver must confirm the new address.",
                    confirmation_id=asked.id,
                )
                return Saved(answer, awaiting_confirmation=True)
            before = await self._store.load(uow, "active", lock=True)
            await self._store.put(uow, "active", stored)
            summary = _change_summary(principal.display, before, stored, not use_saved_key)
            if summary is not None:
                await _history.record_change(uow, "model", principal.user_id, summary)
            return Saved(answer, awaiting_confirmation=False)

    async def turn_off(self, principal: Principal) -> SettingsOff | None:
        if self._box is None:
            return SettingsOff()
        async with self._db.transaction("orchestration") as uow:
            if await self._store.load(uow, "active", lock=True) is None:
                return None
            await self._store.remove(uow, "active")
            await _history.record_change(
                uow,
                "model",
                principal.user_id,
                f"{principal.display} turned the AI model off, and the saved key was deleted.",
            )
        return None

    async def decide(
        self,
        principal: Principal,
        confirm: bool,
        digest: str,
        confirmation_id: str | None = None,
    ) -> AddressAnswer:
        """Decides the address waiting now, or only the confirmation named, when one is."""
        if self._box is None:
            return SettingsOff()
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute(confirmations.LOCK_PEOPLE)
            waiting, pending = await self._lock_confirmation_then_pending(uow)
            if waiting is None or pending is None:
                return NothingPending()
            if confirmation_id is not None and waiting.id != confirmation_id:
                return NothingPending()
            if self._people is not None:
                roles = await self._people.roles_now(uow, principal.user_id)
                principal = replace(principal, roles=roles or frozenset())
            decision = (
                confirmations.ConfirmationDecision.CONFIRMED
                if confirm
                else confirmations.ConfirmationDecision.NOT_NOW
            )
            decided = confirmations.decide(waiting, principal, decision, digest, uow.now)
            match decided:
                case confirmations.DecideRefused(confirmations.DecideRefusal.NOT_AN_APPROVER):
                    return NotAnApprover()
                case confirmations.DecideRefused(confirmations.DecideRefusal.DIGEST_CHANGED):
                    return PendingChanged()
                case confirmations.DecideRefused(confirmations.DecideRefusal.ALREADY_DECIDED):
                    return NothingPending()
                case confirmations.DecideRefused():
                    return OwnAddress()
                case _:
                    pass
            if not await _history.record_decision(uow, decided):
                return NothingPending()
            host = host_of(pending.base_url)
            await self._store.remove(uow, "pending")
            if confirm:
                await self._store.confirm(uow, host, principal.user_id)
                await self._store.put(uow, "active", pending)
                summary = f"{principal.display} confirmed {host}. Runs now use {pending.model}."
            else:
                summary = f"{principal.display} declined {host}, and its key was deleted."
            await _history.record_change(
                uow,
                "model",
                waiting.asked_by,
                summary,
                confirmed_by=principal.user_id,
                confirmation_id=waiting.id,
            )
            return AddressDecided(confirmed=confirm)

    async def _lock_confirmation_then_pending(
        self, uow: UnitOfWork
    ) -> tuple[confirmations.Confirmation | None, StoredModel | None]:
        return await _lock_waiting(uow, self._store)

    async def _key_for(
        self, uow: UnitOfWork, box: KeyBox, base_url: str, api_key: str | None, use_saved_key: bool
    ) -> str | KeyNeeded:
        if not use_saved_key:
            return api_key or ""
        active = await self._store.load(uow, "active")
        if active is None or host_of(active.base_url) != host_of(base_url):
            return KeyNeeded(
                "The saved key belongs to another address. Paste the key for this one."
            )
        key = box.open(active.sealed_key)
        if key is None:
            return KeyNeeded("The saved key can no longer be read. Paste it again.")
        return key


def _change_summary(
    name: str, before: StoredModel | None, after: StoredModel, key_replaced: bool
) -> str | None:
    if before is None:
        return (
            f"{name} turned on {after.model} ({after.provider}), with a key ending in "
            f"{after.key_hint}."
        )
    switched = (before.style, before.base_url, before.model) != (
        after.style,
        after.base_url,
        after.model,
    )
    if switched and key_replaced:
        return (
            f"{name} switched to {after.model} ({after.provider}) and replaced the key, now "
            f"ending in {after.key_hint}."
        )
    if switched:
        return f"{name} switched to {after.model} ({after.provider})."
    if key_replaced:
        return f"{name} replaced the key, now ending in {after.key_hint}."
    return None
