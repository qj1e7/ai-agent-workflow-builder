from lib import *
import time,json
call("POST","/_reset",{},base=HS)
script("/step/a1v2","false")
print("POST work",hook("release-check/work",{"run_id":"run-F1"}))
time.sleep(3)
s,r=call("GET","/executions?limit=1&includeData=true"); e=r["data"][0]
print("EXEC",e["id"],e["status"],"finished",e.get("finished"),"nodes run",list(e["data"]["resultData"]["runData"].keys()),"error",e["data"]["resultData"].get("error"))
print("STUB LOG")
for l in stublog(): print(l["t"],l["path"],l["status"])
s,r=call("GET","/executions?limit=20"); print("all executions (id,status,workflowId):",[(x["id"],x["status"],x["workflowId"]) for x in r["data"]])
