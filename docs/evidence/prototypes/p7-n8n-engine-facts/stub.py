"""Stands in for our API's /internal/v1/n8n routes. Records every node call.

On the first call of each execution it reads GET /api/v1/executions/{id}?includeData=true from n8n,
the way our API would link the execution to a run, and records what it saw.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = os.environ["WAB_NODE_KEY"]
N8N = os.environ["N8N_URL"]
LOCK = threading.Lock()
STATE: dict = {"apikey": None, "plan": {}, "ask": "wait", "calls": [], "failures": [], "first_reads": {}, "other_requests": []}


def read_execution(eid: str) -> dict:
    req = urllib.request.Request(f"{N8N}/api/v1/executions/{eid}?includeData=true", headers={"X-N8N-API-KEY": STATE["apikey"] or ""})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ex = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode()[:200]}
    run_data = ((ex.get("data") or {}).get("resultData") or {}).get("runData") or {}
    start = run_data.get("Start from the Portal")
    item = start[0]["data"]["main"][0][0]["json"] if start else None
    return {"http": 200, "status": ex.get("status"), "mode": ex.get("mode"), "retryOf": ex.get("retryOf"), "nodes_in_runData": sorted(run_data), "start_item": item}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> dict:
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        with LOCK:
            if self.path != "/":
                STATE["other_requests"].append(self.path)
                return self.reply(200, [{"leaked": True}])
            self.reply(200, {k: v for k, v in STATE.items() if k != "apikey"})

    def do_POST(self):
        b = self.body()
        if self.path == "/control":
            with LOCK:
                STATE.update(b)
            return self.reply(200, {"ok": True})
        if self.path == "/reset":
            with LOCK:
                STATE.update(plan={}, ask="wait", calls=[], failures=[], first_reads={})
            return self.reply(200, {"ok": True})
        if self.headers.get("x-wab-node-key") != KEY:
            return self.reply(401, {"detail": "Bad node key."})
        if self.path == "/internal/v1/n8n/failures":
            with LOCK:
                STATE["failures"].append(b)
            return self.reply(200, {"ok": True})
        kind = self.path.rsplit("/", 1)[-1]
        eid = str(b.get("execution_id"))
        first = False
        with LOCK:
            if eid not in STATE["first_reads"]:
                STATE["first_reads"][eid] = "pending"
                first = True
        seen = read_execution(eid) if first else None
        with LOCK:
            if first:
                STATE["first_reads"][eid] = seen
            STATE["calls"].append({**b, "kind": kind, "at": round(time.time(), 2)})
            plan = STATE["plan"].get(b.get("node_name")) or []
            code = plan.pop(0) if plan else 200
            ask = STATE["ask"]
        if code != 200:
            return self.reply(code, {"detail": f"Stub answered {code} on purpose."})
        if kind == "ask":
            return self.reply(200, {"answer": ask})
        return self.reply(200, {"kind": kind, "node": b.get("node_name"), "ok": True})


ThreadingHTTPServer(("0.0.0.0", 8041), Handler).serve_forever()
