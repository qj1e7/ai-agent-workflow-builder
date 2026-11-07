"""Team requests (ADR 0038): what a person asks the team when the platform can't help.

Ask the team is for something the Planner can't do. Report to support is for a platform fault.
Both go in one list that every Operator and Approver can read and answer. Keeping a request
writes only to our own database, so it is not an agent write action and needs no approval.
Nothing in here writes to Jira or any other outside system, and nothing here approves anything.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import Field, StringConstraints, model_validator

from platform_api.db import Database, UnitOfWork, json
from platform_api.orchestration import RequestKind, RequestNotice, TeamsPost
from platform_api.shared import Principal, new_id
from platform_api.wire import WireIn, WireModel

NOTE_LIMIT = 1000
REPLY_LIMIT = 1000
LIST_LIMIT = 200
FOLLOWING_UP_SHOWN = 10
DONE_STAYS_LISTED = timedelta(days=30)
"""A request marked Done leaves the list after this long. It stays in the record."""

type RequestStatus = Literal["open", "answered", "done"]
type Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class About(WireIn):
    capability: Annotated[str, Field(min_length=1, max_length=80)] | None = Field(
        default=None, description="For Ask the team: what the person wants, such as `email.send`."
    )
    run_id: Annotated[str, Field(min_length=1, max_length=80)] | None = Field(
        default=None, description="For Report to support: the run that stopped."
    )


class CreateTeamRequest(WireIn):
    kind: RequestKind
    about: About
    note: Note = Field(
        max_length=NOTE_LIMIT,
        description="Plain text. The box says not to paste passwords or keys. A request is never "
        "sent to the AI model.",
    )

    @model_validator(mode="after")
    def _about_matches_the_kind(self) -> Self:
        needs, other = (
            ("capability", "run_id")
            if self.kind == "ask_the_team"
            else (
                "run_id",
                "capability",
            )
        )
        if getattr(self.about, needs) is None or getattr(self.about, other) is not None:
            raise ValueError(f"A request of this kind is about `{needs}` and nothing else.")
        return self


class ReplyIn(WireIn):
    text: Note = Field(max_length=REPLY_LIMIT)
    status: Literal["answered", "done"] = Field(
        default="answered",
        description="Answered when the team has replied. Done when nothing more will happen, "
        "including when the team says it won't be done, and why in the text.",
    )


class ReplyView(WireModel):
    replied_by: str
    replied_by_name: str
    replied_at: datetime
    text: str
    status: Literal["answered", "done"]


class TeamRequestView(WireModel):
    request_id: str
    kind: RequestKind
    about: dict[str, str]
    note: str
    asked_by: str
    asked_by_name: str
    asked_at: datetime
    status: RequestStatus
    replies: list[ReplyView] = Field(description="Oldest first.")
    posted_to_teams: bool = Field(
        description="Whether a card went to the team's Teams channel. When false, the request is "
        "still kept and listed, and the team sees it only in the app."
    )
    not_posted_because: Literal["no_channel", "failed"] | None = Field(
        description="`no_channel` when no Teams channel is set up. `failed` when Teams refused "
        "or did not answer. Null when it was posted."
    )


class TeamRequestList(WireModel):
    requests: list[TeamRequestView] = Field(
        description="Every request, the newest first, at most 200. A request marked Done leaves "
        "the list after 30 days."
    )
    total: int


class FollowingUpItem(WireModel):
    request_id: str
    kind: RequestKind
    about: dict[str, str]
    note: str
    asked_at: datetime
    status: RequestStatus
    latest_reply: ReplyView | None


@dataclass(frozen=True)
class Created:
    request: TeamRequestView
    new: bool


@dataclass(frozen=True)
class NoSuchRun:
    run_id: str


class RunLookup(Protocol):
    async def get_run(self, run_id: Any) -> object | None: ...


class RequestChannel(Protocol):
    async def post(self, notice: RequestNotice) -> TeamsPost: ...


def _reply(row: Mapping[str, Any]) -> ReplyView:
    return ReplyView(
        replied_by=row["replied_by"],
        replied_by_name=row["replied_by_name"],
        replied_at=row["replied_at"],
        text=row["text"],
        status=row["status"],
    )


def _view(row: Mapping[str, Any], replies: list[ReplyView]) -> TeamRequestView:
    post: TeamsPost = row["teams_post"]
    return TeamRequestView(
        request_id=row["request_id"],
        kind=row["kind"],
        about=row["about"],
        note=row["note"],
        asked_by=row["asked_by"],
        asked_by_name=row["asked_by_name"],
        asked_at=row["asked_at"],
        status=row["status"],
        replies=replies,
        posted_to_teams=post == "posted",
        not_posted_because=None if post == "posted" else post,
    )


_LISTED = "(status <> 'done' OR done_at > %(since)s)"


async def _replies_of(uow: UnitOfWork, ids: list[str]) -> dict[str, list[ReplyView]]:
    rows = await (
        await uow.conn.execute(
            "SELECT * FROM builder.team_request_replies WHERE request_id = ANY(%s)"
            " ORDER BY replied_at, reply_id",
            (ids,),
        )
    ).fetchall()
    by_request: dict[str, list[ReplyView]] = {}
    for row in rows:
        by_request.setdefault(row["request_id"], []).append(_reply(row))
    return by_request


class TeamRequests:
    def __init__(
        self, db: Database, channel: RequestChannel, runs: RunLookup, public_base_url: str
    ) -> None:
        self._db = db
        self._channel = channel
        self._runs = runs
        self._open_url = f"{public_base_url.rstrip('/')}/settings?tab=team-requests"

    async def create(
        self, asker: Principal, idempotency_key: str, body: CreateTeamRequest
    ) -> Created | NoSuchRun:
        run_id = body.about.run_id
        if run_id is not None and await self._runs.get_run(run_id) is None:
            return NoSuchRun(run_id)
        about = body.about.model_dump(exclude_none=True)
        async with self._db.transaction("builder") as uow:
            row = await (
                await uow.conn.execute(
                    "INSERT INTO builder.team_requests (request_id, kind, about, note, asked_by,"
                    " asked_by_name, asked_at, idempotency_key) VALUES (%s, %s, %s, %s, %s, %s,"
                    " %s, %s) ON CONFLICT (asked_by, idempotency_key) DO NOTHING RETURNING *",
                    (
                        new_id("trq"),
                        body.kind,
                        json(about),
                        body.note,
                        asker.user_id,
                        asker.display,
                        uow.now,
                        idempotency_key,
                    ),
                )
            ).fetchone()
            if row is None:
                kept = await (
                    await uow.conn.execute(
                        "SELECT * FROM builder.team_requests"
                        " WHERE asked_by = %s AND idempotency_key = %s",
                        (asker.user_id, idempotency_key),
                    )
                ).fetchone()
                assert kept is not None
                replies = (await _replies_of(uow, [kept["request_id"]])).get(kept["request_id"])
                return Created(_view(kept, replies or []), new=False)
        posted = await self._channel.post(
            RequestNotice(kind=body.kind, asked_by_name=asker.display, open_url=self._open_url)
        )
        async with self._db.transaction("builder") as uow:
            row = await (
                await uow.conn.execute(
                    "UPDATE builder.team_requests SET teams_post = %s WHERE request_id = %s"
                    " RETURNING *",
                    (posted, row["request_id"]),
                )
            ).fetchone()
        assert row is not None
        return Created(_view(row, []), new=True)

    async def list(self) -> TeamRequestList:
        async with self._db.transaction("builder") as uow:
            since = uow.now - DONE_STAYS_LISTED
            total = await (
                await uow.conn.execute(
                    f"SELECT count(*) AS n FROM builder.team_requests WHERE {_LISTED}",
                    {"since": since},
                )
            ).fetchone()
            rows = await (
                await uow.conn.execute(
                    f"SELECT * FROM builder.team_requests WHERE {_LISTED}"
                    " ORDER BY asked_at DESC, request_id DESC LIMIT %(limit)s",
                    {"since": since, "limit": LIST_LIMIT},
                )
            ).fetchall()
            replies = await _replies_of(uow, [r["request_id"] for r in rows])
        assert total is not None
        return TeamRequestList(
            requests=[_view(r, replies.get(r["request_id"], [])) for r in rows],
            total=total["n"],
        )

    async def reply(
        self, replier: Principal, request_id: str, body: ReplyIn
    ) -> TeamRequestView | None:
        async with self._db.transaction("builder") as uow:
            row = await (
                await uow.conn.execute(
                    "UPDATE builder.team_requests SET status = %s,"
                    " done_at = CASE WHEN %s = 'done' THEN %s END"
                    " WHERE request_id = %s RETURNING *",
                    (body.status, body.status, uow.now, request_id),
                )
            ).fetchone()
            if row is None:
                return None
            await uow.conn.execute(
                "INSERT INTO builder.team_request_replies (reply_id, request_id, replied_by,"
                " replied_by_name, replied_at, text, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    new_id("trr"),
                    request_id,
                    replier.user_id,
                    replier.display,
                    uow.now,
                    body.text,
                    body.status,
                ),
            )
            replies = await _replies_of(uow, [request_id])
        return _view(row, replies.get(request_id, []))

    async def following_up(self, asker: Principal) -> tuple[list[FollowingUpItem], int]:
        """The person's own requests, the newest first, and how many they have in all."""
        async with self._db.transaction("builder") as uow:
            since = uow.now - DONE_STAYS_LISTED
            params = {"who": asker.user_id, "since": since, "limit": FOLLOWING_UP_SHOWN}
            total = await (
                await uow.conn.execute(
                    f"SELECT count(*) AS n FROM builder.team_requests"
                    f" WHERE asked_by = %(who)s AND {_LISTED}",
                    params,
                )
            ).fetchone()
            rows = await (
                await uow.conn.execute(
                    f"SELECT * FROM builder.team_requests WHERE asked_by = %(who)s AND {_LISTED}"
                    " ORDER BY asked_at DESC, request_id DESC LIMIT %(limit)s",
                    params,
                )
            ).fetchall()
            replies = await _replies_of(uow, [r["request_id"] for r in rows])
        assert total is not None
        return (
            [
                FollowingUpItem(
                    request_id=r["request_id"],
                    kind=r["kind"],
                    about=r["about"],
                    note=r["note"],
                    asked_at=r["asked_at"],
                    status=r["status"],
                    latest_reply=(replies.get(r["request_id"]) or [None])[-1],
                )
                for r in rows
            ],
            total["n"],
        )
