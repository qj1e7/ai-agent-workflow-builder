"""Makes the owner (the platform's account) and its API key, and hands the key to the stub.

Members are made in q09, because how to make them is one of the questions.
"""

import secrets as rnd

from lib import Raw, Rest, save_secrets, secrets, stub_post

raw = Raw("setup")
s = secrets()
s["owner"] = {"email": "platform@example.com", "password": "P7-" + rnd.token_urlsafe(12) + "a1A"}
owner = Rest()
st, r = owner.call("POST", "/owner/setup", {"email": s["owner"]["email"], "firstName": "Platform", "lastName": "Account", "password": s["owner"]["password"]})
raw("POST /rest/owner/setup", [st, (r.get("data") or {}).get("role") if isinstance(r, dict) else r])
save_secrets(s)
owner.login(s["owner"]["email"], s["owner"]["password"])

st, r = owner.call("GET", "/api-keys/scopes")
scopes = r["data"]
raw("GET /rest/api-keys/scopes", [st, len(scopes), scopes])
st, r = owner.call("POST", "/api-keys", {"label": "p7", "expiresAt": None, "scopes": scopes})
raw("POST /rest/api-keys (all scopes)", [st, "created" if st == 200 else r])
s["apikey"] = r["data"]["rawApiKey"]
save_secrets(s)
stub_post("/control", {"apikey": s["apikey"]})
raw("stub has the API key")
