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
from platform_api.shared import Principal, RunId, UserId, new_id
from platform_api.wire import WireIn, WireModel

NOTE_LIMIT = 1000
REPLY_LIMIT = 1000
LIST_LIMIT = 200
FOLLOWING_UP_SHOWN = 50
DONE_STAYS_LISTED = timedelta(days=30)
"""A request marked Done leaves the list after this long. It stays in the record."""
POSTING_GIVES_UP_AFTER = timedelta(minutes=2)
"""A request still being posted after this long lost its post to a crash. The next press of the
same button posts it again."""
REQUEST_PAGE = "/workflows"
"""Following up on Workflows (prototype v4) is where a person finds their requests and the
replies. Plan item N9b builds the section and lands on the request the link names."""

type PostState = Literal["posting", "posted", "no_channel", "failed"]


def request_link(public_base_url: str, request_id: str) -> str:
    """The one place that says where a request opens: the card's button and nothing else."""
    return f"{public_base_url.rstrip('/')}{REQUEST_PAGE}?request={request_id}"


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
        "including when the team says it won't be done, and why in the text. A reply by the "
        "person who asked changes the request's status only when this is `done`. Otherwise the "
        "request keeps the status it had.",
    )


class ReplyView(WireModel):
    replied_by: str
    replied_by_name: str
    replied_at: datetime
    text: str
    status: Literal["answered", "done"] = Field(
        description="What the reply asked for. For a reply by the person who asked, `answered` "
        "means a note that left the request's status alone."
    )


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
    not_posted_because: Literal["posting", "no_channel", "failed"] | None = Field(
        description="`posting` while the card is still going out, so the answer is not final. "
        "`no_channel` when no Teams channel is set up. `failed` when Teams refused or did not "
        "answer. Null when it was posted."
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


class SeenIn(WireIn):
    through: datetime = Field(
        description="The time of the newest reply the asker has on screen. A reply that arrived "
        "after it is still new."
    )


@dataclass(frozen=True)
class NoSuchRequest:
    request_id: str


@dataclass(frozen=True)
class NotTheAsker:
    request_id: str


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


class SupportReports(Protocol):
    async def note_support_report(
        self, run_id: RunId, request_id: str, reported_by: UserId, display: str
    ) -> None: ...


def _reply(row: Mapping[str, Any]) -> ReplyView:
    return ReplyView(
        replied_by=row["replied_by"],
        replied_by_name=row["replied_by_name"],
        replied_at=row["replied_at"],
        text=row["text"],
        status=row["status"],
    )


def _view(row: Mapping[str, Any], replies: list[ReplyView]) -> TeamRequestView:
    post: PostState = row["teams_post"]
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


def _following(row: Mapping[str, Any], latest: ReplyView | None) -> FollowingUpItem:
    return FollowingUpItem(
        request_id=row["request_id"],
        kind=row["kind"],
        about=row["about"],
        note=row["note"],
        asked_at=row["asked_at"],
        status=row["status"],
        latest_reply=latest,
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
        self,
        db: Database,
        channel: RequestChannel,
        runs: RunLookup,
        reports: SupportReports,
        public_base_url: str,
    ) -> None:
        self._db = db
        self._channel = channel
        self._runs = runs
        self._reports = reports
        self._public_base_url = public_base_url

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
                    " asked_by_name, asked_at, idempotency_key, teams_post, posting_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'posting', %s)"
                    " ON CONFLICT (asked_by, idempotency_key) DO NOTHING RETURNING *",
                    (
                        new_id("trq"),
                        body.kind,
                        json(about),
                        body.note,
                        asker.user_id,
                        asker.display,
                        uow.now,
                        idempotency_key,
                        uow.now,
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
                again = kept, replies or []
            else:
                again = None
        if again is not None:
            kept, replies = again
            await self._note_report(asker, kept)
            if kept["teams_post"] == "posting" and await self._take_over_stale(kept["request_id"]):
                return Created(await self._post(asker, kept), new=False)
            return Created(_view(kept, replies), new=False)
        assert row is not None
        await self._note_report(asker, row)
        return Created(await self._post(asker, row), new=True)

    async def _note_report(self, asker: Principal, row: Mapping[str, Any]) -> None:
        """Written for a new request and again for a repeat, since the first try may have
        stopped between saving the request and writing this. The event is keyed on the request,
        so the repeat writes nothing the second time."""
        if row["kind"] == "support":
            await self._reports.note_support_report(
                RunId(row["about"]["run_id"]), row["request_id"], asker.user_id, asker.display
            )

    async def _take_over_stale(self, request_id: str) -> bool:
        async with self._db.transaction("builder") as uow:
            taken = await (
                await uow.conn.execute(
                    "UPDATE builder.team_requests SET posting_at = %s WHERE request_id = %s"
                    " AND teams_post = 'posting' AND posting_at <= %s RETURNING request_id",
                    (uow.now, request_id, uow.now - POSTING_GIVES_UP_AFTER),
                )
            ).fetchone()
        return taken is not None

    async def _post(self, asker: Principal, row: Mapping[str, Any]) -> TeamRequestView:
        posted = await self._channel.post(
            RequestNotice(
                kind=row["kind"],
                asked_by_name=asker.display,
                open_url=request_link(self._public_base_url, row["request_id"]),
            )
        )
        async with self._db.transaction("builder") as uow:
            done = await (
                await uow.conn.execute(
                    "UPDATE builder.team_requests SET teams_post = %s"
                    " WHERE request_id = %s AND teams_post = 'posting' RETURNING *",
                    (posted, row["request_id"]),
                )
            ).fetchone()
            if done is None:
                done = await (
                    await uow.conn.execute(
                        "SELECT * FROM builder.team_requests WHERE request_id = %s",
                        (row["request_id"],),
                    )
                ).fetchone()
            assert done is not None
            replies = (await _replies_of(uow, [row["request_id"]])).get(row["request_id"])
        return _view(done, replies or [])

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

    async def get(self, request_id: str) -> TeamRequestView | None:
        async with self._db.transaction("builder") as uow:
            row = await (
                await uow.conn.execute(
                    "SELECT * FROM builder.team_requests WHERE request_id = %s", (request_id,)
                )
            ).fetchone()
            if row is None:
                return None
            replies = await _replies_of(uow, [request_id])
        return _view(row, replies.get(request_id, []))

    async def mark_seen(
        self, asker: Principal, request_id: str, body: SeenIn
    ) -> TeamRequestView | NoSuchRequest | NotTheAsker:
        """The asker has opened the request and read the replies up to `through`. Only the asker
        marks it, and a mark never moves back."""
        async with self._db.transaction("builder") as uow:
            marked = await (
                await uow.conn.execute(
                    "UPDATE builder.team_requests SET asker_seen_at = GREATEST("
                    "COALESCE(asker_seen_at, '-infinity'), LEAST(%(through)s, %(now)s))"
                    " WHERE request_id = %(id)s AND asked_by = %(who)s RETURNING request_id",
                    {
                        "through": body.through,
                        "now": uow.now,
                        "id": request_id,
                        "who": asker.user_id,
                    },
                )
            ).fetchone()
            if marked is None:
                exists = await (
                    await uow.conn.execute(
                        "SELECT 1 FROM builder.team_requests WHERE request_id = %s", (request_id,)
                    )
                ).fetchone()
                return NotTheAsker(request_id) if exists else NoSuchRequest(request_id)
        found = await self.get(request_id)
        assert found is not None
        return found

    async def replied(self, asker: Principal) -> list[FollowingUpItem]:
        """The asker's own requests with a reply from someone else that they have not opened
        since, the newest reply first. Each is a line in Needs you."""
        async with self._db.transaction("builder") as uow:
            rows = await (
                await uow.conn.execute(
                    f"SELECT * FROM builder.team_requests r WHERE r.asked_by = %(who)s"
                    f" AND {_LISTED} AND EXISTS (SELECT 1 FROM builder.team_request_replies p"
                    " WHERE p.request_id = r.request_id AND p.replied_by <> r.asked_by"
                    " AND (r.asker_seen_at IS NULL OR p.replied_at > r.asker_seen_at))"
                    " ORDER BY (SELECT max(p.replied_at) FROM builder.team_request_replies p"
                    " WHERE p.request_id = r.request_id AND p.replied_by <> r.asked_by) DESC,"
                    " r.request_id DESC LIMIT %(limit)s",
                    {
                        "who": asker.user_id,
                        "since": uow.now - DONE_STAYS_LISTED,
                        "limit": LIST_LIMIT,
                    },
                )
            ).fetchall()
            replies = await _replies_of(uow, [r["request_id"] for r in rows])
        pairs: list[tuple[ReplyView, FollowingUpItem]] = []
        for r in rows:
            theirs = [p for p in replies.get(r["request_id"], []) if p.replied_by != r["asked_by"]]
            pairs.append((theirs[-1], _following(r, theirs[-1])))
        pairs.sort(key=lambda pair: (pair[0].replied_at, pair[1].request_id), reverse=True)
        return [item for _, item in pairs]

    async def reply(
        self, replier: Principal, request_id: str, body: ReplyIn
    ) -> TeamRequestView | None:
        async with self._db.transaction("builder") as uow:
            kept = await (
                await uow.conn.execute(
                    "SELECT status, asked_by FROM builder.team_requests"
                    " WHERE request_id = %s FOR UPDATE",
                    (request_id,),
                )
            ).fetchone()
            if kept is None:
                return None
            by_the_asker = kept["asked_by"] == replier.user_id
            status = (
                (body.status if body.status == "done" else kept["status"])
                if by_the_asker
                else body.status
            )
            keeps_done_at = by_the_asker and kept["status"] == "done" and body.status != "done"
            row = await (
                await uow.conn.execute(
                    "UPDATE builder.team_requests SET status = %(status)s,"
                    " done_at = CASE WHEN %(status)s <> 'done' THEN NULL"
                    " WHEN %(keeps)s THEN done_at ELSE %(now)s END"
                    " WHERE request_id = %(id)s RETURNING *",
                    {
                        "status": status,
                        "keeps": keeps_done_at,
                        "now": uow.now,
                        "id": request_id,
                    },
                )
            ).fetchone()
            assert row is not None
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
            [_following(r, (replies.get(r["request_id"]) or [None])[-1]) for r in rows],
            total["n"],
        )
