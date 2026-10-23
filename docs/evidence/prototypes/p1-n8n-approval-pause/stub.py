import json, time, urllib.request, urllib.error, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
EVENTS=[]; WRITES=[]; APPROVALS={}; 
def now(): return time.strftime("%H:%M:%S",time.localtime())+f".{int(time.time()*1000)%1000:03d}"
def log(*a): print(now(),*a,flush=True)
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def send(self,code,obj):
        b=json.dumps(obj).encode(); self.send_response(code); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(b)
    def body(self):
        n=int(self.headers.get("content-length") or 0); raw=self.rfile.read(n) if n else b""
        try: return json.loads(raw) if raw else {}
        except Exception: return {"_raw":raw.decode()}
    def do_GET(self):
        if self.path=="/events": return self.send(200,EVENTS)
        if self.path=="/jira/writes": return self.send(200,WRITES)
        if self.path=="/approvals": return self.send(200,APPROVALS)
        self.send(404,{})
    def do_POST(self):
        b=self.body(); p=self.path
        if p=="/reset": EVENTS.clear(); WRITES.clear(); APPROVALS.clear(); return self.send(200,{"ok":1})
        if p=="/events":
            e=dict(b,ts=now()); EVENTS.append(e); log("EVENT",json.dumps(b)); return self.send(200,{"ok":1})
        if p=="/agent":
            log("AGENT",json.dumps(b)); return self.send(200,{"summary":"langgraph 0.9.9 released (fake)","repo":"langchain-ai/langgraph"})
        if p=="/jira/ticket":
            w=dict(b,ts=now()); WRITES.append(w); log("JIRA WRITE",json.dumps(b)); return self.send(200,{"ticket":"MOCK-%d"%len(WRITES)})
        if p=="/approvals/register":
            APPROVALS[b["approval_id"]]=dict(b,registered=now()); log("APPROVAL REGISTER",json.dumps(b)); return self.send(200,{"ok":1})
        if p.startswith("/approvals/") and p.endswith("/decide"):
            aid=p.split("/")[2]; a=APPROVALS.get(aid)
            if not a: return self.send(404,{"error":"unknown approval id"})
            url=b.get("resume_url_override") or a["resume_url"]
            payload=json.dumps({"decision":b["decision"],"approver":b["approver"],"request_id":a["request_id"]}).encode()
            log("RESUME ->",url)
            req=urllib.request.Request(url,data=payload,headers={"content-type":"application/json"},method="POST")
            try:
                r=urllib.request.urlopen(req,timeout=30); code,txt=r.status,r.read().decode()
            except urllib.error.HTTPError as ex: code,txt=ex.code,ex.read().decode()
            log("RESUME RESULT",code,txt[:200]); return self.send(200,{"n8n_status":code,"n8n_body":txt[:500]})
        self.send(404,{})
ThreadingHTTPServer(("127.0.0.1",5690),H).serve_forever()
