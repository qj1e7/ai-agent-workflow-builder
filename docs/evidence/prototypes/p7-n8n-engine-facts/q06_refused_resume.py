"""Q14: does a resume our node refuses leave the execution waiting, so the real yes still lands? Q6: a waiting execution's fields.

Run once per n8n setting: ./run.sh q06 writes raw/q06.txt. The variant name in P7_VARIANT picks the raw file:
respond (the node answers 401 itself), throw (the node throws instead), guard_off (the node does not check the mac).
"""

import os
import time

from lib import (B, Raw, call_node, create, execution, executions, link, node, post_url, public, signed_start, slim, start_node,
                 stub_get, stub_post, wake_body, wait_for)

variant = os.environ.get("P7_VARIANT", "respond")
raw = Raw("q06" if variant == "respond" else f"q06_{variant}")
raw(f"variant: {variant}")
stub_post("/reset", {})

nodes = [start_node(), call_node("Read release", "read"), node("Ask for a yes", "CUSTOM.askForYes", {}, (400, 0)),
         call_node("Create ticket", "write", (600, 0)), call_node("Tell you", "tell", (600, 200))]
conns = link(("Start from the Portal", "Read release"), ("Read release", "Ask for a yes"), ("Ask for a yes", "Create ticket", 0), ("Ask for a yes", "Tell you", 1))
w = create(f"q06 refused resume ({variant})", nodes, conns, raw=raw)
wid, hook = w["id"], w["nodes"][0]["webhookId"]
public("POST", f"/workflows/{wid}/publish", {})
time.sleep(2)

b, h = signed_start()
post_url(f"{B}/webhook/{hook}/start", headers=h, raw_body=b)
ex = wait_for(lambda: next((e for e in executions(wid) if e["status"] == "waiting"), None), 120)
eid = ex["id"]
full = execution(eid)
raw("waiting execution, public GET fields", sorted(full))
raw("waiting execution", slim(full))
ask = next(c for c in stub_get()["calls"] if str(c["execution_id"]) == str(eid) and c["kind"] == "ask")
url = ask["resume_url"]
raw("resume URL shape", url.split("?")[0].replace(str(eid), "{execution_id}") + "?signature=…")


def wake(label, body, target=None):
    st, r = post_url(target or url, body)
    time.sleep(3)
    e = execution(eid)
    writes = [(c["node_name"], c["mode"]) for c in stub_get()["calls"] if str(c["execution_id"]) == str(eid) and c["kind"] in ("write", "tell")]
    raw(f"{label}: answer", [st, r])
    raw(f"{label}: execution after", {**slim(e), "blocks after the yes that called our API (name, mode)": writes})
    return e


wake("a. resume URL with {decision: yes} and no mac", {"decision": "yes"})
wake("b. resume URL with a wrong mac", {**wake_body(eid, "req-1", "yes"), "mac": "00" * 32})
wake("c. resume URL without n8n's signature", wake_body(eid, "req-1", "yes"), target=url.split("?")[0])
e = execution(eid)
if e and e["status"] == "waiting":
    wake("d. the real yes from our API (valid mac)", wake_body(eid, "req-1", "yes"))
    wake("e. the same wake again", wake_body(eid, "req-1", "yes"))
public("POST", f"/workflows/{wid}/unpublish", {})
