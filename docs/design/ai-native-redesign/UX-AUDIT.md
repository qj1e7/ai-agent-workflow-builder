# UX audit of the 6 Nov prototype (version 3)

This audit is the first deliverable of the AI-native redesign. The redesign spec (`AI-NATIVE-UX-REDESIGN.md`) and the version 4 prototype build on it. It audits `docs/design/portal-routines/prototype.html` at commit `afde35f`, and it checks each claim against the built app's code.

The product philosophy it tests against: "Users should focus on what they want to accomplish, not how to operate the system. AI should handle workflow complexity, while the interface presents only what users need to understand, decide, or approve."

## 1. Scope and method

### What was inspected

- **The prototype**, version 3. `docs/design/portal-routines/prototype.html` at `afde35f` (4,518 lines). The working copy has no changes to it (`git diff --stat afde35f -- docs/design/portal-routines/prototype.html` printed nothing). Every `prototype.html:N` below is a line in that file.
- **The design record.** The design note `docs/design/portal-routines.md` and ADR 0037. ADRs 0024, 0025 and 0036 for approvals, the watchlist and Teams.
- **The handover package** in `docs/handover/AI-SYSTEM-HANDOVER/`. Mostly `03b-PROTOTYPE-UI-INVENTORY.md` (sections 4, 6 and 8), `03-UI-UX-INVENTORY.md`, `04-USER-JOURNEYS.md`, `08-LIMITATIONS-AND-TECHNICAL-DEBT.md` and `10-INDEPENDENT-REVIEW-BRIEF.md`. In short references below, "03b 4.4" means section 4.4 of `03b-PROTOTYPE-UI-INVENTORY.md`.
- **Screenshots** in `docs/handover/AI-SYSTEM-HANDOVER/screenshots/prototype/`, cited by file name.
- **Built-app code**, to say what works today. `portal/src/shell/routes.tsx`, `agent-runtime/src/agent_runtime/planner.py`, `abilities.py`, `tools.py`, `jira.py`, `card_runner.py`, `platform-api/src/platform_api/orchestration/write_actions.py`, `jira.py` and `jira_rest.py`.

### How

1. **Code reading.** Every screen's render function and every action handler named in this audit was read. Line numbers were checked against the file.
2. **Two throwaway Playwright probes**, kept outside the repository. They drive the prototype with the Portal's own Playwright at 1280 px and 390 px wide with reduced motion. They ran axe-core (`portal/node_modules/axe-core`, rule sets WCAG 2.0 A and AA, 2.1 AA, 2.2 AA) on eight states. Their printed results are quoted where a finding uses them, marked "probe".
3. **AI-evaluator judgement.** Statements about what a user would find hard are this audit's judgement, read from code and screenshots. They are marked "judgement".

### What the evidence cannot show

No real user has tested version 3. The usability evidence so far is AI evaluators and team judgement (`10-INDEPENDENT-REVIEW-BRIEF.md`, "What the evidence can and can't tell you"). No screen reader was used. No real AI model was scored on the Planner's job (`08` L02).

The prototype's Planner is keyword rules, not a model (`prototype.html:1424-1426`). When a probe shows the mock misreading a request, the finding is about the design gap the misreading exposes, not about the word rules.

### Three layers, kept apart

| Layer | What it is | How a finding names it |
|---|---|---|
| **Built app** | The deployed React and FastAPI app in `portal/`, `platform-api/`, `agent-runtime/`. | "built app" |
| **Prototype** | The clickable HTML design target. Scripted, connected to nothing. | "prototype only" |
| **Planned** | Proposed ADRs (0024, 0025, 0026, 0027, 0036, 0037) and the design note's "Later" items. Nothing implements them. | "planned ADR" when a change needs a new or amended ADR |

A finding whose change needs backend work before the built app can follow it is marked "backend dependency".

### Ratings

- **Priority.** P0 is correctness and trust, where the screen says something false or hides a fact a person needs before they agree to something. P1 is core usability of a daily task. P2 is advanced usability. P3 is future architecture.
- **Effort.** S, M or L to change the prototype, as an **estimate** by this audit. S is under half a day, M is up to two days, L is more. Backend effort is named in the change text where it matters.

## 2. Summary

60 findings. 8 are P0, 24 are P1, 24 are P2 and 4 are P3.

The top five by user impact:

1. **X1. Nothing tells a person which features work today.** The Planner's "I can" list is honest, but the sample workflows, the Tools tab, Settings and the Software watchlist show planned features as working. I1, I2, I4 and I9 are the symptoms. One capability registry with visible states fixes them together.
2. **X2. The front door's first example asks for data the agents cannot read.** "List bug tickets with no update for 10 days" needs a last-update date and an issue type. The built Jira tool returns neither.
3. **SC1. A green "From your words" mark holds words the person never said.** Example 1 drops "bug", adds "with their owners", and marks both parts green.
4. **TM1. The practice Teams message has Approve and Decline.** Approvers learn a path that does not exist in the built app or in ADR 0036.
5. **HM1. An Operator who is also an Approver sees nothing on Home when a yes is waiting.** The only sign is a count on the Workflows tab.

## 3. Index of findings

| ID | Current screen | Finding | Priority | Effort (estimate) | Layer |
|---|---|---|---|---|---|
| X1 | Every screen | No capability registry; planned features look ready | P0 | M | prototype, backend dependency, planned ADR |
| X2 | Home, set-up card, Agent library | Jira reads promise fields the built tool doesn't return | P0 | S | prototype, backend dependency |
| X3 | Every screen | "A yes in Teams" says the decision happens in Teams | P1 | S | prototype, built app |
| X4 | Test controls | No way to see "today" versus "planned" | P1 | M | prototype only |
| X5 | Test controls, phone | The test controls button covers content on phones | P2 | S | prototype only |
| X6 | Test controls | Carol (Operator only) can't be chosen | P2 | S | prototype only |
| X7 | Teams, run page | "Workflow Builder" and "AI Workflow Builder" both used | P3 | S | prototype only |
| I1 | Home, Workflows, Tools, Settings | Teams messages are "Not yet" but samples send them | P0 | M | prototype, built app |
| I2 | Home, Workflows, Tools | Planner reads Jira and GitHub releases; samples read more | P0 | M | prototype only |
| I3 | Home, Tools, agent dialog | One tool request, two answers | P1 | S | prototype, planned ADR |
| I4 | Set-up card, watchlist card, workflow page | Two approval rules side by side | P0 | M | prototype, planned ADR |
| I5 | Home, Settings, Workflows | Day one has no model, yet the Planner works | P1 | S | prototype, backend dependency |
| I6 | Agent library, set-up card | Library says the Planner drafts agents; Home never does | P2 | S | prototype only |
| I7 | Report dialog, n8n dialog | Two texts point to old places | P2 | S | prototype only |
| I8 | Set-up card | The open-answers count goes stale | P1 | S | prototype only |
| I9 | Software watchlist, Planner | Watchlist shows ADR 0025 sources and vulnerability checks as working | P0 | M | prototype, built app |
| HM1 | Home (Operator) | A waiting yes is invisible on an Operator-Approver's Home | P1 | M | prototype, planned ADR |
| HM2 | Home (Operator) | "I can" lines are abstract verbs, not tasks | P1 | S | prototype, backend dependency |
| HM3 | Home (Operator) | The Planner can't answer questions about your workflows | P1 | M | prototype, backend dependency, planned ADR |
| HM4 | Home (Operator) | The Planner's reply is not announced to screen readers | P1 | S | prototype only |
| HM5 | Home and every page | "Nothing changes without a yes" repeated on six screens | P2 | S | prototype only |
| PL1 | Planner answers | Can't-do answers use system words | P1 | S | prototype only |
| PL2 | Planner answers | "Ask the team" follow-up lives in the Agent library | P2 | S | prototype, backend dependency |
| SC1 | Set-up card | Green marks hold words the person never said | P0 | S | prototype, backend dependency |
| SC2 | Set-up card | Five sections and a plan of agents for one yes | P1 | M | prototype, planned ADR |
| SC3 | Set-up card | One sentence of five-colour chips and inline lists | P1 | M | prototype only |
| SC4 | Set-up card, Workflows | Drafts can't be discarded; questions become drafts | P1 | S | prototype, backend dependency |
| SC5 | Set-up card, Workflows | A second workflow turned on from Home replaces the first | P1 | M | prototype only |
| SC6 | Set-up card, schedule editors | "Every month" is offered but not built | P1 | S | prototype, backend dependency |
| SC7 | Set-up card done box | "Open in n8n" at the moment of success | P2 | S | prototype only |
| SC8 | Set-up card | The Jira project is always asked, even with one project | P2 | S | prototype, backend dependency |
| WF1 | Workflows | Each item that needs you shows twice | P1 | S | prototype only |
| WF2 | Workflows | Needs you mixes approvals with platform upkeep | P2 | S | prototype only |
| WF3 | Workflows | Search and filters for four workflows | P2 | S | prototype only |
| WF4 | Workflows | "Start in n8n" under the main list | P2 | S | prototype only |
| WF5 | Workflows | Every row carries an "On" pill | P2 | S | prototype only |
| WF6 | Workflows (Approver only) | Bob sees the same Needs you on Home and Workflows | P2 | S | prototype only |
| WF7 | Workflows | Row faces with no names | P3 | S | prototype only |
| WP1 | Workflow page | Five Operator buttons before the facts | P1 | S | prototype only |
| WP2 | Workflow page | No way to change what a workflow does | P1 | M | prototype, backend dependency |
| WP3 | Workflow page | Only the newest run can be opened | P2 | S | prototype only |
| RN1 | Run page | Replay and a speed switch on every run | P1 | S | prototype only |
| RN2 | Run page, phone | The decision sits under the whole story | P1 | M | prototype, built app |
| RN3 | Run page | Who was asked is said twice | P2 | S | prototype only |
| RN4 | Run page, Teams drawer | Decline takes no reason | P2 | M | prototype, backend dependency |
| RN5 | Run page | All or nothing approval | P3 | L | planned ADR |
| RN6 | Run page, Workflows | Fix it and Report to support look built | P1 | S | prototype only |
| RN7 | Run page | "Pick agents" in runs where nothing is picked | P2 | S | prototype, built app |
| SW1 | Software watchlist | Adding software asks for registry formats | P1 | M | prototype, backend dependency |
| SW2 | Software watchlist | Six sections, most of them planned | P2 | S | prototype only |
| SW3 | Software watchlist | A wrong source can't be changed on the row | P2 | S | prototype, backend dependency |
| AL1 | Agent library | Reference page in the Operator's main menu | P2 | S | prototype, planned ADR |
| AL2 | Agent library | Changing behaviour starts far from the problem | P2 | S | prototype only |
| ST1 | Settings | Connections and AI usage are planned but look built | P1 | S | prototype only |
| ST2 | Settings, Home | The AI model tab needs a technical person, with no handoff | P2 | S | prototype only |
| ST3 | Settings | Add a person has no work email | P2 | S | prototype only |
| TM1 | Teams drawer, Workflows | Approve and Decline in the Teams message | P0 | S | prototype only |
| TM2 | Header | Two "needs you" counts, and a practice Teams button | P1 | S | prototype only |
| TM3 | Teams drawer | Messages @mention people | P2 | S | prototype only |
| TM4 | Teams drawer | Channel name differs from the built app | P3 | S | prototype only |

## 4. Findings by screen

Each finding gives the user problem, the evidence, the proposed change and the expected benefit. The first line after the title is priority, effort (an estimate) and layer.

### 4.1 Cross-screen findings on capability, wording and test controls

#### X1. Nothing tells a person which features work today

P0 · M · prototype, backend dependency, planned ADR

- *User problem.* An Operator reads "Not yet: Send Teams messages" on Home, then sees a sample workflow that sends Teams messages and a Tools tab that lists "Post in Teams" as Working. They can't tell what the platform will really do, so they can't trust the Planner's "I can" list either. A reviewer can't tell the target design from today's product.
- *Evidence.* The prototype keeps five separate hard-coded lists that disagree. `ABILITIES` (`prototype.html:2743-2752`), `TOOLS` (`2946-2960`, 12 tools, every one Working except a drafted one, `toolState` at `2993`), `CONNS` (`2847-2851`), `SOURCES` (`1554`) and `LIBRARY` (`2995-3026`). The built app has the same split: `ABILITIES` in `agent-runtime/src/agent_runtime/abilities.py:52-78`, `TOOLS` in `tools.py:141-173`, the write registry in `platform-api/src/platform_api/orchestration/jira.py:233`, the watchlist lead in `portal/src/shell/routes.tsx:62`. 03b Table 1.1 lists ten prototype features that depend on proposed ADRs and show as working. I1, I2, I4 and I9 are four symptoms.
- *Proposed change.* One capability registry, as the lead chose. Each entry is one thing the platform can do, in plain words, with its system, whether it reads or writes, its approval rule and one state: **Ready**, **Needs setup**, **Planned**, **Unsupported** or **Temporarily down**. The Planner's answers, Home's "I can / Not yet", the Tools tab, Settings Connections and the watchlist sources all read from it. Ready shows plainly. Needs setup says who can fix it. Planned shows only when the "Show planned features" test control is on (X4), always with a Planned tag. Unsupported is what the Planner refuses. Temporarily down comes from the last health check. In the built app this extends ADR 0037's route for the "I can" and "Not yet" lists, so ADR 0037's Consequences need one amendment.
- *Expected benefit.* The Planner can't promise what a page contradicts. One list to update when a tool lands. Reviewers can switch between today and the target.

#### X2. The Jira reads the prototype promises need fields the built tool doesn't return

P0 · S · prototype, backend dependency

- *User problem.* An Operator taps the first example, "Every Friday, list bug tickets with no update for 10 days", and turns it on. The built agents can't see when a ticket was last updated, its type or its owner, so the list they produce would be a guess. Nothing on screen warns them.
- *Evidence.* In the built app, a ticket the agent sees has key, project, title, status, created date, done date and body (`agent-runtime/src/agent_runtime/jira.py:20-29`). The search result sent to the model keeps key, title, status, created and done dates (`card_runner.py:438-447`). Search filters are words, status ("To Do" or "Done") and a done-since date (`tools.py:51-61`). platform-api fetches Jira's `updated` field (`platform-api/src/platform_api/orchestration/jira_rest.py:39-41`) but uses it only as a fallback done date and drops it (`jira_rest.py:255-279`). The Planner's own prompt uses "Bug tickets in MOCK with no update for 10 days" as its example (`planner.py:317`). The abilities check is verb-based (`abilities.py:52-60`), so it passes this request. The prototype makes the same promise in the example (`prototype.html:2079`), the ticket label "Open tickets with no update for N days" (`1428`), "List them, with their owners" (`1431`), "List them, with each one's owner and last update" (`1519`), owners in the preview (`1544`), "Reads one ticket's status, owner and last update" (`2980`) and the "no update for 30 days" suggestion (`2497`). ADR 0037 line 13 says each example "is something the platform can do today".
- *Proposed change.* Pick one. Either add the last-update date, issue type and assignee to the read tool (a small backend change, since the adapter already fetches `updated`, and type and assignee are two more fields), or change the example and the ticket choices to what works today: "Every Monday, list tickets still open after 10 days" (created date and status) and "Sum up the tickets we closed this week". Whichever is chosen, the registry's Jira entry lists the fields it can read, and the set-up card's choices come from it.
- *Expected benefit.* The flagship example does what it says. The Planner stops accepting requests the agents can only guess at.

#### X3. "A yes in Teams" tells people the decision happens in Teams

P1 · S · prototype, built app

- *User problem.* An Approver reads "waits for a yes in Teams" and "Who says yes ... in Teams", then looks for an Approve button in Teams. In the built app and in ADR 0036 the Teams card has only an Open button, and the decision happens on the approval page under their own sign-in.
- *Evidence.* `prototype.html:2757` ("Anything that changes data waits for a yes in Teams"), `2549` (refusal), `2607` (set-up card), `2586` (done box), `1742` and `1749-1750` ("asked in Teams"), `1373`. For the built app, `08` L19 lists "Who says yes: Any Approver except you, in Teams" as a promise the app doesn't keep. ADR 0036, first section.
- *Proposed change.* Say once, on the set-up card's "What needs a yes" section and on the approval page, "Approvers get a message in Teams, and say yes here." Everywhere else, "a yes" or "an Approver's yes". Keep "approvals in Teams" in sponsor-facing text, since the request does arrive in Teams.
- *Expected benefit.* Approvers know where to act. The built app and the prototype say the same thing.

#### X4. No way to see "today" versus "planned"

P1 · M · prototype only

- *User problem.* A reviewer, or the team deciding what to build first, can't see which screens are today's product. Everything planned is always on.
- *Evidence.* 03b section 1 ("Not one consistent today") and Table 1.1. Test controls offer Show, Act as, Make something happen, About and Start over only (`prototype.html:3450-3486`).
- *Proposed change.* Two test controls, as the lead chose. "Show planned features" (off by default) brings back named Approvers, the extra watchlist sources, tool drafting, Connections, AI usage, Report to support and n8n, each with a Planned tag. "Show screens the Portal doesn't have yet" outlines those screens with a dashed frame and the ADR that would add them.
- *Expected benefit.* The default prototype is an honest picture of version 4 on today's backend. The target stays reviewable.

#### X5. The test controls button covers content on phones

P2 · S · prototype only

- *User problem.* On a phone, the dark "Test controls" pill sits above the tab bar, on top of the page.
- *Evidence.* CSS `prototype.html:905` and `921` (moved to 70 px above the bottom at 900 px and below). In the probe's screenshot at 390 px, the pill covers "Expires Thu 5 Nov 2026" on Workflows.
- *Proposed change.* On phones, show a small round icon button, or put the controls behind the person chip.
- *Expected benefit.* Phone review sees the real layout.

#### X6. Carol (Operator only) can't be chosen

P2 · S · prototype only

- *User problem.* Nobody can review what an Operator who isn't an Approver sees, for example a Workflows page with no approvals and the lock on every request.
- *Evidence.* Act as offers Alice and Bob only (`prototype.html:3471-3473`). Carol exists (`1138`). 03b section 2.
- *Proposed change.* Add Carol to Act as.
- *Expected benefit.* All three role combinations can be reviewed.

#### X7. "Workflow Builder" and "AI Workflow Builder" both used

P3 · S · prototype only

- *User problem.* Small, but the app's name changes between the header and its messages.
- *Evidence.* Header "AI Workflow Builder" (`prototype.html:1974`). Teams messages from "Workflow Builder" with "Open in Workflow Builder" (`3358-3360`). Run chat speaker "Workflow Builder" (`1892`). The built card says "Open in AI Workflow Builder" (ADR 0036).
- *Proposed change.* "AI Workflow Builder" everywhere.
- *Expected benefit.* One name, as decided on 27 Oct (design note line 398).

### 4.2 The nine known inconsistencies (03b section 8)

Each has its own finding, with current behaviour taken from code.

#### I1. Teams messages are "Not yet", but samples, tools and Settings send them

P0 · M · prototype, built app

- *User problem.* The Planner refuses "post a summary in Teams", yet the Operator's own sample workflow sends Teams messages and the Tools tab says posting works.
- *Current behaviour in code.* In the prototype, Home lists "Send Teams messages" under Not yet (`prototype.html:2748`), and two answers refuse Teams posting (`2494`, `2496`). Stale ticket nudge "asks their owners in Teams" (`1345`), its last step "Send the messages in Teams" (`1417`), its history "2 messages sent, approved by Bob" (`2280`). The access review asks managers in Teams (`1346`, `1418`). "Post in Teams" is a Working tool (`2957`, `2993`, log `2985`), used by the Message writer and Access checker (`3014`, `3023`). Settings says Teams "Posts approval requests and messages, and receives Approvers' answers" (`2850`). More promised Teams messages: support updates (`2048`, `3389`), the AI usage alert (`2931`), "gets a Teams message that you didn't confirm it" (`4142`). This audit found three more than 03b lists: "Approvers can say yes to changes in Jira, Teams and other systems" (`2009`), "gets a Teams message that you said not now" (`3237`) and "they've had a message in Teams" (`3238`). The built app has four tools, and none posts in Teams (`tools.py:141-173`). The only registered write is Jira create ticket (`platform-api/.../orchestration/jira.py:233`), and the safety checker denies any other write (`write_actions.py:152-154`). Teams carries only the approval card (ADR 0036).
- *Proposed change.* Registry entry "Post a message in Teams", state Planned (X1). Rewrite the samples to today's tools. "Stale ticket nudge" becomes "Stale ticket list", which puts the list in one Jira ticket. The access review moves behind the planned-features control. Connections says Teams "Posts approval requests. Approvers decide in the app." Support updates appear on Workflows, not in Teams.
- *Expected benefit.* The Planner and the rest of the app agree.

#### I2. The Planner reads Jira and GitHub releases; the samples read more

P0 · M · prototype only

- *User problem.* The Planner marks GitLab red ("I can only read Jira and GitHub so far"), while a sample workflow reads GitLab and Entra ID and removes access.
- *Current behaviour in code.* In the prototype, "I can" lists Jira and releases only (`prototype.html:2744-2747`). GitLab and Entra ID requests get a red part (`1462-1463`, `1498`). The access review reads Entra ID, the admin tools and GitLab (`1346`), with "Change someone's access" Working (`2958`, `2986`). Morning bug report check reads GitHub issues (`2948`, `2976`). In the built app, the tools are `github.read_releases`, `jira.search`, `jira.read_ticket` and `jira.create_ticket` (`tools.py:141-173`; `contract.py`, `ToolId`). No GitHub issues, Entra ID or GitLab reader exists. X2 adds that even the Jira read is narrower than the prototype shows.
- *Proposed change.* Sample workflows on today's tools only: the software check (GitHub releases), a weekly closed-ticket summary and a stale-ticket list. GitHub issues, Entra ID and GitLab become Planned registry entries.
- *Expected benefit.* Every sample is something a new Operator could set up today.

#### I3. One tool request gets two different answers

P1 · S · prototype, planned ADR

- *User problem.* On Home the Planner says a component tool is "the team's decision". On the Tools tab and in the Ticket writer's dialog it offers to draft that tool for an Approver's OK. The Operator learns that asking somewhere else gets a different rule.
- *Current behaviour in code.* Home answers with `ANSWERS.tool` (`prototype.html:2547`). The Tools tab drafts through `askForTool` (`3193`), `toolAskPanel` (`3206`) and `toolDialog` (`3236`). The Ticket writer's dialog drafts through `CHANGES.writer` (`3052`) and `agentDialog` (`3292`). In the built app, tools are code the team builds (ADR 0023). No tool drafting exists. ADR 0037 line 25 says a drafted tool needs its own ADR, and until then the answer is Ask the team.
- *Proposed change.* One answer from the registry everywhere: "That needs a new tool. It's planned, and the team decides on new tools", with Ask the team. Tool drafting shows only with the planned-features control.
- *Expected benefit.* One rule wherever the person asks.

#### I4. Two approval rules side by side

P0 · M · prototype, planned ADR

- *User problem.* The set-up card says any Approver except you. The watchlist card and all four samples say "Bob, with Alice as backup", with waits and a stop time. An Operator can't tell who will be asked, and the sponsor sees a feature that isn't built.
- *Current behaviour in code.* In the prototype, the set-up card says "Any Approver on your team except you, in Teams." (`prototype.html:2607`). Watchlist card shows named Approvers (`2634`). Samples have named Approvers with backups and stop times (`BASE_APPR`, `1353-1358`). This audit found that even the prototype's "today's rule" is not today's, because a team-rule request stops at the next run (`req`, `1710-1712`; `timingText`, `1373`). In the built app, every step is "any Approver who is not a party", and a waiting request never expires (`08` R5; `orchestration/cards.py`, `AnyApprover()`; no escalation or expiry code). Two Approvers one after the other is built. ADR 0024 (named Approvers, backup, expiry) is proposed.
- *Proposed change.* Every sample uses today's rule, and the access review shows two Approvers in turn. "Who approves" reads "Any Approver on your team except the person who started it. It waits until someone answers." Named Approvers, backups and stop times return with the planned-features control, tagged ADR 0024.
- *Expected benefit.* The Operator knows who will be asked. The demo shows what the sponsor would get.

#### I5. Day one has no AI model, yet the Planner works

P1 · S · prototype, backend dependency

- *User problem.* A brand-new Operator types a task and gets a set-up card, though Settings says no model is connected. When they reach the built app, the same request fails. A brand-new user also sees "Workflows 1" for a key that is about to expire.
- *Current behaviour in code.* In the prototype, day one has no model ("can't plan new workflows", `prototype.html:2792`, `2814`). `plannerHome` (`2080`) and `ask` (`2684`) never check it. The GitHub key expires in 9 days from day one (`1327`, `2010`), and the probe printed "day one workflows badge: 1". In the built app, without a model, after 10 s, or on a broken answer, the read-back returns starter workflows with "No AI model is connected...", and the Portal stays on step 1 with chips that also need the model (`08` R4). ADR 0037 Consequences says the Planner should say it is offline and show what it can do and Ask the team.
- *Proposed change.* Add an offline state on Home. The Planner's face is stopped, and it says "I can't read new requests until an AI model is connected. Whoever looks after the platform can connect one in Settings." Examples and Ask the team stay. Day one starts with keys that are not expiring.
- *Expected benefit.* The first visit matches what a fresh install does. No false alarm on day one.

#### I6. The Agent library says the Planner drafts new agents; Home never does

P2 · S · prototype only

- *User problem.* The library promises a feature the Operator never sees. A reviewer can't see what a drafted agent would look like on the card.
- *Current behaviour in code.* In the prototype, the library says "New agents come from the Planner on Home..." (`prototype.html:3131`), the Planner's card says the same (`2996`). Every set-up card uses the Jira reader and Summary writer (`2593`), and the "New agent" tag (`2181`) is never set. In the built app, the Planner does draft new agent cards when no saved one fits, and saves them when the workflow is turned on (`04` J2 step 4). They can't be changed or removed afterwards (`08` L04).
- *Proposed change.* Keep the agents out of the Operator's way (SC2). In "How this workflow works", show a drafted agent with a New tag in one example. Change the library note to "The Planner adds an agent when a workflow needs one."
- *Expected benefit.* The claim and the screen agree, without adding agent ideas to the main path.

#### I7. Two texts still point to old places

P2 · S · prototype only

- *User problem.* After reporting a problem, the Operator is told to follow it on Home, where it never appears.
- *Current behaviour in code.* "You can also follow it on Home." (`prototype.html:3389`), while Following up is on Workflows (`2122`). "you won't see 'Check what I understood'" (`3426`) names the built app's step 2, which version 3 doesn't have.
- *Proposed change.* "You can follow it on Workflows." Drop the old step name.
- *Expected benefit.* No dead ends.

#### I8. The Planner's count of open answers goes stale

P1 · S · prototype only

- *User problem.* After choosing a time, the Operator sees "I need 2 more answers" above "1 choice left". Two numbers on one card disagree, at the moment they are deciding whether to trust it.
- *Current behaviour in code.* The sentence is computed once (`ANSWERS.setup.say`, `prototype.html:2542`, called at `2699`). The footer is recomputed on every redraw (`2609-2610`). After a time was chosen, the probe printed the Planner still saying "I need 2 more answers" while the footer said "1 choice left: the Jira project." Screenshot `planner-card.png`.
- *Proposed change.* As the lead chose, the count lives in one place, the card's footer, and stays current. The sentence says "Here's what I understood. I need a few answers from you." with no number.
- *Expected benefit.* One number, always right.

#### I9. The watchlist shows ADR 0025 sources and vulnerability checks as working

P0 · M · prototype, built app

- *User problem.* An Operator asks "tell me when Log4j has a critical vulnerability" and is told it is "checked every Monday for new versions and known vulnerabilities". Nothing checks vulnerabilities today. They would believe they are covered.
- *Current behaviour in code.* In the prototype, these show as working: the sources and vulnerability data (`prototype.html:1551-1621`), the run's agent messages (`1797-1799`), tools (`2949-2953`), the page lead "cross-checks versions, support dates and known vulnerabilities" (`2234`), the day-one empty state (`2246`), the source picker (`2251`), "where known vulnerabilities are checked too" (`2543`) and the already-listed answer (`2544`). In the probe, "Tell me when Log4j has a critical vulnerability" got the already-listed answer. The built app reads GitHub releases only. The built page says so ("Each check reads the newest release from GitHub", `portal/src/shell/routes.tsx:62`). But the built Planner sends vulnerability tasks to the watchlist (`planner.py:336-339`), and the abilities rule counts "vulnerability" as a release word (`abilities.py:34-40`), so the built app has the same overclaim at the front door.
- *Proposed change.* Watchlist samples on GitHub releases only. Registry entries "Check package registries", "Check support dates" and "Check known vulnerabilities", state Planned. The Planner says "I can watch for new releases on GitHub. Vulnerability checks are planned." with Ask the team. In the built app, drop "vulnerability" from the release words and the prompt rule until ADR 0025 lands.
- *Expected benefit.* No one thinks a security check runs when it doesn't.

### 4.3 Home for an Operator, the Planner's box

#### HM1. A waiting yes is invisible on an Operator-Approver's Home

P1 · M · prototype, planned ADR

- *User problem.* Alice is an Operator and an Approver. She opens the app, sees only the Planner's box, and misses that three upgrade tickets, one urgent, wait for her yes. The only sign is an amber "4" on the Workflows tab.
- *Evidence.* `plannerHome` renders the face, heading, box and examples only (`prototype.html:2080-2093`). The count sits on Workflows for Operators (`1964-1968`). 03b section 6 counts approve from Workflows at 3 clicks and approve from the Approver-only Home at 2. The probe printed Alice's Workflows badge 4 and Teams badge 1. The sponsor's first priority is "Nothing critical without approval" (design note line 53).
- *Proposed change.* As the lead chose, Home shows Needs you only when something needs action. A short strip above the box shows the most urgent item as one line with its button, and "and 3 more on Workflows". It shows nothing at all when nothing waits. The box stays the page's main control. This reverses part of ADR 0037 (see section 8).
- *Expected benefit.* Approving from Home takes 2 clicks instead of 3 (counted by this audit). Urgent items are seen first.

#### HM2. "I can" lines are abstract verbs, not tasks

P1 · S · prototype, backend dependency

- *User problem.* "Sum up what I find" and "Read Jira tickets" don't tell a support person what to type. The examples help, but only three show, and only on an empty chat.
- *Evidence.* `ABILITIES` (`prototype.html:2743-2752`). Examples (`2079`) show only when the chat is empty (`2089`). 03b 4.1 notes, as judgement, that nobody has tested whether a non-technical user knows what to type.
- *Proposed change.* Fed by the registry (X1). Each Ready line is a short task: "List tickets closed this week", "Watch a tool for new releases", each tappable to send it. Needs setup lines say who can set them up. Planned lines show as "Not yet".
- *Expected benefit.* Less typing and less guessing. The list never drifts from what works.

#### HM3. The Planner can't answer questions about your workflows

P1 · M · prototype, backend dependency, planned ADR

- *User problem.* A support Operator's daily questions are "what needs me?" and "why did the bug check stop?". The Planner answers the first with a sorry face, and turns the second into a new set-up card that later sits in Drafts.
- *Evidence.* `classify` sends any request with "bug", "report", "list" or similar to a set-up card (`prototype.html:2536`), else to the abilities answer (`2537`, text at `2550`). In the probe, "What needs me?" and "Check my workflows" got "I can't help with that here."; "Why did Morning bug report check stop?" got a set-up card needing 3 answers; "Is the stale ticket nudge running?" got "I can't message ticket owners yet." Design note line 345 makes "no general chat assistant" a non-goal.
- *Proposed change.* A sixth answer, "about your workflows", as the lead chose. It answers "check my workflows", "why did X stop" and "what needs me" from the same data as Needs you and the AI troubleshooter, with the item's own button (Review and decide, See why, Retry). It never changes anything itself. The five-answer contract and the golden set grow by one answer (ADR 0037 amendment).
- *Expected benefit.* The box becomes the one place to start and to check in. Fewer trips through Workflows and the workflow page.

#### HM4. The Planner's reply is not announced to screen readers

P1 · S · prototype only

- *User problem.* A screen-reader user sends a request and hears nothing back. The reply appears silently, and focus stays where it was for set-up and watchlist answers.
- *Evidence.* `ask` (`prototype.html:2684-2725`) never calls `announce`. The reply bubble (`2672`) is not in a live region. Only the thinking dots have `role="status"` (`2671`). Focus moves to the box for other answers only (`2707`). Run lines are announced (`3568`), so the pattern exists. From code reading only; not tested with a screen reader.
- *Proposed change.* Announce the full sentence once it is complete. Move focus to the card's heading for set-up and watchlist answers.
- *Expected benefit.* The front door works without sight.

#### HM5. "Nothing changes without a yes" on six screens

P2 · S · prototype only

- *User problem.* The same promise in slightly different words on almost every page becomes noise, and people stop reading it where it matters.
- *Evidence.* Home lead (`prototype.html:2086`), abilities foot (`2757`), set-up card promises (`2582`), Workflows lead (`2166`), Agent library lead (`3125`), refusal (`2549`).
- *Proposed change.* Keep it in two places, the set-up card's "What needs a yes" and the approval panel. Home's lead becomes "Tell me in plain English. I'll set it up to run by itself."
- *Expected benefit.* Fewer repeated explanations. The rule still shows where a person agrees to something.

### 4.4 The Planner conversation and its answers

#### PL1. Can't-do answers use system words

P1 · S · prototype only

- *User problem.* "A new system is the team's decision" and "a new tool changes what the agents may do" assume the reader knows what a system and a tool are.
- *Evidence.* `CANT` (`prototype.html:2491-2498`), `ANSWERS.tool` (`2547`). 03b 4.3 judgement.
- *Proposed change.* Lead with the outcome, then the alternative, then the ask. "I can't send email yet. I can put the list in a Jira ticket instead. Want me to ask the team to add email?" Registry state words (Planned, Unsupported) replace "system" and "tool".
- *Expected benefit.* Every can't-do answer is one read and one tap.

#### PL2. "Ask the team" follow-up lives in the Agent library

P2 · S · prototype, backend dependency

- *User problem.* After Ask the team, the Operator is told to follow it "on Tools, in the Agent library", a technical page. Nothing ever tells them the answer.
- *Evidence.* `teamReq` toast (`prototype.html:4209`), "Asked the team" section on Tools (`3169`). Approver-only users can't open the Agent library (`1970`). No store for these requests exists in the built app (`08` R6).
- *Proposed change.* Show each request under "Waiting on others" on Workflows, with its state (With the team, Planned, Not planned). The Planner can answer "what did I ask the team?" (HM3). The backend store is already in ADR 0037's Consequences.
- *Expected benefit.* The person sees what happened to their ask where they already look.

### 4.5 The set-up card

#### SC1. Green marks hold words the person never said

P0 · S · prototype, backend dependency

- *User problem.* Example 1 says "bug tickets". The card says it will find "open tickets with no update for 10 days" and "list them, with their owners", and marks both green, "From your words". "Bug" is gone and "with their owners" was added. The Operator trusts green and turns it on.
- *Evidence.* `parseIntent` has no rule for ticket type (`prototype.html:1449-1454`). `ACTIONS.list` adds "with their owners" (`1431`). A parsed part is marked `ok` (`1490`), shown as "from your words" (`2462`). The probe printed tickets chip class `schip ok` and title "From your words". ADR 0037 line 16 says every name or default the Planner read in is marked as its own guess, never as the person's words. In the built app, the model self-reports "understood" (`planner.py:322`), and nothing checks that a part keeps the person's words.
- *Proposed change.* Green, or no mark at all, only for the person's own words. Anything mapped, widened or added is grey, "my guess". A word the Planner couldn't use is named under the sentence: "I left out 'bug'. I can't tell bug tickets from others yet." (see X2). In the built app, check that an "understood" part's key words appear in the request.
- *Expected benefit.* The mark people trust most is always true.

#### SC2. Five sections and a plan of agents for one yes

P1 · M · prototype, planned ADR

- *User problem.* To turn on one workflow, the Operator reads a name, a coloured sentence with notes, a three-step plan with agent names and tags, a "Who says yes" line and a promises paragraph. Agent names and "No system access" are ideas they don't need to act on.
- *Evidence.* `setupCard` (`prototype.html:2596-2611`). Plan with agents (`2593`, `2604-2606`). 03b 4.4 judges that "The agent names in 'The plan' are a technical idea a user does not need to act on."
- *Proposed change.* As the lead chose, three sections and one collapsed one. **What will happen** is one plain sentence, with only the parts that need an answer as questions. **When** is the schedule in words, with Change. **What needs a yes** says "Before the ticket is created, an Approver on your team says yes. Not you." **How this workflow works** starts collapsed and holds the steps, the agents and what each can reach. Name and Rename stay in the header. This moves ADR 0037's plan out of view (section 8).
- *Expected benefit.* Fewer concepts at the moment of decision. The detail stays one tap away.

#### SC3. One sentence of five-colour chips and inline lists

P1 · M · prototype only

- *User problem.* The read-back is one long sentence where four or five parts are chips, each with a colour and a hidden list, and a note list under it. On a phone it wraps into a block of chips.
- *Evidence.* `understoodSentence` (`prototype.html:2471-2480`), five states in `CHIP_HINT` (`2462`), each list a `select` inside the chip (`2468`). Probe printed the sentence with every option inline: "find open tickets with no update for 10 days Change... Tickets closed this week ... in a Jira project Choose... MOCK OPS SUP ...".
- *Proposed change.* The sentence is plain text. Parts that need an answer become questions under it, with buttons for the choices ("Which Jira project? MOCK, OPS, SUP"). Three marks only: your words (plain), my guess (grey with a dotted underline you can tap to change), needs your answer (amber question).
- *Expected benefit.* Fewer colours to learn. Answers are taps, not list menus inside a sentence.

#### SC4. Drafts can't be discarded, and questions become drafts

P1 · S · prototype, backend dependency

- *User problem.* Any request the Planner reads as a task becomes a card, and a new chat saves it as a Draft. A draft that can never be turned on, such as one with GitLab, stays on Workflows for good.
- *Evidence.* `startDraft` and `saveLive` save the open card on every new request and new chat (`prototype.html:2559-2572`). Only `openDraft` and `turnOn` remove a draft (`4297`, `4346`; 03b 4.7). In the probe, "Every week, sum up the tickets in GitLab" stayed as "Weekly summary, 4 choices left" with `openDraft` as its only action. HM3 shows a question becoming a card.
- *Proposed change.* Discard on each draft row and on the card, with Undo, as the lead chose. Save a card as a draft only after the person changed something on it.
- *Expected benefit.* Drafts are things the person meant to keep.

#### SC5. A second workflow turned on from Home replaces the first

P1 · M · prototype only

- *User problem.* A reviewer turns on two workflows from Home. The first disappears from Workflows.
- *Evidence.* `turnOn` keeps one Home-made workflow in `S.nr` and `S.conf` (`prototype.html:4346-4362`; `routineIds`, `1421`). In the probe, after turning on "Weekly stale ticket list" and then "Weekly open ticket summary", Workflows listed only the second. 03b 4.7 notes a draft and a live workflow with the same name in `workflows-no-answer.png`.
- *Proposed change.* Keep a list of Home-made workflows in the prototype state.
- *Expected benefit.* The prototype behaves like the product it describes.

#### SC6. "Every month" is offered but not built

P1 · S · prototype, backend dependency

- *User problem.* An Operator picks "Every month". The built platform can't run it.
- *Evidence.* `FREQ_WORD` includes month (`prototype.html:1255`), used by the schedule fields (`1907-1909`) and `parseIntent` (`1442`). Built schedules are every day, weekdays or named days (`08` L17; design note line 261).
- *Proposed change.* Registry entry "Monthly schedule", state Planned. Hide the option unless planned features are on. A monthly request gets "I can run it every week. Monthly runs are planned."
- *Expected benefit.* No choice the backend refuses.

#### SC7. "Open in n8n" at the moment of success

P2 · S · prototype only

- *User problem.* Right after turning a workflow on, the Operator is offered n8n, a technical tool most support staff won't use.
- *Evidence.* Done box links "See it in Workflows", "Do a test run", "Open in n8n" (`prototype.html:2586`). n8n editing is planned (ADR 0026, 0027; 03b Table 1.1).
- *Proposed change.* Done box offers "See it in Workflows" and "Try it now" (the test run, with "it still waits for a yes"). n8n moves to the workflow page's advanced options.
- *Expected benefit.* One clear next step.

#### SC8. The Jira project is always asked

P2 · S · prototype, backend dependency

- *User problem.* Most teams use one Jira project for this work. The Operator still has to choose it every time.
- *Evidence.* Choices are hard-coded (`prototype.html:2487`), and a missing project is amber (`1509`, `2577`). 03b section 6 counts example 1 at 2 clicks and 2 fields, one of them the project.
- *Proposed change.* When Connections lists one Jira project, fill it in grey ("my guess"). Ask only when there are several. Needs a project list from the Jira connection (backend).
- *Expected benefit.* Example 1 drops to 2 clicks and 1 field (estimate).

### 4.6 Workflows

#### WF1. Each item that needs you shows twice

P1 · S · prototype only

- *User problem.* A stopped workflow appears in Needs you with its reason and button, and again in All workflows with a pill and the same button. "Coming up next" repeats each row's "Next". The page is twice as long on a phone.
- *Evidence.* `needs` (`prototype.html:2002-2021`), row buttons from `actionFor` (`2095-2104`, used at `2154`), "Coming up next" (`2134`). In the probe's screenshot at 390 px, Morning bug report check and Stale ticket nudge each appear twice with their buttons. 03b 4.7 "Essential vs repeated".
- *Proposed change.* Rows keep their status pill but no button when the item is already in Needs you. Drop "Coming up next".
- *Expected benefit.* One place per action. A shorter page.

#### WF2. Needs you mixes approvals with platform upkeep

P2 · S · prototype only

- *User problem.* "The GitHub key expires in 9 days" sits between an urgent approval and a stopped workflow, and on day one it is the only item.
- *Evidence.* Key expiry item (`prototype.html:2010`), AI model address (`2011`), tool OK (`2012`). In the probe, Alice's Needs you lists the key between the approval and the stopped workflow.
- *Proposed change.* Needs you holds decisions and stopped workflows. Upkeep (keys, model address) shows as a dot on Settings, and on a workflow only when it is about to stop it ("Will stop on 5 Nov: the GitHub key expires").
- *Expected benefit.* Needs you means "your work needs you".

#### WF3. Search and filters for four workflows

P2 · S · prototype only

- *User problem.* A search box and three filters for a list of four add controls without saving time.
- *Evidence.* `boardView` (`prototype.html:2169-2170`). Rows that need you already sort first (`2148`).
- *Proposed change.* Show search and filters only above about eight workflows.
- *Expected benefit.* Fewer controls on the common page.

#### WF4. "Start in n8n" under the main list

P2 · S · prototype only

- *User problem.* A link to build workflows in n8n sits under every Operator's list, next to the Planner's own add row.
- *Evidence.* `prototype.html:2174`. Planned (ADR 0026, 0027).
- *Proposed change.* Move it to Settings or behind the planned-features control.
- *Expected benefit.* One way to start a workflow on the main path.

#### WF5. Every row carries an "On" pill

P2 · S · prototype only

- *User problem.* "On" on every row is the normal case, so it says nothing. Rows that need you carry two pills.
- *Evidence.* `lifePill` and `pills` (`prototype.html:1691-1692`).
- *Proposed change.* Show only "Paused". On is the default.
- *Expected benefit.* The pill that remains carries information.

#### WF6. Bob sees the same Needs you on Home and Workflows

P2 · S · prototype only

- *User problem.* An Approver-only person sees the same list twice in two tabs.
- *Evidence.* `approverHome` (`prototype.html:2064-2076`) and `attention` for every role (`2107`). The probe confirmed that Bob's Workflows has Needs you.
- *Proposed change.* For an Approver-only person, Workflows shows only the list of workflows.
- *Expected benefit.* One place for their decisions.

#### WF7. Row faces with no names

P3 · S · prototype only

- *User problem.* Three tiny faces per row identify agents only by colour. An Operator doesn't need to know which agents a workflow uses to manage it.
- *Evidence.* `faces(..., 26)` in rows (`prototype.html:2159`). They have a screen-reader label (`1243`) but no visible name. 03b 4.7 judgement.
- *Proposed change.* Drop faces from rows. Show them on the workflow page and the run page, where they mean something.
- *Expected benefit.* Calmer rows. Faces keep their meaning in the live view.

### 4.7 Workflow page

#### WP1. Five Operator buttons before the facts

P1 · S · prototype only

- *User problem.* Change schedule, Change who approves, Pause, Open in n8n and Delete sit in a row above what the workflow does. Two of them are planned.
- *Evidence.* `routineView` (`prototype.html:2284-2289`). 03b section 6 counts Pause at 3 clicks and Delete at 4.
- *Proposed change.* Pause or Resume stays as a button. Change schedule moves onto the When fact (tap it to edit). Delete goes in a "More" menu. Change who approves and Open in n8n show only with planned features.
- *Expected benefit.* One obvious action. Fewer buttons to read.

#### WP2. No way to change what a workflow does

P1 · M · prototype, backend dependency

- *User problem.* The card promised "You can pause, change or delete it at any time". To change which tickets it finds or what it writes, the only paths are n8n or the agent dialog, which changes the agent for every workflow.
- *Evidence.* Promise (`prototype.html:2582`). No change control in `routineView` (`2284-2289`). In the built app, only the schedule can change (`04` J9; `08` L19).
- *Proposed change.* "Change what it does" opens the workflow's set-up card on its own page, filled in, with the same questions and marks. Saving makes a new version from the next run. The Planner can take a plain-English change there ("only bugs in OPS"). It is a change where the thing lives, as ADR 0037 asks.
- *Expected benefit.* The promise holds. Fixing a workflow needs no technical person, which is the sponsor's main concern.

#### WP3. Only the newest run can be opened

P2 · S · prototype only

- *User problem.* Older runs in Recent runs are plain text. To see last week's tickets the Operator can't click the run.
- *Evidence.* Only the live row is a button (`prototype.html:2309-2311`).
- *Proposed change.* Every run row opens its run page.
- *Expected benefit.* Past results are one tap away.

### 4.8 Run page, with the live activity view, approval panel and AI troubleshooter

#### RN1. Replay and a speed switch on every run

P1 · S · prototype only

- *User problem.* An Approver opening a run to decide sees "Replay the run", "1x", "2x" and "Instant". They exist only because the prototype replays a script.
- *Evidence.* `prototype.html:2361`. The probe listed the run page buttons as "Replay the run", "1x", "2x", "Instant", "Approve 3 tickets", "Decline". The built run is live, with no replay (`03` 4.6; `04` J5).
- *Proposed change.* Remove both from the product design. Keep replay speed as a test control for demos.
- *Expected benefit.* Three fewer controls at the moment of decision. The design matches the live build.

#### RN2. On a phone, the decision sits under the whole story

P1 · M · prototype, built app

- *User problem.* On a phone the page is the eight-step run line, every agent's message, then the approval panel with three tickets and their links. The page does jump to the decision, but going back up to understand it is a long scroll.
- *Evidence.* `openRun` lands on the decision (`prototype.html:3841-3849`). In the probe's screenshot at 390 px, the run page is about 3,870 px tall, with Approve near the bottom. Ticket links (registry, release notes, NVD, CISA) are in the panel (`2396-2399`).
- *Proposed change.* When a run is opened to decide or fix, show the decision first with a one-line summary ("3 agents checked 14 tools and drafted 3 tickets"), then "See how the agents got here" for the run line and chat. Ticket links move behind "Details" on each ticket. A run opened to watch keeps today's order.
- *Expected benefit.* Decide without scrolling. The live view stays one tap away for the curious and for the demo.

#### RN3. Who was asked is said twice

P2 · S · prototype only

- *User problem.* The approval gate's chat line and the panel both explain who was asked and when it stops.
- *Evidence.* `gateText` (`prototype.html:1756-1766`) and `askLineHtml` in the panel (`2408`). 03b 4.9.
- *Proposed change.* Keep it in the panel only. The chat line says "Asked for a yes."
- *Expected benefit.* One explanation.

#### RN4. Decline takes no reason

P2 · M · prototype, backend dependency

- *User problem.* An Approver declines and can't say why. The Operator sees "declined" and has to chase them.
- *Evidence.* `decline` (`prototype.html:3988-3995`). Built the same (`08` L20).
- *Proposed change.* After Decline, optional reason chips ("Wrong tickets", "Not now", "Ask me first") and a short note, shown to the Operator, in the log and to the Planner when the Operator asks why. Declining stays one tap. Needs a reason field on the decision record.
- *Expected benefit.* Fewer back-and-forth messages. The Planner can suggest a fix.

#### RN5. All or nothing approval

P3 · L · planned ADR

- *User problem.* The Approver may want the urgent Log4j ticket now and the others later. They must approve or decline all three.
- *Evidence.* "You approve or decline the whole check." (`prototype.html:2410`). In the built app, one digest covers every action in a proposal (`write_actions.py:50-60`). ADR 0019 sets one approval for the week's tickets.
- *Proposed change.* None for version 4. Record as a future option that needs an ADR, because it changes what the approval covers.
- *Expected benefit.* Noted so the redesign doesn't promise it.

#### RN6. Fix it and Report to support look built

P1 · S · prototype only

- *User problem.* An Operator sees "Use langchain-ai/langchain and retry" and "Report to support" with coding agents writing a fix. Today the troubleshooter explains from a fixed table, and Retry is only on the built Home for people tied to the run.
- *Evidence.* Fix and report panels (`prototype.html:2425-2439`), report stages with coding agents (`2032-2037`). In the built app, the troubleshooter is a fixed lookup table with no model (`08` L05), Retry is only on Home (`08` L15), and Fix it and Report to support are not built (`03` 4.6).
- *Proposed change.* Default samples show today's case, where the GitHub check failed because GitHub didn't answer, with "Retry" on the run page. Fix it and Report to support show with planned features, tagged Planned. Retry on the run page is a small built-app change.
- *Expected benefit.* The troubleshooter's promise matches what an Operator can do.

#### RN7. "Pick agents" in runs where nothing is picked

P2 · S · prototype, built app

- *User problem.* The live view says the Planner brought in agents. In a watchlist run, fixed code does this, not a model. A curious Approver is misled about what the AI decided.
- *Evidence.* Prototype "Pick agents" station and "I'm bringing in..." (`prototype.html:1797`). In the built app, `FixedPlanner` writes these lines (`planner.py:84-148`; `08` L13).
- *Proposed change.* For a fixed run, label the station "Start the check" and the line "The weekly check uses the Version checker." Keep "Pick agents" for runs a model planned.
- *Expected benefit.* The live view never overstates what the AI did.

### 4.9 Software watchlist

#### SW1. Adding software asks for registry formats

P1 · M · prototype, backend dependency

- *User problem.* The page's Add form asks where the software is published and for a reference such as `groupId:artifactId` or `owner/name`. Support staff won't know these. The Planner already guesses them on Home.
- *Evidence.* Add form (`prototype.html:2249-2254`), formats (`SRC_FIELD`, `1556`). 03b 4.10 judgement. The watchlist card guesses and checks the source (`2621-2622`). In the built app, the Operator types the GitHub repository and no guess is checked (`08` R6).
- *Proposed change.* Add asks for the name only. The same guess as the Planner's card appears with Looks right and Change. The source picker moves into Change. Needs the guess check from ADR 0037's Consequences.
- *Expected benefit.* 1 field instead of 2 or 3 plus a select (03b section 6 counts 2 clicks, 3 fields with 1 optional, and 1 select). Clicks rise by about 1 (Looks right). Less technical knowledge.

#### SW2. Six sections, most of them planned

P2 · S · prototype only

- *User problem.* Security risks, Needs a person, Support ending, Not checked yet, Up to date and Add software, plus a schedule box, a banner and a note. On today's backend only three of them would have content.
- *Evidence.* `softwareView` (`prototype.html:2234-2255`). Security risks and Support ending depend on ADR 0025.
- *Proposed change.* The default view keeps the banner when a yes waits, Needs a person, Not checked yet, Up to date (folded) and Add. Security risks and Support ending return with planned features.
- *Expected benefit.* A shorter page that shows what works.

#### SW3. A wrong source can't be changed on the row

P2 · S · prototype, backend dependency

- *User problem.* If the GitHub project is wrong, the Operator must remove the row and add it again.
- *Evidence.* Row actions are History and Remove (`prototype.html:2228`). In the built app, no route edits a watched software (`08` L16).
- *Proposed change.* "Change source" on the row, using the same guess-and-confirm control.
- *Expected benefit.* One fix instead of remove and re-add.

### 4.10 Agent library

#### AL1. A reference page in the Operator's main menu

P2 · S · prototype, planned ADR

- *User problem.* The Agent library and its Tools tab explain agents, tools, read and write, versions and health. A support Operator's daily work doesn't need them, yet the page takes a quarter of the menu.
- *Evidence.* Menu (`prototype.html:1970`, `1995`). 03b 4.11 calls it "reference material and a power-user feature". Most of its content is planned (03b Table 1.1).
- *Proposed change.* Take it out of the main menu. Reach it from a workflow's "How this workflow works", from agent chips on the workflow and run pages, and from Settings as "Agents and tools". The menu becomes Home, Workflows and Software watchlist for everyone. This changes the design note's menu (section 8).
- *Expected benefit.* Three tabs for every role. Less navigation for daily work.

#### AL2. Changing behaviour starts far from the problem

P2 · S · prototype only

- *User problem.* An Operator whose workflow does the wrong thing has to know which agent is responsible, find it in the library, and change it for every workflow that uses it.
- *Evidence.* Change box in `agentDialog` (`prototype.html:3302-3308`), "N workflows use this agent" (`3285`). Design note open question 5.
- *Proposed change.* Most changes go through "Change what it does" on the workflow page (WP2). The agent change stays in the library, behind planned features, for changes meant for every workflow.
- *Expected benefit.* The common fix starts where the problem shows.

### 4.11 Settings

#### ST1. Connections and AI usage are planned but look built

P1 · S · prototype only

- *User problem.* Settings shows three connections with keys, expiry and tests, and a usage limit with a cost meter. None is built. The Teams card says it "receives Approvers' answers", which ADR 0036 rules out.
- *Evidence.* `connPanel` (`prototype.html:2853-2878`), `CONNS.teams` (`2850`), `usagePanel` (`2915-2934`). Design note "Later". Built Settings has AI model and People and roles (`03` 4.11).
- *Proposed change.* Connections becomes a registry view that shows each system with its state (Ready, Needs setup, Planned) and, for Ready ones, a plain status line. Key replacement and AI usage show with planned features. Teams reads "Posts approval requests."
- *Expected benefit.* Settings shows what exists. ADR 0036 holds.

#### ST2. The AI model tab needs a technical person, with no handoff

P2 · S · prototype only

- *User problem.* A support Operator meets providers, addresses, API keys and model names. When the Planner can't work without a model, nothing tells them who should fix it.
- *Evidence.* `modelPanel` (`prototype.html:2808-2838`). `03` 4.11 judgement; `04` J8. Two roles only, so no admin role can own this.
- *Proposed change.* Keep the tab as it is. Add the handoff. Home's offline state (I5) and the tab's empty state say "Whoever looks after the platform connects the AI model here", and the Planner can say who last connected it (from the change history).
- *Expected benefit.* A non-technical Operator knows what to ask and of whom.

#### ST3. Add a person has no work email

P2 · S · prototype only

- *User problem.* The prototype adds a person by name only, while the built form also asks for a work email. A reviewer can't see a field the real form needs.
- *Evidence.* The prototype form is at `prototype.html:2904-2907`. The built form asks for work email and name (`04` J8 step 2).
- *Proposed change.* Add the Work email field.
- *Expected benefit.* The prototype matches the built form.

### 4.12 The Teams approval message (practice Teams drawer)

#### TM1. Approve and Decline in the Teams message

P0 · S · prototype only

- *User problem.* Bob approves from the practice Teams drawer in two clicks. In the built app and in real Teams there is no such button, so the demo teaches a path that doesn't exist. The messages also say "You can decide on the message above." Workflows has an "Open in Teams" button, which sends Bob to Teams, whose only button sends him back.
- *Evidence.* Drawer buttons (`prototype.html:3359`), "decide on the message above" (`3330`, `3340`, `3341`), "Open in Teams" (`2005`). The probe listed Bob's drawer buttons as "Approve", "Decline" and "Open in Workflow Builder". The built card has one button, Open in AI Workflow Builder (`03` 4.10; ADR 0036). 03b section 6 counts approve from the drawer at 2 clicks, and the built path is 3 (`03` section 5).
- *Proposed change.* As the lead chose, one Open button. The message shows what ADR 0036's card shows: what will be written, what the agents found, who can decide, and who can't because it is their own work. Remove "Open in Teams" from Needs you.
- *Expected benefit.* Approvers practise the real path. No loop between the app and Teams.

#### TM2. Two "needs you" counts, and a practice Teams button in the header

P1 · S · prototype only

- *User problem.* Alice sees "4" on Workflows and "1" on Teams. They count different things, and neither label says what. The Teams button opens a practice copy of a different product.
- *Evidence.* Workflows count from `needs` (`prototype.html:1964-1968`), Teams count from `teamsCount` (`3346-3352`, `1977`). The probe printed Alice's Workflows badge 4 and Teams badge 1.
- *Proposed change.* One count, on Workflows (and on Home's strip, HM1). In the prototype, the practice Teams drawer moves into the test controls. The built app keeps its header button on practice stacks only (section 8).
- *Expected benefit.* One number to watch. The header has only the app's own controls.

#### TM3. Messages @mention people

P2 · S · prototype only

- *User problem.* "@Bob" suggests Teams will notify Bob personally. The built webhook can't mention anyone.
- *Evidence.* `teamsItems` (`prototype.html:3329-3342`). ADR 0036's Consequences say "No real mention yet."
- *Proposed change.* Name people in plain text. Mentions show only with planned features.
- *Expected benefit.* No false sense that someone was pinged.

#### TM4. The channel name differs from the built app

P3 · S · prototype only

- *User problem.* Small, but a reviewer comparing the two sees two channels.
- *Evidence.* "# CODESparks Support" (`prototype.html:3364`). Built default "CODESparks Ops" (`03` 4.10; `08` L18).
- *Proposed change.* Use one name.
- *Expected benefit.* Consistency.

## 5. Keep, simplify, make contextual, move to advanced

Every existing interaction or control on each screen, in exactly one class. "Simplify" includes removing a control when the reason says so. New controls (Discard in SC4, Change what it does in WP2, the two test controls in X4) are proposed in their findings and are not listed here. "Move to advanced" means Settings, a collapsed section, or the planned-features test control.

### Header and menu

| Control | Class | Reason |
|---|---|---|
| Logo, goes Home | Keep | Standard and cheap. |
| Home menu item | Keep | The start of every visit. |
| Workflows menu item | Keep | Where every workflow lives. |
| Workflows count badge | Simplify | The only "needs you" count (TM2). |
| Software watchlist menu item | Keep | A daily list with its own add flow. |
| Agent library menu item | Move to advanced | Reference material (AL1). |
| Teams button and badge | Move to advanced | A practice copy; moves to test controls (TM2). |
| Settings gear | Keep | Needed for upkeep; the person chip area is the right place. |
| Person chip | Keep | Shows who you are acting as. |
| Skip to main content | Keep | Keyboard access. |
| Phone tab bar | Keep | Same items as the menu, three after AL1. |

### Home (Operator)

| Control | Class | Reason |
|---|---|---|
| Planner face, 128 px, breathing once | Keep | Makes the one thing to do obvious. |
| Listening, thinking, speaking faces | Keep | Show real events; nothing waits for them. |
| Heading ("What does your team do again and again?") | Keep | One clear question. |
| Lead sentence | Simplify | Drop the repeated "nothing changes without a yes" (HM5). |
| Text box and send button | Keep | The front door. |
| Enter sends, Shift+Enter new line | Keep | Expected chat behaviour. |
| Three example chips | Simplify | Only Ready capabilities, from the registry (X2, HM2). |
| "I can / Not yet" lists | Simplify | Registry-driven tasks with states (HM2). |
| "What can I ask for?" toggle | Keep | Progressive disclosure after day one. |
| New chat | Keep | Clears the thread, keeps work as a draft. |

### Home (Approver only)

| Control | Class | Reason |
|---|---|---|
| Greeting and "N things need you" | Keep | Says at once if there is work. |
| Needs you card and rows | Keep | Their whole job, two clicks to decide. |
| All quiet with next run | Keep | A clear empty state. |
| Role note ("You're an Approver...") | Keep | One line that explains the missing box. |

### The Planner's answers

| Control | Class | Reason |
|---|---|---|
| Thinking dots and the reply sentence | Keep | Plus an announcement (HM4). |
| Set that up (nearest doable thing) | Keep | Turns a no into a next step. |
| Ask the team | Keep | The only path for a new system or tool. |
| "Asked the team" pill | Make contextual | Follow-up shows on Workflows (PL2). |
| Which software question and "never mind" | Keep | One question at most, with a way out. |
| Open Software watchlist (already listed) | Keep | Direct link to the thing. |
| Abilities answer | Simplify | Registry-driven (HM2). |
| Refusal card with the safe version | Keep | Explains the rule and offers the right workflow. |

### Set-up card

| Control | Class | Reason |
|---|---|---|
| Name and Rename | Keep | Drafted for you, changeable. |
| "Workflow" kind label | Simplify | Remove; the heading says it. |
| What I understood sentence | Simplify | Plain sentence, questions under it (SC3). |
| Chip lists for tickets, project, action | Simplify | Become question buttons (SC3). |
| When chip and schedule picker | Keep | Opens by itself only while the time is missing. |
| Picker Done button | Simplify | Fold automatically once complete. |
| Notes under the sentence | Simplify | Only for guesses and dropped words (SC1). |
| Similar workflow "Open it" | Keep | Stops duplicates. |
| The plan with agent faces and tags | Move to advanced | Into "How this workflow works" (SC2). |
| "Done by the Jira reader..." note | Move to advanced | Same section. |
| Who says yes | Simplify | Becomes "What needs a yes" (SC2, X3). |
| Promises paragraph | Simplify | Merged into "What needs a yes" (HM5). |
| Ask the team on a red part | Keep | The way forward for an unsupported system. |
| Turn it on, off until nothing is unclear | Keep | One yes; the core of the design. |
| "N choices left" footer | Keep | The single count (I8). |
| Planner's "I need N more answers" | Simplify | Drop the number (I8). |
| See it in Workflows, in the done box | Keep | Confirms where it lives. |
| Do a test run, in the done box | Keep | Lets the Operator see it work once. |
| Open in n8n, in the done box | Move to advanced | Technical (SC7). |

### Watchlist card (from the Planner)

| Control | Class | Reason |
|---|---|---|
| Software name, "From your words" | Keep | True mark. |
| Guessed source with where it came from | Keep | The person confirms a fact, not a hunch. |
| Looks right | Keep | One tap. |
| Change source | Keep | Field with a shape check. |
| Version field and "Not sure? Start from the newest" | Keep | Explains the consequence. |
| "Checked: Every Monday", same for all | Simplify | Remove; the watchlist page says it. |
| "Who says yes", same for all | Simplify | Remove, or today's rule (I4). |
| Add | Keep | One yes. |
| No, set it up as a new workflow | Keep | Escape when the guess is wrong. |

### Workflows

| Control | Class | Reason |
|---|---|---|
| Heading and lead | Simplify | Drop the repeated rule (HM5). |
| Needs you, one full card then rows | Keep | Most urgent first, one main button. |
| Review and decide | Keep | The main action. |
| Open in Teams | Simplify | Remove; Teams only links back (TM1). |
| See why and fix it, Report to support | Keep | Tagged Planned where not built (RN6). |
| Key expiry, model address items | Make contextual | To Settings, or on the affected workflow (WF2). |
| Confirm an Approver item | Keep | A decision this person must make. |
| Waiting on others | Keep | Shows what you are waiting for. |
| Drafts | Keep | With Discard (SC4). |
| Following up (support case) | Make contextual | Shows only while a case is open; Planned (RN6). |
| Coming up next | Simplify | Remove; rows show Next (WF1). |
| Find a workflow | Make contextual | Only for long lists (WF3). |
| All, Stopped, Paused filters | Make contextual | Only for long lists (WF3). |
| On pill | Simplify | Show only Paused (WF5). |
| Run pill (Needs a yes, Stopped, No answer) | Keep | The state that matters. |
| Row agent faces | Move to advanced | To the workflow page (WF7). |
| Row button | Simplify | None when the item is in Needs you (WF1). |
| Ask the Planner for a new one | Keep | Points back to the front door. |
| Start in n8n | Move to advanced | Technical, planned (WF4). |

### Workflow page

| Control | Class | Reason |
|---|---|---|
| Back to Workflows | Keep | Navigation. |
| Status pills | Keep | State at a glance. |
| Main action button | Keep | One obvious next step. |
| Change schedule | Make contextual | Tap the When fact (WP1). |
| Change who approves and its editor | Move to advanced | Planned, ADR 0024 (I4). |
| More approval options | Move to advanced | Planned, ADR 0024. |
| Pause or Resume | Keep | A common safe control. |
| Open in n8n and its dialog | Move to advanced | Technical, planned. |
| Delete, dialog and Undo | Make contextual | In a More menu (WP1). |
| When, Next run, Who approves facts | Keep | The facts a person checks. |
| Agents chips | Move to advanced | Into "How this workflow works". |
| In n8n fact, Changes in n8n panel | Move to advanced | Planned. |
| What it does steps with tags | Keep | Plain description of the work. |
| Recent runs | Keep | With every row openable (WP3). |
| Support case panel | Make contextual | Only while a case is open. |
| Schedule owner warning | Keep | A real rule that changes who may approve. |

### Run page

| Control | Class | Reason |
|---|---|---|
| Back link | Keep | Navigation. |
| Headline with result pill | Keep | States the result first. |
| Replay the run | Move to advanced | Test control only (RN1). |
| Speed switch 1x, 2x, Instant | Move to advanced | Test control only (RN1). |
| Run line with faces | Keep | The live view; first when watching. |
| Agent chat | Make contextual | Behind "See how the agents got here" when deciding (RN2). |
| Typing indicator | Keep | Shows who works now. |
| Hidden live region | Keep | Reads new lines aloud. |
| Approval panel and ticket bodies | Keep | Exactly what will be written. |
| Ticket links (registry, notes, NVD, CISA) | Make contextual | Behind Details (RN2). |
| Risk box for an urgent ticket | Keep | Plain words for severity; Planned (I9). |
| Who was asked line in the panel | Keep | The single place (RN3). |
| Approve | Keep | One click. |
| Decline | Keep | With optional reason (RN4). |
| Lock with the reason | Keep | Explains why you can't decide. |
| Whole-check note | Simplify | One sentence. |
| What happened, What to do | Keep | The troubleshooter's job. |
| Use the new name and retry | Keep | Tagged Planned; today's case is Retry (RN6). |
| Report to support and its dialogs | Move to advanced | Planned (RN6). |
| Undo Carol's change, Fix it in n8n | Move to advanced | Planned, n8n. |
| No answer panel buttons | Move to advanced | Planned, ADR 0024. |
| Done panel ticket pills | Keep | Shows the result. |
| Back to Home | Simplify | Back to where the person came from. |

### Software watchlist

| Control | Class | Reason |
|---|---|---|
| Check now | Keep | A direct action Operators use. |
| Schedule box | Simplify | Two short sentences. |
| Change schedule | Make contextual | Tap the schedule. |
| Change who approves | Move to advanced | Planned (I4). |
| Approval banner and Review and decide | Keep | Shows when a yes waits. |
| Find software | Make contextual | Only for long lists. |
| Security risks section | Move to advanced | Planned, ADR 0025 (SW2). |
| Needs a person table | Keep | The work to do. |
| Ours and Newest with source notes | Simplify | Drop cross-check notes until ADR 0025. |
| History | Keep | Shows where our version came from. |
| Remove with Undo | Keep | Safe, reversible. |
| Support ending | Move to advanced | Planned, ADR 0025. |
| Not checked yet, Confirm or Choose source | Keep | Today's source is GitHub; confirm stays. |
| Up to date, folded | Keep | Calm by default. |
| Add form, Name | Keep | The only field needed (SW1). |
| Add form, Published on | Move to advanced | Into Change source (SW1). |
| Add form, reference field | Make contextual | Only when the guess is wrong (SW1). |
| Add form, Our version | Keep | Optional, with "start from newest". |
| Footer note about the Planner | Simplify | One line. |

### Agent library (reached from advanced places after AL1)

| Control | Class | Reason |
|---|---|---|
| Agents and Tools tabs | Move to advanced | Reference material (AL1). |
| Agent cards and Details | Move to advanced | Same. |
| Change how it works, chips, Suggest, Save, Discard | Move to advanced | Planned (AL2). |
| Version history and Go back | Move to advanced | Planned. |
| Tool rows and health | Move to advanced | Registry view (X1). |
| Check it works | Move to advanced | Upkeep. |
| Need a tool that isn't here? | Move to advanced | Planned, needs its own ADR (I3). |
| Tool OK and Not now | Move to advanced | Planned. |
| Asked the team section | Make contextual | Shows on Workflows (PL2). |

### Settings

| Control | Class | Reason |
|---|---|---|
| Section tabs with a dot | Keep | Shows what needs attention. |
| AI model tab, current model and Test now | Keep | Upkeep, already in Settings. |
| AI model tab, provider, address, key, Connect, model, Test and save | Keep | The admin job, recorded. |
| Change history | Keep | Who changed what. |
| Connections cards | Simplify | Registry states (ST1). |
| Replace key and Test | Move to advanced | Planned (ST1). |
| People rows and role tick boxes | Keep | Built, approachable. |
| Approver confirmation | Keep | Safety rule. |
| Add a person | Simplify | Add work email (ST3). |
| AI usage meter and limit | Move to advanced | Planned. |

### Teams drawer

| Control | Class | Reason |
|---|---|---|
| Approve | Simplify | Remove (TM1). |
| Decline | Simplify | Remove (TM1). |
| Open in Workflow Builder | Keep | The only button, renamed (X7). |
| Lock line | Simplify | Plain "who can decide" text, as the built card (TM1). |
| Decided pill | Keep | Shows the outcome. |
| Backup and reminder messages | Move to advanced | Planned, ADR 0024. |
| Support case messages | Move to advanced | Planned (I1). |
| Tool OK message | Move to advanced | Planned (I3). |
| @mentions | Move to advanced | Planned (TM3). |

### Test controls

| Control | Class | Reason |
|---|---|---|
| Show, with A normal week and Day one | Keep | Two key states. |
| Act as | Keep | Add Carol (X6). |
| Make something happen | Keep | Plays other people and time. |
| About this prototype | Keep | Honest limits. |
| Start over | Keep | Reset. |

## 6. Interaction counts

"03b" means taken from 03b section 6. "Audit" means counted from the code by this audit. Proposed counts are estimates from the proposed change.

| Task | Role | Today in version 3 | Source | Proposed | Note |
|---|---|---|---|---|---|
| Set up from example 1 | Operator | 2 clicks, 2 fields | 03b | 2 clicks, 1 field | With one Jira project (SC8). |
| Set up a typed workflow with every part stated | Operator | 1 field, Enter, 1 click | 03b | Same | Already minimal. |
| Approve, Operator who is an Approver | Alice | 3 clicks | 03b | 2 clicks | Needs you strip on Home (HM1). |
| Approve, Approver only, from Home | Bob | 2 clicks | 03b | 2 clicks | Unchanged. |
| Approve from the Teams message | Approver | 2 clicks (Teams, Approve) | 03b | 2 clicks in real Teams (Open, Approve) | Version 3's path doesn't exist in the built app; built drawer is 3 (`03` section 5). |
| Add software on the watchlist page | Operator | 2 clicks, 3 fields (1 optional), 1 select | 03b | 3 or 4 clicks, 1 field | More clicks, no registry knowledge (SW1). |
| Add software from Home, example 3 | Operator | 4 clicks | 03b | 4 clicks | Unchanged. |
| Fix a stopped run the Operator can fix | Operator | 3 clicks | 03b | 2 clicks when it is the top item on Home's strip, otherwise 3 | HM1. |
| Ask what needs you | Operator | 1 click (Workflows) | Audit | 1 typed question, or 0 when the strip shows | HM3; not fewer clicks, fewer places. |
| Discard a draft | Operator | Not possible | Audit (`prototype.html:4297`, `4346`) | 2 clicks (Workflows, Discard) | SC4. |
| Change what a workflow does | Operator | Not possible except n8n | Audit (`2284-2289`) | 4 clicks and 1 choice | WP2. |
| Pause a workflow | Operator | 3 clicks | 03b | 3 clicks | Unchanged. |
| Delete a workflow | Operator | 4 clicks | 03b | 5 clicks | Delete moves into More (WP1); rare and destructive. |

## 7. What works and should stay

- **One yes turns a workflow on.** Turn it on stays off until nothing is unclear, and the footer names what is left (`prototype.html:2609-2610`).
- **An Approver-only Home.** Bob sees only what waits for his yes, with no box (`2064-2076`).
- **Refusing to skip a yes, without catching the product's own words.** `UNSAFE` matches "without asking" but spares "run it by itself" (`3039`), and the refusal offers the same workflow with a yes (`2659-2664`).
- **Every no comes with a next step.** Can't-do answers offer the nearest doable thing and Ask the team (`2642-2657`).
- **A guessed source says where it came from.** The person confirms a fact, and "Not sure? Start from the newest" says what that means (`2621-2625`).
- **The approval panel shows exactly what will be written.** "This is exactly what will be written, and nothing else." (`2407`). A lock says why you can't decide (`2402-2404`).
- **The troubleshooter says who can fix it.** "You can fix this yourself" versus "a problem in the platform" (`2016-2017`).
- **Needs you puts the most urgent item first, with one main button.** One full card, then one-line rows, and only the first keeps a dark button (`2000`, `2052-2058`).
- **Undo on delete and remove, with no time limit** while the message is open (`3796`; 03b 4.14).
- **The chat is not the record.** Unfinished cards become drafts (`2554-2572`).
- **Faces follow real state, and text always says the same** (03b section 5; `1243`).
- **Accessibility basics hold.** axe found no violations on Home, Home with a set-up card, Workflows, the run page, the Software watchlist, the Agent library, Settings and the Teams drawer (probe). Focus moves to each page's heading, dialogs trap focus and return it, and reduced motion stops movement (03b sections 3 and 5). No sideways scroll at 390 px on Home, Workflows, the watchlist, the Agent library, the run page or Settings (probe, 0 px each).
- **Home's "I can" list is today's four abilities**, matching `abilities.py:52-78`. X2 shows why that alone is not enough.

## 8. Conflicts with recorded decisions

| Change | Decision it reverses or changes | What the change gains | What the recorded decision gains |
|---|---|---|---|
| HM1. Needs you on Home when something needs action | ADR 0037 lines 13 and 36 ("Home shows nothing else"; Needs you moves to Workflows). ADR 0037 rejected "the box on Home with Needs you under it" (line 49). Design note sections 2 and 8. The lead's brief asks for a "Needs attention" section on Home. | An Operator-Approver sees a waiting yes on arrival, and approves in 2 clicks instead of 3. Matches the sponsor's first priority. | One job per page. The box never gets pushed down, and Home stays calm on most days. The strip proposed here appears only when something waits, which answers part of the ADR's worry. |
| HM3. The Planner answers questions about your workflows | Design note line 345 ("No general chat assistant ... It doesn't answer other questions"). ADR 0037 line 29 (anything else gets the abilities list) and its five-answer contract. | The box becomes one place to start and to check in. Fewer pages to visit. | A narrow Planner is easier to test and can't drift into promises. The new answer is fixed text from platform data, never the model's own words, to keep that. |
| SC2. Set-up card with a collapsed "How this workflow works" | ADR 0037 lines 17 and 34 list the plan, each step's agent and the new-agent mark as card content. Design note section 3. | Fewer concepts at the moment of decision. | The Operator sees which agents and systems a workflow uses before agreeing. Still one tap away. |
| SC3. Three marks instead of five | Design note section 3 (five marks); ADR 0037 line 16 ("a mark on each part"). | Less to learn; colour is not the only signal. | "Changed by you" and "please choose when it runs" each had a distinct look. |
| TM1. One Open button in the Teams message | Design note line 54 ("Teams is where you approve"), line 249 ("Bob OKs it from Home or Teams"), and the prototype's drawer. It follows ADR 0036 (proposed) and the built app. | The demo shows the real path. No loop. | Approving in Teams is faster, and a Teams bot could add it later (ADR 0036, Considered options). |
| TM2. Practice Teams drawer moves into the test controls | Design note line 84 ("The Teams button in the header opens the practice Teams copy"). The built header has the button on practice stacks. | One count. The header shows only the app's own controls. | Reviewers find the Teams side of the flow without opening test controls. |
| RN1. Remove Replay and the speed switch | Design note section 5 (line 176, "Replay the run plays it again"). | Three fewer controls; matches the live build. | Demos and reviews can replay a run. Kept as a test control. |
| AL1. Agent library out of the main menu | Design note menu table (line 76) and "The menu becomes". | Three tabs for every role; less navigation. | Changing agents in plain English answers the sponsor's maintainability worry, and a menu item makes it findable. |
| WF7. No faces on Workflows rows | Design note menu table (line 74, "its agents") and section 8. | Calmer rows. | Faces make the agents visible everywhere, part of the demo's character. |
| WF4, SC7, WP1. n8n links move to advanced | Design note section 8 ("a quiet link offers Start in n8n") and thing to try 8. ADRs 0026 and 0027 are proposed, not reversed. | One way to start and change workflows on the main path. | The n8n design note and ADRs 0026 and 0027 propose that staff can open and change workflows in n8n, and a visible link keeps that in view. |
| I4. Samples use today's approval rule | Design note section 6 and things to try 1 and 9 depend on ADR 0024 (proposed). | The demo shows what is built; the sponsor isn't shown a rule they haven't agreed. | Named Approvers answer the sponsor's access review and the 27 Oct evaluation. They return with planned features. |
| I1, I2. Samples rewritten to today's tools | Design note things to try 2, 3 and 8 use Morning bug report check (GitHub issues) and Stale ticket nudge (Teams). | Every sample is something an Operator can set up today. | Those samples show the sponsor's Phase 2 shape and the troubleshooter's best cases. They return with planned features. |
| X1. Registry shows Planned items | ADR 0037 rejected "Show the target platform on Home now" (line 56). | Reviewers see the target, clearly tagged. | The Planner never promises what the platform refuses. Compatible as long as Planned items show only as "Not yet" on Home and with the test control elsewhere. |
| WP2. A change box on the workflow page | ADR 0037 line 35 ("New things start in the box. Changes happen where the thing lives") and line 48 (two ways to do the same thing were rejected). | Fixing a workflow needs no technical person. | One box for the Planner. This change keeps new things in Home's box and puts changes where the workflow lives, so it fits the rule; it is listed because it adds a second place to talk to the Planner. |
| RN5. Ticket-by-ticket approval (not proposed for version 4) | ADR 0019 (one approval for the week's tickets) and the proposal digest. | An urgent ticket could go ahead alone. | One decision per week, and a digest that covers exactly what was approved. |
