"""Q3: a test run of a draft through POST /rest/workflows/{id}/run with triggerToStartFrom (D4).

Body A is the plan's body. Body B passes the start item as n8n's task data. Body C names the trigger only.
"""

import json
import time

from lib import (SETTINGS, Raw, Rest, call_node, create, execution, executions, finished, link, node, public, signed_start, slim,
                 start_node, stub_get, stub_post)

raw = Raw("q03")
owner = Rest("owner")
stub_post("/reset", {})
stub_post("/control", {"ask": "test"})

nodes = [start_node(), call_node("Read release", "read"), node("Ask for a yes", "CUSTOM.askForYes", {}, (400, 0)), call_node("Create ticket", "write", (600, 0))]
conns = link(("Start from the Portal", "Read release"), ("Read release", "Ask for a yes"), ("Ask for a yes", "Create ticket", 0))
w = create("q03 test run of a draft", nodes, conns, raw=raw)
wid = w["id"]
item = json.loads(signed_start(kind="test")[0])
item["signature"] = "sig-of-the-body"
task_data = {"startTime": 0, "executionTime": 0, "source": [], "data": {"main": [[{"json": item}]]}}
draft = owner.call("GET", f"/workflows/{wid}")[1]["data"]


def run(label, body, who=owner):
    seen = {e["id"] for e in executions(wid)}
    t0 = time.time()
    st, r = who.call("POST", f"/workflows/{wid}/run", body)
    raw(f"{label}: answer in {time.time() - t0:.1f}s", [st, r])
    eid = (r.get("data") or {}).get("executionId") if isinstance(r, dict) else None
    if not eid:
        return None
    finished(eid, 60)
    ex = execution(eid)
    raw(f"{label}: execution", slim(ex))
    raw(f"{label}: node calls (node, mode)", [(c["node_name"], c["mode"]) for c in stub_get()["calls"] if str(c["execution_id"]) == str(eid)])
    raw(f"{label}: start item each node read itself", [c["start_item"] for c in stub_get()["calls"] if str(c["execution_id"]) == str(eid)][:1])
    raw(f"{label}: our API's first read of the execution", stub_get()["first_reads"].get(str(eid)))
    raw(f"{label}: new executions in the list", [e["id"] for e in executions(wid) if e["id"] not in seen])
    return eid


run("Body A (plan): {workflowData, triggerToStartFrom: {name, data: item}}", {"workflowData": draft, "triggerToStartFrom": {"name": "Start from the Portal", "data": item}})
run("Body B: {triggerToStartFrom: {name, data: taskData(item)}}", {"triggerToStartFrom": {"name": "Start from the Portal", "data": task_data}})
run("Body C: {triggerToStartFrom: {name}} only", {"triggerToStartFrom": {"name": "Start from the Portal"}})

s, r = public("POST", f"/workflows/{wid}/publish", {})
raw("publish, so a draft and a published version differ next", [s, r.get("activeVersionId") if s == 200 else r])
renamed = [dict(n, name="Read release (draft)") if n["name"] == "Read release" else n for n in nodes]
s, r = public("PUT", f"/workflows/{wid}?publishIfActive=false", {"name": w["name"], "nodes": renamed, "settings": SETTINGS,
                                                                  "connections": link(("Start from the Portal", "Read release (draft)"), ("Read release (draft)", "Ask for a yes"), ("Ask for a yes", "Create ticket", 0))})
raw("PUT a draft change with publishIfActive=false", [s, {k: r.get(k) for k in ("versionId", "activeVersionId")} if s == 200 else r])
run("Body B on a published workflow with a newer draft", {"triggerToStartFrom": {"name": "Start from the Portal", "data": task_data}})
public("POST", f"/workflows/{wid}/unpublish", {})
stub_post("/control", {"ask": "wait"})
