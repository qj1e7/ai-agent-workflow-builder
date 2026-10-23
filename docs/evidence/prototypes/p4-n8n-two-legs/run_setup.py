from lib import *
import json
# error workflow
et=node("Error Trigger","n8n-nodes-base.errorTrigger",1,{},[0,0])
eh=node("Report error","n8n-nodes-base.httpRequest",4.2,{"method":"POST","url":STUB+"/error","sendBody":True,"specifyBody":"json","jsonBody":'={ "failed_execution_id": "{{ $json.execution.id }}", "last_node": "{{ $json.execution.lastNodeExecuted }}", "message": "{{ $json.execution.error.message }}" }',"options":{}},[220,0])
ew={"name":"legs-error","nodes":[et,eh],"connections":{"Error Trigger":{"main":[[{"node":"Report error","type":"main","index":0}]]}},"settings":{"executionOrder":"v1"}}
s,r=call("POST","/workflows",ew); print("create err",s,r if s!=200 else r["id"]); eid=r["id"]
print("activate err",call("POST",f"/workflows/{eid}/activate",{})[0])
ns,c=main_wf()
mw={"name":"legs-main","nodes":ns,"connections":c,"settings":{"executionOrder":"v1","errorWorkflow":eid}}
s,r=call("POST","/workflows",mw); print("create main",s,r if s!=200 else r["id"]); mid=r["id"]
s,r=call("POST",f"/workflows/{mid}/activate",{}); print("activate main",s,"" if s==200 else r)
json.dump({"err":eid,"main":mid},open("ids.json","w"))
