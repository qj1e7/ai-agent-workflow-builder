"""Helpers for the P6 scripts. Local test logins and the API key live in p6-secrets.json, which git ignores."""

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request

B = "http://localhost:5683"
STUB = "http://localhost:5693"
STUB_IN_NET = "http://stub:5690"
SECRETS = "p6-secrets.json"


def secrets() -> dict:
    return json.load(open(SECRETS)) if os.path.exists(SECRETS) else {}


def save_secrets(s: dict) -> None:
    json.dump(s, open(SECRETS, "w"), indent=1)


def _send(opener, method, url, body=None, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with opener.open(req, timeout=30) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t else {})
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        try:
            return e.code, json.loads(t)
        except ValueError:
            return e.code, t[:300]


class Rest:
    """n8n's internal REST API, signed in with a cookie, as a person in the editor would be."""

    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None):
        return _send(self.op, method, B + "/rest" + path, body)

    def login(self, email, password):
        s, r = self.call("POST", "/login", {"emailOrLdapLoginId": email, "password": password})
        assert s == 200, (s, r)
        return r["data"]


def public(method, path, body=None):
    """n8n's public API with the platform's API key, as our API would call it."""
    return _send(urllib.request.build_opener(), method, B + "/api/v1" + path, body, {"X-N8N-API-KEY": secrets()["apikey"]})


def stub(method, path, body=None):
    return _send(urllib.request.build_opener(), method, STUB + path, body)


def hook(path, body=None):
    return _send(urllib.request.build_opener(), "POST", B + "/webhook/" + path, body or {})


def node(name, type_, params, pos, tv=1, **kw):
    n = {"id": name.lower().replace(" ", "-"), "name": name, "type": type_, "typeVersion": tv, "position": pos, "parameters": params}
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


def wait_for(fn, timeout=30, step=0.5):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def execution(eid):
    s, r = public("GET", f"/executions/{eid}?includeData=true")
    return r if s == 200 else None


def show(label, value):
    print(f"{label}: {json.dumps(value, default=str)[:600]}")
