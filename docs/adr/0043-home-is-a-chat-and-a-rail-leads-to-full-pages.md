---
status: accepted
---

# Home is a chat, and a rail leads to full pages

The team lead accepted this decision on 12 Nov 2026, after all four redraw steps were merged (#204 to #208) and the spec and build plan followed them (#210).

This amends ADR 0037 and the AI-native redesign spec. It keeps the Planner's answers, the capability registry and the approval gate as they are, and changes where things sit and how a conversation continues.

## Context

On 10 Nov 2026 the team lead asked for a chat-first app: people talk to the Planner for everything, including checking and changing workflows. The same day an independent UX review tested prototype version 4 and a chat-first sketch with eight operator tasks (`docs/evidence/usability/2026-11-10-ux-review/`). It found:

- **Version 4 has the stronger engine.** The troubleshooter's answers, the honest "can't" answers and the approval page held up in every task.
- **Version 4 loses context.** Needs you disappears once you type, and opening a workflow leaves the conversation.
- **The Planner drops parts of a request silently.** In 3 of 8 tasks it dropped a part, such as "haven't been updated for 10 days", and still said "Nothing is unclear".
- **You can't change a workflow by saying so.** "Make it daily" made a new draft.
- **A declined approval's record says the tickets were created.**
- **The chat-first sketch has the better layout but nothing behind it.** Needs you stays pinned, cards update live, and things open beside the chat, but its word rules sent unrelated requests to the same card.

A third version of the sketch combined the two and offered three ways to browse: a rail, chips that drop lists into the chat, and a panel that stays open. The team lead chose the rail, then asked for its lists to open as full pages, with the chat only on Chat.

## Decision

- **Home is the chat, and it starts calm.** Before the first message, Home is as version 4 draws it: the Visor bot, the heading, the box, three suggestions, and Needs you rows under them. After the first message the box moves to the bottom and the conversation fills the page. The chat is still not the record. Every card is a live view of the same data the lists and pages use.
- **A rail replaces the tabs.** A slim column on the left holds three items: Chat, Workflows and Watchlist, each with a count. Workflows and Watchlist open as full pages, and the chat shows only on Chat. Going back to Chat returns the conversation where it was. Needs you sits at the top of the Workflows page, as version 4 has it. The Agent library moves into Settings as "How it works", because no daily task needs it. Teams, Settings and the signed-in person stay in the header. In a window 900 px wide or narrower, the rail is a bar across the top.
- **Where you came from decides how an item opens.**
  - **From the rail or a page:** a workflow, run, approval or software row opens as a full page, with Back.
  - **From a card in the chat:** it opens in a side panel beside the chat, so the conversation stays in view. Wider than 900 px, a card's answer may open its view in the panel by itself, such as the n8n blocks going in while the Planner builds. In a window 900 px wide or narrower, the panel covers the window with Close, and opens only when the person presses Open. A flow shows once: while a card's item is open in the panel, the card hides its own flow and its Open button, and both come back when the panel closes.
  - **From inside the side panel:** the panel shows one thing and keeps no history. A link inside it, such as "Open the run" on a workflow, opens a full page with Back to the chat, and the panel is still there on return. More details in the panel's bar does the same for what it shows. Actions such as Retry, Approve, Pause or changing the schedule stay in the panel, because they change something rather than go somewhere.
- **The side panel is a summary, and the full page adds the details.** The panel shows what the item is, its state and the next step, and the chat keeps the width. The panel widens only while the Planner builds, to show the n8n blocks going in. The full page adds what helps someone understand the item, and nothing for show:
  - **Workflow:** the panel shows the sentence, any problem with its fix, and the last and next run. The page adds the steps, the schedule editor, who says yes, recent runs, versions and Pause.
  - **Run:** the panel shows the state, the steps and the three answers, with Retry. The page adds the agents on each step and a timed log of what happened.
  - **Software:** the panel shows the version you run, the newest, and what checks it. The page adds what changed from the release notes, the upgrade ticket, when it was last checked, and the source.
  - **Approval:** the panel shows everything that will be written, what wasn't checked, and the decision. Only the AI's summary, when it was sent and why it came to this Approver wait for the page. An Approver never decides on a trimmed change.
  - **The rail's pages** carry more per row than a chat card. Workflows shows each one's last run. The Watchlist opens with a count line, such as "3 have a newer version · 1 can't be found", lists what needs action first, and names what checks each software.
- **Needs you stays pinned during a conversation.** One line at the top of the chat names the most urgent item, with Open and "N more". The list is grouped into Do now (stops, approvals) and Set up (keys, missing sources). `needs()` stays its one source. A "can't" answer never hides it.
- **Every part of a request shows what happened to it.** The set-up card lists each part with a tick, a cross and its reason, or a question. Code checks that every clause of the request landed in a part, and any clause left over becomes a cross saying "I didn't follow this part". While a part has a cross, the button says "Set up the part I can", and "Nothing is unclear" never shows. The card asks one question at a time, and a time is never guessed.
- **A workflow can be changed by asking.** "Make the React check run on Mondays only" gets an edit card. It shows only what changes, before and after, with Save change and Never mind. Saving publishes a new version, with Undo. In this first version the edit card changes the schedule. Other changes keep their editors on the workflow's page, where the schedule editor also stays.
- **A stopped run answers three questions on its card:** what happened, what was affected, and whether a retry is safe. Retry and Report to support sit under them.
- **The approval page adds three things.**
  - A "Not checked" line, such as security advisories the platform can't read yet.
  - Ask the requester a question. The request stays open while they answer.
  - An optional reason when declining.
  
  A declined record says Declined and shows no write, in every place it appears.
- **An Approver who can't set up workflows gets the box for questions.** It answers what waits for their yes and what they decided before. A request to set something up gets "Operators set up workflows." The rail's lists are read-only for them.
- **n8n views show only to people with n8n access.** Everyone else sees the plain steps.

The sketch (version 3 of the chat-first desktop sketch) shows all of this with sample data. It is throwaway, so this ADR records what it showed.

Nothing here changes the approval gate or the safety checker. Every write still waits for an Approver's yes in Teams, and nobody approves their own work. Asking the requester a question and giving a reason add no way to approve. They are messages and notes attached to the request.

## Considered options

- **Chips under the box drop lists into the chat.** This is the purest chat-first option, and the closest to the team lead's first idea. Each list stays in the thread, so checking workflows five times a day leaves five list cards to scroll past.
- **A panel that stays open on the right, with Needs you, Workflows and Watchlist tabs.** Everything is visible at once, but the chat narrows, the screen reads as a dashboard beside a chat, and on a phone the panel has nowhere to go.
- **Chat only: ask for everything, with no lists.** The cleanest screen. The review showed that scanning beats asking for overview tasks, and that occasional users need a place they can find without knowing what to type. It also breaks principle 10, "Not chat-only".
- **The rail's lists open beside the chat too.** The sketch tried this first. The lists and pages are squeezed into a column beside the chat, and the screen has three columns.
- **Full pages for everything, with Back to chat.** One rule, and the simplest to build. It loses the side-by-side view while the Planner builds or a run is fixed, which is where the review found version 4 costing effort.
- **A desktop app.** The rail, the chat and the side panel look like one, but the work runs on the server and approvals happen in Teams. An app installed on every NCS laptop needs IT approval and an update for every fix, adds more to maintain after handover, and leaves out the Approvers on their phones. The app stays on the web. If people want it in its own window, it can be installed from the browser or opened as a Teams tab, from the same code.
- **Keep version 4's tabs and add the pinned line and the side panel.** This was the review's first recommendation, and the smallest change. The team lead preferred a chat-first app. The rail keeps what the tabs gave, one tap to every list, in less space.

## Consequences

- **ADR 0037 changes in four places.**
  - "The chat is Home" was rejected there because urgent items scroll away and pinning them rebuilds Home inside the chat. The pinned line is one row, not Home again, and the rail keeps the lists one tap away.
  - "Changes happen where the thing lives" now allows asking for a schedule change in the chat.
  - The Approver-only Home gains the box, for questions only.
  - The menu becomes the rail.
- **The prototype is redrawn before the Portal changes.** Version 4, `docs/design/ai-native-redesign/prototype.html`, is redrawn in four steps, each checked like version 4 was (axe, keyboard, a narrow window, reduced motion):
  1. **The shell.** The rail with full pages for Workflows and the Watchlist, Home as a chat, the pinned Needs you line, and the side panel for items opened from the chat. The Agent library moves to Settings.
  2. **The Planner's answers.** Part marks on the set-up card, one question at a time, the edit card, status questions in any wording, and live cards.
  3. **Runs and approvals.** The three answers on a stopped run, the approval page's three additions, and the declined record.
  4. **Roles.** The Approver's box and n8n views for people with n8n access.

  On 11 Nov the team lead dropped the phone layout. The Portal is a responsive web view, from a narrow browser window to a wide screen, and approvals on a phone happen in Teams.

  Then the spec (`AI-NATIVE-UX-REDESIGN.md`, sections 3, 5 to 12 and 18) and `IMPLEMENTATION-PLAN.md` follow the redrawn prototype.
- **The agent runtime's answer grows.** The set-up card's parts must account for every clause of the request. The Planner gains an edit answer for an existing workflow. The evals' golden set adds paraphrases that must keep or flag each part, such as "haven't been updated for 10 days", so a lost part fails CI.
- **platform-api gains two things.** It serves a workflow change as a new published version, the same path the page's schedule editor uses. It keeps the requester's question and the decline reason with the approval request.
- **The principles hold.** The box is for intent, and the rail, chips and card buttons are faster than typing (principle 10). Home keeps its calm centred start (principle 11). The part marks enforce "no part of a request is dropped" (principle 4).
- **It is our judgement, not tested with users.** The same check as ADR 0037 applies. Give the redrawn prototype to 2 or 3 people outside the team with three tasks: start the morning, change a schedule by asking, and decline an approval with a reason.
