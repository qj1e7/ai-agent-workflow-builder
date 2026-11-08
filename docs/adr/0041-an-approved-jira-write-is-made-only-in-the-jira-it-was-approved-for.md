---
status: accepted
---

# An approved Jira write is made only in the Jira it was approved for

From the investigation of issue #166. Number 0039 is kept for "Operators replace connection keys in Settings" (implementation plan, section 5).

This changes the approval gate and the safety checker, so `AGENTS.md` requires an ADR.

An Approver says yes to a ticket in a project, such as "Create Jira ticket in MOCK: Upgrade Redis from 8.0.2 to 8.2.1". The proposal's digest (ADR 0008) covers the connector, the operation, the target and the fields. For Jira the target is only the project key. Which Jira the ticket goes to is not in the proposal at all. platform-api builds its one Jira adapter from `JIRA_BASE_URL` when it starts (`wiring.py`, `jira_for`), and the write gateway's Jira connector uses whatever adapter the running process has.

So if `JIRA_BASE_URL` changes between the yes and the write, the ticket is made in the new Jira. The digest still matches, because both the stored proposal and the approval request were saved before the change. On 7 Nov 2026 we showed this on a live stack, with the practice Jira and a second Jira that has a project of the same key. Issue #166 has the steps and the logs.

- Bob approved a ticket while the practice Jira was set up. The act leg was held, `JIRA_BASE_URL` was moved to a second Jira, and the act leg then made the ticket in the second Jira. Nothing reached the practice Jira.
- A write that failed on the practice Jira was retried after the move. The retry needed no new yes, looked for the write's label in the second Jira, found nothing there, and made the ticket there.
- The watchlist then asked the second Jira whether a ticket made in the practice Jira was Done. The second Jira had an unrelated Done ticket with the same key, so the watchlist moved "our version" on the strength of a ticket nobody on the team touched.

This breaks the product safety rule that no write runs without approval for that write. The real switch from the practice Jira to NCS's Jira, a move from Data Center to Cloud (which keeps project keys), or a sandbox and a live Jira with the same project key all set up this case. ADR 0039 will let an Operator change the Jira address in Settings with no restart, which makes it easier to reach.

## Decision

**Each write records the Jira site it was approved for.** A site is where tickets live, not the key the platform signs in with. Its identity is `practice` for the practice Jira, or `jira:` and a one-way fingerprint of the site's address, made the same way as the connection identities from N18 and #163 (`identity_of` in `orchestration/dispatch.py`). Before it is hashed, the address is normalised. The scheme and the host are put in lower case, the port is kept, and the path is kept with no trailing slash. A Data Center Jira may live under a path such as `/jira`.

The site leaves out the token, the email and the flavor. ADR 0035 says a retry after a new token needs no second approval, and a new token does not move any ticket. This is why the site is not the Jira connection check's identity, which includes the token and the email so that a new token is checked again.

**The site is part of what the Approver approves.** When our API forms a proposal, it adds the site its Jira connector writes to now to each Jira action's target, beside the project, as in `{"project": "MOCK", "site": "practice"}`. The digest already covers the whole target, so the digest the Approver's decision quotes now covers the site too. The builder does not learn about sites. Orchestration adds the site after it binds the intents, because orchestration holds the connector.

**The safety checker refuses a write whose site no longer matches.** `write_actions.check` gets, beside the registry of operations, the site each connector writes to now. The write gateway gives both, as it gives the registry today. After the digest check, the checker compares each action's site with its connector's site. If they differ, or the action has no site, it denies with a new reason, `target_changed`. The checker still denies by default, and it stays the only code that can issue an `AuthorizedWrite`.

**The run says so in plain words.** The run fails at the write step with `SafetyDenied`, as every denial does, and the denial cannot be retried. The run's failure summary, the retry refusal and the AI troubleshooter say:

> Jira's settings changed after the Approvers said yes, so the platform did not make the ticket in a Jira they did not approve. Check Jira for a ticket with this run's label. If there is one, the work is done and no new run is needed. If there is none, report it to support, and start a new run only once the cause is fixed.

The last three sentences are the agreed write-step advice (`WRITE_STOP_ADVICE`, ADR 0035), unchanged. They fit this case, because an earlier try may have made the ticket in the approved Jira before the settings changed. A new run proposes the ticket again, for the Jira set up now, and asks for a new yes. The AI troubleshooter's advice for `target_changed` is to check Jira's settings.

**A ticket key means a ticket only together with its site.** The watchlist keeps the site with each ticket it wrote (`orchestration.proposed_tickets`), and with the Done ticket that "our version" came from (`orchestration.our_versions`). It takes one list from the Jira set up now: the tickets written there and not yet Done. That list gives each software's open ticket, and it is all the Done check asks Jira about, so the two cannot disagree. A ticket written in another Jira stays as written, but it is not open here. The watchlist does not move "our version" for it, does not show its key, and does not count it when the next check decides whether a software needs a ticket. So the Portal never links a key to a Jira it was not written in. The ticket "our version" came from is named only while its Jira is set up. The same holds for anything later that reads a ticket the platform made.

## What stays the same

- Who may approve, the order of the steps, and that nobody approves their own work.
- The digest check. A proposal that changed since the Approver read it is still denied with `digest_mismatch`.
- The gateway's and the connector's records, the write key, the label lookup and the rules for accepting a ticket found by its label (ADR 0035). With this check, they only ever run against the Jira the write was approved for.
- A retry after a new token, or after Jira was busy, still needs no second approval.
- The agents' Jira reads. They read the Jira set up now, and every write they propose is checked at the write.
- n8n holds no Jira key (ADR 0026).

## Considered options

- **Put the address in the digest only.** The digest compares the stored proposal with the approval request, and both are saved before the settings change. So the digest alone cannot see a change made after the yes. The check has to compare with the site in use at the write. The site goes in the target so that the yes covers it, and the check compares it with the connector's site.
- **Check the site inside the Jira connector.** It would work for Jira. But ADR 0008 makes the safety checker the one place that decides whether a write may happen, and a second gate in one connector is easy for the next connector to miss.
- **Use the connection check's identity.** It includes the token, so every token rotation would deny every approved write that has not run yet, which goes against ADR 0035's retry rule.
- **Keep the plain address instead of a fingerprint.** It could be shown to the Approver. But a DevNet address may be internal, and the run records, the activity log and the Portal would carry it. #163 and N18 keep only a fingerprint.
- **Ask the Approvers again when the site changed.** It would save the Operator a new run. But a second request about the same change could look like a repeat of the first, and the Approvers said yes to another place. A new run, with its own request, is clearer.
- **Refuse to start platform-api while an approved write is waiting and the site changed.** A deploy or a Settings change (ADR 0039) would then be blocked by one waiting run. Denying that run is enough.
- **A runbook step that lets waiting writes finish before a Jira switch.** It helps, and the switch steps in `infra/README.md` should say it. But it depends on people remembering. The safety checker denies by default.

## Consequences

- **The switch to a real Jira fails the runs approved but not yet written,** with the plain message above. Operators start new runs. `infra/README.md`'s "A real Jira" steps gain a line that says to wait until no run is between a yes and its write, or to expect those runs to stop.
- **During a revision switch on Azure,** two revisions can run at once, one with each Jira. Each write is checked by the revision that makes it, so a write approved for the old Jira is refused by the new revision, whichever replica picks it up.
- **ADR 0039 must keep this rule.** Replacing the Jira key in Settings keeps the site. A new address is a new site, and its confirmation should say that runs waiting between a yes and their write will stop.
- **Proposals and written tickets saved before this change have no site.** Deny by default treats them as another site, as #163 did for Teams posts. A waiting approved write stops with the message above. The watchlist stops checking those tickets for Done and no longer counts them as open, so the next check proposes a new upgrade ticket for each software that had one open, and an Approver decides it. The software page no longer names the ticket an earlier Done came from. The `azure-dev` environment has no `JIRA_BASE_URL` set, so every proposal and ticket on the Azure deploy so far is the practice Jira's. The team lead decided on 8 Nov 2026 to keep deny by default: rows saved before this change are not filled in as `practice`.
- **Tests.** The safety checker's tests gain a changed site and a missing site. A test like #163's `test_outcome_channel.py` approves on one Jira and writes after a switch to another. The live repro in issue #166 becomes a check that the second Jira gets no call.
- **The approval page and the Teams card name the Jira** each ticket goes to, "the practice Jira" or the site's host, so the Approver sees where the ticket goes before saying yes (decided 8 Nov 2026). The issue type (`JIRA_ISSUE_TYPE`) can also change after the yes. The Approver does not see it today, so it stays outside what they approve.
- **The glossary** gains "Jira site", the Jira that tickets live in and that an approved write is checked against.

## Decision record

Accepted by the team lead on 8 Nov 2026, with the three recommendations in PR #167: the approach above (the site is part of what the Approver approves, and the safety checker refuses a write whose site no longer matches); proposals and tickets saved before the change are denied by default rather than filled in as `practice`; and the approval page and the Teams card name the Jira.
