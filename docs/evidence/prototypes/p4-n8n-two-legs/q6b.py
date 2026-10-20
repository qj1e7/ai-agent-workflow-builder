from lib import *
import time,json
ids=json.load(open("ids.json")); mid=ids["main"]
def run(label,rid):
    print("##",label); print("POST",hook("release-check/work",{"run_id":rid})); time.sleep(3)
    s,r=call("GET","/executions?limit=1&includeData=true"); e=r["data"][0]
    print("EXEC",e["id"],e["status"],list(e["data"]["resultData"]["runData"].keys()))
run("30s+ after PUT, still active, no toggle","run-U3")
print("deactivate",call("POST",f"/workflows/{mid}/deactivate",{})[0])
print("POST while inactive",hook("release-check/work",{"run_id":"run-U4"}))
print("activate",call("POST",f"/workflows/{mid}/activate",{})[0])
run("after deactivate+activate","run-U5")
