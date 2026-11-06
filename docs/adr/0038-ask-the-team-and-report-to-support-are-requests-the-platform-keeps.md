---
status: proposed
---

# Ask the team and Report to support are requests the platform keeps

The AI-native redesign (`docs/design/ai-native-redesign/`) gives people two ways to reach a human when the platform can't help.
- **Ask the team.** When the Planner can't do something, for example "email me a list", the person can ask the team for it.
- **Report to support.** When the AI troubleshooter says a run stopped because of a fault in the platform, not in the workflow, the person can report it.

The prototype shows both working. Nothing in the built app does either today. The plan builds them as N1 (this ADR) and N14 (`POST` and `GET /api/v1/team-requests`). Until someone decides who reads these requests, the app would tell people "sent" with nobody on the other end. An outside review of the redesign flagged exactly that (finding F-01).

Three facts limit the choice.
- **Two roles only.** There are Operators and Approvers, and no "admin" role to send requests to.
- **No new outbound channels.** Email isn't on the team's plan, and agents can't post messages in Teams (ADR 0036 uses Teams only for the approval card).
- **Private networks.** The app must later run inside DevNet, so the answer can't depend on an outside service.

## Proposed decision

This is a draft. The team and the sponsor must confirm the open questions below before it is accepted.

- **The platform keeps every request in its own database,** in the builder context. Each request records:
  - who asked, and when;
  - the kind: Ask the team, or Report to support;
  - the person's words;
  - for Report to support, the run and the AI troubleshooter's notes;
  - a status: Open, Answered or Done;
  - each reply, with who wrote it and when.

  Writing to our own database is not an agent write action, so it needs no Approver's yes. The audit log records each request and each reply.
- **Everyone on the team can read them.** One list, Team requests, sits under Settings. Every Operator and Approver can see it. Any Operator can reply to a request, mark it Answered or Done, or say it won't be done and why. No new role is added.
- **A new request posts a card to the team's existing Teams channel.** It reuses the approval card's webhook (`TEAMS_WEBHOOK_URL`) and ADR 0036's pattern:
  - the card has one button, Open in AI Workflow Builder, which opens the request in the app;
  - nothing can be decided or answered inside Teams.
- **The person hears back in the app.** Their own requests and support cases show under "Following up" on Workflows, with the status and the latest reply. A reply also puts the request in that person's Needs you until they open it. No Teams message is sent for a reply, so the channel only sees new requests.
- **Report to support uses the same list,** marked "Platform problem", with the run attached. The support case track the prototype shows (Reported, Support is looking at it, Fixed) is set by whoever handles it in the list. The coding-agent stages stay Planned.
- **What a request may contain.**
  - The box says "Don't paste passwords or keys."
  - Requests are never sent to the AI model.
  - A request is plain text with a length limit. The plan sets the limit with the API.
- **How long requests are kept.** As long as the audit log. Done requests leave the list but stay in the record.

The confirmation in the app then says what is true, for example "Saved as a request for the team. Everyone on the team can see it, and you'll see replies under Following up."

## Questions for the team and the sponsor

1. **After handover, who looks at "Platform problem" reports?** During the project it is our team. After handover it is whoever at CODESparks or NCS looks after the platform. The sponsor should name that group, even if the app itself needs no change.
2. **Is the approvals channel the right place for new-request cards?** If CODESparks wants them in a different channel, that needs a second webhook setting, `TEAMS_REQUESTS_WEBHOOK_URL`. It falls back to the approvals one when unset.
3. **Should requests be kept as long as the audit log,** or for a shorter, fixed time?
4. **Should Approvers who are not Operators be able to reply?** The draft says no, because replying changes a request's status, and only Operators set things up.

## Considered options

- **A named platform contact in Settings receives them.** Rejected for now. It adds a named person to look after, much like ADR 0024's named Approvers, which are not built. Requests stop when that person is away.
- **Each request becomes a Jira ticket in a support project,** through the platform's one write. Attractive, because CODESparks lives in Jira, and the person could hear back by the platform reading the ticket's status. Rejected for the first version because:
  - every write needs an Approver's yes, so even asking for help would wait on an approval;
  - it needs a support project to exist and be agreed;
  - it mixes the team's own requests into their Jira.

  It stays the natural next step if the sponsor prefers Jira.
- **Email to a support mailbox.** Rejected. Email isn't on the team's plan, and it needs an outside service.
- **Keep showing "sent" in the prototype and decide later.** Rejected. It promises a delivery nobody receives.

## Consequences

- **Teams usage widens.** Teams carries approval requests and new team requests, still with one button that opens the app and no decisions in Teams. Spec section 14 and the product rule "Teams is used for one thing" need one line each.
- **The glossary gains "Team request".**
- **Plan N14 builds the store,** the two routes and the Settings list. Plan N15 links Report to support from the run page.
- **Nothing here touches the approval gate or the safety checker.**
