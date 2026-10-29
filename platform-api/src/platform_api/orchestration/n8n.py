"""The owner and API key calls use n8n's internal `/rest` API with a login cookie, so the pinned
n8n version matters. Everything else goes through the public `/api/v1` API with the key.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

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

    def _login(self, email: str, password: str) -> None:
        response = self._http.post(
            "/rest/login", json={"emailOrLdapLoginId": email, "password": password}
        )
        if response.status_code != 200:
            raise N8nError(f"could not sign in as {email}: HTTP {response.status_code}")

    def fresh_api_key(self, label: str) -> int:
        listed = self._rest("GET", "/rest/api-keys")
        stale = [item for item in listed["data"]["items"] if item["label"] == label]
        for item in stale:
            self._rest("DELETE", f"/rest/api-keys/{item['id']}")
        created = self._rest(
            "POST",
            "/rest/api-keys",
            json={"label": label, "expiresAt": None, "scopes": list(API_KEY_SCOPES)},
        )
        self._api_key = str(created["data"]["rawApiKey"])
        return len(stale)

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


def _short(response: httpx.Response) -> str:
    return f"HTTP {response.status_code} {response.text[:200]}"
