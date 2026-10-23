from lib import *
import time,json
def show(label):
    time.sleep(8)
    s,r=call("GET","/executions?limit=3&includeData=true")
    print("== after",label)
    for e in r["data"]:
        rd=e["data"]["resultData"]
        print("EXEC",e["id"],"wf",e["workflowId"],e["status"],e["mode"],"lastNode",rd.get("lastNodeExecuted"),"err",(rd.get("error") or {}).get("message"))
    for l in stublog(): print(l["t"],l["path"],l["call"],l["status"],json.dumps(l["body"]))
call("POST","/_reset",{},base=HS)
script("/step/b1","409")
print("POST act (b1=409, b1 has retry)",hook("release-check/act",{"run_id":"run-C1"}))
show("b1 409")
call("POST","/_reset",{},base=HS)
script("/step/b2","409")
print("POST act (b2=409, b2 has no retry)",hook("release-check/act",{"run_id":"run-C2"}))
show("b2 409")
