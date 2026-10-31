"""Keeps a request body the API can't read safely from turning into a 500 (#60).

A body nested far deeper than any real request overflows the stack of the code that walks it,
so it is refused before a route reads it. A 422 never echoes text that can't be written back
out as UTF-8, such as a lone surrogate escape.
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

# A JSON string, a bracket, or a quote that starts a string with no end. Strings are skipped
# whole, so a bracket inside one is not counted. Possessive, so a string is scanned once.
_TOKEN = re.compile(rb'"(?:[^"\\]|\\.)*+"|[\[\]{}]|"')
_NO_BODY = frozenset({"GET", "HEAD", "OPTIONS"})


def nests_deeper_than(body: bytes, limit: int) -> bool:
    depth = 0
    for token in _TOKEN.finditer(body):
        match token.group():
            case b"[" | b"{":
                depth += 1
                if depth > limit:
                    return True
            case b"]" | b"}":
                depth -= 1
            case b'"':
                # A string with no end is not JSON, so FastAPI refuses it anyway.
                return False
            case _:
                pass
    return False


def _reads_as_json(scope: Scope) -> bool:
    """FastAPI reads a body as JSON when its type is JSON or when it names no type."""
    for name, value in scope["headers"]:
        if name == b"content-type":
            media = value.split(b";", 1)[0].strip().lower()
            return media == b"application/json" or (
                media.startswith(b"application/") and media.endswith(b"+json")
            )
    return True


class RefuseDeepJson:
    """Reads a JSON body whole, refuses it with a 422 if it nests too deep, and otherwise hands
    the same bytes on. FastAPI reads the whole body before a route runs, so nothing streams."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in _NO_BODY or not _reads_as_json(scope):
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
        if nests_deeper_than(bytes(body), MAX_DEPTH):
            problem = {"type": "json_too_deep", "loc": ["body"], "msg": TOO_DEEP_MESSAGE}
            await JSONResponse({"detail": [problem]}, status_code=422)(scope, receive, send)
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
