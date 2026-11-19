"""Reading an outside service's answer with a size limit (ADR 0025).

The body is streamed and reading stops as soon as it passes the limit, so a service that answers
far more than it should never fills the runtime's memory. Redirects are not followed: each
reader asks one fixed address, and an answer that points elsewhere is not the service's own.
"""

from collections.abc import Mapping

import httpx

MEGABYTE = 1024 * 1024


class TooLarge(Exception):
    """The answer was longer than the reader takes."""


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
    limit, and httpx.TransportError when the service could not be read."""
    with client.stream(
        method, url, headers=headers, params=params, json=json, follow_redirects=False
    ) as response:
        declared = response.headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > limit:
            raise TooLarge
        body = bytearray()
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > limit:
                raise TooLarge
        return response.status_code, bytes(body)
