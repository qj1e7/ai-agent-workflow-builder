"""n8n's two APIs. The owner and API key calls, and five others below, use n8n's internal `/rest`
API with a login cookie, so the pinned n8n version matters. Everything else goes through the
public `/api/v1` API with the key.

N8nClient is bootstrap's, synchronous. N8nApi is the platform's own while it runs.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal, Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from platform_api.db import Database
from platform_api.orchestration.n8n_calls import (
    Ended,
    ExecutionFacts,
    FailedExecution,
    Finished,
    Publisher,
)
from platform_api.settings import N8nOwner
from platform_api.shared import N8nExecutionId, UserId

log = logging.getLogger(__name__)

API_KEY_SCOPES = (
    "workflow:create",
    "workflow:read",
    "workflow:update",
    "workflow:delete",
    "workflow:list",
    "workflow:activate",
    "workflow:deactivate",
    "execution:read",
    "execution:list",
    "credential:create",
    "credential:list",
    "credential:read",
    "credential:delete",
)
_OWNER_EXISTS = "Instance owner already setup"
# n8n 2.42.6 limits /rest/login to 5 tries a minute per email and 1000 per 5 minutes per address,
# and answers 429 with Retry-After in seconds. Anyone who can reach n8n can use up those tries,
# so the sign-in waits them out, up to this long in all.
LOGIN_RATE_LIMIT_WAIT = 180.0
_RETRY_AFTER_DEFAULT = 10.0


class N8nError(Exception):
    pass


class OwnerOutcome(Enum):
    CREATED = "created"
    SIGNED_IN = "signed in"


@dataclass(frozen=True)
class UpsertedWorkflow:
    id: str
    created: bool


@dataclass(frozen=True)
class WorkflowRecord:
    id: str
    name: str
    active: bool
    document: dict[str, Any]


class N8nClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        self._api_key: str | None = None
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def wait_healthy(self, timeout: float = 120) -> None:
        """n8n's /healthz answers 200 before and while its database is unreachable, and its
        /rest routes then answer 503, so readiness is the check that matters."""
        self._until(
            lambda: self._http.get("/healthz/readiness").status_code == 200,
            timeout,
            f"n8n at {self._http.base_url} did not become ready",
        )

    def _until(self, ready: Callable[[], bool], timeout: float, failure: str) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if ready():
                    return
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise N8nError(failure)
            self._sleep(1)

    def ensure_owner(self, email: str, password: str, timeout: float = 60) -> OwnerOutcome:
        body = {
            "email": email,
            "firstName": "Platform",
            "lastName": "Bootstrap",
            "password": password,
        }
        response = self._http.post("/rest/owner/setup", json=body)
        if response.status_code == 503:
            self._until(
                lambda: self._http.get("/healthz/readiness").status_code == 200,
                timeout,
                "n8n lost its database and did not get it back",
            )
            response = self._http.post("/rest/owner/setup", json=body)
        if response.status_code == 200:
            outcome = OwnerOutcome.CREATED
        elif response.status_code == 400 and _OWNER_EXISTS in response.text:
            outcome = OwnerOutcome.SIGNED_IN
        else:
            raise N8nError(f"owner setup failed: {_short(response)}")
        self._login(email, password)
        return outcome

    def _login(self, email: str, password: str, wait_limit: float = LOGIN_RATE_LIMIT_WAIT) -> None:
        waited = 0.0
        while True:
            response = self._http.post(
                "/rest/login", json={"emailOrLdapLoginId": email, "password": password}
            )
            if response.status_code != 429 or waited >= wait_limit:
                break
            delay = min(_retry_after(response), wait_limit - waited)
            self._sleep(delay)
            waited += delay
        if response.status_code == 429:
            raise N8nError(
                f"could not sign in as {email}: n8n's sign-in was still rate limited after "
                f"{waited:.0f}s"
            )
        if response.status_code != 200:
            raise N8nError(f"could not sign in as {email}: HTTP {response.status_code}")

    def remove_api_keys(self, label: str) -> int:
        listed = self._rest("GET", "/rest/api-keys")
        stale = [item for item in listed["data"]["items"] if item["label"] == label]
        for item in stale:
            self._rest("DELETE", f"/rest/api-keys/{item['id']}")
        return len(stale)

    def fresh_api_key(self, label: str) -> int:
        removed = self.remove_api_keys(label)
        created = self._rest(
            "POST",
            "/rest/api-keys",
            json={"label": label, "expiresAt": None, "scopes": list(API_KEY_SCOPES)},
        )
        self._api_key = str(created["data"]["rawApiKey"])
        return removed

    def create_header_credential(self, name: str, header: str, value: str) -> str:
        created = self._public(
            "POST",
            "/credentials",
            json={"name": name, "type": "httpHeaderAuth", "data": {"name": header, "value": value}},
        )
        return str(created["id"])

    def credentials_named(self, name: str) -> list[str]:
        listed = self._public("GET", "/credentials")
        return [str(item["id"]) for item in listed["data"] if item["name"] == name]

    def delete_credential(self, credential_id: str) -> None:
        self._public("DELETE", f"/credentials/{credential_id}")

    def find_workflow(self, name: str) -> WorkflowRecord | None:
        listed = self._public("GET", "/workflows", params={"name": name})
        matches = [item for item in listed["data"] if item["name"] == name]
        return _record(matches[0]) if matches else None

    def upsert_workflow(self, body: dict[str, Any]) -> UpsertedWorkflow:
        """An update never deactivates, because P4 saw webhooks answer 404 during a
        deactivate and activate cycle, while a PUT on an active workflow had no gap.
        """
        existing = self.find_workflow(str(body["name"]))
        if existing is None:
            created = self._public("POST", "/workflows", json=body)
            workflow_id = str(created["id"])
            self._public("POST", f"/workflows/{workflow_id}/activate")
            return UpsertedWorkflow(workflow_id, created=True)
        self._public("PUT", f"/workflows/{existing.id}", json=body)
        if not existing.active:
            self._public("POST", f"/workflows/{existing.id}/activate")
        return UpsertedWorkflow(existing.id, created=False)

    def read_back(self, workflow_id: str) -> WorkflowRecord:
        return _record(self._public("GET", f"/workflows/{workflow_id}"))

    def delete_workflow(self, workflow_id: str, timeout: float = 30) -> None:
        """n8n refuses to delete a published workflow, and finishes an unpublish in the
        background, so the delete answers 409 until that is done."""
        self._public("POST", f"/workflows/{workflow_id}/deactivate")
        deadline = time.monotonic() + timeout
        while True:
            response = self._send("DELETE", f"/workflows/{workflow_id}")
            if response.status_code != 409 or time.monotonic() > deadline:
                _ok(response)
                return
            self._sleep(1)

    def _rest(self, method: str, path: str, json: Any | None = None) -> dict[str, Any]:
        response = self._http.request(method, path, json=json)
        if response.status_code != 200:
            raise N8nError(f"{method} {path} failed: {_short(response)}")
        return response.json()

    def _public(
        self,
        method: str,
        path: str,
        json: Any | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return _ok(self._send(method, path, json, params))

    def _send(
        self,
        method: str,
        path: str,
        json: Any | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        if self._api_key is None:
            raise N8nError("no API key yet, call fresh_api_key first")
        return self._http.request(
            method,
            f"/api/v1{path}",
            json=json,
            params=params,
            headers={"X-N8N-API-KEY": self._api_key},
        )


def _ok(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        raise N8nError(
            f"{response.request.method} {response.request.url.path} failed: {_short(response)}"
        )
    return response.json()


def _record(item: dict[str, Any]) -> WorkflowRecord:
    return WorkflowRecord(str(item["id"]), str(item["name"]), bool(item["active"]), item)


def _retry_after(response: httpx.Response) -> float:
    """Seconds from a Retry-After header, at least one. n8n sends whole seconds, so anything
    else, such as an HTTP date, gets the default."""
    value = response.headers.get("Retry-After", "").strip()
    if not value.isdigit():
        return _RETRY_AFTER_DEFAULT
    return max(float(value), 1.0)


def _short(response: httpx.Response) -> str:
    return f"HTTP {response.status_code} {response.text[:200]}"


# The platform's own calls to n8n while it runs (ENGINE-PLAN 2.1), as the owner: the public API
# with a key the platform makes for itself, and n8n's internal /rest API with the owner's
# sign-in for the five things the public API lacks. Each /rest call is one method below and one
# line in docs/evidence/prototypes/p7-n8n-engine-facts, so a version bump has a short checklist.

PLATFORM_API_KEY_LABEL = "platform-api"
"""Bootstrap removes keys with this label at each deploy, and platform-api removes its own older
than a day whenever it makes one."""
PLATFORM_API_SCOPES = (
    "workflow:create",
    "workflow:read",
    "workflow:update",
    "workflow:delete",
    "workflow:move",
    "workflow:activate",
    "workflow:deactivate",
    "execution:read",
    "execution:list",
)
"""Only what the platform's calls need, as n8n 2.42.6's public controllers check them: read covers
history and versions, activate covers publish, move covers transfer."""
KEY_LIFETIME = timedelta(days=3)
"""A key that leaks stops working within days. When n8n refuses it, the platform makes another."""
STALE_KEY_AGE = timedelta(days=1)
START_TYPE = "CUSTOM.wabStartFromPortal"
START_NAME = "Start from the Portal"
VOUCHED = frozenset({"running", "waiting"})
"""The only execution statuses whose node calls our API takes: n8n says the execution is live."""
ENDED = frozenset({"success", "error", "crashed", "canceled"})
"""The statuses of an execution n8n will run no further."""
LANDED = frozenset({"running", "success", "error"})
"""A wake that met a 409 after an earlier try still landed when n8n shows the execution running
or finished: the earlier try resumed it, and only its answer was lost."""
DOCUMENT_KEYS = ("name", "nodes", "connections", "settings")
"""What the public API's PUT takes, and so what the platform keeps of each version."""
PUBLISH_WAIT_SECONDS = 20.0
RETRY_WAIT_SECONDS = 30.0
"""How long the platform waits on n8n's retry, which answers only when the retry stops (P7 Q5).
No answer by then means n8n took the retry and is running it. It stays under the outbox lease."""


@dataclass(frozen=True)
class N8nWorkflow:
    id: str
    version_id: str
    """The draft's version."""
    active_version_id: str | None
    """The published version, or None while nothing is published."""
    document: dict[str, Any]


@dataclass(frozen=True)
class TriggerStatus:
    node_id: str
    status: str
    error: str | None


@dataclass(frozen=True)
class PublicationStatus:
    status: str
    live_version_id: str | None
    triggers: tuple[TriggerStatus, ...]

    @property
    def published(self) -> bool:
        """Every trigger is live, Ask for a yes's resume webhook included (P7 Q19)."""
        return self.status == "published" and all(t.status == "activated" for t in self.triggers)


@dataclass(frozen=True)
class PublishEvent:
    version_id: str
    event: str
    """activated or deactivated."""
    user_id: str
    at: str


def publisher_of(
    version_id: str,
    published_in: Literal["portal", "n8n"],
    portal_actor: UserId | None,
    timeline: Sequence[PublishEvent],
    people: Mapping[str, UserId],
) -> Publisher | None:
    """Who published a version (D5), never guessed. A Portal publish is the Portal person who
    acted, never the owner account n8n's timeline names. A publish made in n8n is the n8n user
    who last activated that version, matched by the n8n user id stored for each person (`people`),
    never by email or name. Nobody matched is Publisher(None), and a run of that version stops at
    its first call until an Operator matches the person. None when the timeline holds no publish
    of the version yet."""
    if published_in == "portal":
        return None if portal_actor is None else Publisher(portal_actor)
    activated = [e for e in timeline if e.version_id == version_id and e.event == "activated"]
    if not activated:
        return None
    last = max(enumerate(activated), key=lambda pair: (pair[1].at, pair[0]))[1]
    return Publisher(people.get(last.user_id))


@dataclass(frozen=True)
class HistoryEntry:
    version_id: str
    authors: str
    """A display name such as "Alice Tester", never an id (P7 Q4): a hint, never a party."""
    created_at: str


@dataclass(frozen=True)
class N8nProject:
    id: str
    type: str
    name: str


@dataclass(frozen=True)
class ExecutionRecord:
    id: str
    workflow_id: str
    status: str
    mode: str
    retry_of: str | None
    version_id: str | None
    start_nonce: str | None
    failed_node: str | None = None
    """The block whose error ended the execution, or the last block n8n ran."""
    error: str | None = None
    """n8n's error text, when the execution ended in an error."""


@dataclass(frozen=True)
class Written:
    version_id: str
    document: dict[str, Any]


@dataclass(frozen=True)
class StillRetrying:
    """n8n had not answered the retry when the wait ran out: it may be running it, or may yet
    refuse it."""


@dataclass(frozen=True)
class RetryRefused:
    """n8n would not retry the execution, in its own words: it succeeded, a retry of it already
    did, or n8n no longer holds it."""

    detail: str


@dataclass(frozen=True)
class ChangedInN8n:
    """Someone changed the workflow in n8n while the platform wrote it, so the platform's change
    did not land, or was not published. The Portal says "Changed again since, in n8n."."""


class _Data(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _WorkflowOut(_Data):
    id: str
    version_id: str = Field(alias="versionId")
    active_version_id: str | None = Field(default=None, alias="activeVersionId")
    name: str
    nodes: list[dict[str, JsonValue]]
    connections: dict[str, JsonValue]
    settings: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class _RestWorkflow(_Data):
    version_id: str = Field(alias="versionId")
    checksum: str


class _Trigger(_Data):
    node_id: str = Field(alias="nodeId")
    status: str
    error_message: str | None = Field(default=None, alias="errorMessage")


class _Publication(_Data):
    status: str
    live_version_id: str | None = Field(default=None, alias="liveVersionId")
    triggers: list[_Trigger] = Field(default_factory=list[_Trigger])


class _User(_Data):
    id: str


class _TimelineEntry(_Data):
    version_id: str = Field(alias="versionId")
    event: str
    user: _User
    created_at: str = Field(default="", alias="createdAt")


class _HistoryOut(_Data):
    version_id: str = Field(alias="versionId")
    authors: str = ""
    created_at: str = Field(default="", alias="createdAt")


class _ProjectOut(_Data):
    id: str
    type: str
    name: str = ""


class _ExecutionOut(_Data):
    id: str | int
    workflow_id: str | int = Field(alias="workflowId")
    status: str
    mode: str
    retry_of: str | int | None = Field(default=None, alias="retryOf")
    workflow_version_id: str | None = Field(default=None, alias="workflowVersionId")
    data: dict[str, JsonValue] | None = None
    workflow_data: dict[str, JsonValue] | None = Field(default=None, alias="workflowData")


class _KeyOwner(_Data):
    email: str


class _ListedKey(_Data):
    id: str
    label: str
    created_at: str = Field(alias="createdAt")
    owner: _KeyOwner


class _KeyList(_Data):
    items: list[_ListedKey]


class _Page[T](_Data):
    data: list[T]


class _Rest[T](_Data):
    data: T


def _parse[T](model: type[T], response: httpx.Response) -> T:
    try:
        return TypeAdapter(model).validate_python(response.json())
    except ValidationError, ValueError:
        raise N8nError(
            f"{response.request.method} {response.request.url.path} answered in a shape the "
            "platform does not know"
        ) from None


def _expect(response: httpx.Response, *ok: int) -> httpx.Response:
    if response.status_code not in (ok or (200,)):
        raise N8nError(
            f"{response.request.method} {response.request.url.path} failed: {_short(response)}"
        )
    return response


def document_of(workflow: Mapping[str, Any]) -> dict[str, Any]:
    return {key: workflow[key] for key in DOCUMENT_KEYS if key in workflow}


def same_as_sent(sent: Mapping[str, Any], saved: Mapping[str, Any]) -> bool:
    """Whether n8n holds what was sent: the same blocks with every field that was sent, the same
    edges and the same settings. Fields n8n adds of its own are not compared."""
    if sent.get("name") != saved.get("name"):
        return False
    if sent.get("connections") != saved.get("connections"):
        return False
    held = _fields(saved.get("settings"))
    if any(held.get(key) != value for key, value in _fields(sent.get("settings")).items()):
        return False
    saved_nodes = {str(node.get("name")): node for node in _nodes(saved)}
    sent_nodes = _nodes(sent)
    if set(saved_nodes) != {str(node.get("name")) for node in sent_nodes}:
        return False
    return all(
        saved_nodes[str(node.get("name"))].get(key) == value
        for node in sent_nodes
        for key, value in node.items()
    )


def _fields(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _nodes(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [_fields(node) for node in cast(list[object], nodes)]


def _start_nonce(execution: _ExecutionOut) -> str | None:
    """The nonce in the Start from the Portal item, when the execution has one. n8n saves it
    mid-run because every layout sets saveExecutionProgress (P7 Q15)."""
    starts = [
        str(node.get("name"))
        for node in _nodes(execution.workflow_data or {})
        if node.get("type") == START_TYPE
    ]
    for name in starts or [START_NAME]:
        path = ("resultData", "runData", name, 0, "data", "main", 0, 0, "json", "nonce")
        nonce = _at(execution.data, *path)
        if isinstance(nonce, str):
            return nonce
    return None


def _at(value: object, *path: str | int) -> object:
    for step in path:
        if isinstance(step, str):
            value = _fields(value).get(step)
        else:
            items = cast(list[object], value) if isinstance(value, list) else []
            value = items[step] if step < len(items) else None
    return value


def _record_of(execution: _ExecutionOut) -> ExecutionRecord:
    result = ("resultData",)
    node = _at(execution.data, *result, "error", "node", "name") or _at(
        execution.data, *result, "lastNodeExecuted"
    )
    error = _at(execution.data, *result, "error", "message")
    return ExecutionRecord(
        str(execution.id),
        str(execution.workflow_id),
        execution.status,
        execution.mode,
        None if execution.retry_of is None else str(execution.retry_of),
        execution.workflow_version_id,
        _start_nonce(execution),
        node if isinstance(node, str) else None,
        error if isinstance(error, str) else None,
    )


class N8nApi:
    """One per process. It signs in once and makes its own API key once, and again only when n8n
    refuses them. It never deletes a key, so a second process during a deploy keeps working."""

    def __init__(
        self,
        base_url: str,
        owner: N8nOwner,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http = client or httpx.AsyncClient(base_url=base_url, timeout=30)
        self._owner = owner
        self._sleep = sleep
        self._clock = clock
        self._wall = wall
        self._signed_in = False
        self._key: str | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._http.aclose()

    async def _sign_in(self) -> None:
        response = await self._http.post(
            "/rest/login",
            json={"emailOrLdapLoginId": self._owner.email, "password": self._owner.password},
        )
        if response.status_code != 200:
            raise N8nError(f"could not sign in to n8n as its owner: HTTP {response.status_code}")
        self._signed_in = True

    async def _rest(
        self,
        method: str,
        path: str,
        json: Any | None = None,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        async with self._lock:
            if not self._signed_in:
                await self._sign_in()
        response = await self._http.request(method, f"/rest{path}", json=json, params=params)
        if response.status_code == 401:
            async with self._lock:
                await self._sign_in()
            response = await self._http.request(method, f"/rest{path}", json=json, params=params)
        return response

    async def _api_key(self, refused: str | None = None) -> str:
        async with self._lock:
            if self._key is not None and self._key != refused:
                return self._key
        await self._remove_stale_keys()
        expires = int((self._wall() + KEY_LIFETIME).timestamp())
        body = {
            "label": PLATFORM_API_KEY_LABEL,
            "expiresAt": expires,
            "scopes": list(PLATFORM_API_SCOPES),
        }
        created = _expect(await self._rest("POST", "/api-keys", body))
        key = _parse(_Rest[dict[str, JsonValue]], created).data.get("rawApiKey")
        if not isinstance(key, str):
            raise N8nError("n8n made an API key but did not show it")
        async with self._lock:
            self._key = key
        return key

    async def _remove_stale_keys(self) -> None:
        """The platform's own keys older than a day, which an earlier process or a key that ran
        out left behind. A key another process made today is left alone, and so is any key of
        someone else's, whatever its label."""
        listed = _parse(_Rest[_KeyList], _expect(await self._rest("GET", "/api-keys"))).data
        cutoff = self._wall() - STALE_KEY_AGE
        for key in listed.items:
            ours = key.label == PLATFORM_API_KEY_LABEL and key.owner.email == self._owner.email
            if ours and datetime.fromisoformat(key.created_at) < cutoff:
                _expect(await self._rest("DELETE", f"/api-keys/{key.id}"))

    async def _public(
        self,
        method: str,
        path: str,
        json: Any | None = None,
        params: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        async def send(key: str) -> httpx.Response:
            return await self._http.request(
                method,
                f"/api/v1{path}",
                json=json,
                params=params,
                headers={"X-N8N-API-KEY": key},
                timeout=timeout or httpx.USE_CLIENT_DEFAULT,
            )

        key = await self._api_key()
        response = await send(key)
        if response.status_code == 401:
            response = await send(await self._api_key(refused=key))
        return response

    async def create(self, document: Mapping[str, Any]) -> N8nWorkflow:
        """Saves a new workflow as a draft. n8n gives it its id."""
        created = _parse(_WorkflowOut, _expect(await self._public("POST", "/workflows", document)))
        return _workflow(created)

    async def workflow(self, workflow_id: str) -> N8nWorkflow | None:
        response = await self._public("GET", f"/workflows/{workflow_id}")
        if response.status_code == 404:
            return None
        return _workflow(_parse(_WorkflowOut, _expect(response)))

    async def delete(self, workflow_id: str) -> None:
        """A draft that was never published. n8n refuses a published one (P7 Q8)."""
        _expect(await self._public("DELETE", f"/workflows/{workflow_id}"), 200, 404)

    async def version(self, workflow_id: str, version_id: str) -> dict[str, Any] | None:
        """A version n8n still holds. Community keeps a day of history (P7 Q7)."""
        response = await self._public("GET", f"/workflows/{workflow_id}/versions/{version_id}")
        if response.status_code == 404:
            return None
        return document_of(_parse(dict[str, Any], _expect(response)))

    async def history(self, workflow_id: str) -> list[HistoryEntry]:
        response = _expect(await self._public("GET", f"/workflows/{workflow_id}/history"))
        return [
            HistoryEntry(item.version_id, item.authors, item.created_at)
            for item in _parse(_Page[_HistoryOut], response).data
        ]

    async def publish(self, workflow_id: str, version_id: str) -> None:
        """Puts a version n8n holds live and leaves the draft alone, so no open editor can
        overwrite it (P7 Q7)."""
        body = {"versionId": version_id}
        _expect(await self._public("POST", f"/workflows/{workflow_id}/publish", body))

    async def unpublish(self, workflow_id: str) -> None:
        """Takes the workflow off, so none of its triggers runs it. Nothing to do when nothing is
        published."""
        workflow = await self.workflow(workflow_id)
        if workflow is None or workflow.active_version_id is None:
            return
        _expect(await self._public("POST", f"/workflows/{workflow_id}/unpublish", {}))

    async def run_draft(self, workflow_id: str, item: Mapping[str, Any]) -> str:
        """/rest: runs the draft by hand from Start from the Portal with this item as its output,
        and answers the execution's id at once (P7 Q3, body B). n8n runs the stored draft."""
        body: dict[str, Any] = {
            "triggerToStartFrom": {
                "name": START_NAME,
                "data": {
                    "startTime": 0,
                    "executionTime": 0,
                    "source": [],
                    "data": {"main": [[{"json": dict(item)}]]},
                },
            }
        }
        response = _expect(await self._rest("POST", f"/workflows/{workflow_id}/run", body))
        execution = _parse(_Rest[dict[str, JsonValue]], response).data.get("executionId")
        if not isinstance(execution, str | int) or isinstance(execution, bool) or not execution:
            raise N8nError(f"n8n did not start a run of {workflow_id}")
        return str(execution)

    async def retry(
        self, execution_id: str, wait: float = RETRY_WAIT_SECONDS
    ) -> RetryRefused | StillRetrying | None:
        """n8n's own retry, from the block that stopped, on the version that ran (P7 Q5). n8n
        answers only once the retry stops, so a wait that runs out says nothing yet. None when
        it took it. Raises when n8n could not be asked."""
        try:
            response = await self._public(
                "POST",
                f"/executions/{execution_id}/retry",
                {"loadWorkflow": False},
                timeout=httpx.Timeout(10.0, read=wait),
            )
        except httpx.ReadTimeout:
            return StillRetrying()
        if response.status_code in (400, 404, 409):
            return RetryRefused(_short(response))
        _expect(response)
        return None

    async def transfer(self, workflow_id: str, project_id: str) -> None:
        body = {"destinationProjectId": project_id}
        _expect(await self._public("PUT", f"/workflows/{workflow_id}/transfer", body), 200, 204)

    async def execution(self, execution_id: str, data: bool = True) -> ExecutionRecord | None:
        """With data, the start item and a failure's block and words too. Without, its status
        and links only, which is all the sweep reads every few seconds."""
        params = {"includeData": "true" if data else "false"}
        response = await self._public("GET", f"/executions/{execution_id}", params=params)
        if response.status_code == 404:
            return None
        return _record_of(_parse(_ExecutionOut, _expect(response)))

    async def executions(
        self, workflow_id: str, status: str | None = None
    ) -> list[ExecutionRecord]:
        """The newest hundred, without their data."""
        params = {"workflowId": workflow_id, "limit": "100"}
        if status is not None:
            params["status"] = status
        response = _expect(await self._public("GET", "/executions", params=params))
        return [_record_of(item) for item in _parse(_Page[_ExecutionOut], response).data]

    async def publication_status(self, workflow_id: str) -> PublicationStatus:
        """/rest: whether n8n has moved every trigger over (P7 Q19)."""
        response = _expect(await self._rest("GET", f"/workflows/{workflow_id}/publication-status"))
        out = _parse(_Rest[_Publication], response).data
        triggers = tuple(TriggerStatus(t.node_id, t.status, t.error_message) for t in out.triggers)
        return PublicationStatus(out.status, out.live_version_id, triggers)

    async def wait_published(
        self, workflow_id: str, timeout: float = PUBLISH_WAIT_SECONDS
    ) -> PublicationStatus:
        """Until n8n reads published with every trigger activated. It reads in_progress while it
        moves the triggers. Raises N8nError when that takes longer than `timeout`."""
        deadline = self._clock() + timeout
        while True:
            status = await self.publication_status(workflow_id)
            if status.published:
                return status
            if self._clock() > deadline:
                raise N8nError(f"n8n did not finish publishing {workflow_id} in {timeout:g} s")
            await self._sleep(0.5)

    async def publish_timeline(self, workflow_id: str) -> list[PublishEvent]:
        """/rest: who published or unpublished each version, by n8n user id (P7 Q19)."""
        response = _expect(
            await self._rest("GET", f"/workflow-history/workflow/{workflow_id}/publish-timeline")
        )
        return [
            PublishEvent(e.version_id, e.event, e.user.id, e.created_at)
            for e in _parse(_Rest[list[_TimelineEntry]], response).data
        ]

    async def projects(self) -> list[N8nProject]:
        """/rest: every project, a member's personal one included, because the public /projects
        is 403 on Community (P7 Q9)."""
        response = _expect(await self._rest("GET", "/projects"))
        return [
            N8nProject(p.id, p.type, p.name)
            for p in _parse(_Rest[list[_ProjectOut]], response).data
        ]

    async def write(
        self,
        workflow_id: str,
        expected_version_id: str,
        change: Callable[[dict[str, Any]], Mapping[str, Any]],
        *,
        publish: bool = True,
    ) -> Written | ChangedInN8n:
        """Changes the draft and publishes it, refusing whenever the workflow changed under the
        platform (ENGINE-PLAN 2.5, P7 Q18). The public PUT cannot compare by itself, so: read and
        compare the draft's version, PUT without publishing, read back and compare what n8n
        holds, then publish through /rest with the draft's checksum, which n8n refuses with 409
        when anything saved the draft in between. An open editor tab's autosave never wins.
        With publish False the change stays a draft, for a workflow that is not on."""
        before = await self.workflow(workflow_id)
        if before is None or before.version_id != expected_version_id:
            return ChangedInN8n()
        wanted = document_of(change(before.document))
        put = await self._public(
            "PUT", f"/workflows/{workflow_id}", wanted, params={"publishIfActive": "false"}
        )
        ours = _parse(_WorkflowOut, _expect(put)).version_id
        after = await self.workflow(workflow_id)
        if after is None or not same_as_sent(wanted, after.document) or after.version_id != ours:
            return ChangedInN8n()
        if not publish:
            return Written(after.version_id, after.document)
        draft = _parse(
            _Rest[_RestWorkflow], _expect(await self._rest("GET", f"/workflows/{workflow_id}"))
        ).data
        if draft.version_id != ours:
            return ChangedInN8n()
        published = await self._rest(
            "POST",
            f"/workflows/{workflow_id}/activate",
            {"versionId": draft.version_id, "expectedChecksum": draft.checksum},
        )
        if published.status_code == 409:
            return ChangedInN8n()
        _expect(published)
        return Written(after.version_id, after.document)


def _workflow(out: _WorkflowOut) -> N8nWorkflow:
    document = {
        "name": out.name,
        "nodes": out.nodes,
        "connections": out.connections,
        "settings": out.settings,
    }
    return N8nWorkflow(out.id, out.version_id, out.active_version_id, document)


ERROR_WORKFLOW_NAME = "run_failure_reporter"


class N8nExecutions:
    """n8n's records of executions, through its public API (ENGINE-PLAN 2.3)."""

    def __init__(self, api: N8nApi) -> None:
        self._api = api

    async def _record(self, execution_id: str, data: bool = True) -> ExecutionRecord | None:
        try:
            return await self._api.execution(execution_id, data)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read n8n execution %s: %s", execution_id, error)
            return None

    async def execution(self, execution_id: N8nExecutionId) -> ExecutionFacts | None:
        """None unless n8n says the execution is running or waiting, so nothing is stored for an
        execution n8n does not vouch for."""
        record = await self._record(execution_id)
        if record is None or record.status not in VOUCHED:
            return None
        retry_of = None if record.retry_of is None else N8nExecutionId(record.retry_of)
        return ExecutionFacts(
            record.workflow_id, record.mode, retry_of, record.start_nonce, record.version_id
        )

    async def landed(self, execution_id: N8nExecutionId) -> bool:
        """Whether n8n shows the execution running or finished, after a wake met a 409."""
        record = await self._record(execution_id, data=False)
        return record is not None and record.status in LANDED


@dataclass(frozen=True)
class SavedDraft:
    workflow_id: str
    version_id: str
    document: dict[str, Any]
    """What n8n holds, which is what the platform keeps as this version's record."""


class N8nDrafts(Protocol):
    """Where the builder keeps each use case's own n8n workflow. Every call but remove raises
    N8nError or httpx.HTTPError when n8n did not do what was asked."""

    async def error_workflow_id(self) -> str | None: ...

    async def save_draft(self, document: Mapping[str, Any]) -> SavedDraft: ...

    async def remove(self, workflow_id: str) -> None: ...

    async def go_live(self, workflow_id: str, version_id: str) -> None:
        """Publishes exactly this version and returns once n8n has every trigger live."""
        ...

    async def go_off(self, workflow_id: str) -> None: ...

    async def change(
        self, workflow_id: str, expected_version_id: str, document: Mapping[str, Any], live: bool
    ) -> Written | ChangedInN8n:
        """Saves the document over the version the platform last stored, under the version
        compare, and puts it live when `live`."""
        ...


class N8nWorkflows:
    """Where the builder saves the Planner's layouts, as drafts nobody has published, and where
    failure reports and the sweep read n8n's record of failed executions (ENGINE-PLAN 2.8)."""

    def __init__(self, api: N8nApi, db: Database) -> None:
        self._api = api
        self._db = db

    async def error_workflow_id(self) -> str | None:
        """The platform's error workflow, as bootstrap last loaded it."""
        async with self._db.connection("orchestration") as conn:
            row = await (
                await conn.execute("SELECT workflows FROM orchestration.engine_status WHERE id = 1")
            ).fetchone()
        loaded: list[dict[str, Any]] = [] if row is None else row["workflows"]
        return next((str(w["id"]) for w in loaded if w.get("name") == ERROR_WORKFLOW_NAME), None)

    async def save_draft(self, document: Mapping[str, Any]) -> SavedDraft:
        """Creates the workflow, then reads it back and compares, because n8n may keep something
        other than what was sent. A draft that did not land as sent is removed again."""
        created = await self._api.create(document)
        held = await self._api.workflow(created.id)
        if held is None or not same_as_sent(document, held.document):
            await self.remove(created.id)
            raise N8nError("n8n did not keep the draft as the platform sent it")
        return SavedDraft(held.id, held.version_id, held.document)

    async def remove(self, workflow_id: str) -> None:
        try:
            await self._api.delete(workflow_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not remove n8n draft %s: %s", workflow_id, error)

    async def go_live(self, workflow_id: str, version_id: str) -> None:
        """The version the platform graded and stored, never whatever the draft holds now, so
        what runs is what was checked (ENGINE-PLAN 2.5). n8n keeps the draft and the published
        versions, so the stored one is there to publish."""
        await self._api.publish(workflow_id, version_id)
        await self._live(workflow_id, version_id)

    async def go_off(self, workflow_id: str) -> None:
        await self._api.unpublish(workflow_id)

    async def change(
        self, workflow_id: str, expected_version_id: str, document: Mapping[str, Any], live: bool
    ) -> Written | ChangedInN8n:
        written = await self._api.write(
            workflow_id, expected_version_id, lambda _: dict(document), publish=live
        )
        if live and isinstance(written, Written):
            await self._live(workflow_id, written.version_id)
        return written

    async def _live(self, workflow_id: str, version_id: str) -> None:
        status = await self._api.wait_published(workflow_id)
        if status.live_version_id != version_id:
            raise N8nError(f"n8n has another version of {workflow_id} live")

    async def ended(self, execution_id: N8nExecutionId) -> Ended | None:
        """Its status alone, and its data only once it failed, for the block and the words."""
        try:
            record = await self._api.execution(execution_id, data=False)
            if record is not None and record.status in ENDED - {"success"}:
                record = await self._api.execution(execution_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read n8n execution %s: %s", execution_id, error)
            return None
        if record is None or record.status not in ENDED:
            return None
        if record.status == "success":
            return Finished(execution_id)
        return FailedExecution(execution_id, record.failed_node, record.error)

    async def failure(self, execution_id: N8nExecutionId) -> FailedExecution | None:
        """The block that failed and n8n's words for it, from n8n's own record. None unless n8n
        has the execution and it ended in an error."""
        try:
            record = await self._api.execution(execution_id)
        except (N8nError, httpx.HTTPError) as error:
            log.warning("could not read n8n execution %s: %s", execution_id, error)
            return None
        if record is None or record.status != "error":
            return None
        return FailedExecution(execution_id, record.failed_node, record.error)
