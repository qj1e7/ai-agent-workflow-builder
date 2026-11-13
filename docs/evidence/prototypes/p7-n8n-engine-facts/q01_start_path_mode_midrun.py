"""Q1 the mode our nodes see, Q2 the trigger's path and its 401, Q15 the execution's data mid-run, Q20 settings kept."""

import time

from lib import (B, SETTINGS, Raw, Rest, calls_for, call_node, create, execution, executions, finished, link, node, post_url, psql,
                 public, signed_start, slim, start_node, stub_get, stub_post, wait_for)

raw = Raw("q01")
owner = Rest("owner")
stub_post("/reset", {})


def publish(wid):
    s, r = public("POST", f"/workflows/{wid}/publish", {})
    raw(f"POST /api/v1/workflows/{wid}/publish", [s, {k: r.get(k) for k in ("active", "versionId", "activeVersionId")} if s == 200 else r])
    st = wait_for(lambda: (x := owner.call("GET", f"/workflows/{wid}/publication-status")[1].get("data")) and x.get("status") == "published" and all(
        t.get("status") == "activated" for t in x.get("triggers") or []) and x, 60)
    raw(f"GET /rest/workflows/{wid}/publication-status", st)


def start(wid_hook, body, headers):
    before = time.time()
    s, r = post_url(f"{B}/webhook/{wid_hook}/start", headers=headers, raw_body=body)
    return s, r, before


nodes = [start_node(), call_node("Read release", "read", (200, 0)), call_node("Compare", "agent", (400, 0))]
w = create("q01 start and link", nodes, link(("Start from the Portal", "Read release"), ("Read release", "Compare")), raw=raw)
wid, hook_id = w["id"], w["nodes"][0].get("webhookId")
raw("settings as n8n stored them", w.get("settings"))
raw("Start from the Portal webhookId as stored", hook_id)
publish(wid)
raw("webhook_entity rows", psql(f"select \"webhookPath\", method, node, \"webhookId\" from webhook_entity where \"workflowId\" = '{wid}'"))

body, headers = signed_start()
s, r, _ = start(hook_id, body, headers)
raw("POST /webhook/{webhookId}/start, signed", [s, r])
s2, r2 = post_url(f"{B}/webhook/start", headers=headers, raw_body=signed_start()[0])
raw("POST /webhook/start (no webhookId)", [s2, r2])
ex = wait_for(lambda: (e := executions(wid)) and e[0], 90)
finished(ex["id"])
raw("the execution", slim(execution(ex["id"])))
raw("node calls (node, mode) as our nodes reported", calls_for(ex["id"]))
raw("our API's first read of GET /executions/{id} mid-run (saveExecutionProgress on)", stub_get()["first_reads"].get(str(ex["id"])))
raw("start item each node read itself with $('Start from the Portal')", [c["start_item"] for c in stub_get()["calls"] if str(c["execution_id"]) == str(ex["id"])])

n_before = len(executions(wid))
bad_body, _ = signed_start()
s, r = post_url(f"{B}/webhook/{hook_id}/start", headers={"x-wab-signature": "00" * 32}, raw_body=bad_body)
raw("start with a bad signature", [s, r])
old_body, old_headers = signed_start(expires_in=-1)
s, r = post_url(f"{B}/webhook/{hook_id}/start", headers=old_headers, raw_body=old_body)
raw("start with an expired body", [s, r])
time.sleep(3)
raw("executions before and after the two refused starts", [n_before, len(executions(wid))])

reads = []
for _ in range(10):
    b, h = signed_start()
    post_url(f"{B}/webhook/{hook_id}/start", headers=h, raw_body=b)
wait_for(lambda: len(executions(wid)) >= 11, 120)
for e in executions(wid)[:10]:
    fr = stub_get()["first_reads"].get(str(e["id"])) or {}
    reads.append([e["id"], fr.get("http"), fr.get("status"), bool(fr.get("start_item"))])
raw("10 more starts: [execution, first-read http, status seen, start item seen]", reads)

s, r = public("PUT", f"/workflows/{wid}?publishIfActive=true", {"name": w["name"], "nodes": nodes, "connections": w["connections"], "settings": {**SETTINGS, "saveExecutionProgress": False}})
raw("PUT saveExecutionProgress false", [s, r.get("settings") if s == 200 else r])
time.sleep(2)
reads = []
for _ in range(5):
    b, h = signed_start()
    post_url(f"{B}/webhook/{hook_id}/start", headers=h, raw_body=b)
wait_for(lambda: len(executions(wid)) >= 16, 120)
for e in executions(wid)[:5]:
    fr = stub_get()["first_reads"].get(str(e["id"])) or {}
    reads.append([e["id"], fr.get("http"), fr.get("status"), bool(fr.get("start_item")), fr.get("body")])
raw("5 starts with saveExecutionProgress off: [execution, http, status, start item seen, body]", reads)
raw("start items the nodes read themselves (fallback) in those runs", [bool(c["start_item"]) for c in stub_get()["calls"] if c["execution_id"] in [x[0] for x in reads]])
public("POST", f"/workflows/{wid}/unpublish", {})

sched = create("q01 schedule", [node("Every 20 seconds", "n8n-nodes-base.scheduleTrigger", {"rule": {"interval": [{"field": "seconds", "secondsInterval": 20}]}}, (0, 0), tv=1.2),
                                call_node("Read release", "read")], link(("Every 20 seconds", "Read release")), raw=raw)
publish(sched["id"])
first = wait_for(lambda: psql(f"select id from execution_entity where \"workflowId\" = '{sched['id']}' order by id limit 1"), 180)
public("POST", f"/workflows/{sched['id']}/unpublish", {})
finished(first, 180)
raw("scheduled execution", slim(execution(first)))
raw("node calls (node, mode) in the scheduled run", calls_for(first))
raw("start item a node reads in a scheduled run", [c["start_item"] for c in stub_get()["calls"] if str(c["execution_id"]) == str(first)])
raw("our API's first read in a scheduled run", stub_get()["first_reads"].get(str(first)))
raw("every scheduled execution while published (id, startedAt)", psql(f"select id, \"startedAt\" from execution_entity where \"workflowId\" = '{sched['id']}' order by id").splitlines())
