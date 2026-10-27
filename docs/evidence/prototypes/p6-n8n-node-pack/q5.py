"""Q5: can n8n's NODES_INCLUDE allow list stop staff from sending data out or using their own keys?

python3 q5.py before   # staff publish an n8n workflow that sends data to an outside address (the stub stands in)
# restart n8n with compose.q5.yaml
python3 q5.py after    # does it still run? can a new one with an HTTP Request node be made? do our nodes still work?
"""

import sys

from lib import STUB_IN_NET, Rest, execution, hook, link, node, public, secrets, show, stub, wait_for

s = secrets()
staff = Rest()
staff.login(s["staff"]["email"], s["staff"]["password"])
phase = sys.argv[1]


def leak_workflow():
    return {"name": "P6 staff sends data out", "nodes": [
        node("Start", "n8n-nodes-base.webhook", {"httpMethod": "POST", "path": "p6-leak", "responseMode": "onReceived", "options": {}}, [0, 0], tv=2, webhookId="p6-leak"),
        node("Send it out", "n8n-nodes-base.httpRequest", {"method": "POST", "url": STUB_IN_NET + "/error", "sendBody": True, "specifyBody": "json",
             "jsonBody": '={ "leaked": "ticket list" }', "options": {}}, [220, 0], tv=4.2),
    ], "connections": link(("Start", "Send it out")), "settings": {"executionOrder": "v1"}}


def leaked_count():
    return sum(1 for e in stub("GET", "/_log")[1] if e["path"] == "/error" and e["body"].get("leaked"))


if phase == "before":
    st, r = staff.call("POST", "/workflows", leak_workflow())
    w = r["data"]
    st, r = staff.call("POST", f"/workflows/{w['id']}/activate", {"versionId": w["versionId"]})
    show("Q5 before: staff publish an n8n workflow with an HTTP Request node", [st, r.get("data", {}).get("active") if st == 200 else r])
    n = leaked_count()
    wait_for(lambda: hook("p6-leak")[0] == 200, 15)
    show("Q5 before: data reached the outside address", wait_for(lambda: leaked_count() > n, 10) is not None)
    sys.exit()

# after the restart with the allow list
n = leaked_count()
show("Q5 after: call the staff workflow's webhook", hook("p6-leak"))
wait_for(lambda: leaked_count() > n, 5)
show("Q5 after: data reached the outside address", leaked_count() > n)
st, r = staff.call("GET", "/workflows")
show("Q5 after: staff's workflows and whether they are live", [st, [(w["name"], w["active"]) for w in r.get("data", [])]])

st, r = staff.call("POST", "/workflows", {**leak_workflow(), "name": "P6 a new leak"})
show("Q5 after: staff make a new one with an HTTP Request node", [st, r if st != 200 else "saved"])
if st == 200:
    w = r["data"]
    st, r = staff.call("POST", f"/workflows/{w['id']}/activate", {"versionId": w["versionId"]})
    show("Q5 after: staff publish it", [st, r if st != 200 else r["data"].get("active")])

st, r = staff.call("POST", "/workflows", {"name": "P6 uses staff's Jira key", "nodes": [
    node("Start", "n8n-nodes-base.manualTrigger", {}, [0, 0]),
    node("Create issue", "n8n-nodes-base.jira", {"resource": "issue", "operation": "create", "project": "MOCK", "summary": "x"}, [220, 0]),
], "connections": link(("Start", "Create issue")), "settings": {"executionOrder": "v1"}})
show("Q5 after: staff make one with n8n's Jira node", [st, r if st != 200 else "saved"])

# Our own nodes still work: a fresh software check, made and published by the platform, approved through our API.
api = {"apiUrl": STUB_IN_NET}
wf = {"name": "P6 software check after allow list", "nodes": [
    node("Start", "n8n-nodes-base.webhook", {"httpMethod": "POST", "path": "p6-run-2", "responseMode": "onReceived", "options": {}}, [0, 0], tv=2, webhookId="p6-run-2"),
    node("Ticket writer", "CUSTOM.agent", {**api, "agent": "ticket_writer"}, [220, 0]),
    node("Ask for a yes", "CUSTOM.askForYes", api, [440, 0]),
    node("Make the approved changes", "CUSTOM.makeApprovedChanges", api, [660, 0]),
], "connections": link(("Start", "Ticket writer"), ("Ticket writer", "Ask for a yes"), ("Ask for a yes", "Make the approved changes", 0)),
    "settings": {"executionOrder": "v1"}}
st, r = public("POST", "/workflows", wf)
wid = r["id"]
show("Q5 after: platform publishes our nodes", public("POST", f"/workflows/{wid}/activate")[0])
before = {x["execution_id"] for x in stub("GET", "/_runs")[1]}
wait_for(lambda: hook("p6-run-2")[0] == 200, 15)
run = wait_for(lambda: next((x for x in stub("GET", "/_runs")[1] if x["execution_id"] not in before and x["request"]), None), 20)
stub("POST", "/_decide", {"execution_id": run["execution_id"], "decision": "yes", "approver": "bob"})
e = wait_for(lambda: (lambda x: x if x and x.get("status") not in ("waiting", "running", "new") else None)(execution(run["execution_id"])), 20)
show("Q5 after: our software check with a yes", {"status": e["status"], "nodes_ran": list(e["data"]["resultData"]["runData"].keys())})
