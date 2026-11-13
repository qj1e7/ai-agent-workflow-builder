"""Q16: does n8n's pruning skip a waiting execution? Needs the prune variant (variants.py): EXECUTIONS_DATA_PRUNE=true,
EXECUTIONS_DATA_PRUNE_MAX_COUNT=2, EXECUTIONS_DATA_PRUNE_SOFT_DELETE_INTERVAL=1 (minute).
"""

import time

from lib import (B, Raw, call_node, create, execution, executions, link, node, post_url, psql, public, signed_start, slim, start_node, stub_get,
                 stub_post, wake_body, wait_for)

raw = Raw("q16")
stub_post("/reset", {})
stub_post("/control", {"ask": "wait"})
nodes = [start_node(), call_node("Read release", "read"), node("Ask for a yes", "CUSTOM.askForYes", {}, (400, 0)), call_node("Create ticket", "write", (600, 0))]
w = create("q16 prune", nodes, link(("Start from the Portal", "Read release"), ("Read release", "Ask for a yes"), ("Ask for a yes", "Create ticket", 0)), raw=raw)
wid, hook = w["id"], w["nodes"][0]["webhookId"]
public("POST", f"/workflows/{wid}/publish", {})
time.sleep(2)

b, h = signed_start()
post_url(f"{B}/webhook/{hook}/start", headers=h, raw_body=b)
waiting = wait_for(lambda: next((e for e in executions(wid) if e["status"] == "waiting"), None), 120)
raw("the oldest execution waits for a yes", slim(waiting))
stub_post("/control", {"ask": "nothing_to_change"})
for _ in range(4):
    b, h = signed_start()
    post_url(f"{B}/webhook/{hook}/start", headers=h, raw_body=b)
    time.sleep(1)
wait_for(lambda: len([e for e in executions(wid) if e["status"] == "success"]) >= 4, 120)
raw("then four that finished", [(e["id"], e["status"]) for e in executions(wid)])
t0 = time.time()
gone = wait_for(lambda: psql(f"select count(*) from execution_entity where \"workflowId\" = '{wid}' and \"deletedAt\" is not null") not in ("", "0"), 200, 5)
raw(f"soft-deleted rows appeared after {time.time() - t0:.0f}s", bool(gone))
raw("rows now (id, status, soft-deleted?)", psql(f"select id, status, \"deletedAt\" is not null from execution_entity where \"workflowId\" = '{wid}' order by id").splitlines())
url = next(c["resume_url"] for c in stub_get()["calls"] if str(c["execution_id"]) == str(waiting["id"]) and c["kind"] == "ask")
st, r = post_url(url, wake_body(waiting["id"], "req-p", "yes"))
time.sleep(3)
raw("the real yes on the waiting execution after pruning", [st, slim(execution(waiting["id"]) or {})])
public("POST", f"/workflows/{wid}/unpublish", {})
