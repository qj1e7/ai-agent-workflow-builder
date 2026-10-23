# Prototype findings: LangGraph agent events and HTTP interface

THROWAWAY prototype. Scripts live beside this file: `graph.py` (3-node graph), `samples.py` (Q1), `server.py` + `receiver.py` (Q2), `timing.py` (Q5), `fail.py` (failure path). Raw output of Q1 is in `samples.out`. Run on 2026-10-20, Python 3.14, macOS.

## Package versions (latest at install time)
langgraph 1.2.16, langchain-core 1.6.12, httpx 0.28.1, fastapi 0.151.0, uvicorn 0.54.0, starlette 1.9.0, pydantic 2.14.1. No LANGSMITH_* or LANGCHAIN_* env vars were set (checked with `env | grep`, count 0). No API keys. Summarize node uses `GenericFakeChatModel`.

## Q1. Event streams: VERIFIED
Same run, three modes. Values trimmed.

**stream_mode="updates"** (3 chunks, one per node, emitted only AFTER the node finishes):
```
{"fetch_releases": {"releases": [{"tag_name": "cli==0.4.37", "published_at": "2026-10-19T14:06:22Z", "prerelease": false, "draft": false, ...}, ...]}}
{"find_new": {"new": [{"tag_name": "cli==0.4.37", ...}, ...]}}
{"summarize": {"summary": "5 new release(s): cli==0.4.37, 1.2.16, ..."}}
```
Observed: no "step started" event. Payload is the raw state diff (whole release lists), so the live view would get big, node-shaped data.

**stream_mode="custom"** (6 chunks, exactly what my nodes wrote with `get_stream_writer()`):
```
{"type": "step_started", "step": "fetch_releases"}
{"type": "step_finished", "step": "fetch_releases", "result": {"count": 5}}
{"type": "step_started", "step": "find_new"}
{"type": "step_finished", "step": "find_new", "result": {"new_count": 5, "tags": ["cli==0.4.37", "1.2.16", ...]}}
{"type": "step_started", "step": "summarize"}
{"type": "step_finished", "step": "summarize", "result": {"summary": "5 new release(s): ..."}}
```
Clean, but only exists if every node author remembers to write the events.

**astream_events(version="v2")** (31 events for this tiny graph: 4 on_chain_start, 6 on_chain_stream, 4 on_chain_end, 1 on_chat_model_start, 15 on_chat_model_stream, 1 on_chat_model_end). First samples:
```
{"event": "on_chain_start", "name": "LangGraph", "tags": [], "metadata": {"ls_integration": "langgraph"}, "data": {"input": {"last_known_tag": "__NONE__"}}}
{"event": "on_chain_start", "name": "fetch_releases", "tags": ["graph:step:1"], "metadata": {"ls_integration": "langgraph", "langgraph_step": 1, "langgraph_node": "fetch_releases", "langgraph_triggers": ["branch:to:fetch_releases"], "langgraph_path": ["__pregel_pull", "fetch_releases"], "langgraph_checkpoint_ns": "fetch_releases:c63e464e-..."}, "data": {"input": ...}}
{"event": "on_chain_stream", "name": "fetch_releases", ... "data": {"chunk": {"releases": [...]}}}
{"event": "on_chain_end", "name": "fetch_releases", ... "data": {"output": {"releases": [...]}}}
{"event": "on_chain_stream", "name": "LangGraph", ... "data": {"chunk": {"fetch_releases": {...}}}}
{"event": "on_chat_model_start", "name": "GenericFakeChatModel", "tags": ["seq:step:1"], "metadata": {... "langgraph_node": "summarize" ...}}
{"event": "on_chat_model_stream", ...}   (x15, one per token chunk of the fake reply)
```
Observed: it does have start and end per node, but it leaks LangGraph internals (`langgraph_triggers`, `langgraph_path`, `langgraph_checkpoint_ns`, `graph:step:N`, a root "LangGraph" chain, duplicate on_chain_stream echoes) and dumps full inputs/outputs. It is noisy: 31 events for 3 steps.

**Verdict.** `custom` gives the clean step started/finished/result shape with no internals. `updates` adds a reliable "node really finished with this state" signal but no start. Best of both, which I used in `server.py`: `stream_mode=["custom","updates"]`; output was interleaved custom and updates tuples (`["custom", {...}]`, `["updates", {...}]`). `astream_events` is only worth it later for token streaming or tool-call detail.

## Q2. HTTP interfaces: VERIFIED (both work); n8n SSE: INCONCLUSIVE
`server.py` wraps the raw LangGraph chunks into one envelope (`run_id`, `seq`, `ts`, `type`, ...) and adds `run_started`, `run_finished`, `run_failed`. Agent on :9100, callback receiver on :9101.

**(a) POST /runs with callback_url**
```
$ curl -s -X POST localhost:9100/runs -H 'content-type: application/json' \
  -d '{"input":{"last_known_tag":"sdk==0.4.8"},"callback_url":"http://localhost:9101/hook"}'
{"run_id":"02318396","status":"finished","result":{"summary":"2 new release(s): cli==0.4.37, 1.2.16","new_tags":["cli==0.4.37","1.2.16"]},"error":null}
```
Receiver log (8 POSTs, in order):
```
CALLBACK {'run_id': '02318396', 'seq': 1, 'type': 'run_started', 'input': {'last_known_tag': 'sdk==0.4.8'}, ...}
CALLBACK {... 'seq': 2, 'type': 'step_started', 'step': 'fetch_releases'}
CALLBACK {... 'seq': 3, 'type': 'step_finished', 'step': 'fetch_releases', 'result': {'count': 5}}
CALLBACK {... 'seq': 4, 'type': 'step_started', 'step': 'find_new'}
CALLBACK {... 'seq': 5, 'type': 'step_finished', 'step': 'find_new', 'result': {'new_count': 2, 'tags': ['cli==0.4.37', '1.2.16']}}
CALLBACK {... 'seq': 6, 'type': 'step_started', 'step': 'summarize'}
CALLBACK {... 'seq': 7, 'type': 'step_finished', 'step': 'summarize', 'result': {'summary': '2 new release(s): cli==0.4.37, 1.2.16'}}
CALLBACK {... 'seq': 8, 'type': 'run_finished', 'result': {'summary': '...', 'new_tags': [...]}}
```

**(b) POST /runs/stream (SSE)**
```
$ curl -sN -X POST localhost:9100/runs/stream -H 'content-type: application/json' -d '{"input":{"last_known_tag":"sdk==0.4.8"}}'
event: run_started
data: {"run_id": "dedc75da", "seq": 1, "ts": "...", "type": "run_started", "input": {...}}

event: step_started
data: {"run_id": "dedc75da", "seq": 2, ..., "type": "step_started", "step": "fetch_releases"}
... (same 8 events) ...
event: run_finished
data: {"run_id": "dedc75da", "seq": 8, ..., "type": "run_finished", "result": {...}}
```

**Failure path** (graph pointed at a 404 repo; called `events()` directly, not over HTTP):
`step_started fetch_releases` then `{"type":"run_failed","error":{"type":"HTTPStatusError","message":"Client error '404 Not Found' for url ..."}}`. A failure is a normal event, so the view can show where it broke. Over `/runs` this would give `status:"failed"`; I did not curl that case.

**Which is simpler for n8n's HTTP Request node?** (a) `/runs`. It returns one normal JSON body, which is what the node expects. Caveat seen in my code: `/runs` blocks until the whole run ends, and it POSTs callbacks inline. A run that waits on an approval would hold the HTTP call open, so real design should return 202 with a run_id fast, and push events to the callback (not tested here).
**Can n8n consume SSE?** INCONCLUSIVE. I did not confirm this from official n8n docs. A web search only showed community threads saying the built-in HTTP Request node cannot read a streamed response (old thread, https://community.n8n.io/t/streaming-response-of-http-node-or-openai-node-via-respond-to-webhook-node/27772) and a community node "n8n-nodes-streaming-http-request" that adds SSE (https://ncnodes.com/package/n8n-nodes-streaming-http-request). Treat "built-in node does not handle SSE" as a GUESS until someone tests it on n8n 2.42.6.

## Q3. GitHub release fields: VERIFIED
Unauthenticated `curl -sI` rate-limit headers (HTTP/2 200):
```
x-ratelimit-limit: 60
x-ratelimit-remaining: 48
x-ratelimit-used: 12
x-ratelimit-resource: core
x-ratelimit-reset: 1792492356
etag: W/"0069f6b6..."
```
Limit is 60 per hour per IP; my testing used 12 of them. Fields per release (all 5 returned): `tag_name`, `name`, `published_at`, `prerelease`, `draft`, `html_url`. In the 5 samples, `prerelease` and `draft` were all false, so I did not see a true value (their semantics are from the field names, NOT VERIFIED beyond that).
```
cli==0.4.37   2026-10-19T14:06:22Z
1.2.16        2026-10-16T22:11:28Z
sdk==0.4.8    2026-10-16T22:09:01Z
cli==0.4.36   2026-10-16T16:39:14Z
prebuilt==1.1.1 2026-10-15T04:32:40Z
```
Important surprise: langgraph is a monorepo, so one repo releases several packages (`cli==`, `sdk==`, `prebuilt==`, plain `1.2.16`). "New release" via last_known_tag needs a tag filter (e.g. only plain version tags) or the user will get mixed packages. Also `find_new` here assumes the API returns newest first; I relied on list order, not on sorting by `published_at`.

## Q4. Tracing off: VERIFIED (run clean); env vars: from docs, NOT fetched
With the env vars unset and no key, `samples.py`, the server runs, and `timing.py` all completed with no tracing errors. Default runs printed no warnings. When I forced `warnings.simplefilter("always")` (timing.py) I saw a `DeprecationWarning` from `langsmith/_internal/_beta_decorator.py` (`asyncio.iscoroutinefunction` deprecated, Python 3.14). It is only an import-time deprecation, not a tracing error, but it shows langsmith is imported even with tracing off.
From LangSmith docs (recalled, I did not fetch the page this session, so treat as unconfirmed until checked): `LANGSMITH_TRACING=true` plus `LANGSMITH_API_KEY`, optionally `LANGSMITH_PROJECT` and `LANGSMITH_ENDPOINT`. The older `LANGCHAIN_TRACING_V2=true` is the legacy name.

## Q5. Rough timing: VERIFIED (rough, one network, n=3)
```
run1 github_call=124ms whole_graph=207ms
run2 github_call=177ms whole_graph=116ms
run3 github_call=303ms whole_graph=179ms
```
The graph is dominated by the GitHub call (the fake model and compare step take about a millisecond). Network noise is bigger than the graph overhead. Whole run is well under half a second, so SSE vs one JSON reply makes no timing difference for this use case.

## Recommended event shape for the live activity view
One flat envelope, same for callback POSTs and SSE `data:` lines. We define it, not LangGraph.
```json
{
  "run_id": "02318396",
  "seq": 5,
  "ts": "2026-10-20T10:11:27.127+00:00",
  "type": "step_finished",
  "step": "find_new",
  "result": {"new_count": 2, "tags": ["cli==0.4.37", "1.2.16"]}
}
```
Types seen: `run_started`, `step_started`, `step_finished`, `run_finished`, `run_failed` (with `error: {type, message}`). Later additions (not tested): `approval_requested`, `agent_message` for agent-to-agent chat.
Reasoning:
- Built from `custom` (clean start/finish) plus `updates` (confirms the node ended). No LangGraph names leak, so the view and the agent hub never depend on LangGraph.
- `seq` and `run_id` let the view reorder, drop duplicates, and replay after a missed callback. `ts` gives timing for animation.
- `result` is a small summary written by the node, not the full state, so events stay small. Release lists never go in the event.
- Failure is just another event, so the view can mark the broken step without parsing exceptions.

## Design implications (plain words)
- Keep the agent a plain HTTP service: `POST /runs` in, events out. It knows nothing about n8n or our API, so NCS's agent hub can reuse it.
- Use the callback style for n8n. n8n sends one normal request; events go to our Run monitoring context by callback. SSE is a nice extra for the browser or tests, not for n8n (unconfirmed, see Q2).
- Nodes must write their own start/finish events. A small wrapper that does this for every node would stop authors forgetting. Not built; this prototype wrote them by hand.
- Real runs must not hold the HTTP call open while waiting for a Teams approval. Return a run id at once and finish over events (untested here).
- Callbacks here were sent inline with a 5 second timeout and failures only printed. Real design needs retry or an outbox so the live view does not miss events. Not tested.
- Release check needs a tag filter because the repo mixes packages, and the 60-per-hour unauthenticated limit is fine for a demo but a token is wise later.
- Port cleanup: after the runs I killed both servers; `lsof -iTCP -sTCP:LISTEN -P | grep -E "910[01]"` showed nothing.
