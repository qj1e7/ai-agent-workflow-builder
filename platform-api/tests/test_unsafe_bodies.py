"""A body the API can't read safely answers 422, never 500 (#60).

A lone surrogate escape can't be written back out as UTF-8, and a very deep body overflows
the stack of any code that walks it. Neither may reach a route, and the 422 never echoes them.
"""

import re
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from platform_api.app import create_app
from platform_api.auth import ConfigError
from platform_api.body_guard import (
    NO_BODY,
    TOO_LARGE_MESSAGE,
    RefuseDeepJson,
    as_json_reads_it,
    nests_deeper_than,
)
from platform_api.builder import Builder, Watchlist
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.db import Database
from platform_api.orchestration import ScheduleBook
from platform_api.settings import settings_from_env
from platform_api.wire import BROKEN_TEXT_MESSAGE
from tests.declared import ALICE, STEP_KEY, app_with
from tests.support import LOCAL_ENV
from tests.test_builder_http import NothingLearned, SecondCallRepeats

pytestmark = pytest.mark.anyio

SURROGATE = b'{"name":"a\\ud800b"}'
DEEP = b'{"name":' + b"[" * 3000 + b"]" * 3000 + b"}"
UNREADABLE = "Input should be a valid string, unable to parse raw data as a unicode string"
HEADERS = {
    **ALICE,
    **STEP_KEY,
    "Content-Type": "application/json",
    "X-Callback-Token": "t",
    "Authorization": "Bearer t",
    "Idempotency-Key": "k",
    "X-N8N-Execution": "41",
}


def json_body_routes() -> list[tuple[str, str]]:
    schema = create_app(LOCAL_ENV).openapi()
    return [
        (method.upper(), re.sub(r"\{[^}]+\}", "x", path))
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if "application/json" in operation.get("requestBody", {}).get("content", {})
    ]


ROUTES = json_body_routes()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = app_with()
    app.state.model_settings = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def saving(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose builder saves to a real database, so text that passes validation is
    written to PostgreSQL."""
    watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db))
    app = app_with(builder=Builder(db, SecondCallRepeats(), watchlist, "http://localhost:8000"))
    app.state.watchlist = watchlist
    app.state.model_settings = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_the_served_api_has_json_body_routes_to_check():
    assert ("POST", "/api/v1/agent-cards") in ROUTES
    assert ("PUT", "/api/v1/drafts/x") in ROUTES


def test_no_route_the_guard_lets_pass_unread_takes_a_body():
    schema = create_app(LOCAL_ENV).openapi()
    with_body = {
        (method.upper(), path)
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if "requestBody" in operation
    }
    assert {(m, p) for m, p in with_body if m in NO_BODY} == set()


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_a_lone_surrogate_answers_422_without_echoing_it(
    client: httpx.AsyncClient, method: str, path: str
):
    response = await client.request(method, path, content=SURROGATE, headers=HEADERS)
    assert response.status_code == 422, response.text
    problems: list[dict[str, Any]] = response.json()["detail"]
    assert problems
    assert all({"type", "loc", "msg"} <= set(p) for p in problems), problems
    assert "\ud800" not in response.content.decode("utf-8", "surrogatepass")


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_a_very_deep_body_answers_422_before_any_route_reads_it(
    client: httpx.AsyncClient, method: str, path: str
):
    response = await client.request(method, path, content=DEEP, headers=HEADERS)
    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert (problem["type"], problem["loc"]) == ("json_too_deep", ["body"])


def too_deep(response: httpx.Response) -> None:
    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert (problem["type"], problem["loc"]) == ("json_too_deep", ["body"])


@pytest.mark.parametrize(
    "content_type", [None, "", "text/plain", "application/x-www-form-urlencoded"]
)
async def test_a_very_deep_body_is_refused_whatever_type_it_names(
    client: httpx.AsyncClient, content_type: str | None
):
    headers = {k: v for k, v in HEADERS.items() if k != "Content-Type"}
    if content_type is not None:
        headers["Content-Type"] = content_type
    too_deep(await client.put("/api/v1/drafts/x", content=DEEP, headers=headers))


# U+2200 holds one 0x22 byte in UTF-16 and UTF-32. A scanner that reads the raw bytes takes it
# for a quote, so it thinks the brackets that follow are inside a string.
CRAFTED = '{"step":1,"content":{"a":"\u2200","b":' + "[" * 3000 + "]" * 3000 + "}}"


@pytest.mark.parametrize(
    "body",
    [
        DEEP.decode().encode("utf-16"),
        DEEP.decode().encode("utf-32"),
        CRAFTED.encode("utf-16-le"),
        CRAFTED.encode("utf-16-be"),
        CRAFTED.encode("utf-32-le"),
    ],
    ids=["utf-16", "utf-32", "crafted-utf-16-le", "crafted-utf-16-be", "crafted-utf-32-le"],
)
async def test_a_very_deep_body_in_another_unicode_encoding_is_refused(
    client: httpx.AsyncClient, body: bytes
):
    too_deep(await client.put("/api/v1/drafts/x", content=body, headers=HEADERS))


@pytest.mark.parametrize(
    "body",
    [
        b'{"name":"never ends' + b"[" * 3000,
        b'{"name":"a\\' + b"\n" + b"[" * 3000 + b'"}',
        b'{"name":"a"' + b'"' + b"[" * 3000,
    ],
    ids=["unterminated", "escaped-newline", "stray-quote"],
)
async def test_deep_brackets_after_a_string_the_scanner_cannot_close_are_refused(
    client: httpx.AsyncClient, body: bytes
):
    too_deep(await client.put("/api/v1/drafts/x", content=body, headers=HEADERS))


async def test_a_body_that_is_not_unicode_text_is_refused(client: httpx.AsyncClient):
    response = await client.put(
        "/api/v1/drafts/x", content=b'{"name":"\xff\xfe' + b"[" * 3000, headers=HEADERS
    )
    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert (problem["type"], problem["loc"]) == ("json_invalid", ["body"])


async def test_an_ordinary_utf_16_body_still_reaches_validation(client: httpx.AsyncClient):
    body = '{"task":' + "[" * 30 + "]" * 30 + "}"
    response = await client.post(
        "/api/v1/builder/plan", content=body.encode("utf-16"), headers=HEADERS
    )
    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert (problem["type"], problem["loc"]) == ("string_type", ["body", "task"])


async def test_a_lone_surrogate_in_a_key_refuses_the_whole_body(client: httpx.AsyncClient):
    body = b'{"task":"Check","a\\udfffb":1}'
    response = await client.post("/api/v1/builder/plan", content=body, headers=HEADERS)
    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": [
            {
                "type": "string_unicode",
                "loc": ["body"],
                "msg": UNREADABLE,
            }
        ]
    }


async def test_an_ordinary_invalid_body_keeps_its_422_shape(client: httpx.AsyncClient):
    response = await client.post("/api/v1/builder/plan", json={"task": 7}, headers=ALICE)
    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": [
            {
                "type": "string_type",
                "loc": ["body", "task"],
                "msg": "Input should be a valid string",
                "input": 7,
            }
        ]
    }


async def test_a_body_nested_a_normal_amount_still_reaches_validation(
    client: httpx.AsyncClient,
):
    body = b'{"task":' + b"[" * 30 + b"]" * 30 + b"}"
    response = await client.post("/api/v1/builder/plan", content=body, headers=HEADERS)
    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert (problem["type"], problem["loc"]) == ("string_type", ["body", "task"])


@pytest.mark.parametrize(
    ("body", "deep"),
    [
        (b"[" * 65 + b"]" * 65, True),
        (b"[" * 64 + b"]" * 64, False),
        (b'{"a":"' + b"[" * 100 + b'"}', False),
        (b'{"a":"\\"' + b"{" * 100 + b'"}', False),
        (b'{"a":"\\\\"' + b"," + b"[" * 65, True),
        (b'{"a":"never ends' + b"[" * 100, True),
        (b'{"a":"never ends' + b"[" * 63, False),
        (b'{"a":"never ends"' + b'"' + b"]" * 100 + b"[" * 65, True),
    ],
)
def test_only_brackets_outside_strings_count_toward_depth(body: bytes, deep: bool):
    assert nests_deeper_than(body.decode(), 64) is deep


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-32-be"])
def test_the_guard_reads_text_as_json_loads_does(encoding: str):
    assert as_json_reads_it('{"a":"\u2200"}'.encode(encoding)) == '{"a":"\u2200"}'


def test_bytes_that_are_not_unicode_text_read_as_nothing():
    assert as_json_reads_it(b'{"a":"\xff"}') is None


USE_CASE = (
    b'{"name":"Watch\\ud800","instruction":"Check LangGraph for new releases.","agents":'
    b'[{"card_id":"' + VERSION_CHECKER_ID.encode() + b'","values":'
    b'{"GitHub repository":"langchain-ai/langgraph","Jira project":"MOCK"}}]}'
)


@pytest.mark.parametrize(
    ("method", "path", "body", "refusal"),
    [
        # A checked text field is refused by pydantic itself.
        (
            "POST",
            "/api/v1/agent-use-cases",
            USE_CASE,
            ("string_unicode", ["body", "name"], UNREADABLE),
        ),
        # Free-form JSON is refused by WireIn, as a NUL byte is.
        (
            "PUT",
            "/api/v1/drafts/d1",
            b'{"step":1,"content":{"steps":[{"say":"x\\udc00"}]}}',
            ("broken_character", ["body", "content"], BROKEN_TEXT_MESSAGE),
        ),
    ],
)
async def test_a_lone_surrogate_in_a_valid_body_is_refused_before_it_is_saved(
    saving: httpx.AsyncClient, method: str, path: str, body: bytes, refusal: tuple[Any, ...]
):
    response = await saving.request(method, path, content=body, headers=HEADERS)
    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert (problem["type"], problem["loc"], problem["msg"]) == refusal
    assert "input" not in problem
    assert (await saving.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"] == []


async def test_an_emoji_sent_as_a_surrogate_pair_still_saves(saving: httpx.AsyncClient):
    body = USE_CASE.replace(b"Watch\\ud800", b"Watch \\ud83d\\ude00")
    response = await saving.post("/api/v1/agent-use-cases", content=body, headers=HEADERS)
    assert response.status_code == 201, response.text
    [saved] = (await saving.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"]
    assert saved["name"] == "Watch \U0001f600"


# A body over the cap is refused before it is held in memory. The cap is small in these tests.
CAP = 1024


async def capped(
    headers: list[tuple[bytes, bytes]], chunks: Iterator[bytes], method: str = "POST"
) -> tuple[int, int, bool]:
    """Sends chunks to the guard around a stand-in app. Answers the status, how many chunks the
    guard read, and whether the request reached the app."""
    read = 0
    reached = False
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal reached
        reached = True
        while (await receive()).get("more_body", False):
            pass
        await JSONResponse({}, 200)(scope, receive, send)

    async def receive() -> Message:
        nonlocal read
        chunk = next(chunks, None)
        if chunk is None:
            return {"type": "http.disconnect"}
        read += 1
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {"type": "http", "method": method, "path": "/api/v1/use-cases/x/pause"}
    await RefuseDeepJson(app, max_bytes=CAP)({**scope, "headers": headers}, receive, send)
    return sent[0]["status"], read, reached


async def test_a_body_whose_content_length_is_over_the_cap_is_refused_unread():
    status, read, reached = await capped(
        [(b"content-length", str(500 * 1024 * 1024).encode())], iter([b"x" * 512] * 10**6)
    )
    assert (status, read, reached) == (413, 0, False)


async def test_a_body_that_streams_past_the_cap_is_refused_once_it_passes():
    status, read, reached = await capped([], iter([b"x" * 512] * 10**6))
    assert (status, read, reached) == (413, CAP // 512 + 1, False)


@pytest.fixture
async def small_cap() -> AsyncIterator[httpx.AsyncClient]:
    app = app_with(env={"MAX_BODY_BYTES": str(CAP)})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def padded(size: int) -> bytes:
    body = b'{"task":7}'
    return body + b" " * (size - len(body))


async def test_a_body_at_the_cap_still_reaches_validation(small_cap: httpx.AsyncClient):
    response = await small_cap.post("/api/v1/builder/plan", content=padded(CAP), headers=HEADERS)
    assert response.status_code == 422, response.text
    [problem] = response.json()["detail"]
    assert (problem["type"], problem["loc"]) == ("string_type", ["body", "task"])


async def test_a_body_one_byte_over_the_cap_answers_413(small_cap: httpx.AsyncClient):
    response = await small_cap.post(
        "/api/v1/builder/plan", content=padded(CAP + 1), headers=HEADERS
    )
    assert (response.status_code, response.json()) == (413, {"detail": TOO_LARGE_MESSAGE % CAP})


async def test_a_body_over_the_cap_is_refused_before_sign_in(small_cap: httpx.AsyncClient):
    response = await small_cap.post("/api/v1/use-cases/x/pause", content=b"x" * (CAP + 1))
    assert response.status_code == 413


def test_the_cap_is_two_mebibytes_unless_max_body_bytes_says_otherwise():
    assert settings_from_env(LOCAL_ENV).max_body_bytes == 2 * 1024 * 1024
    assert settings_from_env({**LOCAL_ENV, "MAX_BODY_BYTES": "4096"}).max_body_bytes == 4096


@pytest.mark.parametrize("value", ["0", "-1", "lots", "1.5"])
def test_max_body_bytes_must_be_a_whole_number_above_zero(value: str):
    with pytest.raises(ConfigError, match="MAX_BODY_BYTES"):
        settings_from_env({**LOCAL_ENV, "MAX_BODY_BYTES": value})
