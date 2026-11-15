---
status: accepted
---

# Every write is checked when it is made, so n8n may hold the wait

> Amended by ADR 0045 (14 Nov 2026): n8n's own nodes may read and post notices with credentials the platform owns; a write by one of n8n's own nodes may happen only through the platform's write proxy, which checks our records at the moment of writing, and no such node is on the list yet.

The sponsor wants his staff to change how workflows run in n8n, to build new ones there, and to see the agents there (ADR 0027). ADR 0007 kept n8n from holding anything that matters: every node calls our step API, and our API owns every pause. Once staff can edit an n8n workflow, they can change the route a run takes, so safety can no longer depend on that route. This changes the approval gate, so `AGENTS.md` requires an ADR.

So the check moves to the moment of writing. The write gateway (ADR 0008) carries out a run's proposal only when our API's own records show all of these:

- The proposal was approved under the rules: by its named Approvers (ADR 0024), by nobody whose work it is, and by two Approvers one after the other where a tool needs two (ADR 0023).
- The proposal's digest still matches the one the Approvers saw.
- It has not been carried out already.
- The request has not expired.

**Whose work a run is.** Our nodes pass on how n8n started the execution: by a trigger, by hand in n8n's editor, or as a retry. n8n sets this, and staff can't change it. A run counts as the work of whoever published the version it used (ADR 0027). Two kinds of run also count as someone else's work:
- A run started by hand in n8n counts as the work of whoever holds the n8n workflow in n8n. On the free edition only they can start it there, and it may run a draft that nobody published.
- A run started from the Portal, such as Run now or a test run, counts as the work of the person who started it.

None of these people may approve that run.

n8n holds no write key. Because the yes is checked at the write, n8n may hold a paused execution again. Our "Ask for a yes" node asks our API to send the approval request, then puts its execution to wait. Our API wakes it with the result: yes, no or no answer. Anyone who wakes it another way gains nothing, because "Make the approved changes" still asks the write gateway, and the gateway reads only our records. When the proposal is empty, "Ask for a yes" asks nobody and leaves at once by a fourth exit, "Nothing to change".

**One run of a workflow waits at a time.** ADR 0024 already ends a request before the workflow's next scheduled run, so scheduled runs never overlap. Under ADR 0027 the schedule lives in n8n, so our API reads the next run from the published version's Schedule Trigger. This rule is the backstop for every other run that can start while a request still waits:
- Run now;
- a test run;
- a run started by hand in n8n;
- the first run after someone moves the schedule earlier.

On such a run's first call to our API, from any of our nodes, our API stops it before it reads anything, with "An earlier run is still waiting for a yes". The Portal shows the skipped run. Otherwise Approvers could get two requests about the same changes. The check sits in our API, not in one node, because staff can reorder nodes.

[Prototype P6](../evidence/prototypes/p6-n8n-node-pack/findings.md) showed the wait and the check at the write on n8n 2.42.6 Community edition. Our own node paused a run with no time limit, and our API woke it. The write refused in both of these cases:
- the run was woken with only the resume URL;
- "Ask for a yes" was deleted and the change published.

A resume URL used a second time got a 409.

The [n8n workflow patterns review](../evidence/usability/2026-10-28-design-skill-audits.md#n8n-design-proposals-now-drafted-into-adrs-0026-and-0027) on 28 Oct added these parts of the decision:
- whose work a run is;
- one waiting run per workflow;
- "Nothing to change";
- a key for each write action;
- repeated calls.

Prototype P7 will test the execution mode our nodes pass on.

If this ADR is accepted, it replaces ADR 0007.

## Considered options

- **Keep ADR 0007.** It is safe, and it is built. But every n8n workflow would have to keep our two-leg shape and step names exactly, and the workflow lint would refuse almost any edit. Staff could change nothing that matters, which is the opposite of what the sponsor asked for.
- **Keep the approval check inside the n8n workflow,** for example an IF node after the wait. Staff could read it. But one edit deletes it, which is the problem our prototypes found before ADR 0007.
- **Let n8n hold the write keys and ask our API before each write.** There would be fewer hops. But the keys would sit in n8n, where anyone who can edit could use them in any other node.
- **Refuse writes from runs started by hand in n8n.** Approval would be simpler. But staff fixing a workflow in n8n need a real run to check their fix, and the Open in n8n dialog promises one.
- **Let a newer run replace an earlier run's waiting request.** No run would be skipped. But a yes already given to the first of two Approvers would be thrown away.

## Consequences

- **n8n holds no keys for other systems, and it loads only an allowed list of node types** (ADR 0027): our node pack, triggers and simple flow nodes. Reading and writing both go through our node pack. Posting in Teams is a write, so it goes through the gateway too.
  - P6 showed that ordinary staff can add their own keys on the free edition, including a Jira key.
  - With the allow list, no node could use those keys. An n8n workflow with an HTTP Request or Jira node could not be published or run by hand.
- **Our API keeps the clock.** ADR 0024's timer still asks the backup and expires the request. On expiry, our API wakes the run with "no answer". n8n's own wait never decides. If an execution is still waiting a day after its request expired, our API fails the run.
- **A lost execution doesn't lose an approved change.** If our API can't wake a waiting execution, it marks the run lost. The Operator can still carry out an approved proposal from the Portal, because the gateway doesn't need n8n.
- **Retries keep the approval.** n8n's own retry of "Make the approved changes", or a retry from the Portal, asks the gateway again. The gateway's idempotency key (ADR 0008) stops a second write.
- **A repeated call gets the first answer.** Our API answers a second call for the same run and node with its first result. So n8n's Retry On Fail, or a failed execution retried in n8n, doesn't run an agent twice or add an action twice. An execution that n8n retries joins the run it retries. Reads that hit a rate limit wait a short, capped time for the reset, then fail with a plain message.
- **Each write action names what it is about,** such as the GitHub release a ticket is for. The tool that proposes it sets this key (ADR 0023). The gateway carries out each key once across runs, not only within one run, so a rerun or a second run can't raise the same ticket twice.
- **A part-done proposal says so.** If one write of three fails, "Make the approved changes" reports "2 of 3 made". A retry carries out only the one that failed.
- **Our API links each n8n execution to our run** on the first call from one of our nodes. Approval requests still key off our own request ID, never n8n's execution ID. If staff add n8n nodes between ours that drop fields, the run still holds together.
- **A run whose "Ask for a yes" was deleted or moved** reaches "Make the approved changes" with nothing approved. The gateway refuses with "No yes for this run", and the AI troubleshooter says which edit caused it.
- **The workflow lint in `orchestration/workflows.py` stops being the safety barrier.** It becomes the usefulness check that ADR 0027 describes.
- **If this ADR is accepted,** the glossary's "Leg" no longer applies, and `AGENTS.md` gains one line: n8n holds no write key, and the write gateway checks every approval itself.

## Accepted on 13 Nov 2026, with these additions

**A notice needs no yes (the Tell rule).** A Teams card or an email that only reports what a run read may go out without an Approver, when all three hold: its recipients are fixed in the Portal's Connections, not chosen per run from the data; its content is composed by our API from the run's stored reads and agent results, never from text in a node; and the Portal says what it does, "Posts in Teams and emails". A change to data in Jira or Confluence always needs a yes. A Tell never claims a change was made unless the write gateway made it.

This rule replaces the consequence above that read "Posting in Teams is a write, so it goes through the gateway too": a Tell is a notice under this rule, and a Teams message that asks a question or carries a change stays a write.

**The write gateway gains two checks** that deny a proposal: the request has not expired, and the run is not a test run. A third rule is per action: an action whose subject key was already carried out for this use case in any run is skipped as "already made", and dropped from the proposal before the Approvers see it. The write key is `(use case, subject)` where the action has a subject, else `(run, proposal, index)`. A part-done proposal is recorded per action, so a retry carries out only what is not done.

**How a run is linked.** Our API links an n8n execution to a run on the first node call by the start item it finds in the execution's data: a nonce our API issued for exactly one run, checked and marked used by our API itself, never by the node alone. An execution started by a trigger with no start item is a new run; one started by hand in n8n is the holder's run, and is refused when nobody holds the workflow.

**Whose work, from our records.** For a version published from the Portal, the publisher is the Portal person who acted, from our records; n8n's timeline names the owner account there, which is nobody. For a version published in n8n, the publisher is the n8n user, matched by the user id stored when the platform made their account. The authors of a republished version are parties too.

**Retries.** A retry from the Portal uses n8n's own retry of the failed execution, after the short delay, and our API records who retried. Our API answers a repeated call for the same run and node with its first answer, so no retry runs an agent twice or adds an action twice.

**A lost wake.** If our API cannot wake a waiting execution for a day, the run is lost and the Operator may carry out the approved proposal from the Portal. A workflow deleted while a request waits ends the request as cancelled, with nothing written, and tells the Approvers.

**Test runs** run the draft by hand in n8n, read for real, and stop at "Ask for a yes" without asking anyone; the gateway refuses any write from a test run.

**Whose work, made fail-safe.** A version published in n8n whose publisher is not matched to a person on our People list cannot run until an Operator matches the person.

**Two lines marked "P7 confirms"**: the manual run of a draft and n8n's public retry are the chosen mechanisms; the spike P7 confirms both on 2.42.6 before the code that relies on them lands, and each has a named fallback.

This ADR supersedes ADR 0007. ADR 0024 is accepted at the same time, unchanged, because this engine builds its two waits and its expiry. The glossary's "Leg" is retired. `AGENTS.md`'s safety rules gain: "n8n holds no write key, and the write gateway checks every approval itself at the moment of writing", and "a notice that only reports what was read may go out without a yes, under the Tell rule".

The team lead accepted this ADR on 13 Nov 2026, when they decided that n8n is the engine behind every workflow. The design and build plan are in `docs/design/chat-first/ENGINE-PLAN.md`.
