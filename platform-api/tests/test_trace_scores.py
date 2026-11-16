import asyncio
import base64
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from platform_api.monitoring import (
    LangfuseScores,
    TraceFlag,
    TraceIds,
    pseudonym,
    typed_again,
)
from platform_api.shared import UserId

pytestmark = pytest.mark.anyio

AT = datetime(2026, 11, 16, 2, 40, 0, 123000, tzinfo=UTC)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
LANGFUSE = "http://langfuse-web:3000"


IDS = TraceIds(b"trace-key-not-real")
ALICE = UserId("alice")
TRACE = IDS.new(ALICE, AT)


def test_a_new_trace_id_is_a_version_7_uuid_made_now_for_its_person():
    made = IDS.new(ALICE)
    assert re.fullmatch(r"[0-9a-f]{32}", made)
    assert UUID(hex=made).version == 7
    assert typed_again(made, datetime.now(UTC), IDS, ALICE) is not None


def test_two_ids_made_for_one_person_in_one_millisecond_differ():
    assert len({IDS.new(ALICE, AT) for _ in range(20)}) > 1


@pytest.mark.parametrize(
    ("later", "flagged"),
    [
        pytest.param(timedelta(0), True, id="at once"),
        pytest.param(timedelta(seconds=59), True, id="59 s"),
        pytest.param(timedelta(seconds=60), True, id="60 s"),
        pytest.param(timedelta(seconds=61), False, id="61 s"),
        pytest.param(timedelta(minutes=30), False, id="30 min"),
        pytest.param(timedelta(seconds=-1), False, id="before the trace was made"),
    ],
)
def test_typing_again_within_60_seconds_flags_the_earlier_trace(later: timedelta, flagged: bool):
    flag = typed_again(TRACE, AT + later, IDS, ALICE)
    expected = TraceFlag(trace_id=TRACE, name="flag_typed_again", at=AT) if flagged else None
    assert flag == expected


@pytest.mark.parametrize(
    "trace_id",
    [
        pytest.param(uuid4().hex, id="version 4"),
        pytest.param(TRACE.upper(), id="upper case"),
        pytest.param(TRACE[:-1], id="too short"),
        pytest.param(f"{{{TRACE}}}", id="braces"),
        pytest.param("not-a-trace", id="not hex"),
        pytest.param("", id="empty"),
        pytest.param(IDS.new(UserId("bob"), AT), id="made for someone else"),
        pytest.param(TraceIds(b"another-key").new(ALICE, AT), id="made with another key"),
        pytest.param(UUID(int=UUID(hex=TRACE).int ^ 1).hex, id="one bit of the signature changed"),
        pytest.param(UUID(int=UUID(hex=TRACE).int + (1 << 80)).hex, id="a millisecond later"),
    ],
)
def test_an_id_the_platform_did_not_make_for_this_person_flags_nothing(trace_id: str):
    assert typed_again(trace_id, AT + timedelta(seconds=1), IDS, ALICE) is None


def test_the_flags_score_id_is_the_trace_and_the_flag_so_a_resend_updates_it():
    flag = typed_again(TRACE, AT + timedelta(seconds=5), IDS, ALICE)
    assert flag is not None and flag.score_id == f"{TRACE}-flag_typed_again"
    assert typed_again(TRACE, AT + timedelta(seconds=40), IDS, ALICE) == flag


def test_the_pseudonym_is_an_hmac_sha256_of_the_person_id_and_never_the_id():
    key = "pseudonym-key-not-real"
    alice = pseudonym(key, UserId("alice"))
    # openssl dgst -sha256 -hmac pseudonym-key-not-real, on "alice"
    assert alice == "3a987e918f1161a4739d15ecc805273ab9d3932b0689a2ca48b36081526bb828"
    assert pseudonym(key, UserId("alice")) == alice
    assert pseudonym(key, UserId("bob")) != alice
    assert pseudonym("another-key", UserId("alice")) != alice


class Langfuse:
    """Langfuse's score route. It answers each request with `status`, or raises `error`."""

    def __init__(self, status: int = 202, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.seen: list[httpx.Request] = []
        self.release = asyncio.Event()
        self.release.set()

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status, json={"message": "Accepted"})

    def scores(self, environment: str | None = "dev") -> LangfuseScores:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        return LangfuseScores(LANGFUSE, "pk-lf-not-real", "sk-lf-not-real", environment, client)


async def test_a_flag_is_posted_as_one_boolean_score_with_the_project_keys():
    langfuse = Langfuse()
    scores = langfuse.scores()
    scores.send(TraceFlag(trace_id=TRACE, name="flag_typed_again", at=AT))
    await scores.close()
    (request,) = langfuse.seen
    assert (request.method, str(request.url)) == ("POST", f"{LANGFUSE}/api/public/scores")
    keys = base64.b64encode(b"pk-lf-not-real:sk-lf-not-real").decode()
    assert request.headers["Authorization"] == f"Basic {keys}"
    assert json.loads(request.content) == [
        {
            "id": f"{TRACE}-flag_typed_again",
            "traceId": TRACE,
            "name": "flag_typed_again",
            "value": 1,
            "dataType": "BOOLEAN",
            "timestamp": "2026-11-16T02:40:00.123+00:00",
            "environment": "dev",
        }
    ]


async def test_without_an_environment_langfuse_picks_its_own():
    langfuse = Langfuse()
    scores = langfuse.scores(environment=None)
    scores.send(TraceFlag(trace_id=TRACE, name="flag_typed_again", at=AT))
    await scores.close()
    (request,) = langfuse.seen
    assert "environment" not in json.loads(request.content)[0]


async def test_sending_returns_before_langfuse_answers():
    langfuse = Langfuse()
    langfuse.release.clear()
    scores = langfuse.scores()
    scores.send(TraceFlag(trace_id=TRACE, name="flag_typed_again", at=AT))
    await asyncio.sleep(0)
    assert len(langfuse.seen) == 1, "the write has started"
    langfuse.release.set()
    await scores.close()


@pytest.mark.parametrize(
    ("langfuse", "logged"),
    [
        pytest.param(Langfuse(status=500), "500", id="server error"),
        pytest.param(Langfuse(status=401), "401", id="wrong keys"),
        pytest.param(Langfuse(status=207), "rejected", id="score rejected"),
        pytest.param(Langfuse(error=httpx.ConnectError("refused")), "ConnectError", id="down"),
        pytest.param(Langfuse(error=httpx.ReadTimeout("slow")), "ReadTimeout", id="too slow"),
    ],
)
async def test_a_write_that_fails_is_logged_by_its_kind_and_raises_nothing(
    langfuse: Langfuse, logged: str, caplog: pytest.LogCaptureFixture
):
    scores = langfuse.scores()
    with caplog.at_level(logging.WARNING):
        scores.send(TraceFlag(trace_id=TRACE, name="flag_typed_again", at=AT))
        await scores.close()
    assert len(langfuse.seen) == 1
    assert logged in caplog.text


async def test_a_write_that_fails_in_an_unexpected_way_still_lets_the_platform_shut_down():
    langfuse = Langfuse(error=RuntimeError("not an HTTP error"))
    scores = langfuse.scores()
    scores.send(TraceFlag(trace_id=TRACE, name="flag_typed_again", at=AT))
    await scores.close()
    assert len(langfuse.seen) == 1
