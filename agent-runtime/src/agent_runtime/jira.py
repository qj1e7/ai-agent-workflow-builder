"""Reading Jira for an agent. The agent only ever reads through the JiraReader port, and the
platform answers it, from the practice Jira or a real one (ADR 0035). The agent holds no Jira
key."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_runtime.contract import TaskRequest

TIMEOUT_SECONDS: Final = 10.0
MAX_TICKETS: Final = 50
MAX_ANSWER_BYTES: Final = 1_000_000
TOKEN_HEADER: Final = "X-Callback-Token"
NO_ANSWER: Final = "Jira could not answer."


class JiraTicket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    project: str
    title: str
    status: str
    created_at: str | None = None
    done_at: str | None = None
    updated_at: str | None = None
    issue_type: str = ""
    assignee: str | None = None
    body: str = ""


class _TicketList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tickets: list[JiraTicket] = Field(max_length=MAX_TICKETS)
    cut_off: bool = False


@dataclass(frozen=True)
class JiraFound:
    """What a search found. `cut_off` is true when more tickets matched than the platform
    returns, so the list may be missing older ones."""

    tickets: list[JiraTicket]
    cut_off: bool = False


class JiraUnavailable(Exception):
    """Jira could not be reached or gave an answer we cannot use. The message is plain words."""


class JiraReader(Protocol):
    def search(
        self,
        project: str,
        text: str | None,
        status: str | None,
        done_since: str | None,
        updated_before: str | None = None,
        issue_type: str | None = None,
        created_since: str | None = None,
    ) -> JiraFound: ...

    def read(self, key: str) -> JiraTicket | None: ...


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
        self,
        project: str,
        text: str | None,
        status: str | None,
        done_since: str | None,
        updated_before: str | None = None,
        issue_type: str | None = None,
        created_since: str | None = None,
    ) -> JiraFound:
        params = {
            "task": self._task_id,
            "project": project,
            "text": text or "",
            "status": status or "",
            "done_since": done_since or "",
            "updated_before": updated_before or "",
            "issue_type": issue_type or "",
            "created_since": created_since or "",
        }
        answer = self._get("/tickets", params)
        if answer is None:
            raise JiraUnavailable(NO_ANSWER)
        try:
            found = _TicketList.model_validate_json(answer)
            return JiraFound(found.tickets, found.cut_off)
        except ValidationError as error:
            raise JiraUnavailable("Jira gave an answer that could not be read.") from error

    def read(self, key: str) -> JiraTicket | None:
        answer = self._get(f"/tickets/{quote(key, safe='')}", {"task": self._task_id})
        if answer is None:
            return None
        try:
            return JiraTicket.model_validate_json(answer)
        except ValidationError as error:
            raise JiraUnavailable("Jira gave an answer that could not be read.") from error

    def _get(self, path: str, params: dict[str, str]) -> bytes | None:
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
            return None
        if response.status_code != 200 or len(response.content) > MAX_ANSWER_BYTES:
            raise JiraUnavailable(NO_ANSWER)
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
