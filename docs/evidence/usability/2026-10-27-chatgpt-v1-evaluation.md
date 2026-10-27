# Independent usability evaluation of prototype v1 (ChatGPT)

- Date: 27 Oct 2026
- Evaluator: ChatGPT, working from `docs/handover/PROTOTYPE_HANDOVER.md`
- Version tested: prototype v1. The copy is `docs/design/portal-routines/v1/prototype.html`, with its screenshots in the same folder.
- The report below is copied as the team received it. The team has not edited it.

---

# Independent operator UX evaluation

Prototype tested: [Portal Routines Prototype](https://claude.ai/artifact/KDxZZkF6BjHmW92YPa2XzU)  
Perspective: first-time, nontechnical support operator  
Scope: interactive prototype only; no code or current MVP reviewed

## Overall verdict

The prototype is strong at telling an operator what needs attention, explaining failures, and making approvals feel controlled. Start-of-day triage, one-click recovery, and fault reporting were notably clear and efficient.

However, routine creation is not trustworthy enough for real operator use. The prototype accepted one task and silently designed a substantially different routine. That is the most serious issue because it could automate the wrong work while still appearing successfully configured.

Overall: **promising operational dashboard, but not yet safe for self-service routine creation.**

## Workflow results

Actions count deliberate clicks or entries, excluding reading and test controls unrelated to the task.

| Workflow | Result | Actions | Key evidence |
|---|---:|---:|---|
| Start-of-day triage | Pass | 0 | Home immediately showed three actionable items, their dates, causes, and direct next actions. |
| Review software versions/history | Pass | 2 | Software grouped items into “Needs a person” and “Up to date”; history showed dated discoveries, approvals and completed tickets. |
| Approve tickets as Bob | Pass with friction | 4 | Bob saw the exact two proposed Jira tickets, source repositories, versions, initiator, destination project and confirmation that nothing had been written yet. |
| Create weekly routine | **Failed user intent** | 8 | A Friday 4pm stale-ticket summary for Teams became a closed-ticket summary that updates Confluence at 5pm. |
| Fix stopped routine | Pass | 2 | The troubleshooter named the moved GitHub repository and offered a specific fix; retry completed without requiring technical knowledge. |
| Report platform fault | Pass with gaps | 2 | The form automatically included the problem, failed step, troubleshooter finding and full run record. |
| Phone-width check | Inconclusive/host issue | — | At 390px, the Claude host left the artifact in an approximately half-width column, producing severe cramping. This does not reliably prove how the self-contained prototype behaves on a phone. |

## Findings

### S1 — Critical: routine creation can silently change the operator’s task

**Observed:** I entered:

> Every Friday at 4pm, summarize open Jira tickets older than 14 days and post the summary to CODESparks Support in Teams.

The generated plan instead:

- found tickets **closed this week**;
- wrote a summary;
- updated a **Confluence** page;
- scheduled it for **17:00**, not 16:00;
- named it “Weekly summary in Confluence.”

The final review did expose the substituted workflow, but it did not warn that the plan contradicted the request. A hurried operator could turn on the wrong routine.

**Impact:** incorrect operational work, messages sent to the wrong destination, and loss of trust in natural-language setup.

**Recommendation:** parse the request into visible fields—trigger, data source, filter, action, destination and time—and highlight every unsupported or changed requirement. Block activation until contradictions are resolved. Never silently replace an unsupported request with a canned workflow.

### S2 — High: approvers cannot verify the underlying release information

**Observed:** The approval panel showed “Release notes link,” but it was plain text rather than an actionable link. The resulting ticket identifiers, MOCK-14 and MOCK-15, were also not links.

The approval otherwise did an excellent job of showing exactly what would be written and who initiated the run.

**Impact:** Bob can see the proposed version change but cannot conveniently inspect the evidence before approving it.

**Recommendation:** make release notes, repositories and created ticket numbers real links. Show release date, risk notes and a short change summary alongside each ticket.

### S2 — High: scheduling does not preserve the requested time

**Observed:** The task specified 4pm, but the schedule defaulted to 17:00. Available times were limited to 09:00, 12:00 and 17:00, with no explanation that 16:00 was unsupported.

**Impact:** routines may execute at the wrong operational boundary, potentially missing handovers or reporting deadlines.

**Recommendation:** extract the requested time automatically. If it is unsupported, show an explicit choice such as: “4pm isn’t available; choose another time.” Support free-form time entry, timezone display and common frequencies beyond weekly.

### S3 — Medium: routine setup becomes too technical for the target operator

**Observed:** The plan introduced “agents,” a “new tool,” a published API call, a tested runner, and platform checks. The safety explanation was valuable, but it dominated the setup flow.

**Impact:** nontechnical staff may believe they are being asked to approve code or understand architecture.

**Recommendation:** lead with operational language: what will be read, what will change, where it will change and when approval occurs. Put API and runner details under “Technical details.”

### S3 — Medium: approval ownership is vague

**Observed:** Setup offered “Any Approver except you” and an optional two-approver checkbox, but did not name a primary approver, backup, deadline or escalation route.

**Impact:** work may wait indefinitely because responsibility is shared but not assigned.

**Recommendation:** allow a named primary approver, backup approver and escalation time. Show who currently owns each waiting decision.

### S3 — Medium: support reporting lacks a durable case identity

**Observed:** Reporting was impressively short and attached useful diagnostic evidence automatically. After submission, Home showed a four-stage “Following up” tracker, but no report number, assigned support person, expected response time or link to a case.

**Impact:** the operator cannot quote the report elsewhere or know when to chase it.

**Recommendation:** return a case ID, submission time, owner, expected response target and notification method. Retain and display the operator’s optional note.

### S3 — Medium: the public hosted mobile experience is cramped

**Observed:** At a 390×844 viewport, the Claude wrapper left the prototype in a narrow column occupying roughly half the available width. Text and controls became heavily compressed.

**Impact:** stakeholders testing the shared link may conclude that the prototype is not mobile-ready, even if the underlying HTML is responsive.

**Recommendation:** validate mobile behavior using the self-contained `prototype.html` or a full-page static host. Test the actual prototype at 375px and 390px without the Claude wrapper.

### S4 — Low: test scaffolding competes with the product

**Observed:** “Mock: OK it as Bob,” actor switching and the fixed mock-control area appear beside real product controls.

**Impact:** first-time evaluators may mistake simulation controls for intended product behavior.

**Recommendation:** visually separate or hide evaluator controls behind a clearly labelled testing drawer.

## What worked especially well

- Home answered “What needs me?” without requiring navigation.
- Each triage card provided a direct next action rather than only a status.
- Software status used plain, actionable groupings.
- Version history connected discoveries, approvals and completed Jira work.
- The approval gate clearly stated that nothing had been written yet.
- Self-approval provenance was visible: the interface named whose schedule started the run.
- The stopped-run explanation was specific, nontechnical and immediately actionable.
- Successful retry clearly distinguished steps that were unnecessary.
- Fault reporting avoided forcing the operator to rewrite technical diagnostics.
- After reporting, Home changed to “Nothing needs you” and preserved follow-up visibility.

## Prioritized design improvements

1. **Guarantee routine-intent fidelity.** Add structured intent confirmation and block activation when the generated workflow contradicts the request.
2. **Make approvals verifiable.** Provide working evidence links, ticket links, richer release context and per-item decisions.
3. **Expand routine controls.** Support exact times, more frequencies, named approvers, edit, pause, disable and delete.
4. **Strengthen fault follow-up.** Add a reference number, owner, service target and notifications.
5. **Simplify language for operators.** Keep agent/tool/API details behind progressive disclosure.
6. **Validate the standalone mobile layout.** Test outside the Claude artifact wrapper.
7. **Prepare for scale.** Add search, filtering and sorting before operators accumulate many routines or software entries.

## Usability assessment

| Dimension | Rating | Assessment |
|---|---:|---|
| Learnability | 4/5 | Daily triage and recovery are understandable without training. Routine-building terminology is less approachable. |
| Efficiency | 4/5 | Common exception workflows require only one or two decisions. Routine creation is longer and includes a separate tool-approval interruption. |
| Workflow suitability | 3/5 | Good for attention management and approvals; weak when requirements differ from the scripted example. |
| Information architecture | 4/5 | Home, Routines, Software and New routine form a clear small-scale structure. |
| Error prevention and recovery | 4/5 | Recovery is excellent, but incorrect AI interpretation is not treated as an error. |
| Operational productivity | 3/5 | The dashboard could save substantial checking time, but unreliable routine generation creates operational risk. |
| Visibility and feedback | 4/5 | Status, provenance and next actions are usually explicit. Support ownership and scheduling substitutions are not. |
| Completeness | 2.5/5 | Essential lifecycle controls, flexible scheduling, accountable approval assignment and scalable list management are still missing. |

## Final recommendation

Proceed with the Home, software visibility, approval and troubleshooting concepts. Treat natural-language routine creation as the next design gate: it should not progress toward implementation until the system can accurately preserve the operator’s intent, clearly flag unsupported requirements, and let the operator correct the generated plan without starting over.
