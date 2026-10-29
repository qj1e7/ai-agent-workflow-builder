"""Whether a use case runs: on, paused, or deleted and restorable for a day.

Pure. The list, the routes and the schedule tick all read a use case's lifecycle through this
module. Nothing is hard-deleted: a deleted use case keeps its rows and its past runs, and
restoring it puts back the state it had, so a paused use case comes back paused.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from platform_api.shared import UserId

RESTORE_WINDOW = timedelta(days=1)

type StateName = Literal["on", "paused", "deleted"]


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
class Gone:
    """The use case is deleted, so it cannot be paused or resumed."""


@dataclass(frozen=True)
class TooLate:
    """The day to restore a deleted use case has passed."""

    until: datetime


def name_of(state: Lifecycle) -> StateName:
    match state:
        case On():
            return "on"
        case Paused():
            return "paused"
        case Deleted():
            return "deleted"


def runs(state: Lifecycle) -> bool:
    """Only a use case that is on starts runs, by hand or on its schedule."""
    return isinstance(state, On)


def pause(state: Lifecycle, now: datetime, by: UserId) -> Lifecycle | Gone:
    match state:
        case On():
            return Paused(now, by)
        case Paused():
            return state
        case Deleted():
            return Gone()


def resume(state: Lifecycle) -> Lifecycle | Gone:
    match state:
        case On() | Paused():
            return On()
        case Deleted():
            return Gone()


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
