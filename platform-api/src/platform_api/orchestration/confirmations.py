"""A setup change that needs a second person (ADR 0030): a new Approver, or a new AI model
address. Anyone with the Approver role may decide it, except the asker and the person it is
about. It is decided once."""

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any, Literal, NewType

from platform_api.db import UnitOfWork
from platform_api.db import json as jsonb
from platform_api.shared import Principal, Role, UserId

ConfirmationId = NewType("ConfirmationId", str)

type Area = Literal["people", "model"]
HISTORY_SHOWN = 50


class ConfirmationKind(Enum):
    APPROVER = "approver"
    MODEL_ADDRESS = "model_address"


class ConfirmationDecision(Enum):
    CONFIRMED = "confirmed"
    NOT_NOW = "not_now"
    CLOSED = "closed"
    """Nobody decided it: the person it is about, or who asked, left first."""


@dataclass(frozen=True)
class Confirmation:
    id: ConfirmationId
    kind: ConfirmationKind
    about: UserId | None
    change: Mapping[str, Any]
    digest: str
    asked_by: UserId
    asked_at: datetime
    decided_by: UserId | None = None
    decision: ConfirmationDecision | None = None
    decided_at: datetime | None = None

    @property
    def open(self) -> bool:
        return self.decided_at is None


class DecideRefusal(Enum):
    NOT_AN_APPROVER = "not_an_approver"
    YOU_ASKED = "you_asked"
    ABOUT_YOU = "about_you"
    ALREADY_DECIDED = "already_decided"
    DIGEST_CHANGED = "digest_changed"
    PERSON_REMOVED = "person_removed"
    ASKER_GONE = "asker_gone"


DECIDE_MESSAGES: dict[DecideRefusal, str] = {
    DecideRefusal.NOT_AN_APPROVER: "Only an Approver can confirm this.",
    DecideRefusal.YOU_ASKED: "You asked for this change, so another Approver must confirm it.",
    DecideRefusal.ABOUT_YOU: "This change is about you, so another Approver must confirm it.",
    DecideRefusal.ALREADY_DECIDED: "This was already decided.",
    DecideRefusal.DIGEST_CHANGED: (
        "This changed after you looked at it. Look again before deciding."
    ),
    DecideRefusal.PERSON_REMOVED: (
        "This person was removed from the list since this was asked. Ask again."
    ),
    DecideRefusal.ASKER_GONE: "The person who asked is no longer an Operator. Ask again.",
}


@dataclass(frozen=True)
class DecideRefused:
    reason: DecideRefusal

    @property
    def message(self) -> str:
        return DECIDE_MESSAGES[self.reason]


def digest_of(
    kind: ConfirmationKind,
    about: UserId | None,
    asked_by: UserId,
    asked_at: datetime,
    change: Mapping[str, Any],
) -> str:
    seen = json.dumps(
        [kind.value, about, asked_by, asked_at.isoformat(), dict(change)], sort_keys=True
    )
    return "sha256:" + hashlib.sha256(seen.encode()).hexdigest()


def why_not(
    confirmation: Confirmation,
    decider: Principal,
    about_on_list: bool = True,
    about_added_at: datetime | None = None,
    asker_is_operator: bool = True,
) -> DecideRefusal | None:
    if not confirmation.open:
        return DecideRefusal.ALREADY_DECIDED
    if not about_on_list or not _same_person(confirmation, about_added_at):
        return DecideRefusal.PERSON_REMOVED
    if not asker_is_operator:
        return DecideRefusal.ASKER_GONE
    if Role.APPROVER not in decider.roles:
        return DecideRefusal.NOT_AN_APPROVER
    if confirmation.asked_by == decider.user_id:
        return DecideRefusal.YOU_ASKED
    if confirmation.about == decider.user_id:
        return DecideRefusal.ABOUT_YOU
    return None


def _same_person(confirmation: Confirmation, about_added_at: datetime | None) -> bool:
    """A person removed and added again has a new added_at, so an old request about them no
    longer matches."""
    asked_about = confirmation.change.get("added_at")
    if about_added_at is None or asked_about is None:
        return True
    return about_added_at.isoformat() == asked_about


def decide(
    confirmation: Confirmation,
    decider: Principal,
    decision: ConfirmationDecision,
    seen_digest: str,
    now: datetime,
    about_on_list: bool = True,
    about_added_at: datetime | None = None,
    asker_is_operator: bool = True,
) -> Confirmation | DecideRefused:
    reason = why_not(confirmation, decider, about_on_list, about_added_at, asker_is_operator)
    if reason is not None:
        return DecideRefused(reason)
    if not hmac.compare_digest(confirmation.digest, seen_digest):
        return DecideRefused(DecideRefusal.DIGEST_CHANGED)
    return replace(confirmation, decided_by=decider.user_id, decision=decision, decided_at=now)


@dataclass(frozen=True)
class SettingsChange:
    at: datetime
    area: Area
    changed_by: UserId
    confirmed_by: UserId | None
    confirmation_id: ConfirmationId | None
    summary: str


def _confirmation(row: Mapping[str, Any]) -> Confirmation:
    return Confirmation(
        id=ConfirmationId(row["id"]),
        kind=ConfirmationKind(row["kind"]),
        about=UserId(row["about"]) if row["about"] is not None else None,
        change=row["change"],
        digest=row["digest"],
        asked_by=UserId(row["asked_by"]),
        asked_at=row["asked_at"],
        decided_by=UserId(row["decided_by"]) if row["decided_by"] is not None else None,
        decision=ConfirmationDecision(row["decision"]) if row["decision"] is not None else None,
        decided_at=row["decided_at"],
    )


_COLUMNS = "id, kind, about, change, digest, asked_by, asked_at, decided_by, decision, decided_at"


class ConfirmationStore:
    async def ask(self, uow: UnitOfWork, confirmation: Confirmation) -> Confirmation:
        """Opens the confirmation. A kind that already has one open for the same person (or none,
        for a model address) is replaced in place, so the open record and its digest change and a
        stale decision is refused."""
        row = await (
            await uow.conn.execute(
                "INSERT INTO orchestration.confirmations "
                "(id, kind, about, change, digest, asked_by, asked_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (kind, coalesce(about, '')) WHERE decided_at IS NULL DO UPDATE SET "
                "change = EXCLUDED.change, digest = EXCLUDED.digest, "
                "asked_by = EXCLUDED.asked_by, asked_at = EXCLUDED.asked_at "
                f"RETURNING {_COLUMNS}",
                (
                    confirmation.id,
                    confirmation.kind.value,
                    confirmation.about,
                    jsonb(dict(confirmation.change)),
                    confirmation.digest,
                    confirmation.asked_by,
                    confirmation.asked_at,
                ),
            )
        ).fetchone()
        assert row is not None
        return _confirmation(row)

    async def load(
        self, uow: UnitOfWork, confirmation_id: str, lock: bool = False
    ) -> Confirmation | None:
        row = await (
            await uow.conn.execute(
                f"SELECT {_COLUMNS} FROM orchestration.confirmations WHERE id = %s"
                + (" FOR UPDATE" if lock else ""),
                (confirmation_id,),
            )
        ).fetchone()
        return _confirmation(row) if row is not None else None

    async def open_one(
        self, uow: UnitOfWork, kind: ConfirmationKind, about: UserId | None, lock: bool = False
    ) -> Confirmation | None:
        row = await (
            await uow.conn.execute(
                f"SELECT {_COLUMNS} FROM orchestration.confirmations "
                "WHERE kind = %s AND coalesce(about, '') = %s AND decided_at IS NULL"
                + (" FOR UPDATE" if lock else ""),
                (kind.value, about or ""),
            )
        ).fetchone()
        return _confirmation(row) if row is not None else None

    async def open_ones(self, uow: UnitOfWork) -> list[Confirmation]:
        rows = await (
            await uow.conn.execute(
                f"SELECT {_COLUMNS} FROM orchestration.confirmations "
                "WHERE decided_at IS NULL ORDER BY asked_at, id"
            )
        ).fetchall()
        return [_confirmation(r) for r in rows]

    async def record_decision(self, uow: UnitOfWork, decided: Confirmation) -> bool:
        """Writes the decision once. False when another decision got there first."""
        assert decided.decision is not None
        result = await uow.conn.execute(
            "UPDATE orchestration.confirmations "
            "SET decided_by = %s, decision = %s, decided_at = %s "
            "WHERE id = %s AND digest = %s AND decided_at IS NULL",
            (
                decided.decided_by,
                decided.decision.value,
                decided.decided_at,
                decided.id,
                decided.digest,
            ),
        )
        return result.rowcount == 1

    async def close_about(
        self, uow: UnitOfWork, person_id: UserId, closed_by: UserId
    ) -> list[Confirmation]:
        """Closes every open confirmation about a person, as the one who removed them."""
        rows = await (
            await uow.conn.execute(
                "UPDATE orchestration.confirmations "
                "SET decided_by = %s, decision = %s, decided_at = %s "
                f"WHERE about = %s AND decided_at IS NULL RETURNING {_COLUMNS}",
                (closed_by, ConfirmationDecision.CLOSED.value, uow.now, person_id),
            )
        ).fetchall()
        return [_confirmation(r) for r in rows]

    async def record_change(
        self,
        uow: UnitOfWork,
        area: Area,
        changed_by: UserId,
        summary: str,
        confirmed_by: UserId | None = None,
        confirmation_id: ConfirmationId | None = None,
    ) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.settings_changes "
            "(changed_at, area, changed_by, confirmed_by, confirmation_id, summary) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (uow.now, area, changed_by, confirmed_by, confirmation_id, summary),
        )

    async def changes(
        self, uow: UnitOfWork, area: Area | None = None, limit: int = HISTORY_SHOWN
    ) -> list[SettingsChange]:
        rows = await (
            await uow.conn.execute(
                "SELECT changed_at, area, changed_by, confirmed_by, confirmation_id, summary "
                "FROM orchestration.settings_changes "
                "WHERE %s::text IS NULL OR area = %s ORDER BY id DESC LIMIT %s",
                (area, area, limit),
            )
        ).fetchall()
        return [
            SettingsChange(
                at=r["changed_at"],
                area=r["area"],
                changed_by=UserId(r["changed_by"]),
                confirmed_by=UserId(r["confirmed_by"]) if r["confirmed_by"] is not None else None,
                confirmation_id=(
                    ConfirmationId(r["confirmation_id"])
                    if r["confirmation_id"] is not None
                    else None
                ),
                summary=r["summary"],
            )
            for r in rows
        ]
