"""Reading Jira for an agent. The agent only ever reads through the JiraReader port, and the
platform answers it, from the practice Jira or a real one (ADR 0035). The agent holds no Jira
key."""

from collections.abc import Callable
from typing import Final, Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_runtime.contract import TaskRequest

TIMEOUT_SECONDS: Final = 10.0
MAX_TICKETS: Final = 50
MAX_ANSWER_BYTES: Final = 1_000_000
TOKEN_HEADER: Final = "X-Callback-Token"


class JiraTicket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    project: str
    title: str
    status: str
    created_at: str | None = None
    done_at: str | None = None
    body: str = ""


class _TicketList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tickets: list[JiraTicket] = Field(max_length=MAX_TICKETS)


class JiraUnavailable(Exception):
    """Jira could not be reached or gave an answer we cannot use. The message is plain words."""


class JiraReader(Protocol):
    def search(
        self, project: str, text: str | None, status: str | None, done_since: str | None
    ) -> list[JiraTicket]: ...

    def read(self, key: str) -> JiraTicket: ...


# One reader for one task, or None when no Jira is set up.
type JiraReaderFor = Callable[[TaskRequest], JiraReader | None]


def no_jira(request: TaskRequest) -> JiraReader | None:
    return None


class PlatformJira:
    """Reads Jira through the platform. The task's callback token goes only to the platform
    address it was set up with, no redirect is followed, and every call times out."""

    def __init__(
        self, base_url: str, run_id: str, task_id: str, token: str, client: httpx.Client
    ) -> None:
        self._base = f"{base_url.rstrip('/')}/internal/v1/runs/{quote(run_id, safe='')}/jira"
        self._task_id = task_id
        self._headers = {TOKEN_HEADER: token}
        self._client = client

    def search(
        self, project: str, text: str | None, status: str | None, done_since: str | None
    ) -> list[JiraTicket]:
        params = {
            "task": self._task_id,
            "project": project,
            "text": text or "",
            "status": status or "",
            "done_since": done_since or "",
        }
        answer = self._get("/tickets", params)
        try:
            return _TicketList.model_validate_json(answer).tickets
        except ValidationError as error:
            raise JiraUnavailable("Jira gave an answer that could not be read.") from error

    def read(self, key: str) -> JiraTicket:
        answer = self._get(f"/tickets/{quote(key, safe='')}", {"task": self._task_id})
        try:
            return JiraTicket.model_validate_json(answer)
        except ValidationError as error:
            raise JiraUnavailable("Jira gave an answer that could not be read.") from error

    def _get(self, path: str, params: dict[str, str]) -> bytes:
        try:
            response = self._client.get(
                f"{self._base}{path}",
                params=params,
                headers=self._headers,
                follow_redirects=False,
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise JiraUnavailable("Jira could not be reached.") from error
        if response.status_code == 404:
            raise JiraUnavailable("Jira has no such ticket.")
        if response.status_code != 200 or len(response.content) > MAX_ANSWER_BYTES:
            raise JiraUnavailable("Jira could not answer.")
        return response.content


class PlatformJiraFor:
    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)

    def __call__(self, request: TaskRequest) -> JiraReader | None:
        return PlatformJira(
            self._base_url,
            request.run_id,
            request.task_id,
            request.callback.token,
            self._client,
        )
