from fastapi import FastAPI, Request
a = FastAPI()
@a.post("/hook")
async def h(req: Request):
    print("CALLBACK", await req.json(), flush=True); return {"ok": True}
