import json,urllib.request,sys
KEY=open("apikey").read().strip(); B="http://localhost:5688/api/v1"
def call(m,p,b=None):
    r=urllib.request.Request(B+p,data=json.dumps(b).encode() if b is not None else None,method=m,headers={"X-N8N-API-KEY":KEY,"content-type":"application/json"})
    try:
        x=urllib.request.urlopen(r); return x.status,json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code,e.read().decode()[:600]
def load(f,errid=None):
    w=json.load(open(f))[0]
    body={k:w[k] for k in("name","nodes","connections","settings")}
    if errid: body["settings"]["errorWorkflow"]=errid
    s,r=call("POST","/workflows",body); print(f,"create",s, r if s!=200 else r["id"]); 
    if s!=200: sys.exit(1)
    return r["id"]
eid=load("wf_error.json"); mid=load("wf_main.json"); fid=load("wf_fail.json",eid)
json.dump({"err":eid,"main":mid,"fail":fid},open("ids.json","w"))
for n,i in(("err",eid),("main",mid),("fail",fid)):
    print(n,"activate",call("POST",f"/workflows/{i}/activate",{}))
