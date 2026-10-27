"""Q5, last step: with the allow list on, can staff run a blocked draft by hand in the editor?

The first attempt (q5_raw.txt lines 12 to 15) sent no start or end node, and n8n refused for that reason.
This version names both, as the editor does, and produced lines 16 to 19.
"""

from lib import Rest, secrets, show, stub, wait_for

s = secrets()
staff = Rest()
staff.login(s["staff"]["email"], s["staff"]["password"])
st, r = staff.call("GET", "/workflows")
for name, dest in (("P6 a new leak", "Send it out"), ("P6 uses staff's Jira key", "Create issue")):
    w = next(x for x in r["data"] if x["name"] == name)
    wd = staff.call("GET", f"/workflows/{w['id']}")[1]["data"]
    n = sum(1 for e in stub("GET", "/_log")[1] if e["path"] == "/error")
    body = {"workflowData": wd, "destinationNode": {"nodeName": dest, "mode": "inclusive"}, "triggerToStartFrom": {"name": "Start"}}
    show(f"Q5 after: staff run the draft '{name}' by hand", staff.call("POST", f"/workflows/{w['id']}/run", body))
    show(f"Q5 after: '{name}' reached the outside address", wait_for(lambda: sum(1 for e in stub("GET", "/_log")[1] if e["path"] == "/error") > n, 6) is not None)
