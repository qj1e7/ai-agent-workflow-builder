"""Q1: does n8n 2.42.6 Community edition load our node pack?
Q2: can our node pause an execution, and our API wake it, with the write checked against our own records?

Runs the software check as one n8n workflow built from n8n's Webhook node and our three nodes, then:
  A. an Approver says yes through our API            -> the change is made
  B. someone wakes the run with the resume URL only   -> the write refuses
  C. an Approver says no                              -> the No exit runs, nothing is written
  D. staff delete Ask for a yes and publish           -> the write refuses
  E. the resume URL from A is used again              -> n8n's answer is recorded
"""

import json

from lib import STUB_IN_NET, Rest, execution, hook, link, node, public, secrets, show, stub, wait_for

s = secrets()
owner = Rest()
owner.login(s["owner"]["email"], s["owner"]["password"])

# Q1a: is the Agent list filled from our API? This is the request the editor makes when the dropdown opens.
st, r = owner.call("POST", "/dynamic-node-parameters/options", {
    "nodeTypeAndVersion": {"name": "CUSTOM.agent", "version": 1}, "methodName": "getAgents",
    "path": "parameters.agent", "currentNodeParameters": {"apiUrl": STUB_IN_NET, "agent": ""},
})
show("Q1 agent list from our API", [st, r])


def software_check(with_ask=True):
    api = {"apiUrl": STUB_IN_NET}
    nodes = [
        node("Start", "n8n-nodes-base.webhook", {"httpMethod": "POST", "path": "p6-run", "responseMode": "onReceived", "options": {}}, [0, 0], tv=2, webhookId="p6-run-hook"),
        node("Version checker", "CUSTOM.agent", {**api, "agent": "version_checker"}, [220, 0]),
        node("Ticket writer", "CUSTOM.agent", {**api, "agent": "ticket_writer"}, [440, 0]),
        node("Make the approved changes", "CUSTOM.makeApprovedChanges", api, [880, 0]),
        node("Declined", "n8n-nodes-base.noOp", {}, [880, 160]),
        node("No answer", "n8n-nodes-base.noOp", {}, [880, 320]),
    ]
    if with_ask:
        nodes.append(node("Ask for a yes", "CUSTOM.askForYes", api, [660, 0]))
        conns = link(("Start", "Version checker"), ("Version checker", "Ticket writer"), ("Ticket writer", "Ask for a yes"),
                     ("Ask for a yes", "Make the approved changes", 0), ("Ask for a yes", "Declined", 1), ("Ask for a yes", "No answer", 2))
    else:
        conns = link(("Start", "Version checker"), ("Version checker", "Ticket writer"), ("Ticket writer", "Make the approved changes"))
    return {"name": "P6 software check", "nodes": nodes, "connections": conns, "settings": {"executionOrder": "v1"}}


def published(wid):
    def ok():
        st, r = owner.call("GET", f"/workflows/{wid}/publication-status")
        d = r.get("data", {}) if st == 200 else {}
        return d if d.get("status") == "published" and d.get("triggers") and all(t["status"] == "activated" for t in d["triggers"]) else None
    return wait_for(ok, 20)


for old in public("GET", "/workflows?name=P6%20software%20check")[1].get("data", []):
    public("POST", f"/workflows/{old['id']}/deactivate")
    show("cleanup old copy", [old["id"], public("DELETE", f"/workflows/{old['id']}")[0]])

st, wf = public("POST", "/workflows", software_check())
show("Q1 create with our nodes", [st, wf.get("id") if st == 200 else wf])
wid = wf["id"]
st, r = public("POST", f"/workflows/{wid}/activate")
show("Q1 publish with our nodes", [st, r.get("active") if st == 200 else r])
show("Q1 publication status (n8n waits a moment before the webhook answers)", published(wid))
json.dump({"workflow": wid}, open("ids.json", "w"))


def start_run():
    before = {r["execution_id"] for r in stub("GET", "/_runs")[1]}
    st, _ = hook("p6-run", {"case": "start"})
    run = wait_for(lambda: next((r for r in stub("GET", "/_runs")[1] if r["execution_id"] not in before and r["request"]), None), 20)
    return st, run


def finished(eid):
    return wait_for(lambda: (lambda e: e if e and e.get("finished") is not None and e.get("status") not in ("waiting", "running", "new") else None)(execution(eid)), 20)


def outcome(e):
    rd = (e.get("data") or {}).get("resultData", {})
    ran = list(rd.get("runData", {}).keys())
    err = (rd.get("error") or {}).get("message")
    return {"status": e.get("status"), "nodes_ran": ran, "error": err}


# A. yes through our API
st, run = start_run()
e = execution(run["execution_id"])
show("Q2 A started, execution status while asked", [st, e.get("status"), "waitTill", e.get("waitTill")])
resume_a = run["request"]["resume_url"]
show("Q2 A resume URL shape", resume_a.split("?")[0] + ("?signature=<redacted>" if "?" in resume_a else ""))
show("Q2 A decide yes", stub("POST", "/_decide", {"execution_id": run["execution_id"], "decision": "yes", "approver": "bob"})[1])
show("Q2 A result", outcome(finished(run["execution_id"])))

# B. woken with the resume URL only
st, run = start_run()
show("Q2 B forge yes", stub("POST", "/_forge", {"execution_id": run["execution_id"], "decision": "yes"})[1])
show("Q2 B result", outcome(finished(run["execution_id"])))

# C. no through our API
st, run = start_run()
show("Q2 C decide no", stub("POST", "/_decide", {"execution_id": run["execution_id"], "decision": "no", "approver": "bob"})[1])
show("Q2 C result", outcome(finished(run["execution_id"])))

# E. resume URL from A used again
import urllib.request
req = urllib.request.Request(resume_a, data=b'{"decision":"yes"}', method="POST", headers={"content-type": "application/json"})
req.full_url = resume_a.replace("http://n8n:5678", "http://localhost:5683")
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        show("Q2 E reuse old resume URL", [r.status, r.read().decode()[:200]])
except urllib.error.HTTPError as err:
    show("Q2 E reuse old resume URL", [err.code, err.read().decode()[:200]])

# D. staff delete Ask for a yes, and the change is published
st, r = public("PUT", f"/workflows/{wid}", software_check(with_ask=False))
show("Q2 D publish without Ask for a yes", [st, r.get("active") if st == 200 else r])
show("Q2 D publication status", published(wid))
before = {r["execution_id"] for r in stub("GET", "/_runs")[1]}
hook("p6-run", {"case": "no-ask"})
run = wait_for(lambda: next((r for r in stub("GET", "/_runs")[1] if r["execution_id"] not in before and r["proposal"]), None), 20)
show("Q2 D result", outcome(finished(run["execution_id"])))

show("stub records", [{k: v for k, v in r.items() if k != "request"} | {"request": (r["request"] or {}).get("status")} for r in stub("GET", "/_runs")[1]])
