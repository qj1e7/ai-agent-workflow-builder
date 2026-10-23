import json, time, uuid, asyncio, datetime
import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from graph import app as graph

api = FastAPI()
class RunReq(BaseModel):
    input: dict = {}
    callback_url: str | None = None

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")

async def events(run_id, inp):
    seq = 0
    def ev(type, **kw):
        nonlocal seq; seq += 1
        return {"run_id": run_id, "seq": seq, "ts": now(), "type": type, **kw}
    yield ev("run_started", input=inp)
    try:
        final = {}
        async for mode, c in graph.astream(inp, stream_mode=["custom", "updates"]):
            if mode == "custom":
                yield ev(c["type"], step=c["step"], **({"result": c["result"]} if "result" in c else {}))
            else:
                for _, upd in c.items(): final.update(upd)
        yield ev("run_finished", result={"summary": final.get("summary"), "new_tags": [x["tag_name"] for x in final.get("new", [])]})
    except Exception as e:
        yield ev("run_failed", error={"type": type(e).__name__, "message": str(e)[:200]})

@api.post("/runs")
async def runs(r: RunReq):
    run_id = uuid.uuid4().hex[:8]; last = None
    async with httpx.AsyncClient(timeout=5) as c:
        async for e in events(run_id, r.input):
            last = e
            if r.callback_url:
                try: await c.post(r.callback_url, json=e)
                except Exception as ex: print("callback failed", ex)
    return {"run_id": run_id, "status": "finished" if last["type"] == "run_finished" else "failed", "result": last.get("result"), "error": last.get("error")}

@api.post("/runs/stream")
async def stream(r: RunReq):
    run_id = uuid.uuid4().hex[:8]
    async def gen():
        async for e in events(run_id, r.input):
            yield f"event: {e['type']}\ndata: {json.dumps(e)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
