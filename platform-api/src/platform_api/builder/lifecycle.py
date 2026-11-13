from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from platform_api.shared import UserId

RESTORE_WINDOW = timedelta(days=1)


@dataclass(frozen=True)
class Draft:
    """Set up, and not turned on yet (ADR 0044)."""


@dataclass(frozen=True)
class On:
    pass


@dataclass(frozen=True)
class Paused:
    at: datetime
    by: UserId


@dataclass(frozen=True)
class Deleted:
    at: datetime
    by: UserId
    before: Draft | On | Paused

    @property
    def restore_until(self) -> datetime:
        return self.at + RESTORE_WINDOW


type Lifecycle = Draft | On | Paused | Deleted


@dataclass(frozen=True)
class AlreadyDeleted:
    pass


@dataclass(frozen=True)
class TooLate:
    until: datetime


def is_on(state: Lifecycle) -> bool:
    return isinstance(state, On)


def comes_on(before: Lifecycle, after: Lifecycle) -> bool:
    return is_on(after) and not is_on(before)


def pause(state: Lifecycle, now: datetime, by: UserId) -> Lifecycle | AlreadyDeleted:
    match state:
        case On():
            return Paused(now, by)
        case Draft() | Paused():
            return state
        case Deleted():
            return AlreadyDeleted()


def resume(state: Lifecycle) -> Lifecycle | AlreadyDeleted:
    """A draft stays a draft: only turning it on publishes it."""
    match state:
        case On() | Paused():
            return On()
        case Draft():
            return state
        case Deleted():
            return AlreadyDeleted()


def turn_on(state: Lifecycle) -> Lifecycle | AlreadyDeleted:
    """Once it was turned on, turning it on again changes nothing, even while it is paused."""
    match state:
        case Draft():
            return On()
        case On() | Paused():
            return state
        case Deleted():
            return AlreadyDeleted()


def delete(state: Lifecycle, now: datetime, by: UserId) -> Deleted:
    match state:
        case Draft() | On() | Paused():
            return Deleted(now, by, state)
        case Deleted():
            return state


def restore(state: Lifecycle, now: datetime) -> Lifecycle | TooLate:
    match state:
        case Draft() | On() | Paused():
            return state
        case Deleted(before=before):
            return before if now <= state.restore_until else TooLate(state.restore_until)


@dataclass(frozen=True)
class Columns:
    paused_at: datetime | None
    paused_by: UserId | None
    deleted_at: datetime | None
    deleted_by: UserId | None
    draft: bool = False


def to_columns(state: Lifecycle) -> Columns:
    match state:
        case Draft():
            return Columns(None, None, None, None, draft=True)
        case On():
            return Columns(None, None, None, None)
        case Paused(at, by):
            return Columns(at, by, None, None)
        case Deleted(at, by, before):
            kept = to_columns(before)
            return Columns(kept.paused_at, kept.paused_by, at, by, kept.draft)


def from_columns(columns: Columns) -> Lifecycle:
    before: Draft | On | Paused = Draft() if columns.draft else On()
    if columns.paused_at is not None and columns.paused_by is not None:
        before = Paused(columns.paused_at, columns.paused_by)
    if columns.deleted_at is not None and columns.deleted_by is not None:
        return Deleted(columns.deleted_at, columns.deleted_by, before)
    return before


def lifecycle_of(row: Mapping[str, Any]) -> Lifecycle:
    return from_columns(
        Columns(
            row["paused_at"], row["paused_by"], row["deleted_at"], row["deleted_by"], row["draft"]
        )
    )
