"""The spike's two stand-ins, standard library only.

On 8600, a stand-in for the simulation gateway (ADR 0054, section 3). It answers our blocks as
platform-api does at {WAB_API_URL}/internal/v1/n8n/..., with the differences the ADR names: it
checks the simulation's own node key, links each call to its execution by the start item's nonce
in n8n's own record (as platform-api's decide_link does), answers Read with the scenario's data,
answers Ask for a yes by waking the execution with the scenario's decision, refuses every write
and sends nothing for Tell. It keeps every call in memory for the driver to read.

On 8700, a stand-in for an outside system that n8n's own blocks call: GitHub's releases and Jira's
REST API. It can answer, answer not found, hold the connection or drop it, and it keeps each
request it got.

It is not the gateway PR 3 will build. It holds no key but the simulation's made-up node key.
"""

import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

NODE_KEY = os.environ["SIM_NODE_KEY"]
N8N_URL = os.environ.get("N8N_URL", "http://n8n:5678")
START_NAME = "Start from the Portal"
START_TYPE = "CUSTOM.wabStartFromPortal"

lock = threading.Lock()
state: dict[str, Any] = {
    "n8n_api_key": None,
    "scenario": {"read": "ok", "ask": "no"},
    "calls": [],
    "wakes": [],
    "upstream_mode": "ok",
    "hold_seconds": 60,
    "seen": [],
}

RELEASES = [
    {"tag_name": "1.2.16", "name": "1.2.16", "published_at": "2026-10-28T09:00:00Z",
     "html_url": "https://github.com/langchain-ai/langgraph/releases/tag/1.2.16",
     "prerelease": False, "draft": False},
    {"tag_name": "1.2.15", "name": "1.2.15", "published_at": "2026-10-21T09:00:00Z",
     "html_url": "https://github.com/langchain-ai/langgraph/releases/tag/1.2.15",
     "prerelease": False, "draft": False},
]  # fmt: skip
ISSUE = {"id": "10001", "key": "MOCK-1", "fields": {"summary": "Simulated issue", "status": {"name": "To Do"}}}


def n8n_execution(execution_id: str) -> dict[str, Any] | None:
    key = state["n8n_api_key"]
    if not key:
        return None
    request = urllib.request.Request(
        f"{N8N_URL}/api/v1/executions/{execution_id}?includeData=true",
        headers={"X-N8N-API-KEY": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return json.loads(answer.read())
    except urllib.error.URLError:
        return None


def at(value: Any, *path: Any) -> Any:
    for step in path:
        if isinstance(step, str):
            value = value.get(step) if isinstance(value, dict) else None
        else:
            value = value[step] if isinstance(value, list) and step < len(value) else None
    return value


def link(execution_id: str) -> dict[str, Any]:
    """What platform-api's _link reads first: n8n's status and mode, and the start item's nonce."""
    record = n8n_execution(execution_id)
    if record is None:
        return {"linked": False, "why": "n8n did not answer for this execution"}
    starts = [
        n.get("name") for n in (at(record, "workflowData", "nodes") or []) if n.get("type") == START_TYPE
    ] or [START_NAME]
    nonce = None
    for name in starts:
        nonce = at(record, "data", "resultData", "runData", name, 0, "data", "main", 0, 0, "json", "nonce")
        if isinstance(nonce, str):
            break
    return {
        "linked": isinstance(nonce, str) and record.get("status") in ("running", "waiting"),
        "status": record.get("status"),
        "mode": record.get("mode"),
        "nonce": nonce,
        "version_id": record.get("workflowVersionId"),
    }


def wake_later(resume_url: str, execution_id: str, request_id: str, decision: str) -> None:
    mac = hmac.new(NODE_KEY.encode(), f"{execution_id}\n{request_id}\n{decision}".encode(), hashlib.sha256).hexdigest()
    body = json.dumps({"execution_id": execution_id, "request_id": request_id, "decision": decision, "mac": mac})
    time.sleep(1.0)
    outcome: dict[str, Any] = {"execution_id": execution_id, "decision": decision, "tries": 0}
    for _ in range(20):
        outcome["tries"] += 1
        request = urllib.request.Request(
            resume_url, data=body.encode(), method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                outcome["status"] = answer.status
                break
        except urllib.error.HTTPError as error:
            outcome["status"] = error.code
        except urllib.error.URLError as error:
            outcome["status"] = str(error.reason)
        time.sleep(0.5)
    with lock:
        state["wakes"].append(outcome)


class Gateway(BaseHTTPRequestHandler):
    def reply(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.reply(200, {"ok": True})
        elif self.path == "/_admin/calls":
            with lock:
                self.reply(200, {"calls": state["calls"], "wakes": state["wakes"]})
        elif self.path.startswith("/internal/v1/n8n/options"):
            self.reply(200, {"options": []})
        else:
            self.reply(404, {"detail": "Not found"})

    def do_POST(self) -> None:
        path = self.path
        body = self.body()
        if path == "/_admin/n8n-key":
            state["n8n_api_key"] = body["key"]
            return self.reply(200, {"ok": True})
        if path == "/_admin/scenario":
            with lock:
                state["scenario"] = body
            return self.reply(200, {"ok": True})
        if path == "/_admin/reset":
            with lock:
                state["calls"].clear()
                state["wakes"].clear()
            return self.reply(200, {"ok": True})
        prefix = "/internal/v1/n8n/"
        if not path.startswith(prefix):
            return self.reply(404, {"detail": "Not found"})
        kind = path[len(prefix) :]
        if not hmac.compare_digest(self.headers.get("X-Wab-Node-Key", ""), NODE_KEY):
            return self.reply(401, {"detail": "Not the simulation's node key."})
        execution_id = str(body.get("execution_id") or "")
        scenario = state["scenario"]
        call = {
            "kind": kind,
            "node": body.get("node_name"),
            "mode": body.get("mode"),
            "execution_id": execution_id,
            "at": time.time(),
            "link": link(execution_id) if kind != "failures" else None,
            "failed": {k: body.get(k) for k in ("failed_execution_id", "failed_mode", "last_node_executed")} if kind == "failures" else None,
        }
        with lock:
            state["calls"].append(call)
        match kind:
            case "calls/read":
                read = scenario.get("read", "ok")
                if read == "not_found":
                    return self.reply(404, {"detail": "The source was not found (simulated)."})
                if read == "timeout":
                    return self.reply(504, {"detail": "The source did not answer in time (simulated)."})
                return self.reply(200, {"items": [] if read == "empty" else RELEASES[:1]})
            case "calls/agent":
                return self.reply(200, {"items": [{"summary": "A recorded reply: 1.2.16 is new."}]})
            case "calls/propose":
                return self.reply(200, {})
            case "calls/ask":
                request_id = f"simreq-{secrets.token_hex(6)}"
                decision = scenario.get("ask", "no")
                threading.Thread(
                    target=wake_later,
                    args=(body["resume_url"], execution_id, request_id, decision),
                    daemon=True,
                ).start()
                return self.reply(200, {"status": "waiting", "request_id": request_id})
            case "calls/write":
                return self.reply(403, {"detail": "A simulation never writes."})
            case "calls/tell":
                return self.reply(200, {"status": "would_have_sent", "line": "Nothing was sent."})
            case "failures":
                return self.reply(200, {"status": "failed", "run_id": "sim", "detail": "recorded"})
        return self.reply(404, {"detail": "Not a call this stand-in knows."})

    def log_message(self, format: str, *args: Any) -> None:
        return


class Upstream(BaseHTTPRequestHandler):
    def reply(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/_admin/mode":
            with lock:
                state["upstream_mode"] = body.get("mode", "ok")
                state["hold_seconds"] = int(body.get("hold_seconds", 60))
                state["seen"].clear()
            return self.reply(200, {"mode": state["upstream_mode"]})
        self.reply(404, {"message": "Not Found"})

    def do_GET(self) -> None:
        if self.path == "/healthz":
            return self.reply(200, {"ok": True})
        if self.path == "/_admin/seen":
            with lock:
                return self.reply(200, {"seen": state["seen"]})
        auth = self.headers.get("Authorization", "")
        with lock:
            mode = state["upstream_mode"]
            state["seen"].append(
                {"path": self.path, "auth": auth.split(" ")[0] if auth else None, "at": time.time(), "mode": mode}
            )
        if mode == "drop":
            # Took the request, then closed the connection without a word.
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        if mode == "hold":
            time.sleep(state["hold_seconds"])
        if mode == "not_found":
            return self.reply(404, {"message": "Not Found"})
        if "/releases" in self.path:
            return self.reply(200, RELEASES)
        if self.path.startswith("/rest/api/"):
            return self.reply(200, ISSUE)
        self.reply(404, {"message": "Not Found"})

    def log_message(self, format: str, *args: Any) -> None:
        return


if __name__ == "__main__":
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", 8700), Upstream).serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8600), Gateway).serve_forever()
