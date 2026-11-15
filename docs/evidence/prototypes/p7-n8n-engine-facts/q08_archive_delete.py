"""Q8 what happens to a waiting execution when its workflow is deleted, and Q17 archive versus delete (D7)."""

import time

from lib import (B, Raw, Rest, call_node, create, execution, executions, link, node, post_url, psql, public, signed_start, slim, start_node,
                 stub_get, stub_post, wake_body, wait_for)

raw = Raw("q08")
owner = Rest("owner")
stub_post("/reset", {})


def waiting(label):
    nodes = [start_node(), call_node("Read release", "read"), node("Ask for a yes", "CUSTOM.askForYes", {}, (400, 0)), call_node("Create ticket", "write", (600, 0))]
    w = create(label, nodes, link(("Start from the Portal", "Read release"), ("Read release", "Ask for a yes"), ("Ask for a yes", "Create ticket", 0)), raw=raw)
    wid = w["id"]
    public("POST", f"/workflows/{wid}/publish", {})
    time.sleep(2)
    b, h = signed_start()
    post_url(f"{B}/webhook/{w['nodes'][0]['webhookId']}/start", headers=h, raw_body=b)
    ex = wait_for(lambda: next((e for e in executions(wid) if e["status"] == "waiting"), None), 120)
    url = next(c["resume_url"] for c in stub_get()["calls"] if str(c["execution_id"]) == str(ex["id"]) and c["kind"] == "ask")
    return wid, ex["id"], url


def look(label, wid, eid):
    st, r = public("GET", f"/workflows/{wid}")
    raw(f"{label}: workflow", [st, {k: r.get(k) for k in ("active", "isArchived", "activeVersionId")} if st == 200 else r])
    raw(f"{label}: execution", slim(execution(eid, data=False)) if execution(eid, data=False) else "404")
    raw(f"{label}: execution rows in n8n's database", psql(f"select id, status, \"deletedAt\" is not null from execution_entity where id = {eid}") or "none")


wid, eid, url = waiting("q08 archive with a waiting execution")
st, r = public("POST", f"/workflows/{wid}/archive", {})
raw("A. public POST /workflows/{id}/archive", [st, r if st != 200 else "archived"])
look("A. after archive", wid, eid)
st, r = post_url(url, wake_body(eid, "req-a", "yes"))
raw("A. the real yes after archive", [st, r])
time.sleep(3)
look("A. after the yes", wid, eid)
raw("A. Create ticket called our API", [c["node_name"] for c in stub_get()["calls"] if str(c["execution_id"]) == str(eid) and c["kind"] == "write"])
st, r = public("POST", f"/workflows/{wid}/unarchive", {})
raw("A. unarchive", [st, r if st != 200 else "unarchived"])
look("A. after unarchive", wid, eid)

wid, eid, url = waiting("q08 delete with a waiting execution")
st, r = public("DELETE", f"/workflows/{wid}")
raw("B. public DELETE /workflows/{id} without archiving first", [st, {k: r.get(k) for k in ("id", "isArchived", "active")} if st == 200 else r])
look("B. after delete", wid, eid)
st, r = post_url(url, wake_body(eid, "req-b", "yes"))
raw("B. the real yes after delete", [st, r])

wid, eid, url = waiting("q08 archive then delete")
public("POST", f"/workflows/{wid}/archive", {})
st, r = public("DELETE", f"/workflows/{wid}")
raw("C. public DELETE after archive", [st, {k: r.get(k) for k in ("id", "isArchived")} if st == 200 else r])
look("C. after archive and delete", wid, eid)
st, r = post_url(url, wake_body(eid, "req-c", "yes"))
raw("C. the real yes after delete", [st, r])

wid, eid, url = waiting("q08 rest delete")
st, r = owner.call("DELETE", f"/workflows/{wid}")
raw("D. DELETE /rest/workflows/{id} (the editor's delete) without archiving", [st, r])
st, r = owner.call("POST", f"/workflows/{wid}/archive", {})
raw("D. POST /rest/workflows/{id}/archive", [st, "archived" if st == 200 else r])
st, r = owner.call("DELETE", f"/workflows/{wid}")
raw("D. DELETE /rest/workflows/{id} after archive", [st, r])
look("D. after", wid, eid)
