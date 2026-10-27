"""Q4 again, with the publisher's email (q34.py read the wrong field), and Q6: can an ordinary staff member add keys?"""

import json

from lib import Rest, secrets, show

s = secrets()
wid = json.load(open("ids.json"))["workflow"]
owner, staff = Rest(), Rest()
owner.login(s["owner"]["email"], s["owner"]["password"])
staff.login(s["staff"]["email"], s["staff"]["password"])
st, r = owner.call("GET", f"/workflow-history/workflow/{wid}/publish-timeline")
show("Q4 timeline (event, who, version)", [(e["event"], (e.get("user") or {}).get("email"), e["versionId"][:8]) for e in r["data"]])
st, r = staff.call("POST", "/credentials", {"name": "Staff's own Jira key", "type": "jiraSoftwareCloudApi",
    "data": {"email": "staff@example.com", "apiToken": "not-a-real-token", "domain": "https://example.atlassian.net"}})
show("Q6 staff adds a Jira key", [st, {k: r.get("data", {}).get(k) for k in ("id", "name", "type")} if st == 200 else r])
st, r = staff.call("POST", "/credentials", {"name": "Staff's own header key", "type": "httpHeaderAuth", "data": {"name": "Authorization", "value": "Bearer not-real"}})
show("Q6 staff adds an HTTP header key", [st, {k: r.get("data", {}).get(k) for k in ("id", "name", "type")} if st == 200 else r])
st, r = owner.call("GET", "/credentials")
show("Q6 platform can list every key, including staff's", [st, [(c["name"], c["type"]) for c in r.get("data", [])]])
