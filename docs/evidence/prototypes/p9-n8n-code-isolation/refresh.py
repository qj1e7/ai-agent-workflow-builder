"""The token-refresh check. Does n8n change a key's updatedAt when it saves a token it got, as the
credential sweep's _vouched() would notice? It runs on whatever p9 stack is up, except ssrf-on, whose
SSRF protection refuses the stand-in on localhost.

A generic OAuth2 key (oAuth2Api, client credentials) points at the stand-in's /token, and an HTTP
Request block calls the stand-in's /api/echo with it. This runs n8n's own code for getting a first
token (oauth.js line 243) and for refreshing one after a 401 (oauth.js line 153). Both save through
CredentialsHelper.updateCredentialsOauthTokenData (credentials-helper.js line 427). No real sign-in.

Usage: python3 refresh.py (after python3 run.py, with the stack still up)
"""

from lib import Raw, clean_up, fake, link, node, public, run_by_hand, setup_owner
import probes


def times(cred_id):
    st, page = public("GET", "/credentials?limit=250")
    for c in (page or {}).get("data", []):
        if c["id"] == cred_id:
            return c["createdAt"], c["updatedAt"]
    return None, None


def main():
    raw = Raw("refresh")
    owner = setup_owner()
    fake("POST", "/p9/reset")
    st, cred = public("POST", "/credentials", {"name": "p9 oauth2 key", "type": "oAuth2Api", "data": {
        "grantType": "clientCredentials", "accessTokenUrl": "http://localhost:42356/token", "clientId": "p9-client",
        "clientSecret": "p9-not-a-secret", "scope": "", "authentication": "header", "sendAdditionalBodyProperties": False,
        "ignoreSSLIssues": False}})
    raw("POST /credentials oAuth2Api (client credentials, stand-in token URL)", {"status": st})
    assert st == 200, "credential not made"
    made = times(cred["id"])
    raw("as made: createdAt, updatedAt", made)
    call = node("Call", "n8n-nodes-base.httpRequest", {
        "method": "GET", "url": "http://localhost:42356/api/echo", "authentication": "genericCredentialType",
        "genericAuthType": "oAuth2Api", "options": {}}, (200, 0), tv=4.2,
        credentials={"oAuth2Api": {"id": cred["id"], "name": cred["name"]}})
    steps = [("first run: no token yet, so n8n gets one", False), ("second run: the saved token works", False),
             ("third run: the stand-in refuses the token with 401, so n8n gets a new one", True)]
    before = made
    results = []
    for label, rotate in steps:
        if rotate:
            fake("POST", "/p9/rotate")
        run, failed = run_by_hand(owner, "p9 refresh", [probes.TRIGGER, call], link(("Run by hand", "Call")), "Call")
        status = run["data"]["status"] if run else failed
        after = times(cred["id"])
        rec = fake("GET", "/p9/record")
        row = {"execution": status, "createdAt_same": after[0] == made[0], "updatedAt_changed": after[1] != before[1],
               "updatedAt": after[1], "tokens_issued_so_far": rec["tokens_issued"], "echo_statuses_so_far": rec["echo"]}
        raw(label, row)
        results.append(row)
        before = after
        clean_up(run)
    public("DELETE", f"/credentials/{cred['id']}")
    raw.put("made", {"createdAt": made[0], "updatedAt": made[1]})
    raw.put("runs", results)
    raw.save()


if __name__ == "__main__":
    main()
