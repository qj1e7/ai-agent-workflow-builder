import json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
SCRIPT={}   # path -> {"mode","n"}
COUNT={}    # path -> calls
def now(): return time.strftime("%H:%M:%S",time.gmtime())+f".{int(time.time()*1000)%1000:03d}"
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def send(self,code,obj):
        b=json.dumps(obj).encode(); self.send_response(code); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path=="/_log": return self.send(200,[json.loads(l) for l in open("/logs/stub.jsonl")])
        self.send(404,{})
    def do_POST(self):
        n=int(self.headers.get("content-length") or 0); raw=self.rfile.read(n) if n else b""
        try: body=json.loads(raw) if raw else {}
        except Exception: body={"_raw":raw.decode()}
        p=self.path
        if p=="/_script":
            SCRIPT[body["path"]]={"mode":body["mode"],"n":body.get("n",0)}; COUNT[body["path"]]=0; return self.send(200,{"ok":1})
        if p=="/_reset":
            SCRIPT.clear(); COUNT.clear(); open("/logs/stub.jsonl","w").close(); return self.send(200,{"ok":1})
        COUNT[p]=COUNT.get(p,0)+1; c=COUNT[p]
        s=SCRIPT.get(p,{"mode":"ok"}); m=s["mode"]
        if m=="false": code,out=200,{"proceed":False}
        elif m=="503n": code,out=(503,{"error":"try again"}) if c<=s["n"] else (200,{"proceed":True})
        elif m=="409": code,out=409,{"refused":"step not allowed in this state"}
        else: code,out=200,{"proceed":True}
        rec={"t":now(),"path":p,"call":c,"status":code,"headers":dict(self.headers),"body":body}
        with open("/logs/stub.jsonl","a") as f: f.write(json.dumps(rec)+"\n")
        self.send(code,out)
ThreadingHTTPServer(("0.0.0.0",5690),H).serve_forever()
