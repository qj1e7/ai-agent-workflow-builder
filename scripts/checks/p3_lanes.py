"""API lanes for the P3 checker (people and roles). Standard library only, so it also runs inside
the platform-api container of an OIDC stack, which publishes no host ports:
    docker compose ... exec -T platform-api python - lane2 http://localhost:8000 /tmp/out \\
        http://mock-oidc:8080/default < scripts/checks/p3_lanes.py

Each command saves its calls as JSON in the folder it is given and prints ok/FAIL lines, then
PASS or FAIL.

usage: python3 -I scripts/checks/p3_lanes.py <command> <api-base-url> <out-dir> [arguments]

  lane1 <api> <out> <file>             alice watches LangGraph, starts a run, bob approves (dev stack)
  lane2 <api> <out> <issuer>           mallory signs in: /me says ask an Operator, every other route 403 (oidc)
  lane3 <api> <out> <issuer>           alice adds erin by email; erin's first sign-in binds her record (oidc)
  lane4 <api> <out>                    alice asks to make dave an Approver, then tries to confirm it herself
  lane5 <api> <out>                    bob confirms dave; dave's /me shows Approver; the history names both
  lane6 <api> <out>                    alice removes her own Operator role: refused
  lane7 <api> <out>                    carol removes bob's Approver role with two Approvers: refused
  lane8 <api> <out>                    three Approvers; two removals at the same moment; two remain
  lane9 <api> <out>                    dave (with erin as a third Approver) loses the role, then decides: refused
  people <api> <out> <file>            save GET /api/v1/people as alice (dev) for before/after comparisons
  token <issuer> <user>                print an access token for <user> from the mock identity provider
"""

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

WAIT_SECONDS = 120
STALE_DIGEST = "sha256:" + "0" * 64


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.log: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def call(
        self,
        who: str | dict[str, str] | None,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        all_headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if isinstance(who, str):
            all_headers["X-Dev-User"] = who
        elif who is not None:
            all_headers.update(who)
        all_headers.update(headers or {})
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers=all_headers
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        try:
            parsed: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw.decode(errors="replace")
        with self.lock:
            self.log.append(
                {
                    "who": who if isinstance(who, str) else ("bearer" if who else None),
                    "method": method,
                    "path": path,
                    "body": body,
                    "status": status,
                    "response": parsed,
                }
            )
        return status, parsed

    def get(self, who: str | dict[str, str], path: str) -> Any:
        status, parsed = self.call(who, "GET", path)
        if status != 200:
            raise SystemExit(f"GET {path}: HTTP {status} {parsed!r}"[:600])
        return parsed

    def must(self, who: str | dict[str, str], method: str, path: str, body: Any, ok: set[int]) -> Any:
        status, parsed = self.call(who, method, path, body)
        if status not in ok:
            raise SystemExit(f"{method} {path}: HTTP {status} {parsed!r}"[:600])
        return parsed

    def wait(self, who: str, run_id: str, states: set[str]) -> Any:
        deadline = time.monotonic() + WAIT_SECONDS
        run = None
        while time.monotonic() < deadline:
            status, run = self.call(who, "GET", f"/api/v1/runs/{run_id}")
            with self.lock:
                self.log.pop()
            if status == 200 and run["state"] in states:
                self.call(who, "GET", f"/api/v1/runs/{run_id}")
                return run
            time.sleep(1)
        raise SystemExit(f"run {run_id} never reached {sorted(states)}; last {run!r}"[:800])


def save(out: Path, name: str, payload: Any) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(payload, indent=2, default=str) + "\n")


def verdict(lines: list[tuple[bool, str]]) -> bool:
    for ok, line in lines:
        print(("ok   " if ok else "FAIL ") + line)
    passed = all(ok for ok, _ in lines)
    print("PASS" if passed else "FAIL")
    return passed


def people_by_email(api: Api, who: str | dict[str, str]) -> dict[str, Any]:
    return {p["email"].lower(): p for p in api.get(who, "/api/v1/people")["people"]}


def ensure_person(
    api: Api, actor: str, email: str, display: str, operator: bool, approver: bool
) -> Any:
    existing = people_by_email(api, actor).get(email.lower())
    if existing is not None:
        return existing
    return api.must(
        actor,
        "POST",
        "/api/v1/people",
        {"email": email, "display": display, "operator": operator, "approver": approver},
        {201},
    )


def pending_about(api: Api, who: str | dict[str, str], person_id: str) -> Any | None:
    for c in api.get(who, "/api/v1/confirmations")["confirmations"]:
        if c["kind"] == "approver" and c["about"] and c["about"]["id"] == person_id:
            return c
    return None


def decide(api: Api, who: str | dict[str, str], confirmation: Any, verdict_word: str) -> tuple[int, Any]:
    return api.call(
        who,
        "POST",
        f"/api/v1/confirmations/{confirmation['confirmation_id']}/decisions",
        {"verdict": verdict_word, "digest": confirmation["digest"]},
    )


def confirmed_approver(api: Api, email: str, display: str) -> Any:
    """dave (or whoever) as an Operator and a confirmed Approver, asked by alice, confirmed by bob."""
    person = ensure_person(api, "alice", email, display, True, False)
    if person["approver"]:
        return person
    if pending_about(api, "alice", person["id"]) is None:
        api.must("alice", "POST", f"/api/v1/people/{person['id']}/approver", None, {202})
    waiting = pending_about(api, "bob", person["id"])
    assert waiting is not None
    status, decided = decide(api, "bob", waiting, "confirm")
    if status != 201:
        raise SystemExit(f"bob could not confirm {display}: HTTP {status} {decided!r}")
    return people_by_email(api, "alice")[email.lower()]


# ---------------------------------------------------------------------------------------------
# Tokens from the mock identity provider, through its interactive authorization code flow.


class _Form(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = a.get("action") or ""
        if tag == "input" and a.get("name"):
            self.fields[str(a["name"])] = a.get("value") or ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        return None


def token_for(issuer: str, user: str, client_id: str = "portal") -> str:
    issuer = issuer.rstrip("/")
    redirect = "http://localhost:8080/auth/callback"
    opener = urllib.request.build_opener(_NoRedirect)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": "openid profile platform-api",
            "state": uuid.uuid4().hex,
            "nonce": uuid.uuid4().hex,
        }
    )
    authorize = f"{issuer}/authorize?{query}"
    with opener.open(authorize, timeout=30) as response:
        page = response.read().decode()
    form = _Form()
    form.feed(page)
    action = urllib.parse.urljoin(authorize, form.action or authorize)
    fields = {**form.fields, "username": user}
    fields.setdefault("claims", "")
    try:
        with opener.open(
            urllib.request.Request(action, data=urllib.parse.urlencode(fields).encode(), method="POST"),
            timeout=30,
        ) as response:
            location = response.headers.get("Location", "")
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 303, 307):
            raise
        location = error.headers.get("Location", "")
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query).get("code", [""])[0]
    if not code:
        raise SystemExit(f"the mock identity provider gave no code for {user}: {location!r}")
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": "not-checked",
            "redirect_uri": redirect,
        }
    ).encode()
    with opener.open(urllib.request.Request(f"{issuer}/token", data=body, method="POST"), timeout=30) as response:
        return str(json.loads(response.read())["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def claims_of(token: str) -> dict[str, Any]:
    import base64

    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


# ---------------------------------------------------------------------------------------------
# Lanes


def lane1(api: Api, out: Path, file: str) -> bool:
    status, added = api.call(
        "alice",
        "POST",
        "/api/v1/watchlist/software",
        {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"},
    )
    if status not in (201, 409):
        raise SystemExit(f"add software: HTTP {status} {added!r}")
    use_case_id = api.get("alice", "/api/v1/watchlist")["watchlist"]["use_case_id"]
    status, started = api.call(
        "alice",
        "POST",
        f"/api/v1/use-cases/{use_case_id}/runs",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    if status not in (200, 201, 202):
        raise SystemExit(f"start run: HTTP {status} {started!r}")
    run_id = started["run_id"]
    run = api.wait("alice", run_id, {"awaiting_approval", "succeeded", "failed", "rejected"})
    lines: list[tuple[bool, str]] = [(run["state"] == "awaiting_approval", f"run {run_id} waits for approval")]
    decision = None
    if run["state"] == "awaiting_approval":
        approval_id = run["approval"]["approval_id"]
        view = api.get("bob", f"/api/v1/approvals/{approval_id}")
        lines.append((view["you_can_decide"], "bob may decide"))
        status, decision = api.call(
            "bob",
            "POST",
            f"/api/v1/approvals/{approval_id}/decisions",
            {"step": 0, "verdict": "approve", "digest": view["digest"]},
        )
        lines.append((status == 201 and decision["decision"]["by"] == "bob", f"bob approved: HTTP {status}"))
        final = api.wait("alice", run_id, {"succeeded", "failed", "rejected"})
        lines.append((final["state"] == "succeeded", f"run ended {final['state']}"))
    me = api.get("bob", "/api/v1/me")
    lines.append((me["roles"] == ["approver"], f"bob's /me roles {me['roles']}"))
    status, people = api.call("bob", "GET", "/api/v1/people")
    lines.append((status in (200, 404), f"GET /api/v1/people: HTTP {status} (404 at trunk, 200 at head)"))
    save(out, file, {"run": run, "decision": decision, "me": me, "people": people, "calls": api.log})
    return verdict(lines)


def lane2(api: Api, out: Path, issuer: str) -> bool:
    mallory = bearer(token_for(issuer, "mallory"))
    me_status, me = api.call(mallory, "GET", "/api/v1/me")
    lines = [
        (me_status == 200 and me.get("on_list") is False and me.get("roles") == [], f"/me: HTTP {me_status} {me}"),
    ]
    for method, path, body in (
        ("GET", "/api/v1/runs", None),
        ("GET", "/api/v1/use-cases", None),
        ("GET", "/api/v1/people", None),
        ("GET", "/api/v1/confirmations", None),
        ("GET", "/api/v1/settings/model", None),
        ("GET", "/api/v1/watchlist", None),
        ("POST", "/api/v1/people", {"email": "x@example.test", "display": "X", "operator": True}),
        ("POST", "/api/v1/runs/run_1/retry", None),
        ("GET", "/api/v1/runs/run_1/events?after=0", None),
    ):
        status, answer = api.call(mallory, method, path, body)
        ok = status == 403 and isinstance(answer, dict) and "Ask an Operator" in str(answer.get("detail"))
        lines.append((ok, f"{method} {path}: HTTP {status}"))
    save(out, "p3-not-on-list.json", {"token_claims": claims_of(mallory["Authorization"].split()[1]), "calls": api.log})
    return verdict(lines)


def lane3(api: Api, out: Path, issuer: str) -> bool:
    alice = bearer(token_for(issuer, "alice"))
    assert api.get(alice, "/api/v1/me")["on_list"] is True
    before = people_by_email(api, alice)
    lines: list[tuple[bool, str]] = []
    if "erin@example.test" not in before:
        status, added = api.call(
            alice,
            "POST",
            "/api/v1/people",
            {"email": "Erin@Example.test", "display": "Erin (added by Alice)", "operator": True},
        )
        lines.append((status == 201, f"alice adds erin by email: HTTP {status}"))
    erin_before = people_by_email(api, alice)["erin@example.test"]
    lines.append((erin_before["signed_in"] is False, "erin has not signed in yet"))
    erin_token = token_for(issuer, "erin")
    erin = bearer(erin_token)
    me1 = api.get(erin, "/api/v1/me")
    lines.append((me1["on_list"] is True and me1["id"] == erin_before["id"], f"erin's first sign-in matched her record by email: {me1}"))
    lines.append((me1["display"] == "Erin (added by Alice)", f"her display stays as the Operator entered it: {me1['display']}"))
    erin_after = people_by_email(api, alice)["erin@example.test"]
    lines.append((erin_after["signed_in"] is True, "the People list shows erin signed in"))
    me2 = api.get(bearer(token_for(issuer, "erin")), "/api/v1/me")
    lines.append((me2["id"] == me1["id"], "a second token matches the same record"))
    save(
        out,
        "p3-first-sign-in.json",
        {"erin_before": erin_before, "erin_after": erin_after, "me_first": me1, "me_second": me2, "oid": claims_of(erin_token).get("oid"), "calls": api.log},
    )
    return verdict(lines)


def lane4(api: Api, out: Path) -> bool:
    dave = ensure_person(api, "alice", "dave@example.test", "Dave", True, False)
    lines: list[tuple[bool, str]] = [(dave["approver"] is False, "dave is not an Approver")]
    if pending_about(api, "alice", dave["id"]) is None:
        status, asked = api.call("alice", "POST", f"/api/v1/people/{dave['id']}/approver")
        lines.append((status == 202 and asked["pending_approver"]["asked_by"] == "alice", f"alice asks: HTTP {status}"))
    waiting = pending_about(api, "alice", dave["id"])
    lines.append((waiting is not None and waiting["why_not"] == "you_asked", f"alice sees why not: {waiting and waiting['why_not']}"))
    assert waiting is not None
    status, refused = decide(api, "alice", waiting, "confirm")
    lines.append((status == 403 and refused.get("refusal") == "you_asked", f"alice confirming herself: HTTP {status} {refused}"))
    me = api.get({"X-Dev-User": dave["id"]}, "/api/v1/me")
    lines.append((me["roles"] == ["operator"], f"dave's /me roles {me['roles']}"))
    save(out, "p3-self-confirm.json", {"dave": dave, "waiting": waiting, "refused": refused, "me": me, "calls": api.log})
    return verdict(lines)


def lane5(api: Api, out: Path) -> bool:
    dave = people_by_email(api, "alice")["dave@example.test"]
    waiting = pending_about(api, "bob", dave["id"])
    lines: list[tuple[bool, str]] = [(waiting is not None and waiting["you_can_decide"], "bob may confirm")]
    assert waiting is not None
    status, decided = decide(api, "bob", waiting, "confirm")
    lines.append((status == 201 and decided["decided_by"] == "bob", f"bob confirms: HTTP {status}"))
    me = api.get({"X-Dev-User": dave["id"]}, "/api/v1/me")
    lines.append((me["roles"] == ["operator", "approver"], f"dave's /me roles {me['roles']}"))
    history = api.get("carol", "/api/v1/settings/history")["changes"]
    line = next((h for h in history if h["confirmation_id"] == waiting["confirmation_id"] and h["confirmed_by"]), None)
    lines.append(
        (line is not None and line["by"] == "alice" and line["confirmed_by"] == "bob", f"history names alice as asker and bob as confirmer: {line and line['summary']}")
    )
    save(out, "p3-confirmed.json", {"waiting": waiting, "decided": decided, "me": me, "history": history, "calls": api.log})
    return verdict(lines)


def lane6(api: Api, out: Path) -> bool:
    status, refused = api.call("alice", "PUT", "/api/v1/people/alice/operator", {"operator": False})
    me = api.get("alice", "/api/v1/me")
    lines = [
        (status == 409 and refused.get("refusal") == "own_operator_role", f"alice removing her own Operator role: HTTP {status} {refused}"),
        ("operator" in me["roles"], f"alice still an Operator: {me['roles']}"),
    ]
    save(out, "p3-own-operator.json", {"refused": refused, "me": me, "calls": api.log})
    return verdict(lines)


def lane7(api: Api, out: Path) -> bool:
    people = people_by_email(api, "carol")
    approvers = sorted(p["id"] for p in people.values() if p["approver"])
    lines: list[tuple[bool, str]] = [(approvers == ["alice", "bob"], f"the Approvers are {approvers}")]
    status, refused = api.call("carol", "DELETE", "/api/v1/people/bob/approver")
    lines.append((status == 409 and refused.get("refusal") == "two_approvers", f"carol removing bob's Approver role: HTTP {status} {refused}"))
    lines.append(("two people must stay Approvers" in str(refused.get("message")), "the message names the rule"))
    me = api.get("bob", "/api/v1/me")
    lines.append((me["roles"] == ["approver"], f"bob keeps the role: {me['roles']}"))
    save(out, "p3-floor.json", {"refused": refused, "me": me, "calls": api.log})
    return verdict(lines)


def lane8(api: Api, out: Path) -> bool:
    dave = confirmed_approver(api, "dave@example.test", "Dave")
    before = people_by_email(api, "alice")
    approvers_before = sorted(p["id"] for p in before.values() if p["approver"])
    lines: list[tuple[bool, str]] = [(len(approvers_before) == 3, f"three Approvers: {approvers_before}")]
    results: dict[str, tuple[int, Any]] = {}

    def remove(actor: str, target: str) -> None:
        results[f"{actor}->{target}"] = api.call(actor, "DELETE", f"/api/v1/people/{target}/approver")

    threads = [
        threading.Thread(target=remove, args=("alice", dave["id"])),
        threading.Thread(target=remove, args=("carol", "alice")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = sorted(s for s, _ in results.values())
    lines.append((statuses == [200, 409], f"one removal succeeded and one was refused: {statuses}"))
    refusals = [r.get("refusal") for s, r in results.values() if s == 409 and isinstance(r, dict)]
    lines.append((refusals == ["two_approvers"], f"the refusal is the two-Approver rule: {refusals}"))
    after = people_by_email(api, "alice")
    approvers_after = sorted(p["id"] for p in after.values() if p["approver"])
    lines.append((len(approvers_after) == 2, f"two Approvers remain: {approvers_after}"))
    save(out, "p3-race.json", {"before": approvers_before, "results": {k: {"status": s, "body": b} for k, (s, b) in results.items()}, "after": approvers_after, "calls": api.log})
    return verdict(lines)


def lane9(api: Api, out: Path) -> bool:
    dave = confirmed_approver(api, "dave@example.test", "Dave")
    erin = confirmed_approver(api, "erin@example.test", "Erin")
    dave_hdr = {"X-Dev-User": dave["id"]}
    status, added = api.call(
        "alice",
        "POST",
        "/api/v1/watchlist/software",
        {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"},
    )
    if status not in (201, 409):
        raise SystemExit(f"add software: HTTP {status} {added!r}")
    use_case_id = api.get("alice", "/api/v1/watchlist")["watchlist"]["use_case_id"]
    status, started = api.call(
        "alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs", headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    if status not in (200, 201, 202):
        raise SystemExit(f"start run: HTTP {status} {started!r}")
    run = api.wait("alice", started["run_id"], {"awaiting_approval", "succeeded", "failed", "rejected"})
    lines: list[tuple[bool, str]] = [(run["state"] == "awaiting_approval", f"run {run['run_id']} waits for approval")]
    approval_id = run["approval"]["approval_id"]
    view = api.get(dave_hdr, f"/api/v1/approvals/{approval_id}")
    lines.append((view["you_can_decide"], "dave may decide while he is an Approver"))
    status, removed = api.call("carol", "DELETE", f"/api/v1/people/{dave['id']}/approver")
    lines.append((status == 200 and removed["approver"] is False, f"carol removes dave's Approver role: HTTP {status}"))
    started_at = time.monotonic()
    status, refused = api.call(
        dave_hdr,
        "POST",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": view["digest"]},
    )
    elapsed = time.monotonic() - started_at
    lines.append((status == 403 and refused.get("refusal") == "not_an_approver", f"dave's decision {elapsed:.1f}s later: HTTP {status} {refused}"))
    after = api.get("bob", f"/api/v1/approvals/{approval_id}")
    lines.append((after["steps"][0]["status"] == "open", "the step is still open"))
    status, decided = api.call(
        "bob", "POST", f"/api/v1/approvals/{approval_id}/decisions", {"step": 0, "verdict": "approve", "digest": view["digest"]}
    )
    lines.append((status == 201, f"bob approves instead: HTTP {status}"))
    save(out, "p3-removed.json", {"run": run, "erin": erin, "removed": removed, "refused": refused, "bob": decided, "calls": api.log})
    return verdict(lines)


def people_snapshot(api: Api, out: Path, file: str) -> bool:
    people = api.get("alice", "/api/v1/people")
    save(out, file, people)
    print(f"saved {len(people['people'])} people to {out / file}")
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    command = argv[1]
    if command == "token":
        print(token_for(argv[2], argv[3]))
        return 0
    api = Api(argv[2])
    out = Path(argv[3])
    rest = argv[4:]
    match command:
        case "lane1":
            ok = lane1(api, out, rest[0])
        case "lane2":
            ok = lane2(api, out, rest[0])
        case "lane3":
            ok = lane3(api, out, rest[0])
        case "lane4":
            ok = lane4(api, out)
        case "lane5":
            ok = lane5(api, out)
        case "lane6":
            ok = lane6(api, out)
        case "lane7":
            ok = lane7(api, out)
        case "lane8":
            ok = lane8(api, out)
        case "lane9":
            ok = lane9(api, out)
        case "people":
            ok = people_snapshot(api, out, rest[0])
        case _:
            print(__doc__)
            return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
