"""Q3: on the free Community edition, can a staff member edit an n8n workflow the platform made, and can
editing be kept apart from publishing?
Q4: does n8n record who published each version?

The platform account is n8n's owner. "staff" is an ordinary member, the only other role the free edition
allowed (setup.py: inviting an admin needs a paid licence).
"""

import json

from lib import Rest, public, secrets, show

s = secrets()
wid = json.load(open("ids.json"))["workflow"]
owner, staff = Rest(), Rest()
owner.login(s["owner"]["email"], s["owner"]["password"])
staff_user = staff.login(s["staff"]["email"], s["staff"]["password"])


def wf_summary(r):
    d = r.get("data", r) if isinstance(r, dict) else r
    return {k: d.get(k) for k in ("id", "active", "versionId", "activeVersionId")} if isinstance(d, dict) else d


# 1. Can staff see the platform's n8n workflow at all?
st, r = staff.call("GET", "/workflows")
show("Q3 staff list of workflows", [st, [w["name"] for w in r.get("data", [])] if st == 200 else r])
st, r = staff.call("GET", f"/workflows/{wid}")
show("Q3 staff opens the platform's workflow", [st, r if st != 200 else wf_summary(r)])

# 2. Can the platform share it with staff?
st, r = staff.call("GET", "/projects/personal")
staff_project = r["data"]["id"]
st, r = owner.call("PUT", f"/workflows/{wid}/share", {"shareWithIds": [staff_project]})
show("Q3 platform shares the workflow with staff", [st, r])

# 3. Can the platform move it into the staff member's own space instead?
st, r = owner.call("PUT", f"/workflows/{wid}/transfer", {"destinationProjectId": staff_project})
show("Q3 platform moves the workflow to staff's personal space", [st, r])

st, r = staff.call("GET", f"/workflows/{wid}")
show("Q3 staff opens it after the move", [st, wf_summary(r) if st == 200 else r])
if st == 200:
    w = r["data"]
    # Staff make an edit: rename the trigger's path, as a stand-in for changing a step.
    for n in w["nodes"]:
        if n["name"] == "Version checker":
            n["notes"] = "Edited by staff"
    st, r = staff.call("PATCH", f"/workflows/{wid}", {"versionId": w["versionId"], "nodes": w["nodes"], "connections": w["connections"]})
    show("Q3 staff saves an edit (a draft)", [st, wf_summary(r) if st == 200 else r])
    draft = r.get("data", {}).get("versionId") if st == 200 else None
    st, r = staff.call("GET", f"/workflows/{wid}/publication-status")
    show("Q3 publication status after the staff edit", [st, r])
    st, r = staff.call("POST", f"/workflows/{wid}/activate", {"versionId": draft})
    show("Q3 staff publishes their edit", [st, wf_summary(r) if st == 200 else r])
    if st != 200:
        st, r = owner.call("POST", f"/workflows/{wid}/activate", {"versionId": draft})
        show("Q3 platform publishes the staff edit instead", [st, wf_summary(r) if st == 200 else r])

    # The platform can still read and publish everything, through the public API too.
    st, r = public("GET", f"/workflows/{wid}")
    show("Q3 platform reads the moved workflow through the public API", [st, wf_summary(r) if st == 200 else r])

# 4. Can staff publish a workflow they made themselves?
st, r = staff.call("POST", "/workflows", {"name": "P6 staff's own", "nodes": [
    {"id": "t", "name": "Start", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0],
     "parameters": {"httpMethod": "POST", "path": "p6-staff-own", "options": {}}, "webhookId": "p6-staff-own"}],
    "connections": {}, "settings": {"executionOrder": "v1"}})
own = r.get("data", {}) if st == 200 else {}
show("Q3 staff creates their own workflow", [st, wf_summary(r) if st == 200 else r])
if own:
    st, r = staff.call("POST", f"/workflows/{own['id']}/activate", {"versionId": own["versionId"]})
    show("Q3 staff publishes their own workflow", [st, wf_summary(r) if st == 200 else r])

# Q4. Who published each version?
st, r = owner.call("GET", f"/workflow-history/workflow/{wid}/publish-timeline")
show("Q4 publish timeline", [st, r])
st, users = owner.call("GET", "/users")
names = {u["id"]: u["email"] for u in users.get("data", {}).get("items", users.get("data", []))} if st == 200 else {}
events = r.get("data", []) if isinstance(r, dict) else []
show("Q4 timeline with emails", [{"event": e.get("event"), "by": names.get(e.get("userId"), e.get("userId")), "version": (e.get("versionId") or "")[:8], "at": e.get("createdAt")} for e in events])
st, r = owner.call("GET", f"/workflow-history/workflow/{wid}?take=10")
show("Q4 version list", [st, [{"version": v.get("versionId", "")[:8], "authors": v.get("authors"), "at": v.get("createdAt")} for v in r.get("data", [])] if st == 200 else r])
