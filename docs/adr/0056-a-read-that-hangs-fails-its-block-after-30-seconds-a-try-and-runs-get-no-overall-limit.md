---
status: proposed
---

# A read that hangs fails its block after 30 seconds a try, and runs get no overall limit

On 24 Nov 2026 the team lead asked for a time limit on real workflows, after the ADR 0054 spike (item S5, `docs/evidence/2026-11-24-simulation-spike/README.md`). This ADR records how, and why parts of the request were left out.

## Context

**What the spike found.** No real workflow has a time limit of its own. A source that holds the connection open holds n8n's GitHub block for 300 s on each try, then fails with "The connection was aborted, perhaps the server is offline". With 3 tries that is about 15 minutes. A workflow time limit (`executionTimeout`) ended a run as `canceled` with no error, and n8n's record left out the block that was running.

**Where n8n sets a block's limit.** In n8n 2.42.6 it is fixed in code, with no setting. It is a limit on silence: the try fails once nothing arrives for that long.

- `@n8n/backend-network` 1.16.4, `dist/http/axios/config.js`: `axios.defaults.timeout = 300000`, for every request a block makes without a timeout of its own. GitHub, Jira, Slack, Teams, Outlook and Gmail set none.
- `n8n-core` 2.42.4, `dist/execution-engine/routing-node.js`: 300 s for a declarative block's request, unless its Request Options set one.
- `n8n-nodes-base` 2.42.4, HTTP Request: versions 3 to 4.5 set 300 s when their Timeout is empty (`HttpRequestV3.node.js`), and versions 1 and 2 set an hour (`HttpRequestV1.node.js`, `HttpRequestV2.node.js`).

Each request passes through the interceptor n8n puts on axios, after axios fills in its default (axios 1.18.0, `Axios._request`). Our own blocks set their own limits: 60 s for a call to our platform (120 s for Agent), and the platform reads GitHub, Jira and Confluence with 10 s a try.

**Which requests are reads.** On the allow list, n8n's GitHub and Jira blocks read, and Teams, Outlook, Gmail and Slack post a notice. Every read is a GET, except a Jira search (`issue getAll`), which the Jira block sends as a POST to `/api/2/search/jql`. Every notice is a POST. A try cut short may still have landed, and Retry On Fail would send it again: a second post, or a second email.

**How n8n's run limit treats a wait.** `EXECUTIONS_TIMEOUT`, or a workflow's `executionTimeout`, is checked in `WorkflowRunner.runMainProcess` (n8n 2.42.6, `dist/workflow-runner.js`). The timer stops when a run goes into a wait. When the run wakes, the timer starts again, shortened by the time since `data.startedAt` when that is set:

- A wake by webhook sets no `startedAt` (`dist/webhooks/webhook-helpers.js`, `executeWebhook`). Our Ask for a yes waits until the year 3000 and our API wakes it by its webhook, so the rest of the run gets a fresh limit. The limit would not cut a run waiting for an Approver.
- A wake by n8n's wait tracker passes the run's first start (`dist/wait-tracker.js`, `startExecution`). `ExecutionRepository.setRunning` keeps that first start (`@n8n/db` 1.42.4). So a timed wait that lasts longer than the limit, such as a Wait block set to an hour, a wait with a time limit, or a "send and wait" block with one, is stopped as `canceled` the moment it wakes.

A run limit therefore cuts some waits. The team lead's rule is that no wait is ever cut, and n8n loads the Wait block and the "send and wait" blocks. An Approver may say yes to a workflow that uses them (ADR 0051), and staff may build one in n8n.

## Decision

1. **A read by one of n8n's own blocks gives up after 30 seconds of silence a try.** Our n8n image adds one check to n8n's axios interceptor (`deploy/n8n/request-limit.mjs`): a GET, HEAD or OPTIONS request whose limit is n8n's 300 s waits `WAB_REQUEST_TIMEOUT_SECONDS` instead. That covers a block that sets no limit, a declarative block, and HTTP Request 3 to 4.5 with an empty Timeout. `deploy/compose.yaml`, `deploy/compose.simulation.yaml` and Terraform set it to 30 for the platform's n8n and the simulation n8n. With it unset, nothing changes.
   - **Anything else keeps its limit.** A POST, PUT, PATCH or DELETE keeps n8n's 300 s, so no post that may have landed is sent again after a short wait. This is the tradeoff: a Jira search, every notice, and HTTP Request's other methods still wait 300 s a try. A block's own Timeout, other than 300 s, still wins, HTTP Request 1 and 2 keep their hour, and our blocks keep their own limits.
   - **What the build checks.** The image build fails unless it finds the interceptor, and the 300 s in the three places above, exactly once in each copy. A block that sets a limit of its own anywhere else keeps it, and the build can't see that. So an n8n upgrade can still bring a block the limit doesn't reach.
   - Retries stay as they are, so a GET read with 3 tries takes about 94 s, not 15 minutes.
2. **Runs get no overall limit.** `EXECUTIONS_TIMEOUT` stays unset and the platform sets no `executionTimeout`, so no wait is cut. No stored workflow version changes, so every approval digest stays valid.
3. **The stop names the source, the block and the likely cause.** When n8n's words for the failed block are one of its connection errors, the run's stop says, in two short sentences, which source didn't answer, which block stopped, after how many tries, and what that likely means (`monitoring/source_stops.py`, `orchestration/block_sources.py`).
   - The source is the system the allow list names for the block's type (`node_classes.json`, the last word of its tag), the host an HTTP Request block writes out in its address, or "The source" when nothing names it. Only a plain host name or IP address counts, so an address with a name and password before an @, or a backslash, names no host.
   - The limit is the one that applied: 30 s for a read sent as a GET, n8n's 300 s for a post or a POST read, the hour of HTTP Request 1 and 2, or the block's own Timeout. When an expression sets the method or the Timeout, or the block is one the allow list doesn't class, the words say "in time" and no number.
   - The tries are the ones n8n makes for the block's settings. The cause is read from n8n's error words only, and n8n keeps only the last try's words.
   - The AI troubleshooter reads the same facts back from the stop, so its explanation and advice say the same.
   - An agent whose source gives no usable answer, every try, now names that source ("Confluence didn't answer.") where it always said GitHub. Only the agent runtime's fixed sentences for GitHub, Jira and Confluence count.

Words to confirm (needs OK), each one sentence:

- `GitHub didn't answer within 30 seconds, so "Get releases" stopped after 3 tries.`
- `Jira didn't answer within 5 minutes, so "Find tickets" stopped.`
- `old.example.com didn't answer within 1 hour, so "Old call" stopped.`
- `api.example.com didn't answer in time, so "Call out" stopped.`
- `Jira refused the connection, so "Find tickets" stopped.`
- `Teams closed the connection, so "Tell the team" stopped after 2 tries.`
- `Slack could not be reached, so "Post in Slack" stopped.`
- `Nothing came back in that time, so it may be down, busy or out of reach.`
- `It may be down, or the block may point at the wrong address.`
- `It ended the connection before a full answer came back, so it may have failed or restarted.`
- `n8n couldn't reach it, so it may be down, or its address may be wrong or blocked.`
- `Retry the run in a few minutes. If it stops here again, check that GitHub is up and that n8n can reach it.`

## Considered options

- **The same 30 s for every method.** Rejected: a post, an email or a POST read cut short may have landed, and Retry On Fail would send it again.
- **`EXECUTIONS_TIMEOUT` of 10 minutes.** Rejected: it stops a run with a timed wait as soon as it wakes, as above.
- **`executionTimeout` on new workflow versions only.** Rejected for the same reason, and a change to the settings changes the digest an approval binds to.
- **The HTTP Request block's Timeout option only.** Rejected as the main fix: GitHub, Jira, Slack, Teams, Outlook and Gmail have no such option.
- **A forward proxy with its own time limits.** Rejected for now: a new service, and n8n's requests to its own services would go through it too.
- **Leave 300 s.** Rejected: a hung source holds a run for about 15 minutes, most of the 20 minutes ADR 0055 gives a whole fix.

## Consequences

- Each n8n upgrade must carry the change. The build fails if the places it knows of change, which is the reminder. It can't find a new place that sets a limit of its own.
- A read whose source is silent for 30 s on a try now fails that try, where it had 300 s. A slow but working endpoint that sends nothing for that long needs its own Timeout, which only an HTTP Request block can set. A Timeout set to exactly 300,000 ms counts as n8n's own and is cut for a read.
- A Jira search, a notice and an HTTP Request that is not a read still wait 300 s a try, about 15 minutes with 3 tries.
- A run whose source hangs is still held for each try and its waits. A run whose block loops for a long time on its own work has no limit.
- The change reaches Azure only with the next deploy, which the team lead approves.
- Naming the source for our own Read block, whose read the platform does, needs the platform to keep its own words for the failed read. n8n's record of that block holds only "Our platform could not do this step (HTTP 503)". That is a follow-up.
