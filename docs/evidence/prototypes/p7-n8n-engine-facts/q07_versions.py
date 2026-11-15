"""Q7 publish {versionId} and the free edition's history retention. Q18 does PUT refuse a stale versionId? Q19 the /rest checklist."""

import time

from lib import B, SETTINGS, Raw, Rest, call_node, create, executions, link, post_url, psql, public, signed_start, start_node, stub_get, wait_for

raw = Raw("q07")
owner = Rest("owner")


def doc(name):
    return [start_node(webhookId="7a7a7a7a-0000-4000-8000-000000000007"), call_node(name, "read")], link(("Start from the Portal", name))


def ids(wid):
    r = public("GET", f"/workflows/{wid}")[1]
    return {"versionId": r["versionId"], "activeVersionId": r["activeVersionId"]}


def put(wid, name, q="", extra=None):
    n, c = doc(name)
    return public("PUT", f"/workflows/{wid}{q}", {"name": "q07 versions", "nodes": n, "connections": c, "settings": SETTINGS, **(extra or {})})


n, c = doc("Read v1")
w = create("q07 versions", n, c, raw=raw)
wid = w["id"]
v1 = w["versionId"]
st, r = public("POST", f"/workflows/{wid}/activate", {})
raw("public POST /workflows/{id}/activate (the plan's Turn it on call)", [st, {k: r.get(k) for k in ("active", "versionId", "activeVersionId")} if st == 200 else r])
st, r = put(wid, "Read v2")
v2 = r["versionId"]
raw("PUT Read v2 (publishIfActive default)", [st, ids(wid)])
st, r = put(wid, "Read v3", "?publishIfActive=false")
v3 = r["versionId"]
raw("PUT Read v3 with publishIfActive=false", [st, ids(wid)])
raw("v1, v2, v3", [v1, v2, v3])

st, r = public("GET", f"/workflows/{wid}/history")
raw("public GET /workflows/{id}/history: (versionId, authors, createdAt)", [st, [(h["versionId"], h["authors"], h["createdAt"]) for h in r["data"]]])
st, r = public("GET", f"/workflows/{wid}/versions/{v1}")
raw("public GET /workflows/{id}/versions/{v1}: node names", [st, [x["name"] for x in r.get("nodes", [])] if st == 200 else r])

st, r = public("POST", f"/workflows/{wid}/publish", {"versionId": v1})
raw("public POST /workflows/{id}/publish {versionId: v1}", [st, ids(wid)])
st, r = owner.call("GET", f"/workflows/{wid}/publication-status")
raw("GET /rest/workflows/{id}/publication-status", [st, r.get("data")])
time.sleep(2)
seen = {e["id"] for e in executions(wid)}
b, h = signed_start()
post_url(f"{B}/webhook/7a7a7a7a-0000-4000-8000-000000000007/start", headers=h, raw_body=b)
ex = wait_for(lambda: next((e for e in executions(wid) if e["id"] not in seen), None), 90)
raw("a start now runs the block named", [c["node_name"] for c in stub_get()["calls"] if str(c["execution_id"]) == str(ex["id"])])

st, r = put(wid, "Read v4 (stale)", "?publishIfActive=false", {"versionId": v1})
raw("PUT with a stale versionId (v1, while the draft is v3)", [st, r if st != 200 else ids(wid)])
cur = ids(wid)["versionId"]
st, r = put(wid, "Read v5 (current)", "?publishIfActive=false", {"versionId": cur})
raw("PUT with the current versionId", [st, r if st != 200 else ids(wid)])
st, r = put(wid, "Read v6 (no versionId)", "?publishIfActive=false")
raw("PUT with no versionId", [st, r if st != 200 else ids(wid)])

cur = owner.call("GET", f"/workflows/{wid}")[1]["data"]
nodes6 = cur["nodes"]
st, r = owner.call("PATCH", f"/workflows/{wid}", {"versionId": v1, "nodes": nodes6, "connections": cur["connections"], "name": "q07 stale rest"})
raw("PATCH /rest/workflows/{id} with a stale versionId", [st, r if st != 200 else "saved"])
st, r = owner.call("PATCH", f"/workflows/{wid}", {"versionId": cur["versionId"], "name": "q07 versions (rest)"})
raw("PATCH /rest/workflows/{id} with the current versionId", [st, (r.get("data") or {}).get("versionId") if st == 200 else r])

st, r = owner.call("GET", f"/workflows/{wid}")
cur = r["data"]
raw("GET /rest/workflows/{id} carries a checksum", ["checksum" in cur, sorted(k for k in cur if "check" in k.lower() or "version" in k.lower())])
st, r = owner.call("PATCH", f"/workflows/{wid}", {"expectedChecksum": "stale", "name": "q07 versions (stale checksum)"})
raw("PATCH /rest/workflows/{id} with a stale expectedChecksum (free edition)", [st, "saved" if st == 200 else r])
cur = owner.call("GET", f"/workflows/{wid}")[1]["data"]
st, r = owner.call("POST", f"/workflows/{wid}/activate", {"versionId": cur["versionId"], "expectedChecksum": "stale"})
raw("POST /rest/workflows/{id}/activate {versionId, expectedChecksum: stale}", [st, r if st != 200 else "published"])
st, r = owner.call("POST", f"/workflows/{wid}/activate", {"versionId": cur["versionId"], "expectedChecksum": cur.get("checksum")})
raw("POST /rest/workflows/{id}/activate {versionId, expectedChecksum: current}", [st, r if st != 200 else ids(wid)])

st, r = owner.call("GET", f"/workflow-history/workflow/{wid}/publish-timeline")
raw("GET /rest/workflow-history/workflow/{id}/publish-timeline: (versionId, event, user email)", [st, [(e["versionId"], e["event"], e["user"]["email"]) for e in r["data"]]])

st, r = owner.call("GET", "/settings")
d = r.get("data") or {}
raw("GET /rest/settings: workflowHistory and license", [st, d.get("workflowHistory"), (d.get("license") or {}).get("planName"), (d.get("enterprise") or {}).get("workflowHistory")])
raw("workflow_history rows for this workflow (versionId, createdAt)", psql(f"select \"versionId\", \"createdAt\" from workflow_history where \"workflowId\" = '{wid}' order by \"createdAt\"").splitlines())
psql(f"update workflow_history set \"createdAt\" = now() - interval '30 hours' where \"workflowId\" = '{wid}' and \"versionId\" = '{v2}'")
raw("v2 (neither draft nor published) backdated 30 hours; q99 checks after n8n's hourly prune whether it is gone", v2)
open("raw/q07_backdated.txt", "w").write(f"{wid} {v2} {time.time()}\n")
public("POST", f"/workflows/{wid}/unpublish", {})
