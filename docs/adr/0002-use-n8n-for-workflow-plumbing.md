---
status: proposed
---

# Use n8n for workflow plumbing and write our own code only where n8n falls short

After the proposal review, the sponsor's biggest concern was maintenance after handover. CODESparks support staff are not technical, and the sponsor wants them to fix routine problems without writing code. We use n8n to run the workflow plumbing: triggers, waits, retries, error alerts and calls to other systems. Our own code goes into the parts n8n does not offer: the AI workflow builder, the Room lead, the live activity view and the AI troubleshooter. In an October sandbox, n8n 2.42.6 with LangGraph and mock GitHub, Jira and Teams services passed 12 end-to-end tests, including approval-gate pausing, self-approval rejection, error-workflow alerts and retry after a fix.

## Considered options

- **A custom LangGraph engine for everything.** It gives the most control over how runs behave. CODESparks would also inherit an engine to patch, upgrade and debug, which is the maintenance load the sponsor wants to avoid.
- **n8n for everything, agents included.** n8n has its own AI agent nodes, but agents built there cannot be reused outside n8n, so they cannot go into NCS's internal agent hub.

## Consequences

- An n8n workflow is a versioned artifact, like code. The sandbox showed that workflow versioning works through the n8n API.
- n8n skips an error workflow that is not active. Every deployment checks that the error workflow is active.
- Approval tokens key off our own request ID, never n8n's execution ID, so the identity of a run does not depend on n8n.
- n8n's Community edition uses the Sustainable Use License, which allows internal business use. Confirm with the sponsor that this fits NCS before handover.
