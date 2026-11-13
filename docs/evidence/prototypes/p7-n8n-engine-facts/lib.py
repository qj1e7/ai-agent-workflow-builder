"""Helpers for the P7 scripts. Keys and logins live in p7.env and p7-secrets.json, which git ignores.

Every raw line goes through mask(), so no key, password, signature or token reaches raw/.
"""

import hashlib
import hmac
import http.cookiejar
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
B = "http://localhost:15721"
STUB = "http://localhost:18041"
SECRETS = os.path.join(HERE, "p7-secrets.json")
ENV = os.path.join(HERE, "p7.env")


def env() -> dict:
    out = {}
    for line in open(ENV):
        k, _, v = line.strip().partition("=")
        if k:
            out[k] = v
    return out


def secrets() -> dict:
    return json.load(open(SECRETS)) if os.path.exists(SECRETS) else {}


def save_secrets(s: dict) -> None:
    json.dump(s, open(SECRETS, "w"), indent=1)


def _sensitive() -> list[str]:
    vals = list(env().values())
    for v in secrets().values():
        if isinstance(v, str):
            vals.append(v)
        elif isinstance(v, dict):
            vals += [x for k, x in v.items() if k in ("password",) and isinstance(x, str)]
    return [v for v in vals if len(v) >= 8]


def mask(text: str) -> str:
    for v in _sensitive():
        text = text.replace(v, "***")
    text = re.sub(r"(signature=)[A-Za-z0-9_\-.%]+", r"\1***", text)
    text = re.sub(r"(token=)[A-Za-z0-9_\-.%]+", r"\1***", text)
    text = re.sub(r'("(?:mac|rawApiKey|apiKey|inviteAcceptUrl|resumeToken)": ?")[^"]+', r"\1***", text)
    return text


class Raw:
    """Tees each line to the console and to raw/<name>.txt."""

    def __init__(self, name: str):
        os.makedirs(os.path.join(HERE, "raw"), exist_ok=True)
        self.f = open(os.path.join(HERE, "raw", f"{name}.txt"), "w")
        self.n = 0

    def __call__(self, label: str, value=None) -> int:
        self.n += 1
        text = label if value is None else f"{label}: {json.dumps(value, default=str)}"
        text = mask(text)
        if len(text) > 1500:
            text = text[:1500] + " …(cut)"
        line = f"{self.n:03d} {text}"
        print(line)
        self.f.write(line + "\n")
        self.f.flush()
        return self.n


def _send(opener, method, url, body=None, headers=None, raw_body=None):
    """GETs are retried on a timeout or a 5xx, because the shared test host was heavily loaded."""
    h = {"content-type": "application/json"}
    h.update(headers or {})
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
    for attempt in range(3 if method == "GET" else 1):
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with opener.open(req, timeout=90) as r:
                t = r.read().decode()
                try:
                    return r.status, (json.loads(t) if t else {})
                except ValueError:
                    return r.status, t[:300]
        except urllib.error.HTTPError as e:
            t = e.read().decode()
            if e.code >= 500 and method == "GET" and attempt < 2:
                time.sleep(3)
                continue
            try:
                return e.code, json.loads(t)
            except ValueError:
                return e.code, t[:300]
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
            if method == "GET" and attempt < 2:
                time.sleep(3)
                continue
            return 599, f"no answer: {e}"
    return 599, "no answer"


class Rest:
    """n8n's internal /rest API, signed in with a cookie, as the owner or a member in the editor."""

    def __init__(self, who: str | None = None):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        if who:
            u = secrets()[who]
            self.login(u["email"], u["password"])

    def call(self, method, path, body=None):
        return _send(self.op, method, B + "/rest" + path, body)

    def node_types(self) -> list[str]:
        s, r = _send(self.op, "GET", B + "/types/nodes.json")
        assert s == 200, (s, r)
        return sorted({t["name"] for t in r})

    def login(self, email, password):
        s, r = self.call("POST", "/login", {"emailOrLdapLoginId": email, "password": password})
        assert s == 200, (s, r)
        return r["data"]


def public(method, path, body=None):
    return _send(urllib.request.build_opener(), method, B + "/api/v1" + path, body, {"X-N8N-API-KEY": secrets()["apikey"]})


def stub_get() -> dict:
    return _send(urllib.request.build_opener(), "GET", STUB + "/")[1]


def stub_post(path, body) -> dict:
    return _send(urllib.request.build_opener(), "POST", STUB + path, body)[1]


def post_url(url, body=None, headers=None, raw_body=None):
    return _send(urllib.request.build_opener(), "POST", url.replace("http://n8n:5678", B), body, headers, raw_body)


def signed_start(kind="run_now", expires_in=300, nonce=None, secret=None) -> tuple[bytes, dict]:
    body = json.dumps({"nonce": nonce or uuid.uuid4().hex, "kind": kind, "expires": int(time.time()) + expires_in}).encode()
    sig = hmac.new((secret or env()["P7_START_SECRET"]).encode(), body, hashlib.sha256).hexdigest()
    return body, {"x-wab-signature": sig}


def wake_body(execution_id, request_id, decision, key=None) -> dict:
    mac = hmac.new((key or env()["P7_NODE_KEY"]).encode(), f"{execution_id}.{request_id}.{decision}".encode(), hashlib.sha256).hexdigest()
    return {"execution_id": str(execution_id), "request_id": request_id, "decision": decision, "mac": mac}


def node(name, type_, params=None, pos=(0, 0), tv=1, **kw):
    n = {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, name + json.dumps(kw, sort_keys=True))), "name": name, "type": type_, "typeVersion": tv, "position": list(pos), "parameters": params or {}}
    n.update(kw)
    return n


def link(*pairs):
    """link(("A", "B"), ("C", "D", 1)) connects A's output 0 to B, and C's output 1 to D."""
    c: dict = {}
    for p in pairs:
        src, dst, out = (p + (0,))[:3]
        outs = c.setdefault(src, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": dst, "type": "main", "index": 0})
    return c


SETTINGS = {"timezone": "Asia/Singapore", "saveManualExecutions": True, "saveExecutionProgress": True, "executionOrder": "v1"}


def start_node(**kw):
    return node("Start from the Portal", "CUSTOM.startFromPortal", {}, (0, 0), webhookId=kw.pop("webhookId", str(uuid.uuid4())), **kw)


def call_node(name, kind, pos=(200, 0), **kw):
    return node(name, "CUSTOM.callOurApi", {"kind": kind}, pos, **kw)


def create(name, nodes, connections, settings=None, raw=None):
    s, r = public("POST", "/workflows", {"name": name, "nodes": nodes, "connections": connections, "settings": settings or SETTINGS})
    assert s == 200, (s, r)
    if raw:
        raw(f"created {name}", {"id": r["id"], "versionId": r.get("versionId"), "activeVersionId": r.get("activeVersionId")})
    return r


def wait_for(fn, timeout=30, step=0.5):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def execution(eid, data=True):
    s, r = public("GET", f"/executions/{eid}" + ("?includeData=true" if data else ""))
    return r if s == 200 else None


def executions(workflow_id, status=None):
    q = f"/executions?workflowId={workflow_id}&limit=100" + (f"&status={status}" if status else "")
    s, r = public("GET", q)
    return r.get("data", []) if s == 200 else []


def finished(eid, timeout=90):
    return wait_for(lambda: (e := execution(eid, data=False)) and e.get("status") not in ("new", "running") and e, timeout)


def latest_execution(workflow_id, after_ids=()):
    return wait_for(lambda: next((e for e in executions(workflow_id) if e["id"] not in after_ids), None), 20)


def slim(ex: dict) -> dict:
    keep = ("id", "status", "mode", "finished", "retryOf", "retrySuccessId", "waitTill", "workflowId", "startedAt", "stoppedAt", "workflowVersionId")
    out = {k: ex.get(k) for k in keep if k in ex}
    rd = ((ex.get("data") or {}).get("resultData") or {})
    if rd:
        out["lastNodeExecuted"] = rd.get("lastNodeExecuted")
        out["nodes_run"] = {k: len(v) for k, v in (rd.get("runData") or {}).items()}
        if rd.get("error"):
            out["error"] = rd["error"].get("message")
    return out


def calls_for(eid) -> list:
    return [(c["node_name"], c["mode"]) for c in stub_get()["calls"] if str(c["execution_id"]) == str(eid)]


def compose(*args, env_extra=None, check=True, input=None, files=("compose.yaml",)):
    e = dict(os.environ, **env(), **(env_extra or {}))
    cmd = ["docker", "compose", *sum((["-f", os.path.join(HERE, f)] for f in files), []), "--project-name", "wab-e2e-p7", *args]
    return subprocess.run(cmd, env=e, check=check, capture_output=True, text=True, input=input)


def psql(sql: str) -> str:
    return compose("exec", "-T", "postgres", "psql", "-U", "n8n", "-d", "n8n", "-At", "-c", sql).stdout.strip()


def in_n8n(*cmd) -> subprocess.CompletedProcess:
    return compose("exec", "-T", "n8n", *cmd, check=False)
