import time, httpx, asyncio, warnings
warnings.simplefilter("always")
from graph import app, URL
for i in range(3):
    t=time.perf_counter(); httpx.get(URL,timeout=20); a=time.perf_counter()-t
    t=time.perf_counter(); app.invoke({"last_known_tag":"sdk==0.4.8"}); b=time.perf_counter()-t
    print(f"run{i+1} github_call={a*1000:.0f}ms whole_graph={b*1000:.0f}ms")
