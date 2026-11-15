# 02. Screen-by-screen audit

This audit covers two prototypes:
- **Prototype version 4 (v4).** `docs/design/ai-native-redesign/prototype.html` on `origin/main`, tested 10 Nov 2026.
- **The chat-first desktop sketch (sketch).** Published 10 Nov.

Every observation comes from the hands-on logs:
- `evidence/v4-hands-on.md`, with screenshots in `shots/v4/`;
- `evidence/chat-first-hands-on.md`, with screenshots in `shots/chat/`.

"(from code)" marks anything read from source rather than seen. Backlog IDs (UX-nn) point to `06-PRIORITIZED-IMPROVEMENT-BACKLOG.md`.

**Priority:** P0 critical, P1 high, P2 medium, P3 low. **Effort:** S is under a day, M is a few days, L is a sprint or more.

---

## Part 1: Prototype version 4

### 1.1 Header and menu (every screen)

**Purpose.** The way to Home, Workflows, Software watchlist, Agent library, the Teams drawer and Settings. Bob, an Approver only, gets no Agent library.

**Hierarchy.** Plain labels. Workflows carries an amber count ("5"), and Teams shows "1". Below 390 px it becomes a bottom tab bar.

**Navigation.** Every destination works. The skip link works. It takes 9 Tab presses to reach the Home box, or 3 with the skip link.

**AI-native opportunities.** The count on Workflows is the only signal outside Home that something needs you. That's good.

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| The Agent library is a top-level tab, but it's an admin area. It shows agents, tools and an internal registry | `v4-agentlib-01..03` | Puts technical concepts in the daily menu for every Operator | Move it under Settings as "How it works", and keep the agent chips on workflow pages as the way in. Fewer daily choices, and nothing is lost (UX-20) | P2 | S |
| Bob typing `#agents` gets Home's content while the address still says `#agents` | Inventory 1.1 | A confusing address when sharing links | Send Bob to `#home` | P3 | S |

### 1.2 Home

**Purpose.** The front door: the Planner box, suggestions, and Needs you. It's essential and is the right place to start.

**Hierarchy.** For Alice in a normal week (`v4-home-01`):
- the Visor bot;
- "Good morning! Alice";
- "Some things need you.";
- the box ("Ask about your software versions, or name software to watch");
- three chips;
- Needs you, showing 3 of 5 rows, with a primary action on the first.

Bob gets his approval and nothing else (`v4-home-05`). The no-model state is honest (`v4-inv-04`).

**Navigation.** One click from a Needs you row to the fix. "See all on Workflows" shows the other 2.

**AI-native.** It answers well when the wording matches its rules. It fails on natural phrasings (Scenario B).

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| "Tell me what needs my attention today." gets "I can't help with that here." and Needs you disappears | `v4-B-02` | The most common daily question is refused, and the answer to it is hidden | Understand any "what needs me / my attention / anything to do" wording. A refusal must never hide Needs you (UX-06) | P1 | S |
| Needs you is hidden while a conversation is on screen | Spec 5.1, `v4-B-02` | The moment she starts typing, she loses sight of what's urgent | Keep a one-line pinned Needs you strip above the thread, as the sketch does (UX-12) | P1 | S |
| 2 of the 5 items (the LangServe address, the GitHub key) only show on Workflows. "Some things need you." doesn't say what | `v4-B-01` | She has to click to learn what the rest are | Say it in the greeting line: "3 things need you here, and 2 setup items are on Workflows" (UX-12) | P2 | S |
| The chip "Which software has a newer version?" answers "There are 14 software on the Software watchlist." | `v4-inv-07` | Home's own suggestion doesn't answer itself, which costs trust on day one | Answer with the names, versions and the waiting approval (UX-07) | P1 | S |
| Home says it's about software versions (the placeholder and day-one heading), yet it accepts Jira summary requests and builds them (Scenario A) | `v4-home-03`, `v4-A-02` | A mixed message about what the product is for | Pick one. Either say "I can also sum up Jira tickets" in "What can you do?", or answer Jira requests with the honest frozen-builder line (UX-16) | P2 | S |

### 1.3 Planner answers and the set-up card

**Purpose.** It turns a sentence into a workflow, or into an honest "can't". This is the core of the AI-native promise.

**Hierarchy.** The reply line, then the card:
- a sentence with chips;
- When;
- What needs a yes;
- How this workflow works, collapsed;
- one primary **Turn it on**.

The footer names what's missing ("2 choices left: which tickets and the Jira project."). When nothing is missing it says "Nothing is unclear. Turn it on when you're ready."

**What works.** The answer kinds Can't with an alternative, Refusal and Part I can do are clear when they fire. G passed, and the A and H control phrasings gave honest answers.

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| Parts of a request are dropped silently: "haven't been updated for 10 days" (A), "important" and "my" (F), "identify… security issues" (H). Then the card says "Nothing is unclear" | `v4-A-02`, `v4-A-04`, `v4-F-02`, `v4-H-01`. From code: the rules match "not updated for" but not "haven't been updated for", and "vulnerab…" but not "security issues" | She turns on a workflow that doesn't do what she asked, and feels sure it does ("High, and wrongly so") | Account for every part. The card lists any part it left out, and "Nothing is unclear" is only allowed when every part is handled. In the built app, test paraphrases in the AI tests (UX-01) | P0 | M |
| Asking to change an existing workflow starts a new draft. "Run the software check every day instead of every Monday" gave a Jira "Monday summary" card | `v4-E-01`, `v4-E-03` | She can't edit by talking, and drafts pile up | Add an "edit" answer: name the existing workflow, show before and after, Save with Undo (UX-08) | P1 | M |
| An ambiguous request gets a 4-choice form named "Weekly summary" with no schedule. Follow-up messages start new cards | `v4-F-02`, `v4-F-04` | It feels like configuration, not help | Ask one question about the biggest unknown, and let follow-ups fill the open card (UX-10) | P1 | M |
| After "Set that up" in G, the old answer's primary button stays active above the new card | `v4-G-03` | Two primary actions on screen | Make the earlier answer's buttons quiet once a card exists (UX-26) | P3 | S |

### 1.4 Workflows

**Purpose.** Everything at once:
- Needs you, in full;
- Drafts;
- Waiting on others;
- Following up;
- All workflows, with search and filters.

It's essential for scanning and for experienced users.

**Hierarchy.** Needs you comes first, with the first item as a card that has Retry. Rows have one action each. Search is hidden behind a magnifier.

**Navigation.** Everything works. Discard has Undo (`v4-inv-01`). Following up shows the support case stages (`v4-C-10`).

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| The troubleshooter's one-liner reads "…last seen working today, 9:00. Yes. A retry reads…". The "Yes." answers a question that isn't shown | Broken item 20 | It reads like a glitch | Turn the four answers into one sentence: "Safe to retry: a retry reads the tickets again, and its ticket still waits for a yes." (UX-19) | P3 | S |
| The row "Keep our software up to date" opens the watchlist page, not a workflow page | Inventory 1.4 | Inconsistent, but useful | Keep it. Label the row "Software watchlist" so where it goes is clear | P3 | S |

### 1.5 Workflow page

**Purpose.** One workflow's status, schedule, approval rule and recent runs, plus Pause and More actions (Run now, Change schedule, Delete). It's essential.

**Hierarchy.**
- **Order:** status banner with one action, then Schedule, Approval, Recent activity, and Technical details (collapsed). That's the right order.
- **Delete:** asks to confirm and names what's kept (`v4-inv-03`).
- **Bob:** gets a read-only version.

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| After changing weekly to daily, the name ("Weekly…"), the purpose ("…this week, every Friday") and the ticket range ("closed… this week") stay. Each daily run would sum up the whole week again | `v4-E-05`, `v4-E-07` | She thinks it's done, but the output is wrong and the page contradicts itself | When how often it runs changes, offer the matching changes in the same editor ("Also sum up since the last run, and rename it Daily…?") (UX-09) | P1 | S/M |
| Only the newest Recent activity row opens a run | Broken item 18 | Older runs can't be checked | Make every row open its run (UX-19) | P2 | S |
| More actions > Run now is shown, then refused, on the platform-bug workflow | Broken item 17 | A dead-end button | Hide it or disable it with the reason next to it (UX-19) | P2 | S |

### 1.6 Run page

**Purpose.** What happened in a run. When stopped, it shows the troubleshooter's four answers. When waiting, it shows the approval panel.

**Hierarchy.** The station strip, then the four answers (What happened, What was affected, Can it be fixed safely, What to do), then **Retry the run**, then "Show what each agent did" (collapsed). It's honest about Jira being down: "Not yet. A retry would stop in the same place…" (`v4-C-07`).

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| After a decline, the headline says "Declined, nothing was written", but the pill is a green "Done", the gate has a green tick, and the log says "Created MOCK-14, MOCK-15 and MOCK-16. Only the approved tickets were written." | `v4-D-07`. From code, line 2178: the Jira step is marked skipped on a decline but still prints its message | The audit record of a decision contradicts itself. An auditor or the sponsor would rightly stop trusting the log | Build log lines from the decision. A decline gets a neutral "Declined" pill, a declined mark on the gate, and no "Created" line (UX-02) | P0 | S |
| The station names "Pick agents" and "Approval gate" | Broken item 22 | Internal words in the most-watched view | "Chose who helps" and "Waiting for a yes" (UX-17) | P2 | S |
| On Jira-down, the troubleshooter says not to retry yet but still shows a Retry button | `v4-C-07` | A mixed signal (the button gives a polite toast) | Change it to "Retry when Jira is back", disabled, with the reason next to it (UX-19) | P3 | S |
| The "Show what each agent did" choice doesn't hold between runs | Broken item 19 | A small annoyance | Remember it for the visit, as spec 10.2 says (UX-19) | P3 | S |

### 1.7 Approval (run page, waiting for a yes) and the Teams drawer

**Purpose.** Bob decides on writes. The Teams card only links to the page, which is correct (ADR 0036). Self-approval was blocked on every path tried (Scenario D).

**Hierarchy.** What will change (one card per ticket, with Release notes and Project page links), Why, Who asked, What happens, Your part, then Approve and Decline. "This is exactly what will be written, and nothing else." That's the strongest screen in v4.

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| No way to ask the requester a question. Decline asks for no reason | `v4-D-04` | Bob's only options are yes or no. When unsure he either approves blind or blocks the work with no explanation | Add "Ask Carol a question" (the request keeps waiting, and the question goes to the requester), plus an optional reason on Decline (UX-11) | P1 | M |
| It doesn't say what wasn't checked. Log4j 2.14.1 (a version with a well-known critical flaw) shows only "Security fixes and bug fixes". "Read 10 of 14" explains only Grafana | `v4-D-04`, broken item 16 | Bob may approve thinking security was considered | Add a "Not checked" line: "Security advisories: not available yet. Couldn't read: LangServe, PostgreSQL, Python." (UX-11) | P1 | S |
| What Teams does is described 3 different ways (drawer, Settings, a Planner answer) | Broken item 15 | Small, but it erodes trust in "one source per fact" | One sentence from the registry everywhere (UX-15) | P2 | S |

### 1.8 Software watchlist

**Purpose.** The Phase 1 job: watch the software the team runs, with one approval a week. It's essential.

**Hierarchy.** Needs attention, then Software we watch (14 rows: We run, Newest, Status), then Add software, then How it's checked. The registry sources are shown honestly (GitHub Ready, the rest "Not yet").

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| "Use the new address" works by default and points LangServe at `langchain-ai/langchain`, a different project. Spec 11 says the platform refuses this 404 case | `v4-watchlist-04` | The prototype shows an unbuilt and wrong action as working, which breaks principle 5 | Show "GitHub can't find LangServe, and it doesn't say where it moved", with Remove and Ask the team (UX-04) | P0 | S |
| Add software accepts a whole sentence as the name | `v4-H-05` | A junk row, and a double full stop in the toast | Pull out the name, or ask "Did you mean Kubernetes?" (UX-14) | P1 | S |
| Bob is shown Check now. His day-one page tells him to add software, which he can't do | Broken item 17 | Dead ends for Approvers | Role-aware text and controls (UX-21) | P2 | S |
| Touch targets for History (55×32) and Remove (61×32) | Section 3 | Hard to tap on a phone | Make them at least 44 px tall (UX-18) | P2 | S |

### 1.9 Agent library

**Purpose.** Admin transparency: the capability registry, agents and tools. Not something an Operator needs daily.

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| The Tools tab's request box crashes on its own suggested chip ("Open a ticket in ServiceNow"), on email, and on delete requests. Spec 12 says the tab has no request box | `v4-agentlib-05`. From code: `toolAskPanel` reads `TOOLS[r.key][0]` with no key | A broken interaction, and the only page errors in the session | Remove the box and send people to Home, or guard the empty key (UX-03) | P0 | S |
| "Tools 2", but the Jira reader uses "Search Jira" and "Read a Jira ticket". "What it can do" leaves out Read Jira and Sum up. Agent "Last run" is out of date | Broken items 13, 14 | Admin views disagree with the rest of the app | Read every list from one registry (UX-20) | P2 | S |

### 1.10 Settings

**Purpose.** Connections, people and roles, the AI model. Admin only.

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| Alice alone removed Bob's and Siti's Approver roles. Adding an Approver needs a second person, but removing one doesn't. The floor of 2 held | `v4-D-14` | One person can shrink who gives oversight. The rule isn't the same both ways | Removing an Approver also needs another Approver's confirmation (UX-13) | P1 | S |
| The AI model shows "AI Singapore gateway · claude-sonnet-5-5 / API key ending 7f" | Inventory 1.9 | Fine for admins, but technical | Keep it here, never in the operator's view (UX-17) | P3 | S |

### 1.11 Visual design and usability (all v4 screens)

**Strengths:**
- **Consistent tokens:** one typeface (Atkinson Hyperlegible Next), flat cards and a calm palette.
- **Status not by colour alone:** status is shown by pill text as well as colour.
- **Real states:** empty, Planner thinking and offline states all exist.
- **Accessibility checks:**
  - axe found 0 violations on 7 screens;
  - the focus ring shows on every Tab stop;
  - reduced motion stops every loop (0 infinite animations);
  - nothing scrolls sideways at 390 px.

**Weaknesses:**
- **Touch targets:** every screen at 390 px has controls under 44 px, including the main actions: Retry the run is 34 px tall and Review and decide 34 px (UX-18).
- **Density:** the watchlist table and the approval page get long on a phone.
- **Internal words:** "Pick agents", "Approval gate" and "Show what each agent did" (UX-17).
- **Small text errors:** "in mock" in lower case, a "Sent 9:12" after the frozen 9:10, a double full stop, and "Alice and Carol, who can't approve them" (UX-25).
- **Feedback after actions:** good. Toasts name the result and offer Undo where it's possible.

---

## Part 2: Chat-first desktop sketch

### 2.1 Home hero

**Purpose.** It's the same front door as v4: the Planner, the box, three chips, and Needs you rows underneath.

**Hierarchy.** The one stopped workflow is visible with 0 clicks (`chat-A-01`).

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| Typed requests go to keyword rules. Unrelated requests (stale Jira tickets, Teams posting, Kubernetes security, change a schedule) all return the same LangGraph set-up card | `chat-A-02`, `chat-G-01`, `chat-H-01`, `chat-E-01` | A confident wrong answer, which is worse than v4's honest "can't" | Port v4's answer kinds and registry before anything else (UX-05) | P0 | M |
| "Tell me what needs my attention today." gets the fallback line | `chat-B-01` | Same as v4's UX-06 | UX-06 | P1 | S |
| The chips come before the box in Tab order, but sit visually below it | Tab-order log | Focus order doesn't match the layout (WCAG 2.4.3) | Put the DOM order to match the layout (UX-23) | P2 | S |
| The "AI" brand mark has 2.75:1 contrast | axe | Fails WCAG AA | Darker blue or a dark mark (UX-23) | P3 | S |

### 2.2 Chat thread and live cards

**Purpose.** Answers arrive as cards that stay live. A retry in the side panel updates the chat card, the strip and the list together (`chat-C-02`). Needs you stays pinned as a strip during the conversation.

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| There's no workflow list unless you ask, and no Software watchlist at all | Inventory | Scanning and the Phase 1 job need a place you can open without typing | Keep Workflows and Software watchlist reachable from the header (see 05) | P1 | M |
| Role switching only happens from the demo bar | Inventory | Can't test Bob's real path | Sign-in role, as in v4 | P3 | S |

### 2.3 Side panel (workflow, live activity, approval, building)

**Purpose.** Opens what you clicked beside the chat, so you keep your place. This is the sketch's best idea for the desktop.

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| "Change" under When it runs and "Run now" only show a toast. The n8n editor only changes the time, never how often | `chat-E-02`, `chat-E-03` | There's no working way to change a schedule | Use v4's schedule editor inside the panel (UX-22) | P2 | S |
| The run view has no "What was affected" and no Report to support | `chat-C-01` | Weaker than v4's troubleshooter | Use v4's four answers and Report to support | P1 | S |
| The approval has no way to ask a question, no consequences line, and no "nothing is written before your yes" | `chat-D-02` | Same gap as v4, and missing v4's strengths | Use v4's approval panel, plus UX-11 | P1 | S |

### 2.4 The "In n8n" views and the mock n8n editor

**Purpose.** Lets staff see and change the n8n workflow, which is what the sponsor wants. It also shows how safety is kept when the yes block is deleted (`Writes refused` card).

| Problem | Evidence | Impact | Improvement, and why it's better | P | Effort |
|---|---|---|---|---|---|
| Every Operator sees n8n words (IF, Our block, blocks, versions) | `chat-E-03` | Technical concepts the persona doesn't need (v4 hides n8n unless Planned features are shown) | Put the n8n tab behind a "For people who maintain workflows" setting or role (UX-24) | P2 | S |
| The canvas `svg role="img"` contains focusable blocks | axe nested-interactive | Screen readers miss the controls | Make the canvas `role="group"` with labelled buttons (UX-23) | P2 | S |
