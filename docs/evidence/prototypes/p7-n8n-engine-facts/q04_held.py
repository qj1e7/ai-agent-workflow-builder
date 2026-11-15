"""Q4: the owner's PUT and publish on a workflow held in a member's project. Also: the member publishes,
the publish timeline and the history's authors, the holder's own manual run, and taking it back.
"""

import json
import time

from lib import SETTINGS, Raw, Rest, call_node, create, execution, finished, link, public, secrets, signed_start, slim, start_node, stub_get

raw = Raw("q04")
owner, alice = Rest("owner"), Rest("alice")
s = secrets()


def state(label, wid):
    st, r = public("GET", f"/workflows/{wid}")
    raw(f"{label}: public GET", [st, {k: r.get(k) for k in ("versionId", "activeVersionId", "active")} if st == 200 else r])


nodes = [start_node(), call_node("Read release", "read")]
conns = link(("Start from the Portal", "Read release"))
w = create("q04 held by Alice", nodes, conns, raw=raw)
wid = w["id"]
public("POST", f"/workflows/{wid}/publish", {})
v_owner = public("GET", f"/workflows/{wid}")[1]["activeVersionId"]

st, r = public("PUT", f"/workflows/{wid}/transfer", {"destinationProjectId": s["alice"]["project"]})
raw("public PUT /workflows/{id}/transfer to Alice's project", [st, r])
state("after transfer", wid)
st, r = alice.call("GET", "/workflows")
raw("Alice lists her workflows", [st, [x["name"] for x in (r.get("data") or [])] if st == 200 else r])

renamed = [dict(n, name="Read release (owner edit)") if n["name"] == "Read release" else n for n in nodes]
st, r = public("PUT", f"/workflows/{wid}", {"name": w["name"], "nodes": renamed, "connections": link(("Start from the Portal", "Read release (owner edit)")), "settings": SETTINGS})
raw("owner public PUT on the held workflow (publishIfActive default)", [st, {k: r.get(k) for k in ("versionId", "activeVersionId")} if st == 200 else r])
st, r = public("POST", f"/workflows/{wid}/publish", {"versionId": v_owner})
raw("owner public POST /publish {versionId: the first version} on the held workflow", [st, {k: r.get(k) for k in ("versionId", "activeVersionId")} if st == 200 else r])

st, r = alice.call("GET", f"/workflows/{wid}")
doc = r["data"]
doc_nodes = [dict(n, name="Read release (Alice)") if n["name"].startswith("Read release") else n for n in doc["nodes"]]
st, r = alice.call("PATCH", f"/workflows/{wid}", {"versionId": doc["versionId"], "nodes": doc_nodes, "connections": link(("Start from the Portal", "Read release (Alice)"))})
raw("Alice saves an edit (PATCH /rest/workflows/{id})", [st, (r.get("data") or {}).get("versionId") if st == 200 else r])
new_v = r["data"]["versionId"]
st, r = alice.call("POST", f"/workflows/{wid}/activate", {"versionId": new_v})
raw("Alice publishes it (POST /rest/workflows/{id}/activate {versionId})", [st, (r.get("data") or {}).get("activeVersionId") if st == 200 else r])
state("after Alice publishes", wid)

st, r = owner.call("GET", f"/workflow-history/workflow/{wid}/publish-timeline")
raw("GET /rest/workflow-history/workflow/{id}/publish-timeline: (versionId, event, user email, user id)",
    [st, [(e["versionId"][:8], e["event"], e["user"]["email"], e["user"]["id"]) for e in r["data"]] if st == 200 else r])
raw("timeline entry keys", sorted(r["data"][0]) if st == 200 else None)
st, r = public("GET", f"/workflows/{wid}/history")
raw("public GET /workflows/{id}/history: (versionId, authors)", [st, [(h["versionId"][:8], h["authors"]) for h in r["data"]] if st == 200 else r])
raw("history entry keys", sorted(r["data"][0]) if st == 200 else None)
users = {x["id"]: x["email"] for x in public("GET", "/users")[1]["data"]}
raw("user ids", users)

item = json.loads(signed_start(kind="test")[0])
st, r = alice.call("POST", f"/workflows/{wid}/run", {"triggerToStartFrom": {"name": "Start from the Portal", "data": {"startTime": 0, "executionTime": 0, "source": [], "data": {"main": [[{"json": item}]]}}}})
raw("Alice runs it by hand (POST /rest/workflows/{id}/run)", [st, r])
eid = (r.get("data") or {}).get("executionId")
if eid:
    finished(eid, 60)
    raw("Alice's run", slim(execution(eid)))
    raw("node calls (node, mode)", [(c["node_name"], c["mode"]) for c in stub_get()["calls"] if str(c["execution_id"]) == str(eid)])
st, r = alice.call("POST", f"/workflows/{wid}/run", {"destinationNode": {"nodeName": "Read release (Alice)", "mode": "inclusive"}})
raw("Alice presses Execute in the editor (destinationNode, no item)", [st, r])
time.sleep(1)

st, r = public("PUT", f"/workflows/{wid}/transfer", {"destinationProjectId": s["owner"]["project"]})
raw("take it back: public transfer to the owner's project", [st, r])
state("after take back", wid)
st, r = alice.call("GET", f"/workflows/{wid}")
raw("Alice opens it after take back", [st, r if st != 200 else "200"])
public("POST", f"/workflows/{wid}/unpublish", {})
