"""Helpers for spike P9. The canaries live in p9.env and the test logins in p9-secrets.json, both git ignored.

Every raw line goes through Raw, which refuses to write a line that holds a canary, the prefix every
canary starts with, the owner's password or the API key. So a probe that went wrong stops the run
instead of saving a secret.
"""

import http.cookiejar
import json
import os
import secrets as rnd
import subprocess
import time
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:15790"
FAKE = "http://127.0.0.1:15791"
ENV = os.path.join(HERE, "p9.env")
SECRETS = os.path.join(HERE, "p9-secrets.json")
PROJECT = "p9"
CANARY_NAMES = ["ENCKEY", "DBPASS", "NODEKEY", "STARTSECRET", "IDHEADER", "RUNNERTOKEN"]
ENV_KEYS = {
    "P9_ENCRYPTION_KEY": "ENCKEY",
    "P9_DB_PASSWORD": "DBPASS",
    "P9_NODE_KEY": "NODEKEY",
    "P9_START_SECRET": "STARTSECRET",
    "P9_IDENTITY_HEADER": "IDHEADER",
    "P9_RUNNER_TOKEN": "RUNNERTOKEN",
}


def make_env() -> None:
    """Fresh made-up values. Each starts with P9CANARY-<NAME>-, which the probes look for."""
    if os.path.exists(ENV):
        return
    with open(ENV, "w") as f:
        for key, name in ENV_KEYS.items():
            f.write(f"{key}=P9CANARY-{name}-{rnd.token_hex(4)}\n")


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


def _forbidden() -> list[str]:
    vals = ["P9CANARY"] + list(env().values())
    s = secrets()
    vals += [v for v in (s.get("password"), s.get("apikey")) if v]
    return vals


class SecretInOutput(RuntimeError):
    pass


class Raw:
    """Writes raw/<name>.json (results) and raw/<name>.txt (one line per step), after the secret check."""

    def __init__(self, name: str):
        os.makedirs(os.path.join(HERE, "raw"), exist_ok=True)
        self.name = name
        self.txt = open(os.path.join(HERE, "raw", f"{name}.txt"), "w")
        self.data: dict = {}
        self.n = 0

    @staticmethod
    def check(text: str) -> str:
        for v in _forbidden():
            if v and v in text:
                raise SecretInOutput("a raw line would hold a canary or a login; nothing was written")
        return text

    def __call__(self, label: str, value=None) -> None:
        self.n += 1
        text = label if value is None else f"{label}: {json.dumps(value, default=str, sort_keys=True)}"
        line = self.check(f"{self.n:03d} {text}")
        print(line)
        self.txt.write(line + "\n")
        self.txt.flush()

    def put(self, key: str, value) -> None:
        self.check(json.dumps(value, default=str))
        self.data[key] = value

    def save(self) -> None:
        text = self.check(json.dumps(self.data, indent=1, sort_keys=True, default=str))
        with open(os.path.join(HERE, "raw", f"{self.name}.json"), "w") as f:
            f.write(text + "\n")


def compose(*args, variant="internal", check=True):
    files = ["compose.yaml"] + (["compose.runners-escape.yaml"] if variant == "external-escape" else [])
    e = dict(os.environ, **env(), P9_VARIANT=variant)
    cmd = ["docker", "compose", *sum((["-f", os.path.join(HERE, f)] for f in files), []), "--project-name", PROJECT]
    if variant.startswith("external"):
        cmd += ["--profile", "external"]
    return subprocess.run(cmd + list(args), env=e, check=check, capture_output=True, text=True, cwd=HERE)


def in_n8n(*cmd, variant="internal"):
    return compose("exec", "-T", "n8n", *cmd, variant=variant, check=False)


def _send(opener, method, url, body=None, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(3 if method == "GET" else 1):
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with opener.open(req, timeout=120) as r:
                t = r.read().decode()
                try:
                    return r.status, (json.loads(t) if t else {})
                except ValueError:
                    return r.status, t[:300]
        except urllib.error.HTTPError as e:
            t = e.read().decode()
            if e.code >= 500 and method == "GET" and attempt < 2:
                time.sleep(2)
                continue
            try:
                return e.code, json.loads(t)
            except ValueError:
                return e.code, t[:300]
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
            if method == "GET" and attempt < 2:
                time.sleep(2)
                continue
            return 599, f"no answer: {type(e).__name__}"
    return 599, "no answer"


class Rest:
    """n8n's internal /rest API, signed in as the owner with a cookie."""

    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None):
        return _send(self.op, method, B + "/rest" + path, body)

    def login(self, email, password):
        s, r = self.call("POST", "/login", {"emailOrLdapLoginId": email, "password": password})
        assert s == 200, (s, r)


def public(method, path, body=None):
    return _send(urllib.request.build_opener(), method, B + "/api/v1" + path, body, {"X-N8N-API-KEY": secrets()["apikey"]})


def fake(method, path):
    return _send(urllib.request.build_opener(), method, FAKE + path)[1]


def setup_owner() -> Rest:
    """Makes n8n's owner and an API key once; later variants reuse them, since the database volume stays."""
    s = secrets()
    owner = Rest()
    if not s:
        s = {"email": "p9-owner@example.com", "password": "P9-" + rnd.token_urlsafe(12) + "a1A"}
        save_secrets(s)
        st, r = owner.call("POST", "/owner/setup", {"email": s["email"], "firstName": "P9", "lastName": "Owner", "password": s["password"]})
        assert st == 200, (st, "owner setup failed")
    owner.login(s["email"], s["password"])
    if "apikey" not in s:
        st, r = owner.call("GET", "/api-keys/scopes")
        scopes = r["data"]
        st, r = owner.call("POST", "/api-keys", {"label": "p9", "expiresAt": None, "scopes": scopes})
        assert st == 200, (st, "api key failed")
        s["apikey"] = r["data"]["rawApiKey"]
        save_secrets(s)
    return owner


def node(name, type_, params=None, pos=(0, 0), tv=1, **kw):
    n = {"id": str(uuid.uuid4()), "name": name, "type": type_, "typeVersion": tv, "position": list(pos), "parameters": params or {}}
    n.update(kw)
    return n


def link(*pairs, kind="main"):
    """link(("A", "B")) wires A's first exit to B's first input."""
    c: dict = {}
    for p in pairs:
        src, dst = p[0], p[1]
        outs = c.setdefault(src, {}).setdefault(kind, [[]])
        outs[0].append({"node": dst, "type": kind, "index": 0})
    return c


def merge_links(*parts):
    out: dict = {}
    for part in parts:
        for src, kinds in part.items():
            for kind, outs in kinds.items():
                dst = out.setdefault(src, {}).setdefault(kind, [[]])
                dst[0].extend(outs[0])
    return out


SETTINGS = {"timezone": "Asia/Singapore", "saveManualExecutions": True, "saveExecutionProgress": False, "executionOrder": "v1"}


def wait_for(fn, timeout=120, step=0.5):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def run_by_hand(owner: Rest, name, nodes, connections, last):
    """Creates the workflow, runs it by hand to `last` as the editor's Execute does, and returns the
    finished execution. The caller deletes both."""
    st, w = public("POST", "/workflows", {"name": name, "nodes": nodes, "connections": connections, "settings": SETTINGS})
    if st != 200:
        return None, {"create_failed": st, "why": (w or {}).get("message") if isinstance(w, dict) else str(w)[:200]}
    st, r = owner.call("POST", f"/workflows/{w['id']}/run", {"destinationNode": {"nodeName": last, "mode": "inclusive"}})
    eid = ((r or {}).get("data") or {}).get("executionId") if isinstance(r, dict) else None
    if not eid:
        public("DELETE", f"/workflows/{w['id']}")
        return None, {"run_failed": st, "why": (r or {}).get("message") if isinstance(r, dict) else str(r)[:200]}

    def done():
        s, e = public("GET", f"/executions/{eid}?includeData=true")
        return e if s == 200 and e.get("status") not in ("new", "running", "waiting") else None

    ex = wait_for(done, 180)
    return {"workflow": w["id"], "execution": eid, "data": ex}, None


def clean_up(run) -> None:
    if not run:
        return
    public("DELETE", f"/executions/{run['execution']}")
    public("DELETE", f"/workflows/{run['workflow']}")


def node_result(ex, name):
    """The first item a node gave, on any of its connection types, or its error."""
    runs = ((((ex or {}).get("data") or {}).get("resultData") or {}).get("runData") or {}).get(name) or []
    if not runs:
        return {"ran": False}
    first = runs[0]
    if first.get("error"):
        return {"ran": True, "error": first["error"].get("message") or "", "description": first["error"].get("description") or ""}
    for outputs in (first.get("data") or {}).values():
        for items in outputs or []:
            for item in items or []:
                return {"ran": True, "json": item.get("json") or {}}
    return {"ran": True, "json": None}
