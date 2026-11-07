---
status: accepted
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

## Decision

Accepted on 7 Nov 2026 by the team lead, with the recommended answers below. Questions 1 and 3 still need the sponsor. Their answers change the handover guide and the retention setting, not the code.

- **The platform keeps every request in its own database,** in the builder context. Each request records:
  - who asked, and when;
  - the kind: Ask the team, or Report to support;
  - the person's words;
  - for Report to support, the run and the AI troubleshooter's notes;
  - a status: Open, Answered or Done;
  - each reply, with who wrote it and when.

  Writing to our own database is not an agent write action, so it needs no Approver's yes. The audit log records each request and each reply.
- **Everyone on the team can read and answer them.** One list, Team requests, sits under Settings. Every Operator and Approver can see it. Anyone on the team can reply to a request, mark it Answered or Done, or say it won't be done and why. No new role is added.
- **A new request posts a card to the team's existing Teams channel.** It reuses the approval card's webhook (`TEAMS_WEBHOOK_URL`) and ADR 0036's pattern:
  - the card has one button, Open in AI Workflow Builder, which opens the request in the app;
  - nothing can be decided or answered inside Teams;
  - an optional setting, `TEAMS_REQUESTS_WEBHOOK_URL`, sends these cards to a different channel instead. When it is unset, they go to the approvals channel;
  - the list in the app is the record. The card is only a nudge, so the feature still works where the app can't post to Teams.
- **The person hears back in the app.** Their own requests and support cases show under "Following up" on Workflows, with the status and the latest reply. A reply also puts the request in that person's Needs you until they open it. No Teams message is sent for a reply, so the channel only sees new requests.
- **Report to support uses the same list,** marked "Platform problem", with the run attached. The support case track the prototype shows (Reported, Support is looking at it, Fixed) is set by whoever handles it in the list. The coding-agent stages stay Planned.
- **What a request may contain.**
  - The box says "Don't paste passwords or keys."
  - Requests are never sent to the AI model.
  - A request is plain text with a length limit. The plan sets the limit with the API.
- **How long requests are kept.** As long as the activity log. A request marked Done leaves the list after 30 days but stays in the record.

The confirmation in the app then says what is true, for example "Saved as a request for the team. Everyone on the team can see it, and you'll see replies under Following up."

## Open questions, with recommended answers

The team lead accepted these answers on 7 Nov. Questions 1 and 3 still need the sponsor, or NCS through the sponsor.

1. **After handover, who looks at "Platform problem" reports?**
   - Recommended:
     - until handover, our team, with one named person each week;
     - after handover, the developers who take over the code. The sponsor names that group.
   - Why: a platform problem is a fault in code, and CODESparks support staff aren't developers. The answer goes in the handover guide, not in the app, so a change of owner needs no change to the app.
   - Needs: the sponsor's answer.
2. **Should new-request cards go to the approvals channel?**
   - Recommended: yes, to start, with the optional `TEAMS_REQUESTS_WEBHOOK_URL` built from the first version.
   - Why:
     - one channel is one place to look for a small team;
     - requests should be rare next to approvals;
     - moving them later is a setting, not a change to the code.

     If cards start burying approvals, set the second channel.
   - Whether the app can post to Teams inside DevNet at all is already question 4 in `docs/design/devnet-move.md`. The in-app list doesn't depend on that answer.
3. **How long are requests kept?**
   - Recommended: as long as the activity log, with Done requests leaving the list after 30 days.
   - Why: a request links to runs and to replies about what the team decided, so it belongs with the rest of the record. One retention rule is simpler than two.
   - Needs: the project has no retention rule for the activity log either. Add "How long must activity and audit records be kept?" to the NCS questions in `docs/design/devnet-move.md`.
4. **Can Approvers who are not Operators reply?**
   - Recommended: yes. This changes the first draft, which said no.
   - Why:
     - the people who decide whether the team gets email or a new tool are often the senior people who approve;
     - stopping them would make them ask an Operator to type their answer;
     - a reply changes no workflow and writes nothing outside the app, so it can't weaken the approval gate;
     - every reply is logged with who wrote it.

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
