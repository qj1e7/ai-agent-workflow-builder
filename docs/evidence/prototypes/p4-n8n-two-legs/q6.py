from lib import *
import time,json
ids=json.load(open("ids.json")); mid=ids["main"]
call("POST","/_reset",{},base=HS)
s,w=call("GET",f"/workflows/{mid}"); print("before: active",w["active"],"versionId",w.get("versionId"),"activeVersionId",w.get("activeVersionId"))
ns,c=main_wf(a1="Step A1 renamed")
body={"name":"legs-main","nodes":ns,"connections":c,"settings":{"executionOrder":"v1","errorWorkflow":ids["err"]}}
s,r=call("PUT",f"/workflows/{mid}",body); print("PUT while active ->",s, r if s!=200 else {"active":r["active"],"versionId":r.get("versionId"),"activeVersionId":r.get("activeVersionId")})
s,w=call("GET",f"/workflows/{mid}"); print("after PUT: active",w["active"],"nodes",[n["name"] for n in w["nodes"] if n["name"].startswith("Step A1")], "versionId",w.get("versionId"),"activeVersionId",w.get("activeVersionId"))
for path,rid in (("release-check/work","run-U1"),("release-check/act","run-U2")):
    print("POST",path,hook(path,{"run_id":rid}))
time.sleep(3)
s,r=call("GET","/executions?limit=2&includeData=true")
for e in r["data"]: print("EXEC",e["id"],e["status"],list(e["data"]["resultData"]["runData"].keys()))
for l in stublog(): print(l["t"],l["path"],l["status"])
