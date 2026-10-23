import json,urllib.request,urllib.error
KEY=open("apikey").read().strip(); B="http://localhost:5680"; STUB="http://stub:5690"; HS="http://localhost:5692"
CRED="OAKL2MURToNrvxf6"
def call(m,p,b=None,base=B+"/api/v1",hdr=None):
    h={"X-N8N-API-KEY":KEY,"content-type":"application/json"}; h.update(hdr or {})
    r=urllib.request.Request(base+p,data=json.dumps(b).encode() if b is not None else None,method=m,headers=h)
    try:
        x=urllib.request.urlopen(r); t=x.read().decode(); return x.status,(json.loads(t) if t else {})
    except urllib.error.HTTPError as e: 
        t=e.read().decode()
        try: return e.code,json.loads(t)
        except Exception: return e.code,t
def hook(path,body):
    return call("POST","/"+path,body,base=B+"/webhook")
def script(path,mode,n=0): return call("POST","/_script",{"path":path,"mode":mode,"n":n},base=HS)
def stublog(): return call("GET","/_log",base=HS)[1]
def node(name,type,tv,params,pos,**kw):
    n={"id":name.replace(" ","_"),"name":name,"type":type,"typeVersion":tv,"position":pos,"parameters":params}; n.update(kw); return n
def http(name,path,pos,retry=False,cred=True,hdr=False):
    p={"method":"POST","url":STUB+path,"sendBody":True,"specifyBody":"json","jsonBody":'={ "run_id": "{{ $json.run_id || $json.body.run_id }}" }',"options":{}}
    kw={}
    if cred:
        p.update({"authentication":"genericCredentialType","genericAuthType":"httpHeaderAuth"}); kw["credentials"]={"httpHeaderAuth":{"id":CRED,"name":"X-Step-Key"}}
    if hdr:
        p.update({"sendHeaders":True,"headerParameters":{"parameters":[{"name":"X-Step-Key","value":"plain-header-value"}]}})
    if retry: kw.update({"retryOnFail":True,"maxTries":3,"waitBetweenTries":2000})
    return node(name,"n8n-nodes-base.httpRequest",4.2,p,pos,**kw)
def iff(name,pos):
    return node(name,"n8n-nodes-base.if",2,{"conditions":{"options":{"caseSensitive":True,"typeValidation":"loose","version":2},"conditions":[{"id":"c1","leftValue":"={{ $json.proceed }}","rightValue":"","operator":{"type":"boolean","operation":"true","singleValue":True}}],"combinator":"and"},"options":{}},pos)
def leg(tag,path,wid,y,names,retry_first=True,cred=True,hdr=False):
    wh=node(f"Webhook {tag}","n8n-nodes-base.webhook",2,{"httpMethod":"POST","path":path,"responseMode":"responseNode","options":{}},[0,y],webhookId=wid)
    rsp=node(f"Respond {tag}","n8n-nodes-base.respondToWebhook",1.1,{"respondWith":"json","responseBody":'={ "run_id": "%s", "n8n_execution_id": "{{$execution.id}}" }'%("{{ $('Webhook %s').first().json.body.run_id }}"%tag),"options":{"responseCode":202}},[220,y])
    s1=http(names[0],f"/step/{tag.lower()}1",[440,y],retry=retry_first,cred=cred,hdr=hdr)
    f=iff(f"Proceed? {tag}",[660,y])
    s2=http(names[1],f"/step/{tag.lower()}2",[880,y],cred=cred,hdr=hdr)
    ns=[wh,rsp,s1,f,s2]
    c={wh["name"]:{"main":[[{"node":rsp["name"],"type":"main","index":0}]]},
       rsp["name"]:{"main":[[{"node":s1["name"],"type":"main","index":0}]]},
       s1["name"]:{"main":[[{"node":f["name"],"type":"main","index":0}]]},
       f["name"]:{"main":[[{"node":s2["name"],"type":"main","index":0}],[]]}}
    return ns,c
def main_wf(a1="Step A1",cred=True,hdr=False):
    na,ca=leg("A","release-check/work","wh-legs-a",100,[a1,"Step A2"],cred=cred,hdr=hdr)
    nb,cb=leg("B","release-check/act","wh-legs-b",400,["Step B1","Step B2"],cred=cred,hdr=hdr)
    ca.update(cb); return na+nb,ca
