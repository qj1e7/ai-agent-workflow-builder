"""Stand-in for our API in P6. It keeps its own records of runs, proposals and decisions.

The node pack calls /agents, /agent, /ask and /write. The test scripts drive /_decide (an
Approver decides through our API, which then wakes n8n) and /_forge (someone wakes n8n with
the resume URL, and our API records nothing). /write decides only from these records.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
RUNS: dict[str, dict] = {}  # n8n execution id -> run
LOG: list[dict] = []
AGENTS = [
    {"id": "version_checker", "name": "Version checker"},
    {"id": "ticket_writer", "name": "Ticket writer"},
]


def run_for(execution_id: str, workflow_id: str | None) -> dict:
    with LOCK:
        if execution_id not in RUNS:
            RUNS[execution_id] = {
                "run_id": f"run-{len(RUNS) + 1}",
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "proposal": [],
                "request": None,
                "done": False,
            }
        return RUNS[execution_id]


def wake(resume_url: str, decision: str) -> tuple[int, str]:
    req = urllib.request.Request(
        resume_url,
        data=json.dumps({"decision": decision}).encode(),
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def reply(self, status: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/agents":
            return self.reply(200, AGENTS)
        if self.path == "/_log":
            return self.reply(200, LOG)
        if self.path == "/_runs":
            return self.reply(200, list(RUNS.values()))
        self.reply(404, {"error": "no route"})

    def do_POST(self) -> None:
        size = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(size) or b"{}")
        LOG.append({"path": self.path, "body": body})
        ex, wf = str(body.get("execution_id", "")), body.get("workflow_id")

        if self.path == "/agent":
            run = run_for(ex, wf)
            said = {"version_checker": "LangGraph 1.2.14 has a newer version, 1.2.17."}.get(body["agent"], "I drafted 1 ticket.")
            if body["agent"] == "ticket_writer":
                run["proposal"].append({"system": "jira", "project": "MOCK", "title": "Upgrade LangGraph to 1.2.17"})
            return self.reply(200, {"run_id": run["run_id"], "agent": body["agent"], "said": said})

        if self.path == "/ask":
            run = run_for(ex, wf)
            run["request"] = {"status": "pending", "resume_url": body["resume_url"]}
            return self.reply(200, {"run_id": run["run_id"], "asked": True})

        if self.path == "/write":
            run = run_for(ex, wf)
            req = run["request"]
            if not run["proposal"]:
                return self.reply(200, {"done": False, "reason": "Nothing was proposed in this run."})
            if req is None or req["status"] != "approved":
                return self.reply(200, {"done": False, "reason": "No yes for this run."})
            if run["done"]:
                return self.reply(200, {"done": True, "again": True, "wrote": run["proposal"]})
            run["done"] = True
            return self.reply(200, {"done": True, "wrote": run["proposal"]})

        if self.path in ("/_decide", "/_forge"):
            run = RUNS.get(ex)
            if run is None or run["request"] is None:
                return self.reply(404, {"error": "no request for that execution"})
            if self.path == "/_decide":
                run["request"]["status"] = {"yes": "approved", "no": "declined"}.get(body["decision"], "expired")
                run["request"]["by"] = body.get("approver")
            status, text = wake(run["request"]["resume_url"], body["decision"])
            return self.reply(200, {"run_id": run["run_id"], "n8n_status": status, "n8n_body": text})

        if self.path == "/error":
            return self.reply(200, {"ok": True})
        self.reply(404, {"error": "no route"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 5690), Handler).serve_forever()
