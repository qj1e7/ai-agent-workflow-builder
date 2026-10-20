"""Stand-in for agent-runtime. Replays the contract fixtures, standard library only."""

import json
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path("/fixtures")
MODES = {"finished": "task-finished.json", "failed": "task-failed.json"}
state = {"mode": "finished"}


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def post_event(callback: dict, task_id: str, event: dict) -> None:
    request = urllib.request.Request(
        callback["url"],
        data=json.dumps({"task_id": task_id, "event": event}).encode(),
        headers={"Content-Type": "application/json", "X-Callback-Token": callback["token"]},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=5).close()
    except Exception as error:
        print(f"callback failed (ignored): {error}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def reply(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.reply(200, {"status": "ok"})
        elif self.path == "/v1/agents":
            self.reply(200, load("agent-cards.json"))
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self.read_json()
        if self.path == "/_admin/mode":
            mode = body.get("mode")
            if mode not in MODES:
                self.reply(422, {"error": "mode must be finished or failed"})
                return
            state["mode"] = mode
            self.reply(200, {"mode": mode})
        elif self.path == "/v1/tasks":
            result = load(MODES[state["mode"]])
            task_id = body["task_id"]
            callback = body.get("callback")
            if callback:
                for event in result.get("events", []):
                    post_event(callback, task_id, event)
            self.reply(200, {**result, "task_id": task_id})
        else:
            self.reply(404, {"error": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8100), Handler).serve_forever()
