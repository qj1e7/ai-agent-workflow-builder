# n8n node pack

Our own n8n nodes: Start from the Portal, Read, Agent, Propose a change, Ask for a yes, Make the approved changes, Tell and Report a failure. `deploy/n8n/Dockerfile` builds them into our n8n image. The design is section 2.2 of `docs/design/chat-first/ENGINE-PLAN.md`.

```sh
npm ci --ignore-scripts
npm run typecheck && npm run lint && npm test
npm run manifest      # after adding or renaming a node: rewrites node-types.json
scripts/pack-smoke.sh # from the repo root: boots the image and checks which nodes n8n loads
```

`node-types.json` lists each node's n8n type name (`CUSTOM.<name>`, as n8n names nodes from a custom extension folder) and the retry settings the Planner puts on it.

## What the nodes need from the container

| Variable | Used for |
|---|---|
| `WAB_API_URL` | The only address any node calls, `{WAB_API_URL}/internal/v1/n8n/...` |
| `WAB_NODE_KEY` | Sent as `X-Wab-Node-Key` on every call, and the key of each wake's mac |
| `WAB_START_SECRET` | The key of each start's signature |

Without them a node makes no call and the trigger starts nothing.

## Signing contracts

Our API signs both messages the same way: HMAC-SHA256, hex-encoded, over the fields below joined by `\n`, in this order. `expires` is the decimal string of Unix seconds, such as `1794556800`. Every other field matches `[A-Za-z0-9_.:-]{1,128}`, so it cannot hold a line break.

**A start**, sent as `POST /webhook/{webhookId}/start` with the signature in the `X-Wab-Signature` header and the body `{"nonce", "kind", "expires"}`:

```
workflow id \n trigger's webhookId \n nonce \n kind \n expires
```

- Key: `WAB_START_SECRET`. `kind` is `run_now`, `test` or `retry`.
- The trigger checks the signature with its own workflow id and webhookId, so a start signed for one workflow cannot start another.
- It accepts `expires` from one minute in the past to six minutes ahead (five minutes, plus a minute either way for the two clocks), and each nonce once while it remembers it.
- It passes on `{"nonce", "kind", "workflow_id"}`, with no signature. Our API checks the nonce against its own records.

**A wake**, sent to the resume URL that Ask for a yes gave our API, with the body `{"execution_id", "request_id", "decision", "mac"}`:

```
execution id \n request id \n decision
```

- Key: `WAB_NODE_KEY`. `decision` is `yes`, `no` or `no_answer`.
- Ask for a yes takes the wake only when the execution is the one waiting, and the request is the one our API answered the ask with. A wake without a valid mac gets 401 and picks no exit.

## What the nodes expect back

- A 4xx with a text `detail` shows on the node in those words. n8n retries a node on any error, a refusal included, so our API must answer a repeated refusal the same way.
- Read and Agent: `{"items": [{...}]}`, each passed on as one item.
- Ask for a yes: `{"status": "waiting", "request_id": "..."}`, or `{"status": "nothing_to_change"}`.
- Make the approved changes: `{"made", "of", "results"}`. `made < of` fails the node with "2 of 3 made".
- Tell: `{"status", "line"}`, where `status` is `sent`, `sending`, `not_confirmed`, `would_have_sent` (a test run) or `nothing_to_report`. Tell sends only `where` and `what`. Our API composes the notice from what the run read, and sends it at most once.
- Report a failure: `{"status": "failed" | "left_as_is", "run_id", "detail"}`. A run that has ended is left as it is.
- The editor's lists, `GET .../options?kind=places|agents|agent_inputs|write_actions`: `{"options": [{"id", "name"}]}`.
