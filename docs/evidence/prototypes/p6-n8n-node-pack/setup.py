"""Sets up the owner (the platform's account), an API key, and one ordinary staff member.

Also tries to make a staff member an n8n admin, to see whether the free edition allows it.
"""

import secrets as rnd

from lib import Rest, save_secrets, secrets, show

API_KEY_SCOPES = [
    "workflow:create", "workflow:read", "workflow:update", "workflow:list", "workflow:delete",
    "workflow:activate", "workflow:deactivate", "execution:read", "execution:list",
]


def password():
    return "P6-" + rnd.token_urlsafe(12) + "a1A"


s = secrets()
owner = Rest()
if "owner" not in s:
    s["owner"] = {"email": "platform@example.com", "password": password()}
    st, r = owner.call("POST", "/owner/setup", {"email": s["owner"]["email"], "firstName": "Platform", "lastName": "Account", "password": s["owner"]["password"]})
    show("owner setup", [st, r.get("data", {}).get("role") if isinstance(r, dict) else r])
show("owner signed in as", owner.login(s["owner"]["email"], s["owner"]["password"])["role"])

st, r = owner.call("POST", "/api-keys", {"label": "p6", "expiresAt": None, "scopes": API_KEY_SCOPES})
show("api key", [st, "created" if st == 200 else r])
s["apikey"] = r["data"]["rawApiKey"]
save_secrets(s)

for who, role in (("staff", "global:member"), ("admin", "global:admin")):
    if who in s:
        continue
    email = f"{who}@example.com"
    st, r = owner.call("POST", "/invitations", [{"email": email, "role": role}])
    show(f"invite {who} as {role}", [st, r])
    if st != 200:
        continue
    user = r["data"][0]["user"]
    token = user["inviteAcceptUrl"].split("token=")[1]
    pw = password()
    st, r2 = Rest().call("POST", "/invitations/accept", {"token": token, "firstName": who.title(), "lastName": "Tester", "password": pw})
    show(f"accept {who}", [st, r2.get("data", {}).get("role") if isinstance(r2, dict) else r2])
    if st == 200:
        s[who] = {"email": email, "password": pw, "id": user["id"]}
save_secrets(s)
print("users saved:", [k for k in s if k not in ("apikey",)])
