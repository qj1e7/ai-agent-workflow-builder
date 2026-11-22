---
status: proposed
---

# One path to a workflow: three steps, four states and one approval rule

On 23 Nov 2026 the team lead chose a simpler core flow and approved its words as written. The prototype is `docs/design/simple-flow/prototype.html` and the sketch with the reasons is `docs/design/simple-flow/sketch.html`. For the core flow (how a request becomes a workflow, the states a workflow shows, and how approval is worded), they win where the chat-first sketch differs. The chat-first sketch stays the source of truth for everything else.

It amends ADR 0043 and how ADR 0051's drafter is reached. It doesn't change the approval gate, the safety checker or ADR 0052, whose look is paused.

## Context

A support person had to learn four overlapping ideas to do one job:

- **Three paths for one request.** A set-up card from our blocks, "Draft it as an n8n workflow", or the Software watchlist. Which one they got depended on things they couldn't see.
- **5 to 7 steps** to get a workflow running.
- **Three kinds of yes:** a yes for each write, a set-up yes for a flagged workflow, and the two Approvers of the access review.
- **Seven states:** Draft, On, Paused, Stopped, Needs a fix, Waiting for a yes and Held.

The team lead found the core flows "very messy and cannot be understood" (22 Nov).

## Decision

1. **Three steps: Describe, Check, Turn on.** Every request gets one card shape. Guesses are marked "I guessed" and can be changed in place. "Turn on" runs the test, which writes nothing, and turns the workflow on if it passes. A failed test leaves a Draft with one reason and one button.
2. **Four states: On, Paused, Draft and Needs you.** Needs you holds one reason and one button: Stopped (Open the run), Waiting for a yes (Open, for the Approvers who can say yes), or Needs a fix (See what to fix). Everyone else sees "On · waiting for Bob's yes". Held becomes a note on the workflow, such as "Carol is editing it in n8n". Done, Nothing new, Declined and Skipped are run results in Recent runs, not states. Home and the Workflows list show the same four, with Needs you first.
3. **One approval rule:** "Nothing is written until an Approver says yes." The same words everywhere. A flagged workflow's one-time check is one line on the same card and a Needs you for Approvers, not a separate path. The access review's two Approvers are the same rule with "two Approvers" written into it. As before, nobody decides inside Teams: the card opens the approval page.
4. **One noun: everything is a workflow.** A request to check one software gets its own release check workflow, with its own schedule and Jira project, even when that software is on the watchlist. The Software watchlist stays as one workflow that checks a list on one schedule, shown and handled like any other workflow.
5. **One path: the Planner picks how to build it.** It uses our blocks when they cover the task, and any n8n block when they don't (ADR 0051). The "Draft it as an n8n workflow" path goes. A quiet "Build it with any n8n block" link stays on the card. "Open in n8n" stays in view on every workflow page, so staff can still change, build and fix workflows in n8n. Only Explain and Versions move behind Details.

## Considered options

- **Keep the three paths and polish the words.** Rejected. The interface review showed the confusion comes from the paths, not the words.
- **Remove editing in n8n to simplify.** Rejected. The sponsor needs staff to fix workflows without a technical person.

## Consequences

- About 9 to 11 pull requests, in this order: steps, states and the rule (Portal), then one noun (backend), then one path (Planner and Portal).
- #350's answer for watched software, "Check all 5 every day at 9:00", is replaced by item 4. Until then it stays.
- Item 4 may move existing watchlist data. That waits for the team lead's OK before it runs.
