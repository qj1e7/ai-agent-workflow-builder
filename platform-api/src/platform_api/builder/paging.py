"""Paged reads of the lists a person works through, the newest first (principles 7 and 9).

A page ends at the place of its last row, and the next page starts after that place, so a row
that arrives later never moves the rows behind it. The cursor is the places of the lists that
still have rows to send, and it means nothing to the Portal."""

import base64
import binascii
import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import AwareDatetime, TypeAdapter


@dataclass(frozen=True, order=True)
class Place:
    """Where a row sits in a list ordered newest first: its time, then its id."""

    at: datetime
    id: str


type Cursor = Mapping[str, Place]
"""For each list with rows still to send, the place of the last row sent."""

_CURSOR = TypeAdapter(dict[str, tuple[AwareDatetime, str]])


def page_of[R](
    rows: Sequence[R], place: Callable[[R], Place], after: Place | None, size: int
) -> tuple[list[R], Place | None]:
    """The next `size` rows after `after`, the newest first, and the place to go on from, or None
    when none are left."""
    newest_first = sorted(rows, key=place, reverse=True)
    rest = [row for row in newest_first if after is None or place(row) < after]
    page = rest[:size]
    return page, place(page[-1]) if len(rest) > size else None


def cursor_text(cursor: Cursor) -> str | None:
    """None when no list has rows left."""
    if not cursor:
        return None
    raw = json.dumps({name: [p.at.isoformat(), p.id] for name, p in sorted(cursor.items())})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def parse_cursor(text: str, lists: Collection[str]) -> dict[str, Place] | None:
    """The cursor a page of these lists gave out, or None when `text` is not one."""
    try:
        raw = _CURSOR.validate_json(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except binascii.Error, ValueError:
        return None
    if not raw or not set(raw) <= set(lists):
        return None
    return {name: Place(at, row_id) for name, (at, row_id) in raw.items()}
