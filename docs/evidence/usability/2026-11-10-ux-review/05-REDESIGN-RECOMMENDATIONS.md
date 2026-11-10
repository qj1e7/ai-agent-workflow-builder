# 05. Redesign recommendations

**The direction in one line:** keep version 4's (v4's) understanding and honesty rules, add three patterns from the chat-first sketch, and fix how the Planner reads requests before changing any layout.

Most failures in the tests were in what the AI understood, not in where things sit on the screen:
- **v4 failures:** A, E, F and H failed or half-failed because a request was misread or part of it was dropped.
- **Sketch failures:** they came from having no understanding at all.

A new layout won't fix that. A layout change is worth making only where the tests showed navigation costing effort: B (Needs you hidden during chat) and leaving the conversation to see a workflow.

## 1. Navigation and information architecture

### What the tests say about today's v4 menu

| Destination | Needed? | Evidence |
|---|---|---|
| Home (Planner and Needs you) | Yes. It's the main workspace | Every scenario started here |
| Workflows (Needs you in full, Drafts, Following up, all workflows) | Yes, for scanning, and for experienced and occasional users | B needed it to see all 5 items. C's support case is tracked here |
| Software watchlist | Yes, while software versioning is the Phase 1 job | H, the weekly approval, the 14-row status table |
| Agent library | Not daily. It's an admin and transparency area | No scenario needed it. Its Tools tab crashed, and its lists disagree with the rest of the app |
| Teams drawer, Settings | Yes (practice Teams card; admin) | D, C2 |

Are people forced to pick a module before saying what they want? No, because Home takes intent first. They are forced to leave Home to see something in full: Workflows for all of Needs you, or a workflow page to change its schedule.

### Recommended structure

```
Header:  Home  ·  Workflows  ·  Software watchlist          Teams  ·  Settings  ·  Alice
                                                                      └ How it works (was Agent library)
Desktop: opening a workflow, run or approval from Home shows it in a side panel beside the chat.
         The same item opened from Workflows or by link shows full page, as today.
Phone:   the side panel opens as a full-screen sheet with Close.
```

| Change | Why | Who benefits | Discoverability risk | How capability stays reachable |
|---|---|---|---|---|
| Move the Agent library into Settings as "How it works" | No daily task needs it, and it shows internal concepts (agents, tools, registry) | Operators: one less tab, no technical vocabulary in the menu | Admins and the professor's demo may look for "agents" | Settings > How it works. The agent chips on workflow pages still open agent dialogs. The live activity view still shows the agents |
| Open items from Home in a side panel on desktop (from the sketch) | Keeps her place in the conversation and saves the back-and-forth | Operators on desktop, the most common sponsor setup | None. It's additive | Deep links and the Workflows page still open the full page |
| Keep Needs you pinned during a conversation (from the sketch) | B: the list disappeared once she typed | Everyone | None | The same `needs()` source |
| Keep the Workflows and Software watchlist tabs | Scanning a list beats asking a question for overview tasks. Occasional users need a place they can find without typing | Experienced and occasional users | n/a | n/a |
| Don't move to chat-only | Chat-only failed B, E, G and H in the sketch, and it hides state you need at a glance | Everyone | n/a | n/a |

## 2. Redesigned Home

**Before you type:**
- the Visor bot, the greeting, and a line that names the top item ("FastAPI release check stopped at 8:00. 2 more things need you.");
- the box;
- three chips chosen from state;
- **all** Needs you items, grouped: "Do now" (stops, approvals) and "Setup" (keys, addresses). Up to 3 rows each, with See all.

**Once you type:**
- the thread;
- a one-line pinned Needs you strip above it, with Open;
- the box at the bottom.

**A refusal never hides Needs you,** and an off-topic answer ends with "Meanwhile, 3 things need you."

**Chips must answer themselves.** "Which software has a newer version?" answers "Log4j core, LangGraph and FastAPI. One approval covers their 3 upgrade tickets." with Review and decide.

## 3. Improved AI interaction patterns

1. **Account for every part.** The Planner splits a request into parts and shows each part's fate on the card:
   ```
   ✓ Every Friday at 9:00
   ✓ Jira tickets in project [MOCK ▾]
   ✗ Not updated for 10 days: I can't see update dates yet. Ask the team
   ✓ Prepare a summary, put in one new Jira ticket after a yes
   ```
   - The footer can't say "Nothing is unclear" while there's a ✗.
   - The primary button becomes **Set up the part I can do**.
   - In the built app, every paraphrase in the AI tests must keep or flag each part (UX-01).
2. **Ask one question, then fill the card.** "Monitor my important Jira issues." gets "Which Jira project?" with chips for the projects she uses. The unsupported meanings of "important" (priority) and "my" (assignee) are shown as ✗ lines. Follow-ups fill the same card (UX-10).
3. **Edit, don't duplicate.** "Make the weekly summary daily" gets an **edit card** on the existing workflow (UX-08, UX-09):
   ```
   Weekly closed-ticket summary
   When:     Every Friday 16:00  →  Every day 16:00
   Tickets:  closed this week    →  closed since the last run
   Name:     Weekly closed-ticket summary  →  Daily closed-ticket summary   [keep old name]
   [Save change]  Never mind
   ```
   If more than one workflow matches, it asks which.
4. **Understand status questions in any wording:** what needs me, is X up to date, which software is behind. They're answered from platform data by code, with the model only choosing which kind of answer (UX-06).
5. **Keep chips and buttons wherever they're faster.** Retry, Approve, Turn it on and Review and decide stay as buttons. The tests show 1 to 2 clicks beat typing for all of them.

## 4. Simplified workflow creation
- Keep v4's set-up card. It's the right size: one sentence with chips, When, What needs a yes, and one primary button.
- Add the part-by-part fate list (pattern 1).
- Rename the card from the request: "Friday stale-ticket summary", not "Friday summary".
- On desktop, show the "building" view in the side panel. In the sketch, the live activity view for building shows the helpers and the safety checker adding the yes. Keep the n8n canvas under "For people who maintain workflows".

## 5. Simplified workflow monitoring
- Home's Needs you plus the pinned strip covers the daily check (B).
- Workflows stays as the full list for scanning.
- A workflow opened from Home appears in the side panel with its status, next run, schedule, recent runs (each opens its run) and versions with Roll back (from the sketch).

## 6. Improved failure recovery
- Keep v4's four answers and Report to support exactly.
- When Jira is still down, change Retry to a disabled "Retry when Jira is back", with the reason next to it.
- Rewrite the one-line version on Workflows as one sentence.

## 7. Improved approval experience
Keep v4's panel, and add:
- **"Not checked":** "Security advisories aren't available yet. Couldn't read LangServe, PostgreSQL and Python this week."
- **Ask Carol a question.** It goes to the requester, the request keeps waiting, and the answer shows on the panel.
- **An optional reason on Decline.** It's shown to the requester and in the record.
- **A correct record after a decline:** a "Declined" pill, a declined mark on the gate, and no "Created" line.

Approve and Decline stay buttons on our page, never in Teams and never by typed words.

## 8. Progressive disclosure of advanced features

| Layer | Who | What |
|---|---|---|
| Always | Operators and Approvers | Needs you, the Planner, cards, Approve and Decline, Retry, Pause |
| One click | Operators | How this workflow works, Show what each agent did, Versions, the schedule editor |
| Maintainers | People with the maintainer setting | "In n8n" tab, Open in n8n editor (the sketch's flow, with its "Writes refused" safety card) |
| Admin | Settings | Connections, People and permissions (with the confirmed role removal), AI model, How it works (agents, tools, registry) |

## 9. Preserving essential functions

Nothing tested is removed:
- Every v4 answer kind, the troubleshooter, Report to support, Drafts, Following up, the watchlist, Teams, Settings and the test controls all stay.
- The Agent library moves under Settings.
- The sketch's side panel, pinned strip, live cards and n8n views are added, the n8n views behind the maintainer layer.

## 10. Before and after: the five most important tasks

| Task | Before (v4 as tested) | After (recommended) |
|---|---|---|
| **1. Set up a workflow** (A) | Type, then a card that silently drops "not updated for 10 days" and says "Nothing is unclear", then 2 selects, then Turn it on: 5 interactions, wrong workflow | Type, then a card with the ✗ line "not updated for 10 days: can't yet", then pick the project, then **Set up the part I can do** or Ask the team: 3 interactions, and she knows exactly what she's getting |
| **2. What needs me today** (B) | Typing is refused and the list disappears, so New chat, then See all on Workflows: 4 interactions | Home lists all items with 0 clicks. Typing any wording answers with the same rows, and the strip stays pinned: 0 to 2 interactions |
| **3. Fix a stopped workflow** (C) | Home row, then Retry: 1 interaction (already good). Reading the details means leaving Home | The same 1 interaction. Details open in the side panel beside the chat. Jira-down shows a disabled Retry with the reason |
| **4. Approve or decline** (D) | Review and decide, then Approve: 2 interactions. A decline leaves a "Done" pill and a "Created" log line. Bob can't ask anything | 2 interactions to approve. Decline has an optional reason and a correct record. "Ask Carol a question" keeps it waiting. A "Not checked" line sets expectations |
| **5. Change weekly to daily** (E) | Talking makes new drafts. The page path is 5 interactions and leaves "Weekly… every Friday" text | "Make the weekly summary daily", then an edit card showing before and after (schedule, ticket window, name), then Save: 3 interactions, and the page agrees with itself |
