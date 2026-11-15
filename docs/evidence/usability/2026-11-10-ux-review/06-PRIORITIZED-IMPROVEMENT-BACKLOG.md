# 06. Prioritized improvement backlog

**How it's ranked:** by expected effect on what users actually achieve, highest first within each priority. Duplicates across the two prototypes are merged.

**Columns:**
- **Screen:** v4 is prototype version 4; sketch is the chat-first sketch.
- **Effort:** S is under a day, M is a few days, L is a sprint or more.
- **Impact:** H means it changes whether a task succeeds or is trusted; M means it changes the effort; L means polish.

## P0: critical (misleading, broken, wrong state, security)

| ID | Screen | Issue | Recommendation | Priority | Impact | Effort |
|---|---|---|---|---|---|---|
| UX-01 | v4 Home / set-up card | Parts of requests are dropped silently ("haven't been updated for 10 days", "important" and "my", "security issues"), and the card still says "Nothing is unclear" (`v4-A-02`, `v4-A-04`, `v4-F-02`, `v4-H-01`) | Show every part's fate on the card (✓ or ✗ with the reason). Block "Nothing is unclear" while any part is ✗, and change the primary button to "Set up the part I can do". In the prototype, widen the word rules (from code: "haven't been updated for", "security issues"). In the built app, add paraphrase cases to the AI tests that fail when a part is lost | P0 | H | M |
| UX-02 | v4 run page (declined) | After Bob declines: a green "Done" pill, a green tick on the gate, and the log line "Created MOCK-14, MOCK-15 and MOCK-16. Only the approved tickets were written." (`v4-D-07`; from code, line 2178 prints the skipped step's message) | Build the record from the decision. A "Declined" pill (not green "Done"), a declined mark on the gate, and no "Created" line. Add a check that a declined run never shows a write | P0 | H | S |
| UX-05 | sketch Home / chat | Keyword routing sends unrelated requests (A, E, G, H) to the same LangGraph card with confidence | Before taking chat-first further, port v4's answer kinds (Part I can do, Can't with an alternative, Refusal, Which software, Already listed) and the capability registry. Never show a card whose contents didn't come from the request | P0 | H | M |
| UX-03 | v4 Agent library > Tools | The request box crashes on its own suggested chip "Open a ticket in ServiceNow", on email and on delete requests (`TypeError … reading '0'`, `v4-agentlib-05`). Spec 12 says the tab has no request box | Remove the box and point to Home's Planner, or guard the empty key | P0 | M | S |
| UX-04 | v4 Software watchlist | "Use the new address" works by default for a 404 case the platform refuses, and points LangServe at a different project (`v4-watchlist-04`) | Show "GitHub can't find LangServe, and it doesn't say where it moved", with Remove and Ask the team. Offer the switch only when GitHub's redirect proves a rename | P0 | M | S |

## P1: high (major friction, poor discoverability, excess effort)

| ID | Screen | Issue | Recommendation | Priority | Impact | Effort |
|---|---|---|---|---|---|---|
| UX-06 | v4 and sketch Home | "Tell me what needs my attention today." is refused (v4) or gets the fallback (sketch). In v4 the refusal hides Needs you. "Is LangGraph up to date?" is also refused (`v4-B-02`, `chat-B-01`) | Recognise status questions in any wording (not matched only as the whole message). A refusal never hides Needs you, and off-topic replies end with "Meanwhile, N things need you" | P1 | H | S |
| UX-08 | v4 Planner | It can't edit an existing workflow by talking. Three phrasings created new drafts, and one reversed the request into a Jira "Monday summary" (`v4-E-01`, `v4-E-03`) | Add an edit answer: find the named workflow, show a before-and-after card, Save with Undo, and ask which one when unclear | P1 | H | M |
| UX-11 | v4 approval page | No way to ask the requester a question. No decline reason. Doesn't say what wasn't checked: security advisories, and 3 of the 4 projects it couldn't read go unnamed (`v4-D-04`) | Add "Ask Carol a question" (the request keeps waiting), an optional decline reason, and a "Not checked" line | P1 | H | M |
| UX-10 | v4 Planner | An ambiguous request gets a 4-choice form named "Weekly summary" with no schedule. Follow-ups start new cards (`v4-F-02`, `v4-F-04`) | Ask one question about the biggest unknown, show the unsupported meanings as ✗ lines, and let follow-ups fill the open card | P1 | H | M |
| UX-12 | v4 Home | Needs you is hidden during a conversation. 2 of 5 items appear only on Workflows. "Some things need you." doesn't say what (`v4-B-01`) | Pin a one-line Needs you strip during the conversation (from the sketch). Group the items into Do now and Setup. Name the top item in the greeting line | P1 | M | S |
| UX-09 | v4 workflow page | After weekly is changed to daily, the name, purpose and ticket window stay weekly (`v4-E-05`, `v4-E-07`) | When how often it runs changes, offer the matching window and name changes in the same editor | P1 | H | S |
| UX-07 | v4 Home chip | "Which software has a newer version?" answers "There are 14 software on the Software watchlist." (`v4-inv-07`) | Name the 3, with versions and the waiting approval, plus Review and decide | P1 | M | S |
| UX-13 | v4 Settings | One Operator alone removed two other Approvers' roles. Adding needs a second person, but removing doesn't (`v4-D-14`) | Removing an Approver role also needs another Approver's confirmation, and is logged | P1 | H | S |
| UX-14 | v4 Software watchlist | Add software saved a whole sentence as the software name (`v4-H-05`) | Pull out the name, or ask "Did you mean Kubernetes?" | P1 | M | S |
| UX-15 | v4 Teams, Settings, Planner | What Teams does is described 3 ways ("approval requests only", "Sends approval requests to Approvers", "approval requests, run outcomes and requests for the team") | One sentence from the registry everywhere | P1 | M | S |

## P2: medium (secondary usability, consistency, navigation)

| ID | Screen | Issue | Recommendation | Priority | Impact | Effort |
|---|---|---|---|---|---|---|
| UX-17 | v4 run page, Planner, Settings | Internal words shown to Operators: "Pick agents", "Approval gate", "Show what each agent did", "Those details don't reach the agents yet", the model ID | "Chose who helps", "Waiting for a yes", "Show the details", "I can't see that yet". Keep the model ID in Settings only | P2 | M | S |
| UX-18 | v4, all screens at 390 px | Controls under 44 px on every screen (Retry the run 110×34, Review and decide 147×34, set-up drop-downs 29 px tall) | At least 44 px tall for every primary and row action at narrow widths | P2 | M | S |
| UX-20 | v4 Agent library | It's a top-level tab for an admin area. "Tools 2" disagrees with the agent cards. "What it can do" leaves out Read Jira and Sum up. Agent "Last run" is out of date | Move it to Settings > How it works, and read every list from the one registry | P2 | M | S |
| UX-24 | sketch | The "In n8n" tab and editor show blocks, IF and versions to every Operator | Show them only to people with the maintainer setting | P2 | M | S |
| UX-22 | sketch side panel | "Change" for the schedule and "Run now" are toasts. The n8n editor only changes the time | Use v4's schedule editor in the panel | P2 | M | S |
| UX-19 | v4 run page, workflow page, Workflows | Only the newest recent run opens. Run now is shown, then refused. Retry is shown while Jira is down. The "Show what each agent did" choice isn't kept. "Yes." appears in a one-liner | Every row opens its run. Disable buttons and show the reason next to them. Remember the choice for the visit. Rewrite the one-liner | P2 | M | S |
| UX-16 | v4 Home | Home says it's about software versions, yet it builds Jira summary workflows (A) | Decide the Phase 1 scope and say it consistently in "What can you do?" and in replies | P2 | M | S |
| UX-21 | v4 Software watchlist | Bob is shown Check now. Bob's day-one page tells him to add software | Role-aware controls and text | P2 | L | S |
| UX-23 | sketch | The brand mark contrast is 2.75:1. The n8n canvas `svg role="img"` contains focusable blocks. On the hero, the chips come before the box in Tab order | A darker mark, `role="group"` with labelled buttons, and a DOM order that matches the layout | P2 | M | S |

## P3: low (cosmetic, optional)

| ID | Screen | Issue | Recommendation | Priority | Impact | Effort |
|---|---|---|---|---|---|---|
| UX-25 | v4 various | "in mock" in lower case in a ticket title. "Sent Tue 27 Oct, 9:12" after the frozen 9:10. A double full stop in the toast. "Alice and Carol, who can't approve them" | Fix the text | P3 | L | S |
| UX-26 | v4 Planner | After "Set that up", the earlier primary button stays active above the new card | Make earlier answers' buttons quiet once a card exists | P3 | L | S |

## Suggested order
1. **Before the 27 Nov demo:** the bugs that would embarrass a live demo or mislead the sponsor are all S effort and in the prototype or built app. They are UX-02, UX-03, UX-04, UX-07, UX-06 and the prototype half of UX-01 (widening the word rules).
2. **Right after:** the understanding work in the built Planner (UX-01 fully, UX-08, UX-10) and the approval additions (UX-11, UX-13). These need the AI tests and, for UX-11, an ADR, because they touch the approval path.
3. **With the chat-first move:** the pinned strip and side panel (UX-12, section 1 of 05), then UX-05, UX-22, UX-23 and UX-24 on the sketch.
