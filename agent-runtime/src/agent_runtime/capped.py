"""Reading an outside service's answer with a size limit and the check's deadline (ADR 0025).

The body is streamed and reading stops as soon as it passes the limit, so a service that answers
far more than it should never fills the runtime's memory. The answer is asked for uncompressed,
and one that comes compressed anyway is refused: a small compressed body can unpack to far more
than the limit before a single chunk could be counted. Redirects are not followed: each reader
asks one fixed address, and an answer that points elsewhere is not the service's own.

One check shares one deadline (`deadline`), so every outside call in it, with its retries and
waits, ends inside the time n8n and platform-api give the task. It is kept in a context
variable, so checks that run at once each keep their own.
"""

import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx

MEGABYTE = 1024 * 1024
CHECK_SECONDS = 40.0
"""How long one check's outside calls may take in all. The summary's own 10 s comes after, and
n8n and platform-api give the task 60 s."""
UNCOMPRESSED = "identity"


class TooLarge(Exception):
    """The answer was longer than the reader takes, or came compressed."""


class OutOfTime(Exception):
    """The check's deadline passed before this call could finish."""


@dataclass(frozen=True)
class _Deadline:
    at: float
    clock: Callable[[], float]

    def left(self) -> float:
        return self.at - self.clock()


_DEADLINE: ContextVar[_Deadline | None] = ContextVar("check_deadline", default=None)


@contextmanager
def deadline(
    seconds: float = CHECK_SECONDS, clock: Callable[[], float] = time.monotonic
) -> Generator[None]:
    """Every capped read inside shares one deadline, `seconds` from now."""
    token = _DEADLINE.set(_Deadline(clock() + seconds, clock))
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def time_left() -> float | None:
    """Seconds left before the check's deadline, or None outside a check."""
    found = _DEADLINE.get()
    return None if found is None else found.left()


def read_capped(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    limit: int,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    json: object = None,
) -> tuple[int, bytes]:
    """The status and body of one answer, read up to `limit` bytes. Raises TooLarge past the
    limit or for a compressed answer, OutOfTime once the check's deadline passes, and
    httpx.TransportError when the service could not be read."""
    left = time_left()
    if left is not None and left <= 0:
        raise OutOfTime
    timeout = client.timeout if left is None else _shorter(client.timeout, left)
    asked = {**(headers or {}), "Accept-Encoding": UNCOMPRESSED}
    with client.stream(
        method,
        url,
        headers=asked,
        params=params,
        json=json,
        timeout=timeout,
        follow_redirects=False,
    ) as response:
        encoding = response.headers.get("content-encoding", UNCOMPRESSED).strip().lower()
        if encoding not in ("", UNCOMPRESSED):
            raise TooLarge
        declared = response.headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > limit:
            raise TooLarge
        body = bytearray()
        # Nothing is unpacked here: a compressed answer was refused above.
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > limit:
                raise TooLarge
            now_left = time_left()
            if now_left is not None and now_left <= 0:
                raise OutOfTime
        return response.status_code, bytes(body)


def _shorter(timeout: httpx.Timeout, left: float) -> httpx.Timeout:
    """The client's own timeouts, none longer than the time the check has left."""

    def cut(value: float | None) -> float:
        return left if value is None else min(value, left)

    return httpx.Timeout(
        connect=cut(timeout.connect),
        read=cut(timeout.read),
        write=cut(timeout.write),
        pool=cut(timeout.pool),
    )
