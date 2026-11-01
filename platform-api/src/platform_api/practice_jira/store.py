"""The practice Jira's tickets, in orchestration.mock_jira_tickets (ADR 0035)."""

import hashlib
import hmac
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from platform_api.db import Database
from platform_api.shared import TicketStatus

PRACTICE_EMAIL = "practice@platform.invalid"
"""The account the adapter names when the practice Jira speaks Cloud's API."""
PRACTICE_ACCOUNT = "wab-platform"
"""The platform's account in the practice Jira: what /myself answers, and who made its tickets."""

_COLUMNS = (
    "key, number, project, title, body, created_at, run_id, proposal_id, status, done_at, "
    "labels, issue_type, creator"
)
_OUR_LABEL = re.compile(r"^wab-(run_[A-Za-z0-9]+)-(prp_[A-Za-z0-9]+)-([0-9]+)$")


def _to_ms(at: datetime) -> datetime:
    """Jira keeps times to the millisecond, so the practice Jira does too."""
    return at.replace(microsecond=at.microsecond // 1000 * 1000)


def practice_token(signing_key: str) -> str:
    """The practice Jira's token, made from the callback signing key so it needs no new secret."""
    return hmac.new(signing_key.encode(), b"practice-jira", hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class PracticeTicket:
    key: str
    number: int
    project: str
    title: str
    body: str
    created_at: datetime
    run_id: str | None
    proposal_id: str | None
    status: TicketStatus
    done_at: datetime | None
    labels: tuple[str, ...]
    issue_type: str
    creator: str | None = None


@dataclass(frozen=True)
class Failure:
    status: int
    retry_after: int | None


def _ticket(row: Mapping[str, Any]) -> PracticeTicket:
    return PracticeTicket(
        key=row["key"],
        number=int(row["number"]),
        project=row["project"],
        title=row["title"],
        body=row["body"],
        created_at=row["created_at"],
        run_id=row["run_id"] or None,
        proposal_id=row["proposal_id"] or None,
        status="Done" if row["status"] == "Done" else "To Do",
        done_at=row["done_at"],
        labels=tuple(row["labels"] or ()),
        issue_type=row["issue_type"],
        creator=row["creator"],
    )


class PracticeJira:
    """The practice Jira's state: its tickets, its token, and the failures a test asked for."""

    def __init__(self, db: Database, token: str, portal_url: str) -> None:
        self._db = db
        self.token = token
        self.portal_url = portal_url.rstrip("/")
        self._failures: list[Failure] = []
        self.calls: list[str] = []
        """Each REST call, as "GET /rest/api/2/search", so a test can see what was asked."""

    def fail_next(self, status: int, times: int = 1, retry_after: int | None = None) -> None:
        """Answers the next calls with this status, as a busy or broken Jira would. For tests."""
        self._failures.extend(Failure(status, retry_after) for _ in range(times))

    def take_failure(self) -> Failure | None:
        return self._failures.pop(0) if self._failures else None

    def now(self) -> datetime:
        return self._db.clock()

    async def create(
        self,
        project: str,
        title: str,
        body: str,
        labels: Sequence[str],
        issue_type: str,
        creator: str = PRACTICE_ACCOUNT,
    ) -> PracticeTicket:
        """A new ticket, numbered after every other. A label in our write-key shape also fills
        the run columns, so the practice Jira's page can link to the run."""
        ours = next((m for label in labels if (m := _OUR_LABEL.match(label))), None)
        async with self._db.transaction("orchestration") as uow:
            await uow.conn.execute("LOCK TABLE orchestration.mock_jira_tickets IN EXCLUSIVE MODE")
            row = await (
                await uow.conn.execute(
                    "SELECT coalesce(max(number), 0) + 1 AS number "
                    "FROM orchestration.mock_jira_tickets"
                )
            ).fetchone()
            assert row is not None
            number = int(row["number"])
            created = await (
                await uow.conn.execute(
                    "INSERT INTO orchestration.mock_jira_tickets "
                    "(key, number, project, title, body, created_at, run_id, proposal_id, "
                    "labels, issue_type, creator) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    f"RETURNING {_COLUMNS}",
                    (
                        f"{project}-{number}",
                        number,
                        project,
                        title,
                        body,
                        _to_ms(uow.now),
                        None if ours is None else ours.group(1),
                        None if ours is None else ours.group(2),
                        list(dict.fromkeys(labels)),
                        issue_type,
                        creator,
                    ),
                )
            ).fetchone()
        assert created is not None
        return _ticket(created)

    async def get(self, key: str) -> PracticeTicket | None:
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    f"SELECT {_COLUMNS} FROM orchestration.mock_jira_tickets WHERE key = %s",
                    (key,),
                )
            ).fetchone()
        return None if row is None else _ticket(row)

    async def newest_first(self) -> list[PracticeTicket]:
        """Every ticket, newest first, for a search to filter."""
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    f"SELECT {_COLUMNS} FROM orchestration.mock_jira_tickets "
                    "ORDER BY created_at DESC, number DESC"
                )
            ).fetchall()
        return [_ticket(row) for row in rows]

    async def tickets(self) -> list[PracticeTicket]:
        """Every ticket in the order it was made, for the practice Jira's page."""
        async with self._db.transaction("orchestration") as uow:
            rows = await (
                await uow.conn.execute(
                    f"SELECT {_COLUMNS} FROM orchestration.mock_jira_tickets ORDER BY number"
                )
            ).fetchall()
        return [_ticket(row) for row in rows]

    async def mark_done(self, key: str) -> PracticeTicket | None:
        """Moves a ticket to Done. A ticket already Done keeps its first done time."""
        async with self._db.transaction("orchestration") as uow:
            row = await (
                await uow.conn.execute(
                    "UPDATE orchestration.mock_jira_tickets SET status = 'Done', "
                    "done_at = coalesce(done_at, %s) WHERE key = %s "
                    f"RETURNING {_COLUMNS}",
                    (_to_ms(uow.now), key),
                )
            ).fetchone()
        return None if row is None else _ticket(row)
