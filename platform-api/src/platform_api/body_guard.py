"""Keeps a request body the API can't read safely from turning into a 500 (#60).

A body nested far deeper than any real request overflows the stack of the code that walks it,
so it is refused before a route reads it, as is a body that is not Unicode text. A 422 never
echoes text that can't be written back out as UTF-8, such as a lone surrogate escape.
"""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_DEPTH = 64
"""The deepest a body may nest. Real bodies nest fewer than ten levels."""
TOO_DEEP_MESSAGE = f"This body nests more than {MAX_DEPTH} levels deep, which can't be read."
NOT_TEXT_MESSAGE = "This body is not UTF-8, UTF-16 or UTF-32 text, so it can't be read."

# A JSON string, a bracket, or a quote the scan can't close. Strings are skipped whole, so a
# bracket inside one is not counted. Possessive, so each string is scanned once.
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*+"|[\[\]{}]|"')
_OPENING = re.compile(r"[\[{]")
NO_BODY = frozenset({"GET", "HEAD", "OPTIONS"})
"""Methods whose requests pass unread, so an event stream starts at once. No route with one of
them takes a body, and tests/test_unsafe_bodies.py checks that stays so."""


def as_json_reads_it(body: bytes) -> str | None:
    """The body as text, decoded as json.loads decodes the raw bytes Starlette hands it: UTF-8,
    UTF-16 or UTF-32, told apart by the first bytes. None when it is none of them."""
    try:
        return body.decode(json.detect_encoding(body), "surrogatepass")
    except UnicodeDecodeError:
        return None


def nests_deeper_than(text: str, limit: int) -> bool:
    """Whether the brackets outside strings nest deeper than the limit. Valid JSON never has a
    quote the scan can't close. After one, the scan may have lost its place, so it fails closed:
    every opening bracket that follows counts, and none closes."""
    depth = 0
    for token in _TOKEN.finditer(text):
        match token.group():
            case "[" | "{":
                depth += 1
            case "]" | "}":
                depth -= 1
            case '"':
                return depth + sum(1 for _ in _OPENING.finditer(text, token.end())) > limit
            case _:
                continue
        if depth > limit:
            return True
    return False


def _refusal(kind: str, message: str) -> JSONResponse:
    return JSONResponse({"detail": [{"type": kind, "loc": ["body"], "msg": message}]}, 422)


class RefuseDeepJson:
    """Reads a request body whole and refuses it with a 422 if it is not Unicode text or nests
    too deep. Otherwise it hands the same bytes on. It checks every body, whatever its
    Content-Type, so it never has to guess which ones FastAPI will parse as JSON. FastAPI reads
    the whole body before a route runs, so nothing streams."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in NO_BODY:
            await self.app(scope, receive, send)
            return
        messages: list[Message] = []
        body = bytearray()
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        if body:
            text = as_json_reads_it(bytes(body))
            refusal = (
                _refusal("json_invalid", NOT_TEXT_MESSAGE)
                if text is None
                else _refusal("json_too_deep", TOO_DEEP_MESSAGE)
                if nests_deeper_than(text, MAX_DEPTH)
                else None
            )
            if refusal is not None:
                await refusal(scope, receive, send)
                return
        waiting = iter(messages)

        async def replay() -> Message:
            return next(waiting, None) or await receive()

        await self.app(scope, replay, send)


def _encodable(value: object) -> Any | None:
    """The value as JSON the response can send, or None if it can't be sent."""
    try:
        encoded = jsonable_encoder(value)
        json.dumps(encoded, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except UnicodeEncodeError, RecursionError, ValueError, TypeError:
        return None
    return encoded


def _printable(part: object) -> object:
    """Text that can be sent as UTF-8, with a lone surrogate written out as its escape."""
    if isinstance(part, str):
        return part.encode("utf-8", "backslashreplace").decode("utf-8")
    return part


def _safe_problem(error: Mapping[str, Any]) -> Any:
    whole = _encodable(error)
    if whole is not None:
        return whole
    loc: Sequence[object] = error.get("loc", ())
    problem: dict[str, Any] = {
        "type": _printable(error.get("type", "value_error")),
        "loc": [_printable(part) for part in loc],
        "msg": _printable(error.get("msg", "")),
    }
    if (ctx := _encodable(error.get("ctx"))) is not None:
        problem["ctx"] = ctx
    return problem


async def refuse_invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's own 422, except that a problem whose input can't be sent leaves the input out."""
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422, content={"detail": [_safe_problem(e) for e in exc.errors()]}
    )
