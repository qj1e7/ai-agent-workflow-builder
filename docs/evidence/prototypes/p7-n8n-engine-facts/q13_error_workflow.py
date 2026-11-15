"""Q13: does the platform's error workflow fire for a failing workflow held in a member's project (M4)? And the fallbacks.

Also records the Error Trigger's item, which Report a failure reads (2.2).
"""

import json
import time

from lib import (B, SETTINGS, Raw, Rest, call_node, create, execution, executions, link, node, post_url, public, secrets, signed_start, slim,
                 start_node, stub_get, stub_post, wait_for)

raw = Raw("q13")
s = secrets()
owner = Rest("owner")
stub_post("/reset", {})


def reporter(label):
    w = create(label, [node("Error Trigger", "n8n-nodes-base.errorTrigger", {}, (0, 0)), node("Report a failure", "CUSTOM.reportFailure", {}, (200, 0))],
               link(("Error Trigger", "Report a failure")), raw=raw)
    st, r = public("POST", f"/workflows/{w['id']}/publish", {})
    raw(f"publish {label}", [st, r.get("active") if st == 200 else r])
    return w["id"]


def failing(label, error_workflow):
    w = create(label, [start_node(), call_node("Read release", "read")], link(("Start from the Portal", "Read release")), {**SETTINGS, "errorWorkflow": error_workflow}, raw=raw)
    return w["id"], w["nodes"][0]["webhookId"]


def fire(label, wid, hook):
    n_fail = len(stub_get()["failures"])
    seen = {e["id"] for e in executions(wid)}
    stub_post("/control", {"plan": {"Read release": [400]}})
    b, h = signed_start()
    post_url(f"{B}/webhook/{hook}/start", headers=h, raw_body=b)
    ex = wait_for(lambda: next((e for e in executions(wid) if e["id"] not in seen), None), 90)
    got = wait_for(lambda: len(stub_get()["failures"]) > n_fail, 45)
    raw(f"{label}: the failed execution", slim(execution(ex["id"])))
    raw(f"{label}: did the error workflow report it within 45 s?", bool(got))
    return ex["id"], (stub_get()["failures"][-1] if got else None)


ew = reporter("q13 platform error workflow (owner's project)")
wid, hook = failing("q13 fails in the owner's project", ew)
public("POST", f"/workflows/{wid}/publish", {})
time.sleep(2)
eid, report = fire("1. owner's project", wid, hook)
if report:
    item = report["error_trigger_item"]
    ex_part = item.get("execution") or {}
    raw("1. the Error Trigger's item: top keys, execution keys, workflow keys", [sorted(item), sorted(ex_part), sorted(item.get("workflow") or {})])
    raw("1. the fields Report a failure needs", {"execution.id": ex_part.get("id"), "execution.mode": ex_part.get("mode"), "execution.retryOf": ex_part.get("retryOf"),
                                                 "execution.lastNodeExecuted": ex_part.get("lastNodeExecuted"), "execution.error.message": (ex_part.get("error") or {}).get("message"),
                                                 "execution.error.node.name": ((ex_part.get("error") or {}).get("node") or {}).get("name"), "workflow": item.get("workflow")})
    raw("1. the error workflow's execution mode, as its node saw it", report["mode"])
raw("1. error workflow executions", [slim(e) for e in executions(ew)])

wid2, hook2 = failing("q13 fails in Alice's project", ew)
st, r = public("PUT", f"/workflows/{wid2}/transfer", {"destinationProjectId": s["alice"]["project"]})
raw("2. transfer to Alice's project", st)
st, r = Rest("alice").call("POST", f"/workflows/{wid2}/activate", {"versionId": public("GET", f"/workflows/{wid2}")[1]["versionId"]})
raw("2. Alice publishes it", [st, "published" if st == 200 else r])
time.sleep(2)
eid2, report2 = fire("2. Alice's project, error workflow in the owner's project", wid2, hook2)
raw("2. Alice reads the failing workflow's settings.errorWorkflow", Rest("alice").call("GET", f"/workflows/{wid2}")[1]["data"]["settings"].get("errorWorkflow"))
refused = [e for e in executions(ew) if e["status"] == "error"]
raw("2. the platform's error workflow executions that failed", [slim(execution(e["id"])) for e in refused])

ew_doc = public("GET", f"/workflows/{ew}")[1]
st, r = public("PUT", f"/workflows/{ew}", {"name": ew_doc["name"], "nodes": ew_doc["nodes"], "connections": ew_doc["connections"], "settings": {**SETTINGS, "callerPolicy": "any"}})
raw("2b. the platform's error workflow gets settings.callerPolicy = any", [st, (r.get("settings") or {}).get("callerPolicy") if st == 200 else r])
time.sleep(2)
fire("2b. Alice's project, platform error workflow with callerPolicy any", wid2, hook2)

st, r = public("GET", f"/executions?status=error&workflowId={wid2}")
raw("3. fallback A: public GET /executions?status=error&workflowId=…", [st, [(e["id"], e["status"], e["mode"]) for e in r.get("data", [])]])
d = execution(eid2)
rd = d["data"]["resultData"]
raw("3. fallback A: the failed node and its words from the execution data", {"lastNodeExecuted": rd.get("lastNodeExecuted"), "error": rd.get("error", {}).get("message"), "node": (rd.get("error", {}).get("node") or {}).get("name")})

ew_alice = reporter("q13 error workflow copy for Alice")
st, r = public("PUT", f"/workflows/{ew_alice}/transfer", {"destinationProjectId": s["alice"]["project"]})
raw("4. fallback B: a copy of the error workflow moved into Alice's project", st)
cur = Rest("alice").call("GET", f"/workflows/{wid2}")[1]["data"]
st, r = Rest("alice").call("PATCH", f"/workflows/{wid2}", {"versionId": cur["versionId"], "settings": {**cur["settings"], "errorWorkflow": ew_alice}})
v = (r.get("data") or {}).get("versionId")
st2, r2 = Rest("alice").call("POST", f"/workflows/{wid2}/activate", {"versionId": v})
raw("4. the held workflow now names the copy, published", [st, st2])
time.sleep(2)
eid4, report4 = fire("4. Alice's project, error workflow copy in Alice's project", wid2, hook2)
raw("4. the copy's executions", [slim(e) for e in executions(ew_alice)])

n_fail = len(stub_get()["failures"])
stub_post("/control", {"plan": {"Read release": [400]}})
st, r = owner.call("POST", f"/workflows/{wid}/run", {"triggerToStartFrom": {"name": "Start from the Portal", "data": {"data": {"main": [[{"json": json.loads(signed_start()[0])}]]}}}})
eid5 = (r.get("data") or {}).get("executionId")
time.sleep(15)
raw("5. a manual run that fails", slim(execution(eid5)) if eid5 else [st, r])
raw("5. did the error workflow report the manual run?", len(stub_get()["failures"]) > n_fail)
n_fail = len(stub_get()["failures"])
stub_post("/control", {"plan": {"Read release": [400]}})
st, r = public("POST", f"/executions/{eid}/retry", {"loadWorkflow": False})
got = wait_for(lambda: len(stub_get()["failures"]) > n_fail, 45)
item = stub_get()["failures"][-1]["error_trigger_item"]["execution"] if got else {}
raw("6. a retry that fails again: execution keys and retryOf in the Error Trigger's item", [st, sorted(item), item.get("retryOf"), item.get("mode")])
for x in (wid, wid2, ew, ew_alice):
    public("POST", f"/workflows/{x}/unpublish", {})
