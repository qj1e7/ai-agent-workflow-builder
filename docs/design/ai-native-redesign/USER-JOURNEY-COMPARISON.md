# User journey comparison: version 3 against version 4

This document compares the 6 Nov prototype (version 3, `docs/design/portal-routines/prototype.html`) with the AI-native redesign (version 4, `docs/design/ai-native-redesign/prototype.html`). It covers scenarios A to H from the redesign brief and the 15 tasks the 6 Nov handover lists for version 3.

Every count here was measured by a script. None is an estimate. Where something can't be counted, such as how clear a sentence is or how sure a person feels, this document says so. Those questions need a study with real support staff (section 6).

## 1. How the numbers were made

- `checks/run.cjs` drove both prototypes in a real browser (Playwright, Chromium) along scripted paths. Version 3's paths are `checks/paths-v3.cjs`, version 4's are `checks/paths-v4.cjs`. An independent judge wrote version 4's paths, not the people who built version 4.
- Each path takes the shortest route a first-time user could see on the screen. It uses no hidden shortcuts.
- The counts are:
  - **Clicks.** Every button press, including a key press on a button and every menu step.
  - **Fields.** Every text box typed into.
  - **Selects.** Every drop-down choice.
  - **Decisions.** Steps where the person chooses something that matters, such as a project, a time, Approve or Delete. A decision is also counted as a click, a field or a select.
  - **Screens.** Distinct pages visited, counting the starting page.
- Test controls (the person switch, Planned features, the simulations) are never counted.
- Each path also checks what the screen says at each step. A path that reaches the end with the wrong text fails.
- Version 4 was measured twice. Both runs gave identical counts and results for all 40 scenarios (`checks/results/v4.json`, `v4-second.json`).
- The raw tables are `checks/results/v3.md`, `v4.md` and `v4-compare.md`.

### What the counts can't show

- A scripted path knows where everything is. A real person may look in the wrong place first. The counts are a floor, not a prediction of real effort.
- The counts say nothing about time, mistakes, understanding or confidence.
- A lower count is not better by itself. Three rises in version 4 were chosen to make approvals safer or the screen clearer. Each is named below with its reason.

### Comparisons that are not like for like

Version 4 changed some sample data to stop showing things the platform can't do (UX audit X2 and I2). Three scenarios moved because of that, not only because of the design:

- **B, F and T9.** In version 3 the stopped workflow was a GitHub project that had moved, fixed by choosing the new address. The built tools can't read the data that sample needed, so version 4's stopped workflow is "Jira not answering", fixed by a retry. The moved project now lives on the Software watchlist as "Use the new address". Part of the one-click saving in B, F and T9 comes from the easier sample stop.
- **D.** Version 3 offered an alternative to the email request. Version 4 offers only Ask the team, because the request also needs a ticket's type, which the agents can't read. The count is the same. The outcome is different on purpose.
- **T2, T11, T13 and T14** changed their sample for the same honesty reasons. Their rows say why.

## 2. Scenarios A to H at a glance

Counts are clicks / fields / selects / decisions / screens at 1280 px wide. A and B also ran at 390 px with the same counts as at 1280.

| Scenario | Version 3 | Version 4 | Change in interactions | Passed on version 4 |
|---|---|---|---|---|
| A. First-time Operator | 2 / 2 / 1 / 3 / 1 | 2 / 2 / 1 / 3 / 1 | 0 | yes |
| B. Experienced Operator, through Workflows | 3 / 0 / 0 / 1 / 3 | 2 / 0 / 0 / 1 / 3 | -1 | yes |
| B. Experienced Operator, from Home (new) | not possible | 1 / 0 / 0 / 1 / 2 | -2 against B in version 3 | yes |
| C. Approver | 2 / 0 / 0 / 1 / 2 | 2 / 0 / 0 / 1 / 2 | 0 | yes |
| C. Operator can't approve their own run | 3 / 1 / 1 / 3 / 2 | 4 / 1 / 1 / 3 / 2 | +1 | yes |
| D. Unsupported request | 1 / 1 / 0 / 0 / 1 | 1 / 1 / 0 / 0 / 1 | 0 | yes |
| E. AI misunderstanding | 3 / 1 / 2 / 2 / 1 | 3 / 1 / 2 / 2 / 1 | 0 | yes |
| F. Failed execution | 7 / 0 / 0 / 2 / 3 | 6 / 0 / 0 / 2 / 3 | -1 | yes |
| G. Software monitoring | 4 / 1 / 0 / 2 / 1 | 4 / 1 / 0 / 2 / 1 | 0 | yes |
| H. Workflow management | 9 / 1 / 2 / 5 / 3 | 10 / 1 / 2 / 5 / 3 | +1 | yes |

The interaction change is clicks plus fields plus selects.

## 3. Each scenario

### A. First-time Operator

**The task.** A new Operator signs in on day one and wants a weekly Jira summary.

**Version 3.** Type "every Friday, sum up the tickets we closed this week", press Enter, choose the time, choose the Jira project, Turn it on.

**Version 4.** The same five steps, with the project asked before the time.

**What the brief asked to measure.**

- **Is the starting action obvious?** On day one, Home in both versions is the Planner's box with "What does your team do again and again?". Version 4 adds a short "I can" list under it, with "What can't I do yet?" folded away (spec 5.2). The keyboard path reaches the box in 3 key presses, using the skip link (`KEYS-A`). Whether a new person sees the box as the place to start can't be measured by a script.
- **Number of decisions.** 3 in both: the Jira project, the time, and Turn it on.
- **Unnecessary prompts.** The Planner asks back twice in both versions, for the project and the time. The request names neither, and neither has a safe guess. The card never guesses a time (spec 7.1). So no prompt was unnecessary by this measure.
- **Does the summary make sense?** Version 4's card reads as one sentence, for example "Every Friday at 16:00, find the tickets closed this week in Jira project MOCK, sum them up, and put the summary in one new Jira ticket." Version 3 marked parts green as "from your words" when the Planner had changed them (UX audit SC1). Version 4 marks a part as hers only when the words came from her request. The check `card-agrees` confirms the sentence, the footer and the disabled reason agree after every edit. Whether people understand the sentence needs real users.
- **Is the approval behaviour clear?** The card's "What needs a yes" section names today's rule: "Any Approver on your team except you can say yes." Version 3's footer said "One yes turns it on", which mixed up her own click with an Approver's decision (review item 13). Version 4's footer reads "Nothing is unclear. Turn it on when you're ready."

**Why the counts didn't move.** The design work in A went into what the card says, not into its steps. The count was already low.

### B. Experienced Operator

**The task.** An Operator wants to know what needs attention today, and to find and act on a stopped workflow.

**Version 3.** Open Workflows, See why and fix it (opens the run page), "Use langchain-ai/langchain and retry". 3 clicks, 3 screens.

**Version 4 through Workflows.** Open Workflows, Retry the run. The AI troubleshooter's answer sits on the Workflows row, so the run page is no longer a step before the retry. 2 clicks.

**Version 4 from Home (B-home).** Home shows Needs you only when something needs her. The stopped workflow is its first row, with Retry the run on it. 1 click.

**How quickly can she find and act on it?** 1 click from Home, down from 3. Two things caused the saving:

- **Design.** Needs you on Home (spec 5.1), and the troubleshooter's answer on the row.
- **Sample data.** The stop is now one a retry fixes, which needs no choice (section 1). In version 3 the fix also needed choosing the new address.

The counts can't separate the two. A fair reading is that the design removed the trip to Workflows and the run page, and the sample removed a choice.

**Counts agree.** The number of things that need her is the same on Home, Workflows, the tab badge and the Planner's "What needs me?" answer in every state the check covers. Those states run from a normal week through approvals, retries, a pause, Bob's view and no AI model, to day one with Jira down (`counts-agree`). Version 3's counts could disagree (I8).

### C. Approver

**The task.** Bob, an Approver only, opens a waiting request, sees what will change and why, and approves.

**Version 3 and version 4.** Review and decide, Approve. 2 clicks, 2 screens in both.

**Are the action, evidence and consequences clear?** The approval panel (spec 10.4) lists:

- what will change, with each ticket's title;
- why, with links to the evidence;
- who asked;
- what happens on a yes and on a no;
- the person's own part.

Version 3's evidence came from security-advisory and support-date sources that aren't built (I9). Version 4's evidence is the GitHub release notes, which the platform really reads. The count is the same, and what Bob reads is now true. Whether he understands it needs real users.

**Can anyone bypass the server's check?** A prototype can't prove server behaviour. What the prototype and the checks show:

- The Teams card has one button, Open in AI Workflow Builder. Nobody can approve inside Teams (ADR 0036). `teams-drawer-never-approves` checks this, and the judge's planted Approve button in Teams was caught.
- On her own test run, Alice sees why she can't decide and no Approve button (`C-self`, and three roles checks).
- Whoever owns the workflow, started the run or retried it can't decide. The prototype reads this from one function, `partiesOf`, the same set the built gate refuses.
- With Planned features shown, the access review needs Bob, then Alice, in that order. Each is blocked from the other's step.

The real enforcement is in the built API, not the prototype. The server builds the set of people who can't decide at `platform-api/src/platform_api/orchestration/service.py:664` (owner, starter and everyone who retried). `platform-api/tests/test_approvals.py` covers the rule (`test_decide`, `test_own_work_serializes_as_the_http_refusal`).

**C-self rose by 1 click.** On a normal week, Home suggests next steps from what is going on. The set-up examples sit behind "Set up another workflow", so starting from an example takes one tap more. This buys a lighter Home for the person who comes back every day. It costs one tap for the person starting a new workflow from an example. Typing the request still costs nothing extra.

### D. Unsupported request

**The task.** An Operator asks "email me a list of open bugs every Monday". Email isn't on the team's plan.

**Version 3.** Type, press Enter. The Planner explained the limit and offered an alternative.

**Version 4.** Type, press Enter. The Planner says email isn't on the team's plan, and that it can't tell a ticket's type yet, so it can't find "bugs". The only next step is Ask the team.

**Does it explain the limit and offer realistic alternatives?** It explains both limits in plain words: "I can't tell a ticket's type yet, and I can't send email." It offers no alternative here, because none would be realistic. An alternative is offered only when it sets up with every part working (review item 2). The judge's check `alternatives-set-up-cleanly` sent 18 requests, and each of the 15 alternatives offered set up with nothing red.

When email is the only missing part, the Planner does offer the rest. "Every Friday, sum up the tickets we closed this week and email it to me" gets "I can write that summary, but I can't send email", with Set that up for the summary in a Jira ticket.

**Why this matters.** Version 3's alternatives included things the agents can't do, such as listing tickets with no update for 30 days (X2). A person who took one would hit a second "can't". Version 4 trades a friendlier first answer for one that doesn't lead into a dead end.

### E. AI misunderstanding

**The task.** The Planner guesses the wrong Jira project and the wrong day. The person corrects both on the card without starting again.

**Both versions.** Type, press Enter, correct the project, open the schedule, correct the day, close the schedule. 3 clicks, 1 field, 2 selects, 1 screen.

**Can she correct it quickly without restarting?** Yes, in both. Each fix is a tap on the chip, in place. In version 4 the sentence, the footer and the disabled reason redraw together after each edit (`card-agrees`). The ticket set also follows the schedule. If she changes a weekly run to daily, "tickets closed this week" becomes "tickets created in the last day", or turns amber when the meaning would change (`card-ticket-set-follows-schedule`). Version 3 kept the old ticket set, so the card could say one thing and do another.

### F. Failed execution

**The task.** A run stopped because an outside system isn't answering. The Operator should understand it, recover when allowed, or pass it on.

**Version 3.** Open Workflows, See why and fix it, use the new address and retry, back to Workflows, Report to support, Send report, Done. 7 clicks.

**Version 4.** Open Workflows, Retry the run, back to Workflows, Report to support, Send report, Done. 6 clicks.

**Can she understand, recover or escalate?**

- **Understand.** The AI troubleshooter's answer says what happened, whether it's safe, and what to do, on the row itself (spec 10.3). The built troubleshooter is a lookup table, so the prototype only shows answers that table can give. Version 3 named a cause ("down for maintenance") the troubleshooter can't know (review item 3). Version 4 doesn't.
- **Recover when allowed.** Retry the run is offered only when a retry can work. While Jira is still down, the retry doesn't start, and the toast says "Jira still isn't answering, so the run can't start" (`down-state-honest`). With no AI model, an agent workflow's retry is held too (`offline-honest`).
- **Escalate.** A platform fault offers Report to support, never a retry. The case then moves through Reported, Support is looking at it, and Fixed. After the fix, a retry stops at the approval gate and waits for a yes like any run.

**Why the count fell.** As in B, partly because the troubleshooter's answer sits on the row, and partly because the sample stop needs no choice.

### G. Software monitoring

**The task.** A person types "Monitor Kubernetes releases" on Home and should end with Kubernetes on the Software watchlist, without knowing where that page is.

**Both versions.** Type, press Enter, Looks right, "Not sure? Start from the newest", Add Kubernetes. 4 clicks, 1 field, 1 screen.

**Is the request routed without navigation knowledge?** Yes in both. The Planner sends the request to the watchlist from Home. Version 4 also stops showing the security-advisory, package-registry and support-date sources as working. Those sources aren't built (I9). By default they read "Not yet". With Planned features on, they are tagged Planned.

### H. Workflow management

**The task.** Pause one workflow, change its schedule, and delete another with its confirmation.

**Version 3.** Open Workflows, open the workflow, Change schedule, three choices, Save, Pause, back, open the other workflow, Delete, Delete workflow. 9 clicks.

**Version 4.** The same, except Delete sits in More actions, so it takes one more tap. 10 clicks.

**Are these actions discoverable and safe?**

- **Discoverable.** Pause is a visible button beside More actions. While a workflow is paused, its banner explains the state and holds Resume, the one primary action for that state (spec 9). Change schedule is on the page. Delete is last in More actions, after a divider.
- **Safe.** Delete always asks for a confirmation that names the workflow. Saving the watchlist check's schedule makes the person who saved it its owner, so they can't approve its runs (`roles-owner-after-schedule-save`). Pausing a stopped workflow takes it out of Needs you.

**Why the count rose by 1.** Delete moved into More actions. A destructive action one tap further away, behind a divider, is harder to hit by mistake. We judge that worth one tap. Nothing measured here shows whether people find Delete there. The study should test it.

**New in version 4 (H2).** Version 3 had no way to remove a draft set-up card. Version 4 has Discard on Workflows, 2 clicks.

## 4. The 15 tasks from the handover

Counts are clicks / fields / selects / decisions / screens at 1280 px.

| Task | Version 3 | Version 4 | Change | Why |
|---|---|---|---|---|
| T1. Set up from example 1 | 2 / 1 / 1 / 3 / 1 | 3 / 1 / 1 / 3 / 1 | +1 | Examples sit behind "Set up another workflow" on a normal week (spec 5.1). |
| T2. Set up a typed request with every part stated | 2 / 1 / 0 / 1 / 1 | 2 / 1 / 0 / 1 / 1 | 0 | Version 3's request needed a ticket's update date, which the tools can't read (X2). Version 4 types a request the tools can do. |
| T3. Do a test run | 1 / 0 / 0 / 0 / 2 | 1 / 0 / 0 / 0 / 2 | 0 | |
| T4. Add software from a Home example | 4 / 0 / 0 / 2 / 1 | 5 / 0 / 0 / 2 / 1 | +1 | The React example sits behind "Set up another workflow". |
| T5. Add software on the watchlist page | 2 / 2 / 0 / 0 / 2 | 3 / 2 / 0 / 0 / 2 | +1 | Add software takes plain words and looks the project up first (spec 11). An unknown project then asks for the repository. |
| T6. Approve from Workflows | 3 / 0 / 0 / 1 / 3 | 3 / 0 / 0 / 1 / 3 | 0 | |
| T7. Approve from Home as an Approver only | 2 / 0 / 0 / 1 / 2 | 2 / 0 / 0 / 1 / 2 | 0 | |
| T8. Approve from Teams | 2 / 0 / 0 / 1 / 1 | 3 / 0 / 0 / 1 / 2 | +1 | Teams carries the request, and its one button opens the approval page (ADR 0036). Version 3 let people approve inside Teams, which the built app does not allow. |
| T9. Fix a stop the user can fix | 3 / 0 / 0 / 1 / 3 | 2 / 0 / 0 / 1 / 3 | -1 | The troubleshooter's answer is on the row. The sample stop is a retry (section 1). |
| T10. Report a platform bug | 4 / 0 / 0 / 1 / 2 | 4 / 0 / 0 / 1 / 2 | 0 | |
| T11. Pause a workflow | 3 / 0 / 0 / 1 / 3 | 3 / 0 / 0 / 1 / 3 | 0 | The access review is Planned and hidden by default (I2), so another workflow is paused. |
| T12. Delete a workflow | 4 / 0 / 0 / 1 / 3 | 5 / 0 / 0 / 1 / 3 | +1 | Delete is last in More actions, after a divider (spec 9). |
| T13. Change who approves | 4 / 0 / 2 / 2 / 3 | 4 / 0 / 2 / 2 / 3 | 0 | Named Approvers (ADR 0024) aren't built. The task exists only with Planned features shown, tagged Planned (I4). |
| T14. Change an agent in plain English | 5 / 0 / 0 / 1 / 2 | 6 / 0 / 0 / 1 / 2 | +1 | Changing an agent is Planned, so the task exists only with Planned features shown. The Agent library opens on "What it can do", so the agents are one tab away. |
| T15. Ask the team after a "can't" | 1 / 0 / 0 / 1 / 1 | 1 / 0 / 0 / 1 / 1 | 0 | |

All 15 tasks are still possible. T13 and T14 need Planned features shown, because the features behind them aren't built. Showing them as working by default would break the brief's rule against faking support.

## 5. New journeys in version 4

These have no version 3 baseline, because version 3 had no way to do them.

| Journey | Counts | What it shows |
|---|---|---|
| B-home. Act on a stop from Home | 1 / 0 / 0 / 1 / 2 | Needs you on Home with the action on the row. |
| ASK-status. "Check my workflows" | 1 / 0 / 0 / 0 / 1 | The Planner answers from live state. The answer changes after a retry (`planner-answers-live`). |
| ASK-why. "Why did the Morning new-ticket check stop?", then retry | 2 / 1 / 0 / 1 / 2 | The Planner gives the troubleshooter's answer and the retry in the chat. |
| ASK-needs. "What needs me?" | 1 / 1 / 0 / 0 / 1 | The same count as Home and Workflows. |
| OFFLINE. No AI model | 1 / 0 / 0 / 0 / 2 | Home says agent workflows can't run without a model, in the built app's words, and offers one Connect a model button. |
| DOWN. Jira stops answering | 1 / 1 / 0 / 0 / 1 | The Planner says Jira isn't answering and offers to keep the request as a draft, so nothing is lost and nothing is set up on a system that's down. |
| PREVIEW. Planned features shown | 3 / 0 / 0 / 0 / 4 | Every planned part carries a Planned tag (`preview-tags-planned`). |
| KEYS-A. Scenario A by keyboard only | 19 key presses, 2 fields, 3 decisions | Every step is reachable with Tab and Enter, with visible focus. |
| KEYS-C. Scenario C by keyboard only | 12 key presses, 1 decision | Approve is reachable with visible focus. |
| H2. Discard a draft | 2 / 0 / 0 / 1 / 2 | Version 3 had no way to remove a draft. |

The keyboard journeys have no version 3 count, so they show reach, not improvement.

## 6. What got heavier

Version 4 is not lighter everywhere. Home on a normal week carries more.

| Home | Words | Controls |
|---|---|---|
| Version 3, normal week | 61 | 6 |
| Version 4, normal week | 92 | 10 |
| Version 3, day one | 122 | |
| Version 4, day one | 114 | 5 |

The extra words and controls on a normal week are Needs you and the suggestions drawn from what is going on. They let B-home take 1 click instead of 3. Home keeps one primary button in every state (`home-one-primary`). Whether the busier Home is easier to scan, or just busier, is a question for real users.

Seven counts rose by one click (C-self, H, T1, T4, T5, T8, T12; T14 also needs Planned features shown). Each is explained above. Four of them buy safety or truth: T8 (no approving in Teams), H and T12 (Delete behind a divider), and T5 (look the project up before adding it). Three are the cost of a lighter normal-week Home (C-self, T1, T4).

## 7. What a study with real users should measure

Everything above comes from automated checks. No support staff have used version 4. A study with CODESparks support Operators should come next. It should run scenarios A to H on both versions and measure:

- **Task success.** Did the person finish without help?
- **Time to finish.**
- **Errors.** Wrong turns, wrong taps and anything undone.
- **Confidence.** After each scenario, how sure they were that it did what they wanted.
- **Perceived effort.** For example, the Single Ease Question after each task.

It should also answer the questions the counts raised:

- Is Home on a normal week easier to scan, or only busier (section 6)?
- Do people find Delete inside More actions (H)?
- Do people understand the set-up card's sentence, and the "What needs a yes" line (A)?
- When the Planner offers only Ask the team (D), do people feel stuck, or well informed?
- Does Bob understand what will change and why before he approves (C)?
