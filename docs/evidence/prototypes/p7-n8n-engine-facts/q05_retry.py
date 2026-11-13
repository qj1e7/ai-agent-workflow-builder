"""Q5: n8n's public retry (D3) from a failed node, and Q6's fields on a retried execution. Q21: can a node see its attempt?"""

import time

from lib import (B, SETTINGS, Raw, call_node, node, create, execution, executions, finished, in_n8n, link, post_url, public, signed_start, slim,
                 start_node, stub_get, stub_post, wait_for)

raw = Raw("q05")
stub_post("/reset", {})


def calls(eid):
    return [c["node_name"] for c in stub_get()["calls"] if str(c["execution_id"]) == str(eid)]


nodes = [start_node(), call_node("Read release", "read"), call_node("Compare", "agent", (400, 0)), call_node("Create ticket", "write", (600, 0))]
conns = link(("Start from the Portal", "Read release"), ("Read release", "Compare"), ("Compare", "Create ticket"))
w = create("q05 retry", nodes, conns, raw=raw)
wid, hook = w["id"], w["nodes"][0]["webhookId"]
public("POST", f"/workflows/{wid}/publish", {})
time.sleep(2)


def start_and_fail(label):
    seen = {e["id"] for e in executions(wid)}
    b, h = signed_start()
    post_url(f"{B}/webhook/{hook}/start", headers=h, raw_body=b)
    ex = wait_for(lambda: next((e for e in executions(wid) if e["id"] not in seen), None), 90)
    finished(ex["id"])
    raw(f"{label}: failed execution", slim(execution(ex["id"])))
    raw(f"{label}: nodes that called our API", calls(ex["id"]))
    return ex["id"]


def retry(label, eid, load_workflow):
    t0 = time.time()
    st, r = public("POST", f"/executions/{eid}/retry", {"loadWorkflow": load_workflow})
    raw(f"{label}: POST /executions/{eid}/retry {{loadWorkflow: {str(load_workflow).lower()}}} answered after {time.time() - t0:.1f}s",
        [st, {k: r.get(k) for k in ("id", "mode", "retryOf", "status", "finished")} if st == 200 else r])
    if st != 200:
        return None
    finished(r["id"])
    raw(f"{label}: the retry execution", slim(execution(r["id"])))
    raw(f"{label}: nodes that called our API in the retry", calls(r["id"]))
    raw(f"{label}: our API's first read of the retry", stub_get()["first_reads"].get(str(r["id"])))
    raw(f"{label}: the original afterwards", slim(execution(eid, data=False)))
    return r["id"]


stub_post("/control", {"plan": {"Compare": [500]}})
first = start_and_fail("1. Compare answers 500 once")
retry("1. retry", first, False)

in_n8n("touch", "/tmp/p7-fail-compare")
second = start_and_fail("2. Compare throws before calling our API")
in_n8n("rm", "-f", "/tmp/p7-fail-compare")
retry("2. retry", second, False)



def republish(name):
    ns = [dict(n, name=name) if n["name"].startswith("Create ticket") else n for n in nodes]
    st, r = public("PUT", f"/workflows/{wid}", {"name": w["name"], "nodes": ns, "settings": SETTINGS,
                                                 "connections": link(("Start from the Portal", "Read release"), ("Read release", "Compare"), ("Compare", name))})
    raw(f"a new version is published after the failure, with the write block renamed '{name}'", [st, r.get("activeVersionId") if st == 200 else r])
    time.sleep(2)
    return ns


stub_post("/control", {"plan": {"Compare": [500]}})
third = start_and_fail("3. version that ran")
republish("Create ticket v2")
retry("3. retry with loadWorkflow false", third, False)
stub_post("/control", {"plan": {"Compare": [500]}})
fourth = start_and_fail("3b. fails on v2")
renamed = republish("Create ticket v3")
retry("3b. retry with loadWorkflow true", fourth, True)

done = executions(wid, status="success")
if done:
    st, r = public("POST", f"/executions/{done[0]['id']}/retry", {"loadWorkflow": False})
    raw("4. retry a succeeded execution", [st, r])

retrying = [dict(n, retryOnFail=True, maxTries=3, waitBetweenTries=2000) if n["name"] == "Compare" else n for n in renamed]
public("PUT", f"/workflows/{wid}", {"name": w["name"], "nodes": retrying, "settings": SETTINGS,
                                    "connections": link(("Start from the Portal", "Read release"), ("Read release", "Compare"), ("Compare", "Create ticket v3"))})
time.sleep(2)
stub_post("/control", {"plan": {"Compare": [500, 500]}})
seen = {e["id"] for e in executions(wid)}
b, h = signed_start()
post_url(f"{B}/webhook/{hook}/start", headers=h, raw_body=b)
ex = wait_for(lambda: next((e for e in executions(wid) if e["id"] not in seen), None), 90)
finished(ex["id"])
raw("5. retryOnFail 3 x 2 s, Compare answers 500 twice", slim(execution(ex["id"])))
mine = [c for c in stub_get()["calls"] if str(c["execution_id"]) == str(ex["id"]) and c["node_name"] == "Compare"]
raw("5. Compare's three calls: (at, every field but at) identical apart from time?", [round(c["at"] - mine[0]["at"], 1) for c in mine])
raw("5. fields a node can send per call", sorted(mine[0]))
raw("5. the three bodies are the same apart from 'at'", len({str({k: v for k, v in c.items() if k != "at"}) for c in mine}) == 1)
public("POST", f"/workflows/{wid}/unpublish", {})

nodes = [start_node(), call_node("Compare", "agent"), node("Ask for a yes", "CUSTOM.askForYes", {}, (400, 0)), call_node("Create ticket", "write", (600, 0))]
w = create("q05 retry into a wait", nodes, link(("Start from the Portal", "Compare"), ("Compare", "Ask for a yes"), ("Ask for a yes", "Create ticket", 0)), raw=raw)
wid, hook = w["id"], w["nodes"][0]["webhookId"]
public("POST", f"/workflows/{wid}/publish", {})
time.sleep(2)
stub_post("/control", {"plan": {"Compare": [500]}, "ask": "wait"})
sixth = start_and_fail("6. fails before the yes")
retry("6. retry that reaches Ask for a yes", sixth, False)
public("POST", f"/workflows/{wid}/unpublish", {})
