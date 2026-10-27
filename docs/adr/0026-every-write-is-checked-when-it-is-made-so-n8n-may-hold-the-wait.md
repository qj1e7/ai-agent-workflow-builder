---
status: proposed
---

# Every write is checked when it is made, so n8n may hold the wait

The sponsor wants his staff to change how workflows run in n8n, to build new ones there, and to see the agents there (ADR 0027). ADR 0007 kept n8n from holding anything that matters: every node calls our step API, and our API owns every pause. Once staff can edit an n8n workflow, they can change the route a run takes, so safety can no longer depend on that route. This changes the approval gate, so `AGENTS.md` requires an ADR.

So the check moves to the moment of writing. The write gateway (ADR 0008) carries out a run's proposal only when our API's own records show all of these:

- The proposal was approved under the rules: by its named Approvers (ADR 0024), by nobody whose work it is, and by two Approvers one after the other where a tool needs two (ADR 0023).
- The proposal's digest still matches the one the Approvers saw.
- It has not been carried out already.
- The request has not expired.

n8n holds no write key. Because the yes is checked at the write, n8n may hold a paused execution again. Our "Ask for a yes" node asks our API to send the approval request, then puts its execution to wait. Our API wakes it with the result: yes, no or no answer. Anyone who wakes it another way gains nothing, because "Make the approved changes" still asks the write gateway, and the gateway reads only our records.

If this ADR is accepted, it replaces ADR 0007.

## Considered options

- **Keep ADR 0007.** It is safe, and it is built. But every n8n workflow would have to keep our two-leg shape and step names exactly, and the workflow lint would refuse almost any edit. Staff could change nothing that matters, which is the opposite of what the sponsor asked for.
- **Keep the approval check inside the n8n workflow,** for example an IF node after the wait. Staff could read it. But one edit deletes it, which is the problem our prototypes found before ADR 0007.
- **Let n8n hold the write keys and ask our API before each write.** There would be fewer hops. But the keys would sit in n8n, where anyone who can edit could use them in any other node.

## Consequences

- **n8n holds read-only keys only,** for Jira, Confluence and GitHub. Posting in Teams is a write, so it goes through the gateway too. Only n8n's owner role can add a key. Our API reads n8n's list of keys every day and alerts on any key that is not on the read-only list.
- **Our API keeps the clock.** ADR 0024's timer still asks the backup and expires the request. On expiry, our API wakes the run with "no answer". n8n's own wait never decides. If an execution is still waiting a day after its request expired, our API fails the run.
- **A lost execution doesn't lose an approved change.** If our API can't wake a waiting execution, it marks the run lost. The Operator can still carry out an approved proposal from the Portal, because the gateway doesn't need n8n.
- **Retries keep the approval.** n8n's own retry of "Make the approved changes", or a retry from the Portal, asks the gateway again. The gateway's idempotency key (ADR 0008) stops a second write.
- **Our API links each n8n execution to our run** on the first call from one of our nodes. Approval requests still key off our own request ID, never n8n's execution ID. If staff add n8n nodes between ours that drop fields, the run still holds together.
- **A run whose "Ask for a yes" was deleted or moved** reaches "Make the approved changes" with nothing approved. The gateway refuses with "No yes for this run", and the AI troubleshooter says which edit caused it.
- **The workflow lint in `orchestration/workflows.py` stops being the safety barrier.** It becomes the usefulness check that ADR 0027 describes.
- **If this ADR is accepted,** the glossary's "Leg" no longer applies, and `AGENTS.md` gains one line: n8n holds no write key, and the write gateway checks every approval itself.
