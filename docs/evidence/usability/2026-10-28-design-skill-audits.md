# Design skill audits of the prototype, 28 Oct 2026

Four published design skills reviewed the clickable prototype, [`docs/design/portal-routines/prototype.html`](../../design/portal-routines/prototype.html). Each review read the code and drove the page in Chrome at desktop and phone widths. The fixes then went in one skill at a time, in this order.

| Skill | Source | What it found | What changed |
|---|---|---|---|
| ux-heuristics | `wondelai/skills` | Score 6/10. 14 findings, 4 of them major. | 13 fixed. Not re-scored. |
| interaction-design | `wshobson/agents` | 12 findings, 4 of them high. | 11 fixed, and part of 1. |
| accessibility (WCAG 2.2 AA) | `addyosmani/web-quality-skills` | axe: 34 problems under 2 rules across 92 runs. 14 findings. | All 14 fixed. axe now finds none. |
| n8n-workflow-patterns | `czlonkowski/n8n-skills` | 4 prototype findings and 11 design proposals. | 2 prototype changes. The proposals are drafted into ADRs 0026 and 0027. |

A fifth skill, `vercel-react-best-practices`, was not run. The prototype is plain JavaScript, so the skill has nothing to check there. It applies to the Portal, which already uses React 19 with Vite.

## What changed in the prototype

**Usability (ux-heuristics)**
- A run that needs you opens at the decision, with the run already drawn. **Replay the run** plays it again. A run you just started, and **Watch**, still play live.
- When the Planner sends a task to the Software watchlist, it says which word made it think so. **No, set it up as a new workflow** carries on when it guessed wrong.
- A declined test run leaves a record: its status, the run, Recent runs, Teams, and a Home row for the person who ran it.
- Browser Back and Forward move between pages.
- The Software watchlist names its workflow, "Keep our software up to date", and so does its Home row.
- A workflow's page names its agents. Each name opens the agent.
- On a phone, the watchlist table stacks, so status and actions stay in view.
- Changing someone's Operator role offers Undo. Approver changes don't, because a new Approver still needs a second Approver to confirm.
- Step 2 of New workflow explains the chip colours in words, not only in a tooltip.
- A workflow opened in n8n gets a **Changes in n8n** history, and the person who has it can **Give it back**.
- Plainer words where a run stopped after an n8n edit, and in the note on platform agents.
- **How it works** stays on Home after the first day.
- Not changed: the phone header's icons. The accessibility audit confirmed that each one has a name.

**Motion (interaction-design)**
- On the run line, a step lights up when the line reaches it, not before. Its message arrives at the same moment.
- A redraw waits while a button is held down, so no click is lost.
- A redraw keeps open sections open and keeps where you scrolled. Toasts leave without redrawing the page.
- A double-click no longer opens a dialog and closes it again.
- During a run, the page follows the newest message until you scroll. After Approve or Decline, focus goes to what the approval gate said.
- Planning that carries on after you leave New workflow no longer moves focus or scrolls.
- Loops don't restart on each redraw, and one-off checks play once.
- A toast stays longer when it has more to read, and never covers a dialog's buttons.
- The caret stays where you put it while you type in a search box.
- With reduced motion, the AI troubleshooter's wrench keeps its angle.
- The Teams panel's backdrop fades in. Going from one dialog to another, such as an agent to its tool, swaps the content instead of closing and opening.
- Not done: motion for opening and closing "More approval options".

**Accessibility (WCAG 2.2 AA)**
- After any action, keyboard focus stays on the control. If the control is gone, focus moves to the nearest one in the same place, else to the heading. It never drops to the top of the page. Busy buttons, such as "Plan it", keep focus while they work.
- A focused control is never hidden under the sticky header or the phone tab bar.
- A toast with Undo has no time limit. It stays until you do something else, leave the page or press Escape. A screen reader is told where the Undo is.
- Agent faces that carry meaning are read out by name. The Planner's messages say who is speaking.
- The run line reads as a clean list. Each step says whether it is done, now or not reached yet.
- The New workflow heading says which step you are on. A search says how many results it found.
- Form fields, search boxes and the run line's open dots have edges with at least 3:1 contrast.
- The chosen tab or speed shows with a dark ring, not just a faint shade.
- The Teams panel's Close button shows its focus on purple.
- Long buttons and project names wrap at 320 px.
- Each role checkbox and each History button says whose or which it is.
- Tab stays inside a dialog, even when a section in it is closed.
- There is a skip link, and the page title names the page.
- An idle agent breathes once when it appears, then holds still. Nothing loops at rest.

**n8n (n8n-workflow-patterns)**
- The Open in n8n dialog draws one "Ask for a yes" and "Make the approved changes" pair for each change a workflow makes. The access review shows both, and the second says it needs 2 people in order.
- The dialog says what staff will find in n8n (our blocks, not n8n's own Jira, web or code steps), what happens if Ask for a yes goes missing, and that trying it in n8n is a real run.
- Not done: Open in n8n on the Software watchlist. The audit asked for it because the software check is the MVP demo, but the team lead decided against it earlier on 28 Oct.
- Not done: a "Made in n8n" workflow on the Workflows page. It needs a new sample workflow.

## Where the skills disagreed

The interaction-design audit asked for a new toast to wait while one with Undo shows. The accessibility audit asked for Undo to have no time limit. The prototype follows accessibility: a toast with Undo stays until the next action, so nothing needs to wait.

## Verification

All checks ran in Chrome through Playwright against the edited prototype.
- **axe** (wcag2a, wcag2aa, wcag21aa, wcag22aa) on 46 screens and dialogs at 1440 and 390 wide: 0 problems in 92 runs, down from 34.
- **Focus:** after each of the 33 actions in the audit's focus script, focus stayed on a control or a heading, never the page body. Before the fix, 13 of them dropped focus to the page body.
- **Dialog Tab loop:** Tab wraps inside the agent dialog with a closed section.
- **Reflow:** the stopped and waiting run pages fit 320 px with no sideways scroll.
- **Smoke tests:** 14 usability checks, 10 motion checks and 3 n8n checks pass, with no console errors.

## n8n design proposals, now drafted into ADRs 0026 and 0027

The n8n audit checked the design in [`n8n-maintained-workflows.md`](../../design/n8n-maintained-workflows.md) and ADRs 0026 and 0027 against common n8n workflow patterns.

On 28 Oct the team lead asked for all 11 proposals, and the data nodes, to go into both ADRs and the design note. Both ADRs stay `proposed`. The ADRs differ from the wording below in two places:
- **Item 4:** our API makes the check on a run's first call from any of our nodes, not one fixed first node, because staff can reorder nodes. It backs up ADR 0024, which already ends a request before the next scheduled run. So the check only stops runs started some other way, such as Run now.
- **Item 9:** the Sticky Note links to the workflow's Approvers in the Portal instead of naming them. Approvers live in our API, so changing them publishes nothing in n8n, and a name in the note would go stale.

1. **The error path breaks under the allow list (high).** Our failure reporter, `run_failure_reporter`, is an Error Trigger followed by an HTTP Request node. The `NODES_INCLUDE` allow list blocks HTTP Request, so failed runs would go unreported while the daily check still says the workflow is published. Proposal: a "Report a failure" node in our pack, and a daily check that sends a test failure all the way through.
2. **The Webhook trigger is a way out of n8n (high).** n8n's Webhook node is on the allow list. It can reply with the last node's data, and it needs no sign-in by default. Proposal: replace it with our own trigger that only accepts calls signed by our API, and test that in a P7 run.
3. **A run started by hand in n8n has no clear starter (high).** A run counts as the work of whoever published the version it used. A hand-started draft has no publisher, so someone could approve their own run. Proposal: our nodes pass on how the run started, and a hand-started run counts as the work of whoever holds the workflow in n8n.
4. **Two runs of one workflow could wait for a yes at the same time.** Proposal: our first node refuses to start while another run of that workflow is waiting.
5. **Schedules would run on New York time.** n8n defaults to America/New_York. Proposal: set `GENERIC_TIMEZONE=Asia/Singapore` in our image, and check each workflow's time zone on publish.
6. **Duplicates across runs, and partial writes.** Proposal: each proposed action carries a key, such as the GitHub issue link, so a rerun never writes it twice. Make the approved changes reports "2 of 3 created" and retries only what failed.
7. **Nothing to propose.** Proposal: when a proposal is empty, Ask for a yes asks nobody and leaves by a "Nothing to change" exit.
8. **Check a version before it runs.** Proposal: our first node asks our API whether this version passed the check, rather than checking a minute after it is published.
9. **The n8n workflow should explain itself.** Proposal: the Planner names each node by what it does and adds a Sticky Note covering the purpose, the Approvers and what is safe to change.
10. **Long lists (Phase 2).** Proposal: Read pages through results up to a cap, and Propose a change adds one action per item, with a size limit.
11. **Retries and rate limits.** Proposal: our API answers a repeated call for the same run and node with the first result, and reads wait for a short rate-limit reset.

**The allow list against "native nodes first".** The skill prefers n8n's own data nodes, and our allow list blocks them. Some only reshape data already in the run and can't reach another system: Filter, Switch, Edit Fields, Limit, Remove Duplicates, Summarize, Aggregate, Split Out, Compare Datasets, Date & Time, Loop Over Items and Stop and Error. They could join the list without weakening the write check, after a P7 test that tries to get data out through each one. Wait should stay off, because its webhook mode accepts outside calls.
