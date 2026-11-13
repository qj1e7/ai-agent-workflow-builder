"""Reading Confluence for an agent. The agent reads only through the ConfluenceReader port, and the
platform answers it, from the pages it may read. The agent holds no Confluence key and never
learns the address."""

from collections.abc import Callable
from typing import Final, Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from agent_runtime.contract import TaskRequest
from agent_runtime.jira import MAX_ANSWER_BYTES, REFUSED_STATUS, TIMEOUT_SECONDS, TOKEN_HEADER

PAGE_ANSWER_BYTES: Final = 3 * MAX_ANSWER_BYTES
"""A page of 1 MB comes back as its storage and its text, both escaped as JSON."""
NO_ANSWER: Final = "Confluence could not answer."
NOT_READABLE: Final = "Confluence gave a page that could not be read."


class ConfluencePage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    version: int
    url: str
    storage: str
    """The page's body in Confluence's storage format."""
    text: str
    """The page as plain lines, each table row on one line."""


class ConfluenceUnavailable(Exception):
    """Confluence could not be reached or gave an answer we cannot use. The message is plain."""


class ConfluenceRefused(ConfluenceUnavailable):
    """The platform or Confluence refused the read: the page is not one the platform may read,
    Confluence is not connected, or it refused the key. Asking again is refused the same way."""


class ConfluenceReader(Protocol):
    def read(self, page: str) -> ConfluencePage | None: ...


type ConfluenceReaderFor = Callable[[TaskRequest], ConfluenceReader | None]


def no_confluence(request: TaskRequest) -> ConfluenceReader | None:
    return None


def _detail(response: httpx.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except ValueError, AttributeError:
        return None
    return detail if isinstance(detail, str) and detail else None


class PlatformConfluence:
    """Reads a page through the platform, by its id or its title. The task's callback token goes
    only to the platform address it was set up with, no redirect is followed, and every call
    times out."""

    def __init__(
        self, base_url: str, run_id: str, task_id: str, token: str, client: httpx.Client
    ) -> None:
        run = quote(run_id, safe="")
        self._base = f"{base_url.rstrip('/')}/internal/v1/runs/{run}/confluence/pages"
        self._task_id = task_id
        self._headers = {TOKEN_HEADER: token}
        self._client = client

    def read(self, page: str) -> ConfluencePage | None:
        try:
            response = self._client.get(
                f"{self._base}/{quote(page, safe='')}",
                params={"task": self._task_id},
                headers=self._headers,
                follow_redirects=False,
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise ConfluenceUnavailable("Confluence could not be reached.") from error
        if response.status_code == 404:
            return None
        if response.status_code in {403, REFUSED_STATUS}:
            raise ConfluenceRefused(_detail(response) or "The platform refused to read the page.")
        if response.status_code != 200 or len(response.content) > PAGE_ANSWER_BYTES:
            raise ConfluenceUnavailable(NO_ANSWER)
        try:
            return ConfluencePage.model_validate_json(response.content)
        except ValidationError as error:
            raise ConfluenceUnavailable(NOT_READABLE) from error


class PlatformConfluenceFor:
    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)

    def __call__(self, request: TaskRequest) -> ConfluenceReader | None:
        return PlatformConfluence(
            self._base_url,
            request.run_id,
            request.task_id,
            request.callback.token,
            self._client,
        )
