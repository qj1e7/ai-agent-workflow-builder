from lib import *
import time,json
call("POST","/_reset",{},base=HS)
for path,rid in (("release-check/work","run-A1"),("release-check/act","run-B1")):
    print("POST",path,hook(path,{"run_id":rid}))
time.sleep(2)
s,r=call("GET","/executions?limit=10&includeData=true")
print("EXECUTIONS status",s)
for e in r["data"]:
    rd=e.get("data",{}).get("resultData",{}).get("runData",{})
    print(e["id"],e["status"],e["mode"],"nodes run:",list(rd.keys()))
print("STUB LOG")
for l in stublog(): print(json.dumps(l))
