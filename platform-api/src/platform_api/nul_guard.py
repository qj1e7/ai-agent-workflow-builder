"""Refuses a NUL byte in a request's path or query string, which PostgreSQL text cannot hold.

A path that holds one names nothing, so it is a 404 like any unknown path. A query string that
holds one is a 422 naming the parameter, in FastAPI's own shape. WireIn checks request bodies.
"""

from urllib.parse import parse_qsl

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from platform_api.wire import NUL_MESSAGE


def _parameter_with_nul(query_string: bytes) -> str | None:
    for name, value in parse_qsl(query_string.decode("latin-1"), keep_blank_values=True):
        if "\x00" in name or "\x00" in value:
            return name
    return None


class RefuseNul:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            refusal: JSONResponse | None = None
            if "\x00" in scope["path"]:
                refusal = JSONResponse({"detail": "Not Found"}, status_code=404)
            elif (name := _parameter_with_nul(scope["query_string"])) is not None:
                problem = {"type": "nul_character", "loc": ["query", name], "msg": NUL_MESSAGE}
                refusal = JSONResponse({"detail": [problem]}, status_code=422)
            if refusal is not None:
                await refusal(scope, receive, send)
                return
        await self.app(scope, receive, send)
