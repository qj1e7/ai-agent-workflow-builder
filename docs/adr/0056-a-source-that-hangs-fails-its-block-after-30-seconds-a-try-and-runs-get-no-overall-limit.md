---
status: proposed
---

# A source that hangs fails its block after 30 seconds a try, and runs get no overall limit

On 24 Nov 2026 the team lead asked for a time limit on real workflows, after the ADR 0054 spike (item S5, `docs/evidence/2026-11-24-simulation-spike/README.md`). This ADR records how, and why one part of the request was left out.

## Context

**What the spike found.** No real workflow has a time limit of its own. A source that holds the connection open holds n8n's GitHub block for 300 s on each try, then fails with "The connection was aborted, perhaps the server is offline". With 3 tries that is about 15 minutes. A workflow time limit (`executionTimeout`) ended a run as `canceled` with no error, and n8n's record left out the block that was running.

**Where n8n sets the 300 s.** In n8n 2.42.6 it is fixed in code, with no setting:

- `@n8n/backend-network` 1.16.4, `dist/http/axios/config.js`: `axios.defaults.timeout = 300000`. Every block's request without a timeout of its own gets it, GitHub, Jira, Slack, Teams, Outlook and Gmail included. It is a limit on silence: the try fails once nothing arrives for that long.
- `n8n-core` 2.42.4, `dist/execution-engine/routing-node.js`: 300 s for a declarative block's request, unless its Request Options set one.

Only an HTTP Request block has a Timeout option of its own, in its parameters. Our own blocks already set theirs: 60 s for a call to our platform (120 s for Agent), and the platform reads GitHub, Jira and Confluence with 10 s a try.

**How n8n's run limit treats a wait.** `EXECUTIONS_TIMEOUT`, or a workflow's `executionTimeout`, is checked in `WorkflowRunner.runMainProcess` (n8n 2.42.6, `dist/workflow-runner.js`). The timer stops when a run goes into a wait. When the run wakes, the timer starts again, shortened by the time since `data.startedAt` when that is set:

- A wake by webhook sets no `startedAt` (`dist/webhooks/webhook-helpers.js`, `executeWebhook`). Our Ask for a yes waits until the year 3000 and our API wakes it by its webhook, so the rest of the run gets a fresh limit. The limit would not cut a run waiting for an Approver.
- A wake by n8n's wait tracker passes the run's first start (`dist/wait-tracker.js`, `startExecution`). `ExecutionRepository.setRunning` keeps that first start (`@n8n/db` 1.42.4). So a timed wait that lasts longer than the limit, such as a Wait block set to an hour, a wait with a time limit, or a "send and wait" block with one, is stopped as `canceled` the moment it wakes.

A run limit therefore cuts some waits. The team lead's rule is that no wait is ever cut, and n8n loads the Wait block and the "send and wait" blocks. An Approver may say yes to a workflow that uses them (ADR 0051), and staff may build one in n8n.

## Decision

1. **Each try of a request by one of n8n's own blocks gives up after 30 seconds of silence.** Our n8n image changes both places above to read `WAB_REQUEST_TIMEOUT_SECONDS`, and keeps 300 s when it is unset (`deploy/n8n/request-limit.mjs`). The image build fails unless each place is found exactly once, so an n8n upgrade can't drop the limit unnoticed. `deploy/compose.yaml` and Terraform set it to 30. A block's own Timeout still wins, as do our blocks' own limits. Retries stay as they are, so 3 tries take about 94 s, not 15 minutes.
2. **Runs get no overall limit.** `EXECUTIONS_TIMEOUT` stays unset and the platform sets no `executionTimeout`, so no wait is cut. No stored workflow version changes, so every approval digest stays valid.
3. **The stop names the source, the block and the likely cause.** When n8n's words for the failed block are one of its connection errors, the run's stop says, in two short sentences, which source didn't answer, which block stopped, after how many tries, and what that likely means. The source is the system the allow list names for the block's type (`node_classes.json`, the last word of its tag), the host an HTTP Request block writes out in its address, or "The source" when nothing names it. The tries are the ones n8n makes for the block's settings. The cause is read from n8n's error words only, and n8n keeps only the last try's words. The AI troubleshooter reads the same facts back from the stop, so its explanation and advice say the same (`monitoring/source_stops.py`).

Words to confirm (needs OK), each one sentence:

- `GitHub didn't answer within 30 seconds, so "Get releases" stopped after 3 tries.`
- `Jira refused the connection, so "Find tickets" stopped.`
- `Teams closed the connection, so "Tell the team" stopped after 2 tries.`
- `Slack could not be reached, so "Post in Slack" stopped.`
- `Nothing came back in that time, so it may be down, busy or out of reach.`
- `It may be down, or the block may point at the wrong address.`
- `It ended the connection before a full answer came back, so it may have failed or restarted.`
- `n8n couldn't reach it, so it may be down, or its address may be wrong or blocked.`
- `Retry the run in a few minutes. If it stops here again, check that GitHub is up and that n8n can reach it.`

An agent whose source gives no usable answer, every try, now names that source ("Confluence didn't answer.") where it always said GitHub.

## Considered options

- **`EXECUTIONS_TIMEOUT` of 10 minutes.** Rejected: it stops a run with a timed wait as soon as it wakes, as above.
- **`executionTimeout` on new workflow versions only.** Rejected for the same reason, and a change to the settings changes the digest an approval binds to.
- **The HTTP Request block's Timeout option only.** Rejected as the main fix: GitHub, Jira, Slack, Teams, Outlook and Gmail have no such option.
- **A forward proxy with its own time limits.** Rejected for now: a new service, and n8n's requests to its own services would go through it too.
- **Leave 300 s.** Rejected: a hung source holds a run for about 15 minutes, most of the 20 minutes ADR 0055 gives a whole fix.

## Consequences

- Each n8n upgrade must carry the change. The build fails if it can't, which is the reminder.
- A source that is silent for 30 s on a try now fails that try, where it had 300 s. A slow but working endpoint that sends nothing for that long needs its own Timeout, which only an HTTP Request block can set.
- A run whose source hangs is still held for each try and its waits. A run whose block loops for a long time on its own work has no limit.
- The change reaches Azure only with the next deploy, which the team lead approves.
- Naming the source for our own Read block, whose read the platform does, needs the platform to keep its own words for the failed read. n8n's record of that block holds only "Our platform could not do this step (HTTP 503)". That is a follow-up.
