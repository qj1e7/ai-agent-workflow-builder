import asyncio, json, time
from graph import app
inp = {"last_known_tag": "__NONE__"}
def t(o, n=300):
    s = json.dumps(o, default=str); return s if len(s) < n else s[:n] + "...<trimmed>"
async def main():
    print("=== updates"); 
    async for c in app.astream(inp, stream_mode="updates"): print(t(c))
    print("=== custom")
    async for c in app.astream(inp, stream_mode="custom"): print(t(c))
    print("=== astream_events v2")
    i = 0; kinds = {}
    async for e in app.astream_events(inp, version="v2"):
        kinds[e["event"]] = kinds.get(e["event"], 0) + 1
        i += 1
        if i <= 12: print(t({k: e[k] for k in ("event", "name", "tags", "metadata") if k in e} | {"data": str(e.get("data"))[:120]}, 450))
    print("total events", i, kinds)
    print("=== combined updates+custom")
    async for c in app.astream(inp, stream_mode=["updates","custom"]): print(t(c, 200))
asyncio.run(main())
