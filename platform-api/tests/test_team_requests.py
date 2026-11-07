import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest

from platform_api.app import create_app
from platform_api.builder import Builder, TeamRequests, Watchlist
from platform_api.builder.team_requests import DONE_STAYS_LISTED, POSTING_GIVES_UP_AFTER
from platform_api.db import Database
from platform_api.monitoring import ActivityLog
from platform_api.orchestration import (
    RequestNotice,
    ScheduleBook,
    TeamsPost,
    TeamsRequestChannel,
)
from platform_api.orchestration.team_request_card import request_card
from platform_api.shared import ExternalIdentity, Principal, Role, RunId, UserId
from tests.conftest import PostgresUrls
from tests.declared import declared_status
from tests.support import LOCAL_ENV
from tests.test_builder_http import NothingLearned, SecondCallRepeats

pytestmark = pytest.mark.anyio

ALICE = {"X-Dev-User": "alice"}
BOB = {"X-Dev-User": "bob"}
CAROL = {"X-Dev-User": "carol"}
STRANGER = {"X-Dev-User": "nobody"}
KEY = {"Idempotency-Key": "z"}
ASK = {
    "kind": "ask_the_team",
    "about": {"capability": "email.send"},
    "note": "We'd like the list by email.",
}
SUPPORT = {"kind": "support", "about": {"run_id": "run_1"}, "note": "It stopped again."}


@dataclass
class RecordingChannel:
    result: TeamsPost = "posted"
    sent: list[RequestNotice] = field(default_factory=list)

    async def post(self, notice: RequestNotice) -> TeamsPost:
        self.sent.append(notice)
        return self.result


class SomeRuns:
    async def get_run(self, run_id: Any) -> object | None:
        return object() if run_id == "run_1" else None


@dataclass
class Lab:
    client: httpx.AsyncClient
    app: Any
    channel: RecordingChannel
    db: Database
    log: ActivityLog

    async def events(self) -> list[Any]:
        return await self.log.read_after(RunId("run_1"), 0)

    async def send(
        self, body: dict[str, Any], who: dict[str, str] = ALICE, key: str = "k1"
    ) -> httpx.Response:
        response = await self.client.post(
            "/api/v1/team-requests", json=body, headers={**who, "Idempotency-Key": key}
        )
        declared_status(self.app, "POST", "/api/v1/team-requests", response)
        return response


@pytest.fixture
async def lab(db: Database) -> AsyncIterator[Lab]:
    app = create_app(LOCAL_ENV)
    watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db))
    app.state.builder = Builder(db, SecondCallRepeats(), watchlist, "http://localhost:8000")
    app.state.watchlist = watchlist
    channel = RecordingChannel()
    log = ActivityLog(db)
    app.state.team_requests = TeamRequests(db, channel, SomeRuns(), log, "http://localhost:8080")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Lab(client, app, channel, db, log)


async def test_an_operator_asks_the_team_and_the_request_is_kept_and_listed(lab: Lab):
    response = await lab.send(ASK)

    assert response.status_code == 201, response.text
    made = response.json()
    assert made["request_id"].startswith("trq_")
    assert made | {"request_id": "x", "asked_at": "t"} == {
        "request_id": "x",
        "kind": "ask_the_team",
        "about": {"capability": "email.send"},
        "note": "We'd like the list by email.",
        "asked_by": "alice",
        "asked_by_name": "Alice",
        "asked_at": "t",
        "status": "open",
        "replies": [],
        "posted_to_teams": True,
        "not_posted_because": None,
    }
    listed = (await lab.client.get("/api/v1/team-requests", headers=BOB)).json()
    assert listed["total"] == 1
    assert [r["request_id"] for r in listed["requests"]] == [made["request_id"]]


async def test_a_report_to_support_names_the_run(lab: Lab):
    response = await lab.send(SUPPORT)

    assert response.status_code == 201, response.text
    assert response.json()["about"] == {"run_id": "run_1"}


async def test_a_report_to_support_marks_the_run_once_and_holds_no_note(lab: Lab):
    first = await lab.send({**SUPPORT, "note": "my password is hunter2"}, key="p1")
    again = await lab.send({**SUPPORT, "note": "my password is hunter2"}, key="p1")
    ask = await lab.send(ASK, key="p2")

    assert (first.status_code, again.status_code, ask.status_code) == (201, 200, 201)
    [event] = await lab.events()
    assert event.kind == "support_reported"
    assert event.actor.id == "alice"
    assert event.summary == "Alice reported a problem with this run to the team."
    assert event.data.request_id == first.json()["request_id"]
    assert "hunter2" not in event.model_dump_json()


class StopsOnce:
    def __init__(self, log: ActivityLog) -> None:
        self.log = log
        self.stop = True

    async def note_support_report(
        self, run_id: RunId, request_id: str, reported_by: UserId, display: str
    ) -> None:
        if self.stop:
            self.stop = False
            raise RuntimeError("stopped before the event was written")
        await self.log.note_support_report(run_id, request_id, reported_by, display)


async def test_a_repeat_writes_the_event_a_stop_before_it_left_out(lab: Lab):
    lab.app.state.team_requests = TeamRequests(
        lab.db, lab.channel, SomeRuns(), StopsOnce(lab.log), "http://localhost:8080"
    )
    with pytest.raises(RuntimeError):
        await lab.send(SUPPORT)
    assert await lab.events() == []

    again = await lab.send(SUPPORT)

    assert again.status_code == 200
    assert [e.kind for e in await lab.events()] == ["support_reported"]
    await lab.send(SUPPORT)
    assert [e.kind for e in await lab.events()] == ["support_reported"]


async def test_a_report_about_a_run_that_does_not_exist_is_refused_and_nothing_is_kept(lab: Lab):
    response = await lab.send({**SUPPORT, "about": {"run_id": "run_nope"}})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "about", "run_id"]
    assert (await lab.client.get("/api/v1/team-requests", headers=ALICE)).json()["total"] == 0
    assert lab.channel.sent == []


@pytest.mark.parametrize(
    "body",
    [
        {**ASK, "about": {"run_id": "run_1"}},
        {**ASK, "about": {}},
        {**ASK, "about": {"capability": "email.send", "run_id": "run_1"}},
        {**SUPPORT, "about": {"capability": "email.send"}},
        {**ASK, "note": "   "},
        {**ASK, "note": "x" * 1001},
        {**ASK, "kind": "ticket"},
    ],
)
async def test_a_request_that_does_not_fit_its_kind_or_length_is_a_422(
    lab: Lab, body: dict[str, Any]
):
    assert (await lab.send(body)).status_code == 422
    assert (await lab.client.get("/api/v1/team-requests", headers=ALICE)).json()["total"] == 0


async def test_the_same_idempotency_key_gives_one_request_and_one_card(lab: Lab):
    first = await lab.send(ASK, key="press-1")
    again = await lab.send(ASK, key="press-1")
    other = await lab.send(ASK, key="press-2")

    assert (first.status_code, again.status_code, other.status_code) == (201, 200, 201)
    assert first.json() == again.json()
    assert other.json()["request_id"] != first.json()["request_id"]
    assert (await lab.client.get("/api/v1/team-requests", headers=ALICE)).json()["total"] == 2
    assert len(lab.channel.sent) == 2


async def test_two_people_may_use_the_same_key_for_their_own_requests(lab: Lab):
    a = await lab.send(ASK, ALICE, key="same")
    b = await lab.send(ASK, BOB, key="same")

    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json()["request_id"] != b.json()["request_id"]


async def test_a_request_needs_an_idempotency_key(lab: Lab):
    response = await lab.client.post("/api/v1/team-requests", json=ASK, headers=ALICE)

    assert response.status_code == 422


async def test_an_approver_who_is_not_an_operator_can_ask_list_and_reply(lab: Lab):
    made = (await lab.send(ASK, BOB)).json()

    replied = await lab.client.post(
        f"/api/v1/team-requests/{made['request_id']}/replies",
        json={"text": "Email is not on the plan."},
        headers=BOB,
    )

    assert replied.status_code == 201, replied.text
    assert (await lab.client.get("/api/v1/team-requests", headers=BOB)).status_code == 200


async def test_the_card_names_the_person_and_holds_no_note(lab: Lab):
    made = (await lab.send({**ASK, "note": "my password is hunter2"}, CAROL)).json()
    request_id = made["request_id"]

    [notice] = lab.channel.sent
    assert (notice.kind, notice.asked_by_name) == ("ask_the_team", "Carol")
    assert notice.open_url == f"http://localhost:8080/workflows?request={request_id}"
    assert "hunter2" not in json.dumps(request_card(notice).as_json())


@pytest.mark.parametrize("post", ["no_channel", "failed"])
async def test_when_nothing_is_posted_the_request_is_still_kept_and_the_answer_says_so(
    lab: Lab, post: TeamsPost
):
    lab.channel.result = post

    response = await lab.send(ASK)

    assert response.status_code == 201
    assert (response.json()["posted_to_teams"], response.json()["not_posted_because"]) == (
        False,
        post,
    )
    [kept] = (await lab.client.get("/api/v1/team-requests", headers=BOB)).json()["requests"]
    assert (kept["posted_to_teams"], kept["not_posted_because"]) == (False, post)
    again = await lab.send(ASK)
    assert again.status_code == 200
    assert again.json()["not_posted_because"] == post


async def test_nobody_signed_out_or_unknown_can_send_list_or_reply(lab: Lab):
    made = (await lab.send(ASK)).json()
    url = f"/api/v1/team-requests/{made['request_id']}/replies"

    for headers in ({}, STRANGER):
        assert (await lab.client.get("/api/v1/team-requests", headers=headers)).status_code == 401
        sent = await lab.client.post("/api/v1/team-requests", json=ASK, headers=headers)
        assert sent.status_code == 401
        replied = await lab.client.post(url, json={"text": "ok"}, headers=headers)
        assert replied.status_code == 401
    assert len(lab.channel.sent) == 1


async def test_someone_signed_in_but_not_on_the_people_list_is_refused_everywhere(lab: Lab):
    made = (await lab.send(ASK)).json()

    async def stranger(request: object) -> ExternalIdentity:
        return ExternalIdentity(subject="oid-zed", user_name="zed@example.test", name="Zed")

    lab.app.state.authenticator = stranger
    url = f"/api/v1/team-requests/{made['request_id']}/replies"

    assert (await lab.client.get("/api/v1/team-requests")).status_code == 403
    assert (
        await lab.client.post("/api/v1/team-requests", json=ASK, headers=KEY)
    ).status_code == 403
    assert (await lab.client.post(url, json={"text": "ok"})).status_code == 403
    assert len(lab.channel.sent) == 1


async def test_a_reply_is_logged_with_who_wrote_it_and_sets_the_status(lab: Lab):
    made = (await lab.send(ASK)).json()
    url = f"/api/v1/team-requests/{made['request_id']}/replies"

    answered = (await lab.client.post(url, json={"text": "Looking at it."}, headers=BOB)).json()
    done = (
        await lab.client.post(
            url, json={"text": "Won't be done: not on the plan.", "status": "done"}, headers=CAROL
        )
    ).json()

    assert answered["status"] == "answered"
    assert done["status"] == "done"
    assert [(r["replied_by"], r["replied_by_name"], r["status"]) for r in done["replies"]] == [
        ("bob", "Bob", "answered"),
        ("carol", "Carol", "done"),
    ]
    missing = await lab.client.post(
        "/api/v1/team-requests/trq_nope/replies", json={"text": "hi"}, headers=BOB
    )
    assert missing.status_code == 404
    empty = await lab.client.post(url, json={"text": " "}, headers=BOB)
    assert empty.status_code == 422


async def test_a_done_request_leaves_the_list_after_30_days_but_stays_in_the_record(lab: Lab):
    made = (await lab.send(ASK)).json()
    await lab.client.post(
        f"/api/v1/team-requests/{made['request_id']}/replies",
        json={"text": "Done.", "status": "done"},
        headers=BOB,
    )
    assert (await lab.client.get("/api/v1/team-requests", headers=ALICE)).json()["total"] == 1

    old = lab.db.clock() - DONE_STAYS_LISTED - timedelta(days=1)
    async with lab.db.transaction("builder") as uow:
        await uow.conn.execute("UPDATE builder.team_requests SET done_at = %s", (old,))

    assert (await lab.client.get("/api/v1/team-requests", headers=ALICE)).json() == {
        "requests": [],
        "total": 0,
    }
    async with lab.db.transaction("builder") as uow:
        row = await (
            await uow.conn.execute("SELECT count(*) AS n FROM builder.team_requests")
        ).fetchone()
    assert row == {"n": 1}


async def test_the_builder_can_change_only_the_columns_the_service_changes(lab: Lab):
    await lab.send(ASK)
    async with lab.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.team_requests SET status = 'answered', teams_post = 'posted'"
        )
    for statement in (
        "UPDATE builder.team_requests SET note = 'changed'",
        "UPDATE builder.team_requests SET asked_by = 'bob'",
        "UPDATE builder.team_requests SET kind = 'support'",
    ):
        async with lab.db.transaction("builder") as uow:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await uow.conn.execute(statement)  # pyright: ignore[reportArgumentType]


async def unseen_by_alice(lab: Lab) -> list[str]:
    alice = Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice")
    return [i.request_id for i in await lab.app.state.team_requests.replied(alice)]


async def test_anyone_on_the_team_can_read_one_request_and_an_unknown_one_is_a_404(lab: Lab):
    made = (await lab.send(ASK)).json()
    url = f"/api/v1/team-requests/{made['request_id']}"
    await lab.client.post(url + "/replies", json={"text": "On it."}, headers=BOB)

    for who in (ALICE, BOB, CAROL):
        got = await lab.client.get(url, headers=who)
        declared_status(lab.app, "GET", "/api/v1/team-requests/{request_id}", got)
        assert got.status_code == 200
        assert [r["text"] for r in got.json()["replies"]] == ["On it."]
    assert (await lab.client.get("/api/v1/team-requests/trq_nope", headers=BOB)).status_code == 404
    assert (await lab.client.get(url)).status_code == 401
    assert (await lab.client.get(url, headers=STRANGER)).status_code == 401


async def test_only_the_asker_marks_replies_as_read_and_a_mark_never_moves_back(lab: Lab):
    made = (await lab.send(ASK)).json()
    request_id = made["request_id"]
    url = f"/api/v1/team-requests/{request_id}/seen"
    first = (
        await lab.client.post(
            f"/api/v1/team-requests/{request_id}/replies", json={"text": "One."}, headers=BOB
        )
    ).json()["replies"][0]["replied_at"]
    second = (
        await lab.client.post(
            f"/api/v1/team-requests/{request_id}/replies", json={"text": "Two."}, headers=BOB
        )
    ).json()["replies"][1]["replied_at"]

    async def unseen() -> list[str]:
        return await unseen_by_alice(lab)

    assert await unseen() == [request_id]
    refused = await lab.client.post(url, json={"through": second}, headers=BOB)
    declared_status(lab.app, "POST", "/api/v1/team-requests/{request_id}/seen", refused)
    assert refused.status_code == 403
    assert (await lab.client.post(url, json={"through": second})).status_code == 401
    assert await unseen() == [request_id]
    missing = await lab.client.post(
        "/api/v1/team-requests/trq_nope/seen", json={"through": second}, headers=ALICE
    )
    assert missing.status_code == 404

    only_first = await lab.client.post(url, json={"through": first}, headers=ALICE)
    assert only_first.status_code == 200
    assert await unseen() == [request_id]
    read = await lab.client.post(url, json={"through": second}, headers=ALICE)
    assert read.status_code == 200
    assert await unseen() == []
    await lab.client.post(url, json={"through": first}, headers=ALICE)
    assert await unseen() == []

    await lab.client.post(
        f"/api/v1/team-requests/{request_id}/replies", json={"text": "Three."}, headers=CAROL
    )
    assert await unseen() == [request_id]


async def test_a_reply_by_the_asker_or_a_mark_ahead_of_the_clock_is_not_new(lab: Lab):
    made = (await lab.send(ASK)).json()
    request_id = made["request_id"]
    url = f"/api/v1/team-requests/{request_id}"
    await lab.client.post(url + "/replies", json={"text": "I added more."}, headers=ALICE)
    assert await unseen_by_alice(lab) == []

    await lab.client.post(url + "/replies", json={"text": "Seen."}, headers=BOB)
    future = (lab.db.clock() + timedelta(days=1)).isoformat()
    await lab.client.post(url + "/seen", json={"through": future}, headers=ALICE)
    async with lab.db.transaction("builder") as uow:
        row = await (
            await uow.conn.execute(
                "SELECT asker_seen_at <= %s AS ok FROM builder.team_requests", (lab.db.clock(),)
            )
        ).fetchone()
    assert row == {"ok": True}


class SlowChannel:
    def __init__(self) -> None:
        self.sent = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def post(self, notice: RequestNotice) -> TeamsPost:
        self.sent += 1
        self.started.set()
        await self.release.wait()
        return "posted"


async def test_a_second_press_while_the_card_is_going_out_says_it_is_being_posted(lab: Lab):
    slow = SlowChannel()
    lab.app.state.team_requests = TeamRequests(
        lab.db, slow, SomeRuns(), lab.log, "http://localhost:8080"
    )
    first = asyncio.create_task(lab.send(ASK, key="race"))
    await slow.started.wait()

    second = await lab.send(ASK, key="race")
    listed = (await lab.client.get("/api/v1/team-requests", headers=ALICE)).json()["requests"]

    assert second.status_code == 200
    assert (second.json()["posted_to_teams"], second.json()["not_posted_because"]) == (
        False,
        "posting",
    )
    assert listed[0]["not_posted_because"] == "posting"
    slow.release.set()
    done = await first
    assert (done.status_code, done.json()["posted_to_teams"]) == (201, True)
    assert slow.sent == 1
    after = await lab.send(ASK, key="race")
    assert (after.json()["posted_to_teams"], slow.sent) == (True, 1)


async def test_a_request_whose_post_was_lost_to_a_crash_is_posted_by_the_next_press(lab: Lab):
    slow = SlowChannel()
    slow.release.set()
    lab.app.state.team_requests = TeamRequests(
        lab.db, slow, SomeRuns(), lab.log, "http://localhost:8080"
    )
    made = (await lab.send(ASK, key="crash")).json()
    async with lab.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.team_requests SET teams_post = 'posting', posting_at = %s",
            (uow.now - POSTING_GIVES_UP_AFTER - timedelta(seconds=1),),
        )

    again = await lab.send(ASK, key="crash")

    assert again.status_code == 200
    assert again.json()["request_id"] == made["request_id"]
    assert (again.json()["posted_to_teams"], slow.sent) == (True, 2)


async def test_requests_and_replies_can_not_be_deleted_by_the_builder(lab: Lab):
    made = (await lab.send(ASK)).json()
    await lab.client.post(
        f"/api/v1/team-requests/{made['request_id']}/replies",
        json={"text": "ok"},
        headers=BOB,
    )
    for table in ("team_requests", "team_request_replies"):
        async with lab.db.transaction("builder") as uow:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await uow.conn.execute(f"DELETE FROM builder.{table}")


async def test_the_list_is_the_newest_first(lab: Lab):
    first = (await lab.send(ASK, key="a")).json()
    second = (await lab.send(SUPPORT, key="b")).json()

    listed = (await lab.client.get("/api/v1/team-requests", headers=ALICE)).json()["requests"]

    assert [r["request_id"] for r in listed] == [second["request_id"], first["request_id"]]


def teams_channel(
    answer: httpx.Response | Exception,
) -> tuple[TeamsRequestChannel, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return TeamsRequestChannel("https://teams.example.test/hook?sig=secret", client), seen


NOTICE = RequestNotice("support", "Alice **bold**", "http://localhost:8080/workflows?request=trq_1")


async def test_the_channel_posts_one_card_with_one_button_and_no_note():
    channel, seen = teams_channel(httpx.Response(202))

    assert await channel.post(NOTICE) == "posted"

    [request] = seen
    card = json.loads(request.content)["attachments"][0]["content"]
    assert [a["title"] for a in card["actions"]] == ["Open in AI Workflow Builder"]
    assert card["actions"][0]["url"] == NOTICE.open_url
    assert "Platform problem reported" in json.dumps(card)


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(500), httpx.ConnectError("https://teams.example.test/hook?sig=secret")],
)
async def test_a_channel_that_fails_says_failed_and_never_logs_its_address(
    answer: httpx.Response | Exception, caplog: pytest.LogCaptureFixture
):
    channel, _ = teams_channel(answer)

    assert await channel.post(NOTICE) == "failed"
    assert "secret" not in caplog.text


async def test_a_channel_with_no_address_posts_nothing_and_says_so():
    assert await TeamsRequestChannel(None).post(NOTICE) == "no_channel"


async def test_the_card_never_makes_a_link_of_a_name():
    card = request_card(RequestNotice("ask_the_team", "see https://evil.example now", "http://x/y"))

    assert "https://evil" not in json.dumps(card.as_json())


def test_the_builder_context_only_reaches_the_table_it_owns(postgres: PostgresUrls):
    with (
        psycopg.connect(postgres.contexts.orchestration) as other,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        other.execute("SELECT count(*) FROM builder.team_requests")
