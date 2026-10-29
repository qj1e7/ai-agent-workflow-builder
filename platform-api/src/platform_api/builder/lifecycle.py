from dataclasses import dataclass
from datetime import datetime, timedelta

from platform_api.shared import UserId

RESTORE_WINDOW = timedelta(days=1)


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
    before: On | Paused

    @property
    def restore_until(self) -> datetime:
        return self.at + RESTORE_WINDOW


type Lifecycle = On | Paused | Deleted


@dataclass(frozen=True)
class AlreadyDeleted:
    pass


@dataclass(frozen=True)
class TooLate:
    until: datetime


def is_on(state: Lifecycle) -> bool:
    return isinstance(state, On)


def pause(state: Lifecycle, now: datetime, by: UserId) -> Lifecycle | AlreadyDeleted:
    match state:
        case On():
            return Paused(now, by)
        case Paused():
            return state
        case Deleted():
            return AlreadyDeleted()


def resume(state: Lifecycle) -> Lifecycle | AlreadyDeleted:
    match state:
        case On() | Paused():
            return On()
        case Deleted():
            return AlreadyDeleted()


def delete(state: Lifecycle, now: datetime, by: UserId) -> Deleted:
    match state:
        case On() | Paused():
            return Deleted(now, by, state)
        case Deleted():
            return state


def restore(state: Lifecycle, now: datetime) -> Lifecycle | TooLate:
    match state:
        case On() | Paused():
            return state
        case Deleted(before=before):
            return before if now <= state.restore_until else TooLate(state.restore_until)


@dataclass(frozen=True)
class Columns:
    paused_at: datetime | None
    paused_by: UserId | None
    deleted_at: datetime | None
    deleted_by: UserId | None


def to_columns(state: Lifecycle) -> Columns:
    match state:
        case On():
            return Columns(None, None, None, None)
        case Paused(at, by):
            return Columns(at, by, None, None)
        case Deleted(at, by, before):
            kept = to_columns(before)
            return Columns(kept.paused_at, kept.paused_by, at, by)


def from_columns(columns: Columns) -> Lifecycle:
    before: On | Paused = On()
    if columns.paused_at is not None and columns.paused_by is not None:
        before = Paused(columns.paused_at, columns.paused_by)
    if columns.deleted_at is not None and columns.deleted_by is not None:
        return Deleted(columns.deleted_at, columns.deleted_by, before)
    return before
