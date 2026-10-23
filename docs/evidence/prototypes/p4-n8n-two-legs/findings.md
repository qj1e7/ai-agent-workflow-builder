# n8n 2.42.6 two-leg design: seven behaviors (THROWAWAY prototype)

Path: docs/evidence/prototypes/p4-n8n-two-legs/findings.md
All evidence is in the same folder. Stack: n8nio/n8n:2.42.6, postgres:17, python stub, compose project `protolegs`, n8n on 5680, stub on 5692. Each test ran once against mock services. Reuse of `../p3-n8n-docker-compose` compose with port, name and a log-mount change. Code: lib.py (workflow builders), run_setup.py, q123.py, q4.py, q5.py, q6.py, q6b.py, q6c.py, q7.py, stub.py.

Workflow shape: Webhook A (`release-check/work`) -> Respond A (202) -> Step A1 (HTTP, retry 3x/2000ms) -> IF `$json.proceed` -> Step A2. Webhook B (`release-check/act`) has the same chain with B nodes. Error workflow = Error Trigger -> HTTP POST /error.

## Q1 Two Webhook triggers in one workflow: OBSERVED
Both paths registered and answered 202 on the first POST. Each POST made its own execution (ids 1 and 2). B's execution ran only B nodes, A's only A nodes.
- q1_raw.txt lines 1-2: `202 {'run_id': 'run-A1', 'n8n_execution_id': '1'}` and `202 {... 'run-B1' ... '2'}`.
- q1_raw.txt lines 4-5: `2 success webhook nodes run: ['Webhook B','Respond B','Step B1','Proceed? B','Step B2']` and `1 success webhook nodes run: ['Webhook A', ... 'Step A2']`.
- executions_all.json holds the raw `/api/v1/executions` list.

## Q2 `{{$execution.id}}` in Respond to Webhook: OBSERVED
Caller gets 202 with `n8n_execution_id` equal to the real id, and `run_id` read from the request body.
- q1_raw.txt lines 1-2 (ids '1', '2') match the ids in the `/api/v1/executions` listing at lines 4-5 (2 = leg B, 1 = leg A).
- Same match in q4_raw.txt line 1 (id '3', EXEC 3), q5_raw.txt (ids 4 and 6 match EXEC 4 and EXEC 6) and q6_raw.txt (8 and 9).
- Caveat: the id is a string, e.g. `"1"`.

## Q3 Header Auth credential through the public API: OBSERVED
`POST /api/v1/credentials` returned 200 with an `httpHeaderAuth` credential (q3_cred_raw.txt, id OAKL2MURToNrvxf6). The API key needed scope `credential:create`; I created the key with credential create/list/read scopes. The response never echoes the secret. The HTTP Request node used it (authentication genericCredentialType, genericAuthType httpHeaderAuth, `credentials.httpHeaderAuth.id`). The stub received `"X-Step-Key": "<redacted-step-key>"` on every step call (q1_raw.txt stub log lines, all four entries). No failure, so the plain-header fallback was NOT tried.

## Q4 Retry on 503 with a delay: OBSERVED
Stub returned 503 `{"error":"try again"}` twice, then 200. n8n retried with no extra node options beyond retryOnFail/maxTries/waitBetweenTries. A JSON 503 body counts as failure by default.
- q4_raw.txt stub log: 11:37:23.002 -> 503, 11:37:25.036 -> 503, 11:37:27.058 -> 200, then `/step/a2` at 11:37:27.068. Gaps 2.034 s and 2.022 s.
- Execution 3 ended `success`; Step A1 took 4064 ms in total.
- Note: the retry also fired on 409 (see Q5), so retryOnFail does not discriminate status codes; it retries every error.

## Q5 A 409 answer: OBSERVED
The HTTP node failed, the execution ended `error`, and the active error workflow fired and posted to the stub. The `Webhook` caller still got 202 because Respond ran first.
- q5_raw.txt, run C1 (409 on Step B1, which has retry): stub saw 3 calls at 11:37:40.069, :42.080, :44.089 (all 409). Execution 4 `error`, lastNode `Step B1`. Error workflow execution 5 `success`. Stub received `/error` at :44.116 with `{"failed_execution_id": "4", "last_node": "Step B1", ...}`.
- run C2 (409 on Step B2, no retry): one call, execution 6 `error`, error workflow execution 7, `/error` body `{"failed_execution_id": "6", "last_node": "Step B2"}`.
- Error message is generic: `Your request is invalid or could not be processed by the service`. The stub's `{"refused": ...}` body is not in that message. To get the reason, the error workflow must read the failed execution through the API (not tried here; the earlier docker prototype did that).
- `settings.errorWorkflow` set to the error workflow id at create time, after the error workflow was activated.

## Q6 Update an active workflow: OBSERVED
`PUT /api/v1/workflows/{id}` succeeded (HTTP 200) while the workflow was active. No deactivate/activate was needed. The update takes effect within about 0.6 s, and the webhooks never returned 404 during it.
- q6_raw.txt: PUT 200, `active True`, new `versionId` and `activeVersionId` both changed to the same new value. The renamed node `Step A1 renamed` is stored.
- q6c_raw.txt: PUT at 11:38:34.383. A POST at :34.489 still ran the old definition (`/step/a1`). The next POST at :35.037 ran the new one (`/step/a1v2`). 15 POSTs over 8 s: all 202, no 404.
- q6_raw.txt: an execution started right after the PUT (exec 8) ran the old node name; the execution 30 s later (exec 10, q6b_raw.txt) ran the new one. So there is a sub-second lag where in-flight and early requests use the old version.
- Side facts: deactivate/activate are asynchronous too (q6c_raw.txt). After `deactivate` (11:38:42.593) a POST at :43.004 still answered 202, then 404 from :43.514 on. After `activate` (11:38:48.700) a POST at :48.756 got 404 `The requested webhook "POST release-check/work" is not registered.` and the next at :49.303 got 202. So a caller that retries once after 1 s survives an activate; a deactivate/activate cycle opens a gap of roughly 0.6 s of 404.
- Not tested: a PUT that changes the webhook path or method of an active workflow; a PUT while an execution is mid-flight.

## Q7 IF on `proceed`: OBSERVED
With `{"proceed": false}` the execution ended `success`, `finished: true`, no error, and Step A2 was not called.
- q7_raw.txt: `EXEC 38 success finished True nodes run ['Webhook A','Respond A','Step A1 renamed','Proceed? A']`; stub log shows one call to `/step/a1v2` only, nothing to `/step/a2`.
- The IF false output was left unconnected. The IF used `$json.proceed` boolean true with typeValidation loose.

## Workarounds and harness notes
- None for the seven questions. The credential API worked first time with the right scopes.
- Needed an API key with extra scopes: credential:create, credential:list, credential:read (plus workflow and execution scopes).
- Step 2 nodes received an empty `run_id` (`{"run_id": ""}` in the q1 stub log) because my node read `$json.run_id`, but `$json` after an HTTP node is the platform API's reply. Real nodes must read `$('Webhook A').first().json.body.run_id` or the platform must echo it. Harness bug, not an n8n issue.
- Retry applies to Step A1 and Step B1 only because my builder set retry on both legs' first node.
- `docker compose` mounts `./logs:/logs`; the stub writes `logs/stub.jsonl` (copy in q_stub_last.jsonl, last test only).

## Implications for the two-leg design
- One workflow with two webhook triggers works: two legs, two separate executions, no cross-talk. n8n gives each POST its own execution id.
- The Respond to Webhook node can hand the caller the real n8n execution id in a 202 immediately, before any step runs. Our API can store it next to its own run id.
- Header Auth credentials can be created and referenced through the public API, so CI can provision the step key without the UI.
- 503 is a real retry signal: n8n retries with the configured delay (about 2.0 s apart). But the same retry also fires on 409. If a refused step must not be retried, either leave retryOnFail off for that node, or the API must turn refusals into a 200 `{"proceed": false}`. The 409-as-failure design is therefore fine only on nodes without retry, or accept 3 identical refusals. This is the main trap.
- A 409 fails the execution and the error workflow fires with the execution id and last node name, but not the refusal reason. The error handler needs the API itself to know why (it already does, since it sent the 409) so it can look it up by `failed_execution_id`.
- `proceed: false` ends the run cleanly as `success`. n8n's status cannot distinguish "finished all steps" from "stopped early"; our API must own that distinction.
- Deploying a new version: a live PUT is safe, with no gap, and takes effect in under a second. Do not deactivate then activate, because it opens a short 404 window. Requests in the first moments after a PUT can still run the old version, so version mismatches between API and workflow are possible for about a second.

## Teardown
`docker compose -p protolegs down -v` removed containers, network and volumes. `docker ps -a | grep protolegs` and `docker volume ls | grep protolegs` printed nothing (teardown_counts.txt: 0 and 0). No protolegs container or volume remains. The git repo was not touched.
