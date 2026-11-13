"""n8n 2.42.6's answers to the calls the platform makes while it runs, as spike P7 recorded them
(docs/evidence/prototypes/p7-n8n-engine-facts), kept in memory."""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "Aa1-owner-password"
OWNER_ID = "ef530bdb-d627-4255-ad0a-b678b6c7c5bb"
ACTIVATED = {"status": "published", "triggers": "activated"}

type Hook = Callable[[str], None]


def _new_version() -> str:
    return str(uuid.uuid4())


@dataclass
class FakeN8n:
    workflows: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    executions: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    timeline: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict[str, list[dict[str, Any]]]
    )
    publishing: list[str] = field(default_factory=list[str])
    """publication-status answers still to give, in_progress first, before published."""
    projects: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    keys: list[str] = field(default_factory=list[str])
    listed_keys: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    """The API keys n8n lists, each with its label, owner and when it was made."""
    key_requests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    logins: int = 0
    minted: int = 0
    deleted_keys: int = 0
    calls: list[str] = field(default_factory=list[str])
    after_put: Hook | None = None
    after_checksum_read: Hook | None = None
    keeps: Callable[[dict[str, Any]], dict[str, Any]] = lambda document: document
    """What n8n keeps of a document it is sent. Unchanged unless a test says otherwise."""

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://n8n")

    def edit(self, workflow_id: str) -> None:
        """Someone saves the draft in n8n's editor."""
        workflow = self.workflows[workflow_id]
        workflow["versionId"] = _new_version()
        workflow["checksum"] = _new_version()
        workflow["nodes"][0]["notes"] = "changed in the editor"

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        body: Any = json.loads(request.content) if request.content else None
        if path == "/rest/login":
            return self._login(body)
        if path.startswith("/rest/"):
            if "n8n-auth=owner" not in request.headers.get("cookie", ""):
                return httpx.Response(401, json={"message": "Unauthorized"})
            return self._rest(request.method, path.removeprefix("/rest"), body)
        if request.headers.get("X-N8N-API-KEY") not in self.keys:
            return httpx.Response(401, json={"message": "'X-N8N-API-KEY' header required"})
        return self._public(request, path.removeprefix("/api/v1"), body)

    def _login(self, body: dict[str, Any]) -> httpx.Response:
        if (body["emailOrLdapLoginId"], body["password"]) != (OWNER_EMAIL, OWNER_PASSWORD):
            return httpx.Response(401, json={"message": "Wrong username or password."})
        self.logins += 1
        return httpx.Response(200, json={"data": {}}, headers={"set-cookie": "n8n-auth=owner"})

    def _rest(self, method: str, path: str, body: Any) -> httpx.Response:
        match method, path.strip("/").split("/"):
            case "GET", ["api-keys", "scopes"]:
                return httpx.Response(200, json={"data": ["workflow:read", "execution:read"]})
            case "GET", ["api-keys"]:
                items = self.listed_keys
                return httpx.Response(200, json={"data": {"items": items, "count": len(items)}})
            case "POST", ["api-keys"]:
                self.minted += 1
                key = f"key-{self.minted}"
                self.keys.append(key)
                self.key_requests.append(body)
                return httpx.Response(200, json={"data": {"rawApiKey": key}})
            case "DELETE", ["api-keys", key_id]:
                self.deleted_keys += 1
                self.listed_keys = [k for k in self.listed_keys if k["id"] != key_id]
                return httpx.Response(200, json={"data": True})
            case "GET", ["workflows", workflow_id]:
                workflow = self.workflows[workflow_id]
                answer = {"versionId": workflow["versionId"], "checksum": workflow["checksum"]}
                if self.after_checksum_read is not None:
                    self.after_checksum_read(workflow_id)
                return httpx.Response(200, json={"data": answer})
            case "POST", ["workflows", workflow_id, "activate"]:
                workflow = self.workflows[workflow_id]
                expected = body.get("expectedChecksum", workflow["checksum"])
                if expected != workflow["checksum"]:
                    return httpx.Response(409, json={"code": 409, "message": "Your most recent"})
                self._activate(workflow_id, body["versionId"])
                return httpx.Response(200, json={"data": {"versionId": body["versionId"]}})
            case "GET", ["workflows", workflow_id, "publication-status"]:
                status = self.publishing.pop(0) if self.publishing else "published"
                live = self.workflows[workflow_id]["activeVersionId"]
                trigger = "activated" if status == "published" else "pending"
                answer = {
                    "status": status,
                    "liveVersionId": live,
                    "pendingVersionId": None,
                    "triggers": [{"nodeId": "n1", "status": trigger, "errorMessage": None}],
                }
                return httpx.Response(200, json={"data": answer})
            case "GET", ["workflow-history", "workflow", workflow_id, "publish-timeline"]:
                return httpx.Response(200, json={"data": self.timeline.get(workflow_id, [])})
            case "GET", ["projects"]:
                return httpx.Response(200, json={"data": self.projects})
            case _:
                return httpx.Response(404, json={"message": f"no /rest{path} in the fake"})

    def _activate(self, workflow_id: str, version_id: str, user_id: str = OWNER_ID) -> None:
        self.workflows[workflow_id]["activeVersionId"] = version_id
        self.timeline.setdefault(workflow_id, []).append(
            {"versionId": version_id, "event": "activated", "user": {"id": user_id}}
        )

    def _public(self, request: httpx.Request, path: str, body: Any) -> httpx.Response:
        parts = path.strip("/").split("/")
        match request.method, parts:
            case "POST", ["workflows"]:
                workflow_id = f"wf{len(self.workflows) + 1}"
                self.workflows[workflow_id] = {
                    **self.keeps(json.loads(json.dumps(body))),
                    "id": workflow_id,
                    "versionId": _new_version(),
                    "checksum": _new_version(),
                    "activeVersionId": None,
                    "active": False,
                }
                return httpx.Response(200, json=self.workflows[workflow_id])
            case "GET", ["workflows", workflow_id] if workflow_id in self.workflows:
                return httpx.Response(200, json=self.workflows[workflow_id])
            case "DELETE", ["workflows", workflow_id] if workflow_id in self.workflows:
                return httpx.Response(200, json=self.workflows.pop(workflow_id))
            case "PUT", ["workflows", workflow_id] if workflow_id in self.workflows:
                if "versionId" in body:
                    return httpx.Response(400, json={"message": "versionId is read-only"})
                workflow = self.workflows[workflow_id]
                workflow.update(self.keeps(json.loads(json.dumps(body))))
                workflow["versionId"] = _new_version()
                workflow["checksum"] = _new_version()
                if request.url.params.get("publishIfActive") != "false" and workflow["active"]:
                    self._activate(workflow_id, workflow["versionId"])
                answer = httpx.Response(200, json=workflow)
                if self.after_put is not None:
                    self.after_put(workflow_id)
                return answer
            case "POST", ["workflows", workflow_id, "publish"]:
                self._activate(workflow_id, body["versionId"])
                return httpx.Response(200, json=self.workflows[workflow_id])
            case "PUT", ["workflows", workflow_id, "transfer"]:
                self.workflows[workflow_id]["projectId"] = body["destinationProjectId"]
                return httpx.Response(204)
            case "GET", ["executions", execution_id] if execution_id in self.executions:
                return httpx.Response(200, json=self.executions[execution_id])
            case "GET", ["executions"]:
                wanted = request.url.params.get("workflowId")
                status = request.url.params.get("status")
                found = [
                    e
                    for e in self.executions.values()
                    if e["workflowId"] == wanted and status in (None, e["status"])
                ]
                return httpx.Response(200, json={"data": found})
            case _:
                return httpx.Response(404, json={"message": f"no {path} in the fake"})

    def execution(
        self,
        execution_id: str,
        status: str,
        *,
        workflow_id: str = "wf1",
        mode: str = "webhook",
        nonce: str | None = None,
        version_id: str | None = "v1",
        retry_of: str | None = None,
        failed: tuple[str, str] | None = None,
        last_node: str | None = None,
    ) -> None:
        run_data = (
            {}
            if nonce is None
            else {
                "Start from the Portal": [
                    {"data": {"main": [[{"json": {"nonce": nonce, "kind": "run_now"}}]]}}
                ]
            }
        )
        self.executions[execution_id] = {
            "id": execution_id,
            "workflowId": workflow_id,
            "status": status,
            "mode": mode,
            "retryOf": retry_of,
            "workflowVersionId": version_id,
            "data": {"resultData": {"runData": run_data}},
        }
        result = self.executions[execution_id]["data"]["resultData"]
        if last_node is not None:
            result["lastNodeExecuted"] = last_node
        if failed is not None:
            node, message = failed
            result["error"] = {"message": message, "node": {"name": node, "type": "CUSTOM.wabRead"}}
