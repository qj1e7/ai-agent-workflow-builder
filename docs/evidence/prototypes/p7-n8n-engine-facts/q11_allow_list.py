"""Q11: NODES_INCLUDE with our pack's names, and test_allow_list (an HTTP Request node can neither be published nor run by hand).

P7_VARIANT names the n8n setting the stack was started with (variants.py sets it):
base (no allow list, the control), custom (pack in N8N_CUSTOM_EXTENSIONS, allow list names CUSTOM.*),
wab_names (allow list names wab.*), package (pack installed as n8n-nodes-wab, allow list names n8n-nodes-wab.*).
"""

import os

from lib import Raw, Rest, create, execution, link, node, public, wait_for

variant = os.environ.get("P7_VARIANT", "base")
raw = Raw(f"q11_{variant}")
owner = Rest("owner")
raw(f"variant: {variant}", os.environ.get("P7_NODES_INCLUDE") or "NODES_INCLUDE unset")

types = owner.node_types()
ours = [t for t in types if "startFromPortal" in t or "callOurApi" in t or "askForYes" in t or "reportFailure" in t]
raw("node types n8n loaded: count, ours", [len(types), ours])
raw("every type n8n loaded" if len(types) < 40 else "first 12 types", types if len(types) < 40 else types[:12])

http = node("Send it out", "n8n-nodes-base.httpRequest", {"url": "http://stub:8041/leak-http", "method": "GET"}, (200, 0), tv=4.2)
st, r = public("POST", "/workflows", {"name": f"q11 http request ({variant})", "nodes": [node("Run by hand", "n8n-nodes-base.manualTrigger", {}, (0, 0)), http],
                                       "connections": link(("Run by hand", "Send it out")), "settings": {"executionOrder": "v1"}})
raw("create a workflow with an HTTP Request node", [st, r.get("id") if st == 200 else r])
if st == 200:
    wid = r["id"]
    st, r2 = public("POST", f"/workflows/{wid}/publish", {})
    raw("publish it", [st, "published" if st == 200 else r2])
    st, r2 = owner.call("POST", f"/workflows/{wid}/run", {"destinationNode": {"nodeName": "Send it out", "mode": "inclusive"}})
    raw("run it by hand", [st, r2])
    eid = (r2.get("data") or {}).get("executionId") if isinstance(r2, dict) else None
    if eid:
        ex = wait_for(lambda: (e := execution(eid)) and e["status"] not in ("new", "running") and e, 60)
        raw("the hand run", [ex["status"], ((ex["data"]["resultData"].get("error") or {}).get("message"))])
    public("POST", f"/workflows/{wid}/unpublish", {})

if variant == "package":
    w = create("q11 package node runs", [node("Run by hand", "n8n-nodes-base.manualTrigger", {}, (0, 0)),
                                         node("Read release", "n8n-nodes-wab.callOurApi", {"kind": "read"}, (200, 0))], link(("Run by hand", "Read release")))
    st, r = owner.call("POST", f"/workflows/{w['id']}/run", {"destinationNode": {"nodeName": "Read release", "mode": "inclusive"}})
    eid = (r.get("data") or {}).get("executionId")
    ex = wait_for(lambda: (e := execution(eid)) and e["status"] not in ("new", "running") and e, 60)
    raw("a workflow using n8n-nodes-wab.callOurApi, run by hand", [ex["status"], list(ex["data"]["resultData"]["runData"])])
