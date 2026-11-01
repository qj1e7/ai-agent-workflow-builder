"""The one Jira adapter (ADR 0035). It speaks Jira's REST API, Data Center's v2 or Cloud's v3.

The same code talks to a real Jira and to the practice Jira, over HTTP, so the practice copy
proves the adapter that a move to the real Jira will use.
"""

import asyncio
import base64
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Final
from urllib.parse import quote

import httpx

from platform_api.jira_format import from_adf, from_wiki, json_list, json_object, to_adf, to_wiki
from platform_api.orchestration.jira import (
    IssueSearch,
    JiraFlavor,
    JiraIssue,
    JiraRefused,
    JiraUnavailable,
    NewIssue,
    TicketStatus,
)

type Sleep = Callable[[float], Awaitable[None]]

ATTEMPTS: Final = 3
"""Each call is tried at most three times when Jira is busy or down."""
MAX_WAIT_SECONDS: Final = 5.0
"""The longest the adapter waits between tries, whatever Retry-After asks. The gateway treats a
write as lost after 30 seconds, so every wait together stays well under that."""
SUMMARY_LIMIT: Final = 255
FIELDS: Final = (
    "summary,description,status,project,labels,created,updated,resolutiondate,"
    "statuscategorychangedate"
)
KEYS_PER_SEARCH: Final = 50
_RETRY_STATUSES: Final = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class JiraAuth:
    """How the adapter signs in: a Data Center personal access token, sent as Bearer, or a Cloud
    account's email and API token, sent as Basic."""

    header: str

    @classmethod
    def bearer(cls, token: str) -> JiraAuth:
        return cls(f"Bearer {token}")

    @classmethod
    def basic(cls, email: str, token: str) -> JiraAuth:
        return cls("Basic " + base64.b64encode(f"{email}:{token}".encode()).decode())

    @classmethod
    def of(cls, flavor: JiraFlavor, token: str, email: str | None) -> JiraAuth:
        if flavor == "cloud":
            return cls.basic(email or "", token)
        return cls.bearer(token)


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _listed(values: Sequence[str]) -> str:
    return ", ".join(_quoted(value) for value in values)


def _when(text: object) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    for shape in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, shape)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _one_line(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


def _body(response: httpx.Response) -> Mapping[str, object]:
    try:
        return json_object(response.json())
    except ValueError:
        return {}


def _messages(response: httpx.Response) -> str:
    """Jira's own words from its error shape, {"errorMessages": [...], "errors": {...}}."""
    body = _body(response)
    parts = [str(message) for message in json_list(body.get("errorMessages")) if message]
    parts.extend(f"{name}: {text}" for name, text in json_object(body.get("errors")).items())
    return _one_line("; ".join(parts), 300)


def _wait(response: httpx.Response | None) -> float:
    if response is None:
        return 1.0
    raw = response.headers.get("retry-after", "").strip()
    if not raw:
        return 1.0
    try:
        seconds = float(raw)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
        except TypeError, ValueError:
            return 1.0
    return min(max(seconds, 0.0), MAX_WAIT_SECONDS)


class JiraRestAdapter:
    """The JiraPort over Jira's REST API."""

    def __init__(
        self,
        base_url: str,
        flavor: JiraFlavor,
        auth: JiraAuth,
        client: httpx.AsyncClient,
        issue_type: str = "Task",
        browse_url: str | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._base = base_url.rstrip("/")
        self.flavor: JiraFlavor = flavor
        self._auth = auth
        self._client = client
        self._issue_type = issue_type
        self._browse = browse_url or f"{self._base}/browse/{{key}}"
        self._sleep = sleep
        self._api = f"{self._base}/rest/api/{'3' if flavor == 'cloud' else '2'}"

    @property
    def auth_header(self) -> str:
        return self._auth.header

    def browse_url(self, key: str) -> str:
        return self._browse.replace("{key}", quote(key, safe=""))

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        params: Mapping[str, str | int] | None = None,
        repeatable: bool = True,
    ) -> httpx.Response:
        """One call to Jira. A busy Jira (429) is always tried again after its Retry-After, as
        it did not act. A Jira that is down or out of reach is tried again only for a call that
        can safely run twice; a create could have been made, so its caller looks first."""
        response: httpx.Response | None = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = await self._client.request(
                    method,
                    f"{self._api}{path}",
                    json=json,
                    params=params,
                    headers={"Authorization": self._auth.header, "Accept": "application/json"},
                    follow_redirects=False,
                )
            except httpx.HTTPError as error:
                if not repeatable or attempt == ATTEMPTS:
                    raise JiraUnavailable(
                        f"Jira could not be reached: {type(error).__name__}."
                    ) from error
                response = None
                await self._sleep(_wait(None))
                continue
            status = response.status_code
            again = status == 429 or (repeatable and status in _RETRY_STATUSES)
            if not again or attempt == ATTEMPTS:
                return response
            await self._sleep(_wait(response))
        assert response is not None
        return response

    def _failure(self, response: httpx.Response, doing: str) -> JiraRefused | JiraUnavailable:
        status = response.status_code
        said = _messages(response)
        detail = f" Jira said: {said}" if said else ""
        if status == 401:
            return JiraUnavailable(
                f"Jira refused the token while it {doing} (401). Replace the Jira token "
                "(JIRA_API_TOKEN), then retry.",
                status,
            )
        if status in {400, 403, 404, 405, 409, 410, 422}:
            return JiraRefused(f"Jira refused to {doing} ({status}).{detail}", status)
        return JiraUnavailable(f"Jira could not {doing} ({status}).{detail}", status)

    def _issue(self, raw: object) -> JiraIssue:
        issue = json_object(raw)
        fields = json_object(issue.get("fields"))
        category = json_object(json_object(fields.get("status")).get("statusCategory"))
        done = category.get("key") == "done"
        state: TicketStatus = "Done" if done else "To Do"
        created = _when(fields.get("created"))
        key = issue.get("key")
        if not isinstance(key, str) or created is None:
            raise JiraUnavailable("Jira gave an issue that could not be read.")
        done_at = None
        if done:
            # A Jira workflow may reach Done without setting a resolution.
            done_at = (
                _when(fields.get("resolutiondate"))
                or _when(fields.get("statuscategorychangedate"))
                or _when(fields.get("updated"))
            )
        description = fields.get("description")
        return JiraIssue(
            key=key,
            project=str(json_object(fields.get("project")).get("key", "")),
            title=str(fields.get("summary") or ""),
            body=from_adf(description) if self.flavor == "cloud" else from_wiki(description),
            status=state,
            created_at=created,
            done_at=done_at,
            labels=tuple(str(label) for label in json_list(fields.get("labels"))),
        )

    async def create_issue(self, issue: NewIssue) -> str:
        fields: dict[str, Any] = {
            "project": {"key": issue.project},
            "summary": _one_line(issue.title, SUMMARY_LIMIT),
            "issuetype": {"name": self._issue_type},
        }
        if issue.body:
            fields["description"] = (
                to_adf(issue.body) if self.flavor == "cloud" else to_wiki(issue.body)
            )
        if issue.labels:
            fields["labels"] = list(issue.labels)
        response = await self._call("POST", "/issue", json={"fields": fields}, repeatable=False)
        if response.status_code not in {200, 201}:
            raise self._failure(response, "create the ticket")
        key = _body(response).get("key")
        if not isinstance(key, str):
            raise JiraUnavailable("Jira made the ticket but gave no key that could be read.")
        return key

    async def get_issue(self, key: str) -> JiraIssue | None:
        response = await self._call(
            "GET", f"/issue/{quote(key, safe='')}", params={"fields": FIELDS}
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise self._failure(response, "read the ticket")
        return self._issue(response.json())

    async def _jql(self, jql: str, limit: int) -> list[JiraIssue]:
        params: dict[str, str | int] = {"jql": jql, "maxResults": limit, "fields": FIELDS}
        path = "/search/jql" if self.flavor == "cloud" else "/search"
        response = await self._call("GET", path, params=params)
        if response.status_code != 200:
            raise self._failure(response, "search")
        body = _body(response)
        if not isinstance(body.get("issues"), list):
            raise JiraUnavailable("Jira gave search results that could not be read.")
        return [self._issue(raw) for raw in json_list(body.get("issues"))]

    async def search(self, query: IssueSearch) -> list[JiraIssue]:
        """Words match as any of them, because Jira's text ~ "a b" may need every word."""
        clauses = [f"project in ({_listed(query.projects)})"]
        if query.words:
            clauses.append("(" + " OR ".join(f"text ~ {_quoted(w)}" for w in query.words) + ")")
        if query.status == "Done":
            clauses.append("statusCategory = Done")
        elif query.status == "To Do":
            clauses.append("statusCategory != Done")
        if query.done_since is not None:
            clauses.append(
                f"resolutiondate >= {_quoted(query.done_since.strftime('%Y-%m-%d %H:%M'))}"
            )
        return await self._jql(" AND ".join(clauses) + " ORDER BY created DESC", query.limit)

    async def find_by_label(self, project: str, label: str) -> str | None:
        jql = f"project = {_quoted(project)} AND labels = {_quoted(label)} ORDER BY created ASC"
        found = await self._jql(jql, 1)
        return found[0].key if found else None

    async def done_tickets(self, keys: Collection[str]) -> Mapping[str, datetime]:
        """Which of these tickets are Done, and when. A key Jira no longer has is skipped: Jira
        refuses a key in (...) search that names one, so those tickets are read one by one."""
        wanted = list(dict.fromkeys(keys))
        done: dict[str, datetime] = {}
        for start in range(0, len(wanted), KEYS_PER_SEARCH):
            chunk = wanted[start : start + KEYS_PER_SEARCH]
            jql = f"key in ({_listed(chunk)}) AND statusCategory = Done"
            try:
                issues = await self._jql(jql, len(chunk))
            except JiraRefused:
                issues = [i for key in chunk if (i := await self.get_issue(key)) is not None]
            for issue in issues:
                if issue.status == "Done" and issue.done_at is not None:
                    done[issue.key] = issue.done_at
        return done

    async def move_to_done(self, key: str) -> None:
        path = f"/issue/{quote(key, safe='')}/transitions"
        response = await self._call("GET", path)
        if response.status_code != 200:
            raise self._failure(response, "list the ticket's transitions")
        target: str | None = None
        for item in json_list(_body(response).get("transitions")):
            transition = json_object(item)
            category = json_object(json_object(transition.get("to")).get("statusCategory"))
            if category.get("key") == "done":
                target = str(transition.get("id"))
                break
        if target is None:
            raise JiraRefused(f"Jira offers no transition to Done for {key}.")
        moved = await self._call(
            "POST", path, json={"transition": {"id": target}}, repeatable=False
        )
        if moved.status_code not in {200, 204}:
            raise self._failure(moved, "move the ticket to Done")
