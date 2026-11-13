"""Q19: what Turn it on's wait sees. Does publication-status list Ask for a yes as a trigger, as P6 Q1 found on SQLite?"""

import time

from lib import Raw, Rest, call_node, create, link, node, public, wait_for

raw = Raw("q19")
owner = Rest("owner")
nodes = [node("Daily", "n8n-nodes-base.scheduleTrigger", {"rule": {"interval": [{"field": "days", "triggerAtHour": 3, "triggerAtMinute": 0}]}}, (0, 200), tv=1.2),
         node("Start from the Portal", "CUSTOM.startFromPortal", {}, (0, 0), webhookId="19191919-0000-4000-8000-000000000019"),
         call_node("Read release", "read"), node("Ask for a yes", "CUSTOM.askForYes", {}, (400, 0)), call_node("Create ticket", "write", (600, 0))]
w = create("q19 turn it on", nodes, link(("Daily", "Read release"), ("Start from the Portal", "Read release"), ("Read release", "Ask for a yes"), ("Ask for a yes", "Create ticket", 0)), raw=raw)
t0 = time.time()
st, r = public("POST", f"/workflows/{w['id']}/activate", {})
raw("public POST /workflows/{id}/activate", [st, r.get("activeVersionId") if st == 200 else r])
seen = []
done = wait_for(lambda: (x := owner.call("GET", f"/workflows/{w['id']}/publication-status")[1].get("data")) and (seen.append(x["status"]) or True)
                and x["status"] == "published" and all(t["status"] == "activated" for t in x["triggers"]) and x, 60, 0.2)
raw(f"publication-status once every trigger is activated, after {time.time() - t0:.1f}s", done)
raw("statuses seen while waiting", sorted(set(seen)))
names = {n["id"]: n["name"] for n in w["nodes"]}
raw("the blocks it lists as triggers", [names.get(t["nodeId"]) for t in (done or {}).get("triggers", [])])
public("POST", f"/workflows/{w['id']}/deactivate", {})
