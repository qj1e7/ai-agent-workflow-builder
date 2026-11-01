---
status: proposed
---

# The approval request goes to Teams as an Adaptive Card that opens our approval page

The Operator asked that every practice copy be built as if it links to the real app, so that moving to the real one has no friction. Teams was not built that way. Its port posted one plain sentence with a link that only worked inside the Portal, and nothing could show a request's outcome later. A real Teams channel takes an Adaptive Card. Posting to a real channel is also a new external dependency, which ADR 0023 says needs its own ADR. The Operator chose "card and link now, bot later" on 1 Nov 2026.

So the platform builds one Adaptive Card for each approval request, and both the practice copy and a real channel get that same card. The card has one button, **Open in AI Workflow Builder**, an `Action.OpenUrl` to the approval page. The Approver decides there, under their own sign-in, as ADR 0009 and ADR 0015 describe. The practice Teams panel draws the stored card and has no Approve or Decline buttons, because the real channel will not have them either.

## The card

- One function, `approval_card(notice)` in `platform-api/src/platform_api/orchestration/teams.py`, builds it. It shows the workflow's name, each write as the approval page lists it (at most 10, then "And 5 more"), what the agents found, who can decide each step, and who can't because the run is their own work.
- The button's address is absolute, built from `PUBLIC_BASE_URL`, because Teams opens it outside the Portal.
- **Version 1.4.** Microsoft says Teams renders Adaptive Cards up to 1.6 for a bot. Reports on the Workflows webhook say 1.4 renders well and some 1.5 parts do not. The card uses nothing newer than 1.2, and a test checks each part against the version it needs.
- **Text we did not write goes only in a `TextRun`.** That covers the agents' summary, the ticket titles, the workflow's name and people's names. The Adaptive Card schema says a `TextRun` has no markdown, so `**Approve now**` shows as typed and cannot pose as our own words. Our fixed headings are in a `TextBlock`, which Teams reads as markdown. The card has no `FactSet`, because a fact's value is markdown too. Each line is one line, cut to 300 characters.
- **Nothing we did not write can be a link.** Microsoft's webhook page says every text field in a card supports basic markdown, which may reach a `TextRun` too. So in text we did not write, every character shown as nothing is removed first, such as a zero-width space or a direction mark (every format character, plus a few others), so none can split a marker. Then every `://` becomes `[:]//` and the address's dots after it are broken (`https[:]//example[.]com`), wherever it appears, even inside a word such as `_https://`. A `www.` that starts a host becomes `www[.]`, with the host's dots broken. It starts a host unless a `/` or `.` comes before it, as in `/var/www.conf` or `cdn.www.example`, and a letter or digit comes after it, so `_www.` and `1www.` are still broken. Every `mailto:` loses its colon, and a markdown link loses its `](`. Any case counts. The card's one button keeps its real address.
- **A name we cannot read is "someone on this run".** Under real sign-in, a person not on the People list has only an Entra object id, so the card never shows one.
- **No secret reaches a card.** The notice holds only what the card shows, plus the run and approval ids and the proposal's digest. A test pins its fields, so a new one gets a second look.
- **Under 28 KB.** Teams refuses a webhook message over 28 KB. A test builds a card for 40 writes and keeps it under.

## The port

`ApprovalChannel` in `orchestration/dispatch.py` has two calls:

- `announce(notice) -> MessageRef` posts the card and says where it went. The platform keeps that reference in `orchestration.approval_messages`.
- `update(ref, outcome)` shows the outcome once the request is approved or declined. A decision queues it in the outbox, so a slow Teams never holds up the decision. It waits while the request itself is still queued. It still runs when the run fails after the yes, because the outcome is still true. After its retries it gives up and only logs, because the approval page shows the outcome anyway.

Any error an adapter raises is now a `DispatchFailure`. Before, anything else ended the whole tick, and the next tick met the same message first, every 5 seconds. Its traceback is logged with every web address hidden. httpx and httpcore log each request's full address at INFO, so when the wiring builds the webhook adapter it sets them to log only warnings, for every client in the process. That is on purpose, and n8n's and the agent runtime's clients lose those INFO lines too.

**Posts are sent at least once.** If Teams accepts a post but its answer is lost, for example to a read timeout, the outbox retries and the channel gets the card twice. A Workflows webhook has no idempotency key to stop that. A second card for the same request is harmless: both open the same approval page, and a decision is recorded once. Two replicas never send the same outbox row, though, as during a revision switch. Each tick takes at most 10 due rows with `FOR UPDATE SKIP LOCKED` and leases them for a minute. Just before it sends a row, it renews that row's lease, and it skips the row if the lease is no longer its own, because another replica took the row after the lease ran out. One send takes far less than the lease, since every client's timeout is 10 seconds, so a renewed lease cannot run out during its send. A row a stopped replica held is sent once its lease runs out. A row that raises an error the adapter did not turn into a `DispatchFailure` is logged and keeps its lease, and the tick carries on with the rest.

**Each post records its adapter.** `MessageRef` and `approval_messages` say which adapter posted the request, `practice` or `teams_workflows`. When the platform moves between the practice copy and real Teams, an outcome for a request the other adapter posted is skipped and logged. So the switch never posts a stray outcome card, and never retries an update that cannot work.

There are two adapters:

- **The practice copy** (`TeamsStub`) keeps the card's JSON and the channel name, and its update puts the outcome at the top of the card, as a bot will edit it. The Portal's Teams panel draws that JSON with a small renderer for the 4 parts the card uses.
- **A Teams Workflows webhook** (`TeamsWorkflowsWebhook`) posts `{"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": <card>}]}` to `TEAMS_WEBHOOK_URL`. It is off unless that is set. A Workflows webhook cannot edit a card it posted, so its update posts a second, short card with the outcome. The webhook's address carries its own signature, so it is a secret. It lives in Key Vault (Terraform's `teams_webhook_url`), and no error message, log line or card holds it. Teams throttles more than 4 posts a second, and the outbox retries a refused post.

## What does not change

The approval gate. `Orchestrator.decide()` is unchanged, so the same rules decide: only an Approver, never one who started, owns or retried the run, the steps in order with a different person for each, and a refused decision when the proposal changed since the Approver read it. Approval ids are our own, and nothing keys off n8n. Nothing in a card can decide: its only button opens a page that needs sign-in. Every decision is still logged with who made it.

## Considered options

- **A Teams bot with `Action.Execute` buttons now.** Approvers could decide inside Teams, and the bot could edit the card and mention the person asked. It needs an Azure Bot, a Teams app that NCS lets us upload, and a sign-in check on every button press, so it waits until NCS confirms. The port is ready for it: `update` and `MessageRef` exist, and the notice carries the digest that a decision must send back.
- **Keep the panel's Approve and Decline buttons.** The demo would show something the real channel cannot do, and the move to real Teams would remove a feature.
- **An Adaptive Cards renderer library in the Portal.** It would need its own ADR, and the card uses only 4 kinds of part, so a small hand-written renderer draws them.
- **Escape markdown and use a `FactSet`.** Microsoft does not fully document Teams' markdown subset, so we cannot be sure an escape works. A `TextRun` has no markdown at all.
- **An Office 365 Incoming Webhook.** Microsoft retired these in May 2026 in favour of Workflows.

## Consequences

- **Moving to real Teams is configuration.** In the channel, create a Workflows flow from "When a Teams webhook request is received" with "Post card in a chat or channel". Put its address in the `azure-dev` environment's secret `TEAMS_WEBHOOK_URL`, and the channel's name in the variable `TEAMS_CHANNEL`. The deploy passes both to Terraform, and Terraform puts the address in Key Vault. In Compose, set them in `.env`.
- **The practice panel shows the card a real channel gets.** The tests and live checks that pressed Approve in the panel now decide on the approval page.
- **A new test-only dependency.** `jsonschema`, in platform-api's dev group, checks every card against the Adaptive Card schema. The schema is a copy in `contracts/schemas/adaptive-card-1.5.json`, with its source address and checksum in `contracts/README.md`, and tests never fetch it.
- **Migration 0009** adds the card and its outcome to the practice copy's messages, and the `approval_messages` table. **Migration 0011** adds each outbox row's lease and each post's adapter.
- **The button is only as good as `PUBLIC_BASE_URL`.** Under real sign-in, platform-api refuses to start unless it is https with a host and no query or fragment. Plain http works only on localhost, for the local sign-in stack.
- **No real mention yet.** A Workflows webhook posts as the flow's owner and cannot mention a person reliably, so the card names who can decide in its text (ADR 0024).
- **Questions for NCS:** a bot or a Workflows webhook, who owns the flow, one channel or one for each workflow (ADR 0027), and whether DevNet lets platform-api reach the webhook's address.
- **Not confirmed:** whether Teams turns a plain web address inside a `TextRun` into a link, or applies markdown there. The card breaks every address and markdown link in text we did not write, and labels the agents' words as theirs, under "What the agents found". Before `TEAMS_WEBHOOK_URL` is set, someone posts a check card full of such text to a test channel once and looks at it in Teams (`scripts/teams-card-check.sh`, in `infra/README.md`). A bare name such as `example.com`, with no `www.` and no `://`, is left as written.
