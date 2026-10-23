import json
STUB="http://stub:5690"
import os
KEY=open("apikey").read().strip() if os.path.exists("apikey") else ""
pos=[0]
def node(name,type,tv,params,**kw):
    pos[0]+=1
    n={"id":f"n{abs(hash(name))%10**8}","name":name,"type":type,"typeVersion":tv,"position":[220*pos[0],300],"parameters":params}
    n.update(kw); return n
def http(name,path,body_expr,method="POST"):
    return node(name,"n8n-nodes-base.httpRequest",4.2,{"method":method,"url":STUB+path,"sendBody":True,"specifyBody":"json","jsonBody":body_expr,"options":{}})
RID="{{ $('Webhook').first().json.body.request_id }}"
def ev(name,step,extra=""):
    return http(name,"/events",'={ "request_id": "%s", "step": "%s", "n8n_exec": "{{ $execution.id }}"%s }'%(RID,step,extra))
def chain(nodes):
    c={}
    for a,b in zip(nodes,nodes[1:]): c[a["name"]]={"main":[[{"node":b["name"],"type":"main","index":0}]]}
    return c
def wf(id,name,nodes,conn,settings=None):
    return {"id":id,"name":name,"nodes":nodes,"connections":conn,"settings":settings or {"executionOrder":"v1"},"active":True}

# error workflow
et=node("Error Trigger","n8n-nodes-base.errorTrigger",1,{})
e1=http("Report raw error payload","/events",'={{ JSON.stringify({step:"error_workflow_fired", raw_error_payload:$json}) }}')
e2=node("Fetch execution data","n8n-nodes-base.httpRequest",4.2,{"method":"GET","url":"=http://localhost:5678/api/v1/executions/{{ $('Error Trigger').first().json.execution.id }}?includeData=true","sendHeaders":True,"headerParameters":{"parameters":[{"name":"X-N8N-API-KEY","value":KEY}]},"options":{}})
e3=node("Extract request_id","n8n-nodes-base.code",2,{"jsCode":"const rd=$input.first().json.data.resultData.runData; const w=rd['Webhook'][0].data.main[0][0].json.body; return [{json:{request_id:w.request_id}}];"})
e4=http("Report recovered request_id","/events",'={{ JSON.stringify({step:"error_recovered_request_id", request_id:$json.request_id, failed_exec:$(\'Error Trigger\').first().json.execution.id, failed_node:$(\'Error Trigger\').first().json.execution.lastNodeExecuted, message:$(\'Error Trigger\').first().json.execution.error.message}) }}')
ns=[et,e1,e2,e3,e4]
json.dump([wf("ERRWF0000000001","error-handler",ns,chain(ns))],open("wf_error.json","w"),indent=1)

def main(id,name,fail=False,errwf=None):
    pos[0]=0
    wh=node("Webhook","n8n-nodes-base.webhook",2,{"httpMethod":"POST","path":"release-check"+("-fail" if fail else ""),"responseMode":"responseNode","options":{}},webhookId=("wh-fail-1" if fail else "wh-main-1"))
    rsp=node("Respond now","n8n-nodes-base.respondToWebhook",1.1,{"respondWith":"json","responseBody":'={ "accepted": true, "request_id": "%s" }'%RID,"options":{"responseCode":202}})
    s=ev("Event started","run_started")
    if fail:
        bad=node("Dead HTTP call","n8n-nodes-base.httpRequest",4.2,{"method":"GET","url":"http://127.0.0.1:1/dead","options":{}})
        ns=[wh,rsp,s,bad]
        return wf(id,name,ns,chain(ns),{"executionOrder":"v1","errorWorkflow":errwf})
    ag=http("Agent","/agent",'={ "request_id": "%s", "repo": "langchain-ai/langgraph" }'%RID)
    ad=ev("Event agent done","agent_done",', "summary": "{{ $json.summary }}"')
    reg=http("Register approval","/approvals/register",'={ "approval_id": "apr-%s", "request_id": "%s", "resume_url": "{{ $execution.resumeUrl }}" }'%(RID,RID))
    aw=ev("Event awaiting approval","awaiting_approval")
    wait=node("Wait for approval","n8n-nodes-base.wait",1.1,{"resume":"webhook","httpMethod":"POST","options":{}},webhookId="wait-1")
    iff=node("Approved?","n8n-nodes-base.if",2,{"conditions":{"options":{"caseSensitive":True,"typeValidation":"loose","version":2},"conditions":[{"id":"c1","leftValue":"={{ $json.body.decision }}","rightValue":"approved","operator":{"type":"string","operation":"equals"}}],"combinator":"and"},"options":{}})
    jira=http("Mock Jira create ticket","/jira/ticket",'={ "request_id": "%s", "approver": "{{ $(\'Wait for approval\').first().json.body.approver }}", "title": "New langgraph release" }'%RID)
    ok=ev("Event finished approved","run_finished_approved")
    rej=ev("Event finished rejected","run_finished_rejected",', "approver": "{{ $(\'Wait for approval\').first().json.body.approver }}"')
    ns=[wh,rsp,s,ag,ad,reg,aw,wait,iff]
    c=chain(ns)
    c["Approved?"]={"main":[[{"node":jira["name"],"type":"main","index":0}],[{"node":rej["name"],"type":"main","index":0}]]}
    c[jira["name"]]={"main":[[{"node":ok["name"],"type":"main","index":0}]]}
    return wf(id,name,ns+[jira,ok,rej],c)
json.dump([main("MAINWF000000001","release-check")],open("wf_main.json","w"),indent=1)
json.dump([main("FAILWF000000001","release-check-fail",True,"ERRWF0000000001")],open("wf_fail.json","w"),indent=1)
