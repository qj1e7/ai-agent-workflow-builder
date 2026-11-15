"""The one Confluence adapter. It reads a page, and only a page the platform allows (ENGINE-PLAN
2.7, D2). It never writes.

The address and the key come from the settings, never from a request. A request names a page by
its id or its title, and only a page on the allowed list is read, so a request can choose among
those pages and nothing else. Confluence's REST API is the same on Atlassian Cloud and Data Center
under the wiki's own address.
"""

import asyncio
import base64
import html
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import quote

import httpx

from platform_api.jira_format import json_object
from platform_api.orchestration.dispatch import Identity, identity_of
from platform_api.orchestration.n8n_calls import NodeOption, ReadFailed, ReadItems
from platform_api.settings import ConfluencePage, ConfluenceSettings

type Sleep = Callable[[float], Awaitable[None]]
type ConfluenceReach = Literal["working", "token_refused", "not_answering"]

CONFLUENCE_PAGE: Final = "confluence_page"
"""The Read block's source for a Confluence page."""
TIMEOUT_SECONDS: Final = 10.0
ATTEMPTS: Final = 3
WAIT_SECONDS: Final = 1.0
PAGE_LIMIT: Final = 1_000_000
"""The most of a page's storage format the platform reads, in characters."""
TEXT_LIMIT: Final = 8 * 1024
"""A page's text as a Read block gives it, at most the size of one agent input."""
_RETRY_STATUSES: Final = frozenset({429, 500, 502, 503, 504})
TOKEN_REFUSED: Final = (
    "Confluence refused the token ({status}). Replace the Confluence token "
    "(CONFLUENCE_API_TOKEN), then retry."
)


class ConfluenceError(Exception):
    """What went wrong, in plain words that never quote the address or the key."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ConfluenceRefused(ConfluenceError):
    """Confluence said no. Asking again is refused the same way until someone fixes the
    connection or the page, so this is not an outage."""


class ConfluenceUnavailable(ConfluenceError):
    """Confluence could not be reached, or was busy or down. Asking again later may work."""


@dataclass(frozen=True)
class PageRead:
    id: str
    title: str
    version: int
    url: str
    storage: str
    """The page's body in Confluence's storage format, its own HTML."""

    @property
    def text(self) -> str:
        return page_text(self.storage)


_TIME: Final = re.compile(r'<time[^>]*datetime="([^"]+)"[^>]*>', re.IGNORECASE)
_ROW: Final = re.compile(r"<tr[^>]*>([\s\S]*?)</tr\s*>", re.IGNORECASE)
_CELL: Final = re.compile(r"<t[hd][^>]*>([\s\S]*?)</t[hd]\s*>", re.IGNORECASE)
_LINE_END: Final = re.compile(r"<br\s*/?>|</(?:p|h[1-6]|li|div)\s*>", re.IGNORECASE)
_TAG: Final = re.compile(r"<[^>]+>")
_SPACES: Final = re.compile(r"[^\S\n]+")


def _row_line(row: re.Match[str]) -> str:
    """A table row on a line of its own, with its cells split by |, whatever a cell holds."""
    cells = (_SPACES.sub(" ", _TAG.sub(" ", cell[1])).strip() for cell in _CELL.finditer(row[1]))
    return "\n" + " | ".join(cells) + "\n"


def page_text(storage: str) -> str:
    """A page as plain lines: a table row on one line with its cells split by |, and a date
    macro as its date."""
    rows = _ROW.sub(_row_line, _TIME.sub(r" \1 ", storage))
    plain = html.unescape(_TAG.sub(" ", _LINE_END.sub("\n", rows)))
    lines = (_SPACES.sub(" ", line).strip() for line in plain.splitlines())
    return "\n".join(line for line in lines if line)


def auth_header(settings: ConfluenceSettings) -> str:
    """Atlassian Cloud signs in with an email and an API token, Data Center with a personal
    access token alone."""
    token = settings.token or ""
    if settings.email is None:
        return f"Bearer {token}"
    return "Basic " + base64.b64encode(f"{settings.email}:{token}".encode()).decode()


def confluence_identity(settings: ConfluenceSettings) -> Identity:
    return identity_of(
        "confluence", settings.base_url or "", settings.email or "", settings.token or ""
    )


def _status_failure(status: int, doing: str) -> ConfluenceError:
    if status in {401, 403}:
        return ConfluenceRefused(TOKEN_REFUSED.format(status=status), status)
    if 400 <= status < 500 and status != 429:
        return ConfluenceRefused(f"Confluence refused to {doing} ({status}).", status)
    return ConfluenceUnavailable(f"Confluence could not {doing} ({status}).", status)


class ConfluenceRest:
    """Confluence's REST API under the wiki's address, such as https://site.atlassian.net/wiki."""

    def __init__(
        self,
        base_url: str,
        auth: str,
        client: httpx.AsyncClient,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": auth, "Accept": "application/json"}
        self._client = client
        self._sleep = sleep

    async def check(self) -> ConfluenceReach:
        """Asks Confluence who the key is, once and with no retry. It reads no page."""
        try:
            response = await self._client.get(
                f"{self._base}/rest/api/user/current",
                headers=self._headers,
                follow_redirects=False,
            )
        except httpx.HTTPError, httpx.InvalidURL:
            return "not_answering"
        if response.status_code in {401, 403}:
            return "token_refused"
        if response.status_code != 200:
            return "not_answering"
        # Confluence answers a key it does not take as the anonymous user.
        match _body(response).get("type"):
            case "known":
                return "working"
            case "anonymous":
                return "token_refused"
            case _:
                return "not_answering"

    async def read_page(self, page_id: str) -> PageRead | None:
        """The page with its body and version, or None when Confluence has no such page."""
        response = await self._get(
            f"/rest/api/content/{quote(page_id, safe='')}", {"expand": "body.storage,version"}
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise _status_failure(response.status_code, "read the page")
        body = _body(response)
        version = json_object(body.get("version")).get("number")
        storage = json_object(json_object(body.get("body")).get("storage")).get("value")
        title = body.get("title")
        if not (isinstance(title, str) and isinstance(version, int) and isinstance(storage, str)):
            raise ConfluenceUnavailable("Confluence gave a page that could not be read.")
        if len(storage) > PAGE_LIMIT:
            raise ConfluenceRefused("The page is larger than 1 MB, so it was not read.")
        url = f"{self._base}/pages/viewpage.action?pageId={quote(page_id, safe='')}"
        return PageRead(page_id, title, version, url, storage)

    async def _get(self, path: str, params: dict[str, str]) -> httpx.Response:
        """A read, so a busy or failing Confluence is tried again, three times at most."""
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = await self._client.get(
                    f"{self._base}{path}",
                    params=params,
                    headers=self._headers,
                    follow_redirects=False,
                )
            except httpx.HTTPError as error:
                if attempt == ATTEMPTS:
                    raise ConfluenceUnavailable(
                        f"Confluence could not be reached: {type(error).__name__}."
                    ) from error
            else:
                if response.status_code not in _RETRY_STATUSES or attempt == ATTEMPTS:
                    return response
            await self._sleep(WAIT_SECONDS)
        raise AssertionError("the last attempt returns or raises")


def _body(response: httpx.Response) -> dict[str, object]:
    try:
        return dict(json_object(response.json()))
    except ValueError:
        return {}


def _named(text: str) -> str:
    return " ".join(text.split()).casefold()


class ConfluencePages:
    """The pages the platform may read, and the one way to read them. While Confluence is not
    connected it lists no page and reads none.

    It is also where a Read block reads a Confluence page, so the editor's options and the check
    at run time list the same pages (ENGINE-PLAN 2.2)."""

    def __init__(
        self,
        allowed: Sequence[ConfluencePage],
        rest: ConfluenceRest | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._allowed = tuple(allowed) if rest is not None else ()
        self._rest = rest
        self._client = client

    @property
    def connected(self) -> bool:
        return self._rest is not None

    @property
    def allowed(self) -> tuple[ConfluencePage, ...]:
        return self._allowed

    def find(self, named: str) -> ConfluencePage | None:
        """An allowed page by its id, or else by its title, in any case and spacing."""
        by_id = next((page for page in self._allowed if page.id == named), None)
        wanted = _named(named)
        return by_id or next((p for p in self._allowed if _named(p.title) == wanted), None)

    async def check(self) -> ConfluenceReach:
        return "not_answering" if self._rest is None else await self._rest.check()

    async def read_page(self, page: ConfluencePage) -> PageRead | None:
        if self._rest is None or page not in self._allowed:
            raise ConfluenceRefused("That page is not one the platform may read.")
        return await self._rest.read_page(page.id)

    async def places(self, source: str) -> Sequence[NodeOption]:
        if source != CONFLUENCE_PAGE:
            return []
        return [NodeOption(page.id, page.title) for page in self._allowed]

    async def read(self, source: str, place: str, query: str | None) -> ReadItems | ReadFailed:
        page = self.find(place) if source == CONFLUENCE_PAGE else None
        if page is None:
            return ReadFailed("That page is not one the platform may read.")
        try:
            read = await self.read_page(page)
        except ConfluenceError as error:
            return ReadFailed(str(error))
        if read is None:
            return ReadFailed(f"Confluence has no page {page.id} now.")
        return [
            {
                "kind": "page",
                "id": read.id,
                "title": read.title,
                "version": read.version,
                "url": read.url,
                "text": read.text[:TEXT_LIMIT],
            }
        ]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def confluence_pages(settings: ConfluenceSettings) -> ConfluencePages:
    """The pages, with an adapter of their own while Confluence is set up."""
    if settings.base_url is None:
        return ConfluencePages((), None)
    client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    rest = ConfluenceRest(settings.base_url, auth_header(settings), client)
    return ConfluencePages(settings.pages, rest, client)
