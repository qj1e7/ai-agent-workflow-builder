from lib import *
import time,json
call("POST","/_reset",{},base=HS)
script("/step/a1","503n",2)
print("POST work",hook("release-check/work",{"run_id":"run-R1"}))
time.sleep(8)
s,r=call("GET","/executions?limit=1&includeData=true"); e=r["data"][0]
print("EXEC",e["id"],e["status"], "startedAt",e["startedAt"],"stoppedAt",e["stoppedAt"])
for name,runs in e["data"]["resultData"]["runData"].items():
    for x in runs: print(" node",name,"startTime",x.get("startTime"),"ms",x.get("executionTime"),"status",x.get("executionStatus"),"err",x.get("error",{}).get("message") if x.get("error") else None)
print("STUB LOG (path,t,status)")
for l in stublog(): print(l["t"],l["path"],l["call"],l["status"])
