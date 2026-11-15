"""Q9: can the platform make a staff member's n8n account through the public POST /users on the free edition?

Alice is made through the public API, Bob through /rest/invitations, so both paths are tried.
"""

import secrets as rnd
import urllib.parse

from lib import Raw, Rest, public, save_secrets, secrets

raw = Raw("q02")
owner = Rest("owner")
s = secrets()


def password():
    return "P7-" + rnd.token_urlsafe(12) + "a1A"


def accept(who, url, user_id):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    pw = password()
    person = Rest()
    if "token" in q:
        st, r = person.call("POST", "/invitations/accept", {"token": q["token"][0], "firstName": who.title(), "lastName": "Tester", "password": pw})
        path = "POST /rest/invitations/accept {token}"
    else:
        st, r = person.call("POST", f"/invitations/{q['inviteeId'][0]}/accept", {"inviterId": q["inviterId"][0], "firstName": who.title(), "lastName": "Tester", "password": pw})
        path = "POST /rest/invitations/{inviteeId}/accept {inviterId}"
    raw(f"{who} accepts: {path}", [st, (r.get("data") or {}).get("role") if isinstance(r, dict) else r])
    if st == 200:
        s[who] = {"email": f"{who}@example.com", "password": pw, "id": user_id}
        save_secrets(s)


raw("the invite link's shape (query keys only)")
st, r = public("POST", "/users", [{"email": "alice@example.com", "role": "global:member"}])
raw("public POST /api/v1/users [alice, global:member]", [st, r])
if st in (200, 201):
    u = r[0]["user"] if isinstance(r, list) else r["data"][0]["user"]
    raw("invite link query keys", sorted(urllib.parse.parse_qs(urllib.parse.urlparse(u["inviteAcceptUrl"]).query)))
    accept("alice", u["inviteAcceptUrl"], u["id"])

st, r = public("POST", "/users", [{"email": "carol@example.com", "role": "global:admin"}])
raw("public POST /api/v1/users [carol, global:admin]", [st, r])

st, r = owner.call("POST", "/invitations", [{"email": "bob@example.com", "role": "global:member"}])
raw("POST /rest/invitations [bob]", [st, r])
if st == 200:
    u = r["data"][0]["user"]
    accept("bob", u["inviteAcceptUrl"], u["id"])

st, r = public("GET", "/users?includeRole=true")
raw("public GET /api/v1/users", [st, [(x["email"], x.get("role"), x.get("isPending")) for x in r.get("data", [])] if st == 200 else r])
st, r = public("GET", "/projects")
raw("public GET /api/v1/projects", [st, r if st != 200 else [(p["name"], p["type"]) for p in r.get("data", [])]])
for who in ("alice", "bob"):
    if who in s:
        st, r = Rest(who).call("GET", "/projects/personal")
        raw(f"{who}: GET /rest/projects/personal", [st, (r.get("data") or {}).get("type")])
        s[who]["project"] = r["data"]["id"]
st, r = owner.call("GET", "/projects")
raw("owner: GET /rest/projects (how the platform finds a member's project without their login)", [st, [(p["type"], p["name"]) for p in (r.get("data") or [])] if st == 200 else r])
st, r = owner.call("GET", "/projects/personal")
s["owner"]["project"] = r["data"]["id"]
save_secrets(s)
raw("project ids saved for owner, alice, bob")
