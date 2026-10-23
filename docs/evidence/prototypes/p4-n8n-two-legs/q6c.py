from lib import *
import lib,time,json
ids=json.load(open("ids.json")); mid=ids["main"]
def t(): return time.strftime("%H:%M:%S",time.gmtime())+f".{int(time.time()*1000)%1000:03d}"
def poll(label,secs,tag):
    print("##",label,"poll every 0.5s for",secs,"s"); end=time.time()+secs; i=0
    while time.time()<end:
        i+=1; s,r=hook("release-check/work",{"run_id":f"{tag}-{i}"}); print(t(),"POST work ->",s, (r if s!=202 else r["run_id"])  if s!=404 else "404 not registered"); time.sleep(0.5)
call("POST","/_reset",{},base=HS)
# swap A1 path to /step/a1v2 via PUT while active, and poll
ns,c=main_wf(a1="Step A1 renamed")
for n in ns:
    if n["name"]=="Step A1 renamed": n["parameters"]["url"]=STUB+"/step/a1v2"
body={"name":"legs-main","nodes":ns,"connections":c,"settings":{"executionOrder":"v1","errorWorkflow":ids["err"]}}
print(t(),"PUT",call("PUT",f"/workflows/{mid}",body)[0])
poll("after PUT while active",8,"P")
print("--- stub log (which URL did step A1 hit and when)")
for l in stublog():
    if l["path"].startswith("/step/a1"): print(l["t"],l["path"],l["body"])
print(t(),"deactivate",call("POST",f"/workflows/{mid}/deactivate",{})[0]); poll("after deactivate",6,"D")
print(t(),"activate",call("POST",f"/workflows/{mid}/activate",{})[0]); poll("after activate",6,"E")
