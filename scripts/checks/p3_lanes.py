"""API lanes for the P3 checker (people and roles). Standard library only, so it also runs inside
the platform-api container of an OIDC stack, which publishes no host ports:
    docker compose ... exec -T platform-api python - lane2 http://localhost:8000 /tmp/p3-out \\
        http://mock-oidc:8080/default < scripts/checks/p3_lanes.py

Each command saves its calls as JSON in the folder it is given and prints ok/FAIL lines, then
PASS or FAIL.

usage: python3 -I scripts/checks/p3_lanes.py <command> <api-base-url> <out-dir> [arguments]

  lane1 <api> <out> trunk|head  alice watches LangGraph, starts a run, bob approves (dev stack).
                                At head, bob's roles also follow a change to the People list
  lane2 <api> <out> <issuer>    mallory signs in: /me says ask an Operator, and every signed-in
                                route in the served OpenAPI document answers 403 (oidc)
  lane3 <api> <out> <issuer>    alice adds erin by email; erin's first sign-in binds her record;
                                her oid with another user name still matches it, and her email
                                with another oid does not (oidc)
  lane4 <api> <out>             alice asks to make dave an Approver, then tries to confirm it
  lane5 <api> <out>             bob confirms dave; dave's /me shows Approver; history names both
  lane6 <api> <out>             alice removes her own Operator role: refused
  lane7 <api> <out>             carol removes bob's Approver role with two Approvers: refused
  lane8 <api> <out> [trials]    three Approvers; two removals released together, 20 times by
                                default; each time one is refused and two Approvers remain
  lane9 <api> <out>             dave loses the Approver role, then decides a run approval and a
                                waiting Approver request: both refused at once
  asker <api> <out>             a request whose asker leaves the list, or loses the Operator
                                role, is closed, and asking again works
  roleless <api> <out>          someone added only as an Approver leaves the list when the
                                answer is not now, or when the request is closed
  readd <api> <out> <issuer>    someone removed and added again under a new email signs in to
                                the new record; a removed person's old sign-in no longer works
  tenant <api> <out> <issuer>   a token whose tid is not the issuer's tenant is refused (oidc)
  people <api> <out> <file>     save GET /api/v1/people as alice (dev) for comparisons
  token <issuer> <user>         print an access token for <user> from the mock identity provider
"""

import base64
import json
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
RACE_TRIALS = 20
NOT_ON_THE_LIST = "Ask an Operator"


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
        keep: bool = True,
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
        if keep:
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

    def must(
        self, who: str | dict[str, str], method: str, path: str, body: Any, ok: set[int]
    ) -> Any:
        status, parsed = self.call(who, method, path, body)
        if status not in ok:
            raise SystemExit(f"{method} {path}: HTTP {status} {parsed!r}"[:600])
        return parsed

    def wait(self, who: str, run_id: str, states: set[str]) -> Any:
        deadline = time.monotonic() + WAIT_SECONDS
        run = None
        while time.monotonic() < deadline:
            status, run = self.call(who, "GET", f"/api/v1/runs/{run_id}", keep=False)
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


def roles(api: Api, who: str | dict[str, str]) -> list[str]:
    return list(api.get(who, "/api/v1/me")["roles"])


def ensure_person(
    api: Api,
    actor: str | dict[str, str],
    email: str,
    display: str,
    operator: bool,
    approver: bool,
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


def decide(
    api: Api, who: str | dict[str, str], confirmation: Any, verdict_word: str
) -> tuple[int, Any]:
    return api.call(
        who,
        "POST",
        f"/api/v1/confirmations/{confirmation['confirmation_id']}/decisions",
        {"verdict": verdict_word, "digest": confirmation["digest"]},
    )


def make_approver(api: Api, asker: str, person_id: str) -> None:
    if pending_about(api, asker, person_id) is None:
        api.must(asker, "POST", f"/api/v1/people/{person_id}/approver", None, {202})
    waiting = pending_about(api, "bob", person_id)
    if waiting is None:
        raise SystemExit(f"no request about {person_id} waits for bob")
    status, decided = decide(api, "bob", waiting, "confirm")
    if status != 201:
        raise SystemExit(f"bob could not confirm {person_id}: HTTP {status} {decided!r}")


def confirmed_approver(api: Api, email: str, display: str) -> Any:
    person = ensure_person(api, "alice", email, display, True, False)
    if not person["approver"]:
        make_approver(api, "alice", person["id"])
    return people_by_email(api, "alice")[email.lower()]


def history(api: Api) -> list[Any]:
    return list(api.get("carol", "/api/v1/settings/history")["changes"])


def history_line(api: Api, summary: str) -> Any | None:
    return next((h for h in history(api) if h["summary"] == summary), None)


def start_watchlist_run(api: Api) -> Any:
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
    return api.wait(
        "alice", started["run_id"], {"awaiting_approval", "succeeded", "failed", "rejected"}
    )


# ---------------------------------------------------------------------------------------------
# The mock identity provider's login form takes extra claims as JSON, so a token can carry any
# oid, user name or tid.


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


def token_for(issuer: str, user: str, claims: dict[str, Any] | None = None) -> str:
    issuer = issuer.rstrip("/")
    redirect = "http://localhost:8080/auth/callback"
    opener = urllib.request.build_opener(_NoRedirect)
    query = urllib.parse.urlencode(
        {
            "client_id": "portal",
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
    fields = {**form.fields, "username": user, "claims": json.dumps(claims) if claims else ""}
    try:
        with opener.open(
            urllib.request.Request(
                action, data=urllib.parse.urlencode(fields).encode(), method="POST"
            ),
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
            "client_id": "portal",
            "client_secret": "not-checked",
            "redirect_uri": redirect,
        }
    ).encode()
    with opener.open(
        urllib.request.Request(f"{issuer}/token", data=body, method="POST"), timeout=30
    ) as response:
        return str(json.loads(response.read())["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def claims_of(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def identity(issuer: str, user: str, oid: str, user_name: str, name: str) -> dict[str, str]:
    claims = {"oid": oid, "preferred_username": user_name, "name": name, "aud": ["platform-api"]}
    return bearer(token_for(issuer, user, claims))


# ---------------------------------------------------------------------------------------------
# Lanes


def people_list_proof(api: Api) -> list[tuple[bool, str]]:
    bob = people_by_email(api, "alice")["bob@example.test"]
    lines = [
        (
            bob["id"] == "bob" and bob["approver"] and not bob["operator"],
            f"the People list has bob as an Approver only: {bob}",
        ),
        (roles(api, "bob") == ["approver"], "bob's /me matches his row"),
    ]
    status, body = api.call("alice", "PUT", "/api/v1/people/bob/operator", {"operator": True})
    lines.append(
        (status == 200 and body["operator"] is True, f"alice makes bob an Operator: HTTP {status}")
    )
    after = roles(api, "bob")
    lines.append((after == ["operator", "approver"], f"bob's /me on his next request: {after}"))
    status, body = api.call("alice", "PUT", "/api/v1/people/bob/operator", {"operator": False})
    lines.append(
        (status == 200 and body["operator"] is False, f"alice takes it back: HTTP {status}")
    )
    back = roles(api, "bob")
    lines.append((back == ["approver"], f"bob's /me again: {back}"))
    status, _ = api.call("mallory", "GET", "/api/v1/me")
    lines.append((status == 401, f"an X-Dev-User not on the list gets 401: HTTP {status}"))
    return lines


def lane1(api: Api, out: Path, side: str) -> bool:
    run = start_watchlist_run(api)
    lines: list[tuple[bool, str]] = [
        (run["state"] == "awaiting_approval", f"run {run['run_id']} waits for approval")
    ]
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
        lines.append(
            (status == 201 and decision["decision"]["by"] == "bob", f"bob approved: HTTP {status}")
        )
        final = api.wait("alice", run["run_id"], {"succeeded", "failed", "rejected"})
        lines.append((final["state"] == "succeeded", f"run ended {final['state']}"))
    me = api.get("bob", "/api/v1/me")
    lines.append((me["roles"] == ["approver"], f"bob's /me roles {me['roles']}"))
    status, people = api.call("bob", "GET", "/api/v1/people")
    expected = 200 if side == "head" else 404
    lines.append((status == expected, f"GET /api/v1/people: HTTP {status} (expected {expected})"))
    if side == "head":
        lines.extend(people_list_proof(api))
    save(
        out,
        f"{side}.json",
        {"run": run, "decision": decision, "me": me, "people": people, "calls": api.log},
    )
    return verdict(lines)


def concrete(path: str) -> str:
    return "/".join("x_1" if part.startswith("{") else part for part in path.split("/"))


def lane2(api: Api, out: Path, issuer: str) -> bool:
    mallory = bearer(token_for(issuer, "mallory"))
    claims = claims_of(mallory["Authorization"].split()[1])
    status, doc = api.call(None, "GET", "/openapi.json", keep=False)
    if status != 200:
        raise SystemExit(f"/openapi.json: HTTP {status}")
    lines: list[tuple[bool, str]] = [
        (
            claims.get("roles") == ["Operator", "Approver"],
            f"mallory's token claims roles {claims.get('roles')}",
        )
    ]
    me_status, me = api.call(mallory, "GET", "/api/v1/me")
    lines.append(
        (
            me_status == 200 and me.get("on_list") is False and me.get("roles") == [],
            f"/me: HTTP {me_status} {me}",
        )
    )
    checked = 0
    notes: list[str] = []
    for path, item in sorted(doc["paths"].items()):
        for method, operation in sorted(item.items()):
            if path == "/api/v1/me":
                continue
            if not operation.get("security"):
                notes.append(f"{method.upper()} {path} is not a signed-in route")
                continue
            body = {} if method in ("post", "put", "patch") else None
            s, answer = api.call(mallory, method.upper(), concrete(path), body)
            ok = (
                s == 403
                and isinstance(answer, dict)
                and set(answer) == {"detail"}
                and NOT_ON_THE_LIST in str(answer["detail"])
            )
            lines.append((ok, f"{method.upper()} {path}: HTTP {s}"))
            checked += 1
    lines.append((checked > 9, f"{checked} signed-in routes from the served OpenAPI document"))
    for note in notes:
        print("note " + note)
    save(out, "p3-not-on-list.json", {"token_claims": claims, "notes": notes, "calls": api.log})
    return verdict(lines)


def lane3(api: Api, out: Path, issuer: str) -> bool:
    alice = bearer(token_for(issuer, "alice"))
    assert api.get(alice, "/api/v1/me")["on_list"] is True
    lines: list[tuple[bool, str]] = []
    if "erin@example.test" not in people_by_email(api, alice):
        status, _ = api.call(
            alice,
            "POST",
            "/api/v1/people",
            {"email": "Erin@Example.test", "display": "Erin (added by Alice)", "operator": True},
        )
        lines.append((status == 201, f"alice adds erin by email: HTTP {status}"))
    erin_before = people_by_email(api, alice)["erin@example.test"]
    lines.append((erin_before["signed_in"] is False, "erin has not signed in yet"))
    erin_token = token_for(issuer, "erin")
    oid = claims_of(erin_token).get("oid")
    me1 = api.get(bearer(erin_token), "/api/v1/me")
    lines.append(
        (
            me1["on_list"] is True and me1["id"] == erin_before["id"],
            f"erin's first sign-in matched her record by email: {me1}",
        )
    )
    lines.append(
        (
            me1["display"] == "Erin (added by Alice)",
            f"her name stays as the Operator entered it: {me1['display']}",
        )
    )
    erin_after = people_by_email(api, alice)["erin@example.test"]
    lines.append((erin_after["signed_in"] is True, "the People list shows erin signed in"))
    renamed = identity(issuer, "erin-renamed", str(oid), "erin.renamed@example.test", "Erin")
    s, me2 = api.call(renamed, "GET", "/api/v1/me")
    lines.append(
        (
            s == 200 and me2.get("on_list") is True and me2.get("id") == erin_before["id"],
            f"her oid with another user name matches on oid alone: HTTP {s} {me2}",
        )
    )
    impostor = identity(
        issuer,
        "erin-impostor",
        "0e21e000-0000-4000-8000-0000000000ff",
        "erin@example.test",
        "Impostor",
    )
    s, me3 = api.call(impostor, "GET", "/api/v1/me")
    lines.append(
        (
            s == 200 and me3.get("on_list") is False,
            f"another oid with erin's email does not get her record: HTTP {s} {me3}",
        )
    )
    save(
        out,
        "p3-first-sign-in.json",
        {
            "erin_before": erin_before,
            "erin_after": erin_after,
            "oid": oid,
            "me_first": me1,
            "me_oid_alone": me2,
            "me_impostor": me3,
            "calls": api.log,
        },
    )
    return verdict(lines)


def lane4(api: Api, out: Path) -> bool:
    dave = ensure_person(api, "alice", "dave@example.test", "Dave", True, False)
    lines: list[tuple[bool, str]] = [(dave["approver"] is False, "dave is not an Approver")]
    if pending_about(api, "alice", dave["id"]) is None:
        status, asked = api.call("alice", "POST", f"/api/v1/people/{dave['id']}/approver")
        lines.append(
            (
                status == 202 and asked["pending_approver"]["asked_by"] == "alice",
                f"alice asks: HTTP {status}",
            )
        )
    waiting = pending_about(api, "alice", dave["id"])
    lines.append(
        (
            waiting is not None and waiting["why_not"] == "you_asked",
            f"alice sees why not: {waiting and waiting['why_not']}",
        )
    )
    assert waiting is not None
    status, refused = decide(api, "alice", waiting, "confirm")
    lines.append(
        (
            status == 403 and refused.get("refusal") == "you_asked",
            f"alice confirming herself: HTTP {status} {refused}",
        )
    )
    me = api.get({"X-Dev-User": dave["id"]}, "/api/v1/me")
    lines.append((me["roles"] == ["operator"], f"dave's /me roles {me['roles']}"))
    save(
        out,
        "p3-self-confirm.json",
        {"dave": dave, "waiting": waiting, "refused": refused, "me": me, "calls": api.log},
    )
    return verdict(lines)


def lane5(api: Api, out: Path) -> bool:
    dave = people_by_email(api, "alice")["dave@example.test"]
    waiting = pending_about(api, "bob", dave["id"])
    lines: list[tuple[bool, str]] = [
        (waiting is not None and waiting["you_can_decide"], "bob may confirm")
    ]
    assert waiting is not None
    status, decided = decide(api, "bob", waiting, "confirm")
    lines.append((status == 201 and decided["decided_by"] == "bob", f"bob confirms: HTTP {status}"))
    me = api.get({"X-Dev-User": dave["id"]}, "/api/v1/me")
    lines.append((me["roles"] == ["operator", "approver"], f"dave's /me roles {me['roles']}"))
    changes = history(api)
    line = next(
        (
            h
            for h in changes
            if h["confirmation_id"] == waiting["confirmation_id"] and h["confirmed_by"]
        ),
        None,
    )
    lines.append(
        (
            line is not None and line["by"] == "alice" and line["confirmed_by"] == "bob",
            f"history names alice as asker and bob as confirmer: {line and line['summary']}",
        )
    )
    save(
        out,
        "p3-confirmed.json",
        {"waiting": waiting, "decided": decided, "me": me, "history": changes, "calls": api.log},
    )
    return verdict(lines)


def lane6(api: Api, out: Path) -> bool:
    status, refused = api.call("alice", "PUT", "/api/v1/people/alice/operator", {"operator": False})
    me = api.get("alice", "/api/v1/me")
    lines = [
        (
            status == 409 and refused.get("refusal") == "own_operator_role",
            f"alice removing her own Operator role: HTTP {status} {refused}",
        ),
        ("operator" in me["roles"], f"alice still an Operator: {me['roles']}"),
    ]
    save(out, "p3-own-operator.json", {"refused": refused, "me": me, "calls": api.log})
    return verdict(lines)


def lane7(api: Api, out: Path) -> bool:
    people = people_by_email(api, "carol")
    approvers = sorted(p["id"] for p in people.values() if p["approver"])
    lines: list[tuple[bool, str]] = [
        (approvers == ["alice", "bob"], f"the Approvers are {approvers}")
    ]
    status, refused = api.call("carol", "DELETE", "/api/v1/people/bob/approver")
    lines.append(
        (
            status == 409 and refused.get("refusal") == "two_approvers",
            f"carol removing bob's Approver role: HTTP {status} {refused}",
        )
    )
    lines.append(
        (
            "two people must stay Approvers" in str(refused.get("message")),
            "the message names the rule",
        )
    )
    me = api.get("bob", "/api/v1/me")
    lines.append((me["roles"] == ["approver"], f"bob keeps the role: {me['roles']}"))
    save(out, "p3-floor.json", {"refused": refused, "me": me, "calls": api.log})
    return verdict(lines)


def approver_ids(api: Api) -> list[str]:
    return sorted(p["id"] for p in people_by_email(api, "alice").values() if p["approver"])


def remove_together(
    api: Api, barrier: threading.Barrier, results: dict[str, Any], actor: str, target: str
) -> None:
    barrier.wait()
    results[f"{actor}->{target}"] = api.call(actor, "DELETE", f"/api/v1/people/{target}/approver")


def lane8(api: Api, out: Path, trials: int) -> bool:
    dave = confirmed_approver(api, "dave@example.test", "Dave")
    lines: list[tuple[bool, str]] = []
    record: list[dict[str, Any]] = []
    for trial in range(trials):
        held = approver_ids(api)
        if "alice" not in held:
            make_approver(api, "carol", "alice")
        if dave["id"] not in held:
            make_approver(api, "alice", dave["id"])
        before = approver_ids(api)
        barrier = threading.Barrier(2)
        results: dict[str, tuple[int, Any]] = {}
        threads = [
            threading.Thread(
                target=remove_together, args=(api, barrier, results, "alice", dave["id"])
            ),
            threading.Thread(
                target=remove_together, args=(api, barrier, results, "carol", "alice")
            ),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        statuses = sorted(s for s, _ in results.values())
        refusals = [
            r.get("refusal") for s, r in results.values() if s == 409 and isinstance(r, dict)
        ]
        after = approver_ids(api)
        ok = (
            len(before) == 3
            and statuses == [200, 409]
            and refusals == ["two_approvers"]
            and len(after) == 2
        )
        lines.append(
            (
                ok,
                f"trial {trial + 1}: before {before} statuses {statuses} "
                f"refusals {refusals} after {after}",
            )
        )
        record.append(
            {
                "before": before,
                "results": {k: {"status": s, "body": b} for k, (s, b) in results.items()},
                "after": after,
            }
        )
    save(out, "p3-race.json", {"trials": record})
    return verdict(lines)


def lane9(api: Api, out: Path) -> bool:
    dave = confirmed_approver(api, "dave@example.test", "Dave")
    erin = confirmed_approver(api, "erin@example.test", "Erin")
    dave_hdr = {"X-Dev-User": dave["id"]}
    frank = ensure_person(api, "alice", "frank@example.test", "Frank", True, False)
    api.must("alice", "POST", f"/api/v1/people/{frank['id']}/approver", None, {202})
    run = start_watchlist_run(api)
    lines: list[tuple[bool, str]] = [
        (run["state"] == "awaiting_approval", f"run {run['run_id']} waits for approval")
    ]
    approval_id = run["approval"]["approval_id"]
    view = api.get(dave_hdr, f"/api/v1/approvals/{approval_id}")
    lines.append((view["you_can_decide"], "dave may decide the run while he is an Approver"))
    waiting = pending_about(api, dave_hdr, frank["id"])
    lines.append(
        (
            waiting is not None and waiting["you_can_decide"],
            "dave may decide the request about frank",
        )
    )
    assert waiting is not None
    status, removed = api.call("carol", "DELETE", f"/api/v1/people/{dave['id']}/approver")
    lines.append(
        (
            status == 200 and removed["approver"] is False,
            f"carol removes dave's Approver role: HTTP {status}",
        )
    )
    started_at = time.monotonic()
    status, refused = api.call(
        dave_hdr,
        "POST",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": view["digest"]},
    )
    elapsed = time.monotonic() - started_at
    lines.append(
        (
            status == 403 and refused.get("refusal") == "not_an_approver",
            f"dave's run decision {elapsed:.1f}s later: HTTP {status} {refused}",
        )
    )
    started_at = time.monotonic()
    status, refused_request = decide(api, dave_hdr, waiting, "confirm")
    elapsed = time.monotonic() - started_at
    lines.append(
        (
            status == 403 and refused_request.get("refusal") == "not_an_approver",
            f"dave's decision on frank's request {elapsed:.1f}s later: "
            f"HTTP {status} {refused_request}",
        )
    )
    after = api.get("bob", f"/api/v1/approvals/{approval_id}")
    lines.append((after["steps"][0]["status"] == "open", "the run's step is still open"))
    still = pending_about(api, "bob", frank["id"])
    lines.append(
        (
            still is not None and still["confirmation_id"] == waiting["confirmation_id"],
            "frank's request is still open",
        )
    )
    lines.append(
        (
            people_by_email(api, "alice")["frank@example.test"]["approver"] is False,
            "frank is not an Approver",
        )
    )
    status, decided = api.call(
        "bob",
        "POST",
        f"/api/v1/approvals/{approval_id}/decisions",
        {"step": 0, "verdict": "approve", "digest": view["digest"]},
    )
    lines.append((status == 201, f"bob approves the run instead: HTTP {status}"))
    save(
        out,
        "p3-removed.json",
        {
            "run": run,
            "erin": erin,
            "removed": removed,
            "refused": refused,
            "refused_request": refused_request,
            "bob": decided,
            "calls": api.log,
        },
    )
    return verdict(lines)


def asker(api: Api, out: Path) -> bool:
    lines: list[tuple[bool, str]] = []
    gina = ensure_person(api, "alice", "gina@example.test", "Gina", True, False)
    hal = ensure_person(api, "alice", "hal@example.test", "Hal", True, False)
    status, _ = api.call({"X-Dev-User": gina["id"]}, "POST", f"/api/v1/people/{hal['id']}/approver")
    lines.append((status == 202, f"gina asks to make hal an Approver: HTTP {status}"))
    status, _ = api.call("alice", "DELETE", f"/api/v1/people/{gina['id']}")
    lines.append((status == 204, f"alice removes gina: HTTP {status}"))
    lines.append(
        (pending_about(api, "bob", hal["id"]) is None, "bob no longer sees a request about hal")
    )
    line = history_line(
        api, "Gina's request to make Hal an Approver was closed, because Gina left the list."
    )
    lines.append(
        (
            line is not None and line["by"] == "alice" and line["confirmed_by"] is None,
            f"the history says why it closed: {line}",
        )
    )
    status, body = api.call("alice", "POST", f"/api/v1/people/{hal['id']}/approver")
    lines.append(
        (status == 202, f"alice asks again: HTTP {status} {body if status != 202 else ''}")
    )
    fresh = pending_about(api, "bob", hal["id"])
    status, _ = decide(api, "bob", fresh, "confirm") if fresh else (0, None)
    lines.append((status == 201, f"bob confirms the fresh request: HTTP {status}"))
    lines.append(
        (
            people_by_email(api, "alice")["hal@example.test"]["approver"] is True,
            "hal is an Approver",
        )
    )

    ivy = ensure_person(api, "carol", "ivy@example.test", "Ivy", True, False)
    status, _ = api.call("alice", "POST", f"/api/v1/people/{ivy['id']}/approver")
    lines.append((status == 202, f"alice asks to make ivy an Approver: HTTP {status}"))
    status, _ = api.call("carol", "PUT", "/api/v1/people/alice/operator", {"operator": False})
    lines.append((status == 200, f"carol removes alice's Operator role: HTTP {status}"))
    lines.append(
        (pending_about(api, "bob", ivy["id"]) is None, "bob no longer sees a request about ivy")
    )
    line = history_line(
        api,
        "Alice's request to make Ivy an Approver was closed, "
        "because Alice is no longer an Operator.",
    )
    lines.append(
        (
            line is not None and line["by"] == "carol" and line["confirmed_by"] is None,
            f"the history says why it closed: {line}",
        )
    )
    status, body = api.call("carol", "POST", f"/api/v1/people/{ivy['id']}/approver")
    lines.append(
        (status == 202, f"carol asks again: HTTP {status} {body if status != 202 else ''}")
    )
    status, _ = api.call("carol", "PUT", "/api/v1/people/alice/operator", {"operator": True})
    lines.append((status == 200, f"carol gives alice the Operator role back: HTTP {status}"))
    save(out, "p3-asker-gone.json", {"calls": api.log})
    return verdict(lines)


def roleless(api: Api, out: Path) -> bool:
    lines: list[tuple[bool, str]] = []
    mia = ensure_person(api, "alice", "mia@example.test", "Mia", False, True)
    lines.append(
        (
            mia["pending_approver"] is not None and roles(api, {"X-Dev-User": mia["id"]}) == [],
            "mia waits with no role",
        )
    )
    waiting = pending_about(api, "bob", mia["id"])
    status, _ = decide(api, "bob", waiting, "not_now") if waiting else (0, None)
    lines.append((status == 201, f"bob says not now: HTTP {status}"))
    lines.append(("mia@example.test" not in people_by_email(api, "alice"), "mia is off the list"))
    status, _ = api.call({"X-Dev-User": mia["id"]}, "GET", "/api/v1/me")
    lines.append((status == 401, f"mia's next request: HTTP {status}"))
    line = history_line(api, "Mia was removed from the list, because Mia has no other role.")
    lines.append((line is not None and line["by"] == "bob", f"the history says why: {line}"))

    kim = ensure_person(api, "alice", "kim@example.test", "Kim", True, False)
    lee = ensure_person(api, {"X-Dev-User": kim["id"]}, "lee@example.test", "Lee", False, True)
    lines.append(
        (lee["pending_approver"] is not None, "kim adds lee and asks for the Approver role")
    )
    status, _ = api.call("alice", "DELETE", f"/api/v1/people/{kim['id']}")
    lines.append((status == 204, f"alice removes kim: HTTP {status}"))
    lines.append(
        ("lee@example.test" not in people_by_email(api, "alice"), "lee is off the list too")
    )
    lines.append(
        (
            history_line(api, "Lee was removed from the list, because Lee has no other role.")
            is not None,
            "the history says why",
        )
    )
    save(out, "p3-roleless.json", {"calls": api.log})
    return verdict(lines)


def readd(api: Api, out: Path, issuer: str) -> bool:
    alice = bearer(token_for(issuer, "alice"))
    lines: list[tuple[bool, str]] = []
    carol = ensure_person(api, alice, "carol@example.test", "Carol", True, False)
    carol_token = token_for(issuer, "carol")
    carol_oid = str(claims_of(carol_token).get("oid"))
    s, me = api.call(bearer(carol_token), "GET", "/api/v1/me")
    lines.append((s == 200 and me.get("id") == carol["id"], f"carol signs in: {me}"))
    s, _ = api.call(alice, "DELETE", f"/api/v1/people/{carol['id']}")
    lines.append((s == 204, f"alice removes carol: HTTP {s}"))
    s, me = api.call(bearer(token_for(issuer, "carol")), "GET", "/api/v1/me")
    lines.append((s == 200 and me.get("on_list") is False, f"carol is no longer on the list: {me}"))
    moved = ensure_person(api, alice, "carol.new@example.test", "Carol (new email)", True, False)
    lines.append((moved["id"] != carol["id"], f"alice adds carol under a new email: {moved['id']}"))
    s, me = api.call(
        identity(issuer, "carol-moved", carol_oid, "carol.new@example.test", "Carol"),
        "GET",
        "/api/v1/me",
    )
    lines.append(
        (
            s == 200 and me.get("on_list") is True and me.get("id") == moved["id"],
            f"carol's oid with her new email signs in to the new record: {me}",
        )
    )

    erin = ensure_person(api, alice, "erin@example.test", "Erin", True, False)
    erin_token = token_for(issuer, "erin")
    erin_oid = str(claims_of(erin_token).get("oid"))
    lines.append(
        (api.get(bearer(erin_token), "/api/v1/me").get("id") == erin["id"], "erin signs in")
    )
    s, _ = api.call(alice, "DELETE", f"/api/v1/people/{erin['id']}")
    lines.append((s == 204, f"alice removes erin: HTTP {s}"))
    s, back = api.call(
        alice,
        "POST",
        "/api/v1/people",
        {"email": "erin@example.test", "display": "Erin again", "operator": True},
    )
    lines.append(
        (
            s == 201 and back["id"] == erin["id"] and back["signed_in"] is False,
            f"alice adds erin back: HTTP {s} {back}",
        )
    )
    s, me = api.call(
        identity(issuer, "erin-renamed", erin_oid, "erin.renamed@example.test", "Erin"),
        "GET",
        "/api/v1/me",
    )
    lines.append(
        (
            s == 200 and me.get("on_list") is False,
            f"erin's old oid with another user name does not sign in: {me}",
        )
    )
    s, me = api.call(
        identity(
            issuer,
            "erin-new",
            "0e21e000-0000-4000-8000-0000000000aa",
            "erin@example.test",
            "Erin New",
        ),
        "GET",
        "/api/v1/me",
    )
    lines.append(
        (
            s == 200 and me.get("on_list") is True and me.get("id") == erin["id"],
            f"a sign-in with erin's email binds the record afresh: {me}",
        )
    )
    s, me = api.call(bearer(token_for(issuer, "erin")), "GET", "/api/v1/me")
    lines.append(
        (
            s == 200 and me.get("on_list") is False,
            f"erin's old sign-in no longer matches the record: {me}",
        )
    )
    save(out, "p3-readd.json", {"carol_oid": carol_oid, "erin_oid": erin_oid, "calls": api.log})
    return verdict(lines)


def tenant(api: Api, out: Path, issuer: str) -> bool:
    plain = token_for(issuer, "alice")
    lines: list[tuple[bool, str]] = [
        ("tid" not in claims_of(plain), "the mock's alice token has no tid")
    ]
    foreign = token_for(issuer, "alice", {"tid": "11111111-2222-3333-4444-555555555555"})
    lines.append(
        (
            claims_of(foreign).get("tid") == "11111111-2222-3333-4444-555555555555",
            "alice with another tenant's tid",
        )
    )
    s, _ = api.call(bearer(foreign), "GET", "/api/v1/me")
    lines.append((s == 401, f"another tenant on /me: HTTP {s}"))
    s, _ = api.call(bearer(foreign), "GET", "/api/v1/people")
    lines.append((s == 401, f"another tenant on /people: HTTP {s}"))
    same = token_for(issuer, "alice", {"tid": "default"})
    s, body = api.call(bearer(same), "GET", "/api/v1/me")
    lines.append(
        (
            s == 200 and body.get("on_list") is True,
            f"control, the issuer's own tenant: HTTP {s} {body}",
        )
    )
    save(out, "p3-tenant.json", {"foreign_claims": claims_of(foreign), "calls": api.log})
    return verdict(lines)


def people_snapshot(api: Api, out: Path, file: str) -> bool:
    people = api.get("alice", "/api/v1/people")
    save(out, file, people)
    print(f"saved {len(people['people'])} people to {out / file}")
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 3:
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
            ok = lane8(api, out, int(rest[0]) if rest else RACE_TRIALS)
        case "lane9":
            ok = lane9(api, out)
        case "asker":
            ok = asker(api, out)
        case "roleless":
            ok = roleless(api, out)
        case "readd":
            ok = readd(api, out, rest[0])
        case "tenant":
            ok = tenant(api, out, rest[0])
        case "people":
            ok = people_snapshot(api, out, rest[0])
        case _:
            print(__doc__)
            return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
