---
status: proposed
---

# n8n carries runs in legs and calls only our step API, and our API owns every pause

Our [prototypes](../evidence/prototypes/README.md) showed that n8n cannot hold the approval rules. Anyone with a paused run's resume URL can resume it with any approver name, its error workflow does not receive our run ID, and anyone who can edit a workflow can delete an approval check. So every node in a run workflow calls one endpoint on our API, `POST /internal/v1/runs/{run_id}/steps/{step}`, and reads one field from the answer, `proceed`. Our API checks each call against the run's state machine, does the work, and records the events. n8n never waits for an approval. A run has a work leg up to the approval and an act leg after it, and our API starts each leg through its own webhook. Prototype P4 showed on n8n 2.42.6 that two Webhook triggers in one workflow start independent executions, and that the 202 reply can carry n8n's execution ID.

This refines ADR 0002. n8n still does the plumbing (triggers, sequencing, retries, error alerts, execution history), but it no longer holds the waits.

## Considered options

- **n8n's Wait node and its resume URL.** It is the shortest path, and P1 and P3 showed it works and survives restarts. But n8n would hold a paused run and a resume URL that works like a password. Two Approvers in order would still need our logic in front of the pause, so the approval rules would be split between our API and the workflow. A write that fails after approval would also have no clean retry that keeps the approval.
- **n8n calls agents and connectors itself.** Fewer hops, but proposals would pass through n8n where an edit can change them, every step would need an event node, and the connector would have to check approval with our API.

## Consequences

- n8n holds no run state, approval, approver name or write credential. If its database is lost, no run is lost.
- n8n's execution list shows one run as two short executions. n8n's own "retry execution" button does nothing useful, so retry lives in the Portal.
- A refused step answers 200 with `proceed: false`, not an HTTP error. P4 showed that n8n retries a 409 three times.
- Active run states carry deadlines that fail a run when n8n loses an execution. Each deadline must be longer than n8n's retry budget for that step plus our outbox's dispatch schedule, and the workflow lint checks this.
- Workflows are short and have no event nodes. A CI lint rejects any node that calls something other than our internal API.
