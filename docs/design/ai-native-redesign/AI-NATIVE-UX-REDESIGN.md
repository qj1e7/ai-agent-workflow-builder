# AI-native UX redesign of the AI Workflow Builder

Status: proposal, 6 Nov 2026. Not agreed yet. The build target stays `docs/design/portal-routines/prototype.html` (version 3) until the team accepts this.

This spec answers the team's AI-native redesign brief, which followed an independent review of the handover package. It changes the existing prototype. It does not start again or change the product's architecture. The redesigned prototype is `prototype.html` in this folder (version 4). The evidence for each change is in `UX-AUDIT.md`, the before and after numbers are in `USER-JOURNEY-COMPARISON.md`, and the build order is in `IMPLEMENTATION-PLAN.md`.

## 1. What this redesign is for

A non-technical support Operator should be able to automate and look after routine work without knowing how agents, tools, n8n and the backend fit together. The product should still be transparent, auditable and controllable.

The aim is less effort and more clarity, not a sparser screen:

- fewer steps and less typing for the common tasks;
- less to understand before acting, and no need to learn where things live;
- the same answer about what the platform can do, on every screen;
- always clear what the AI did, what it guessed, and what waits for a person.

### The three layers

Every statement in this spec is about one of these. Version 4 never shows a planned capability as working.

| Layer | What it is | How version 4 treats it |
|---|---|---|
| Built app | The deployed React and FastAPI app | Not changed by this work. `IMPLEMENTATION-PLAN.md` says what it would take. |
| Prototype | The clickable design target | Changed, in a versioned copy |
| Planned | Proposed ADRs, ADRs not yet written, and later items | By default a planned capability is named only as a plain "Not yet" limitation, never as working and never with roadmap words. A planned screen part (one that needs a proposed or unwritten ADR) is hidden. The Planned features test control shows them, each tagged **Planned**. |

### What does not change

These rules come from the sponsor, the October feasibility test and the ADRs. The redesign keeps every one of them, and shows them to people only at the moment they matter.

- No write runs without an Approver's yes. The safety checker denies writes by default, and the AI's summary never replaces that check.
- Nobody approves their own work. The access review needs two Approvers, one after the other.
- Operator and Approver stay the only two roles.
- Every agent action and every decision is logged with who made it.
- n8n carries the plumbing.
- Teams carries the approval request, and its one button opens the approval page (ADR 0036). Nobody approves inside Teams.
- It must stay usable by non-technical staff and must still be able to move into DevNet.

## 2. The four ideas behind every change

1. **One door for creating and looking after work.** Home is where the Operator says what they want, whether that is a new workflow, a check on existing ones, the reason a run stopped, or what needs them. They never have to choose a page first.
2. **One source of truth for what the platform can do.** A capability registry decides what the Planner offers, what Home lists, what the Tools tab and Settings show, and which watchlist sources appear. A capability is in exactly one state.
3. **Decisions first, details on request.** Each screen leads with what the person must understand or decide. The plan, the agents, the tools and the logs sit one click away, under plainly named sections.
4. **Honest states.** The person can always tell a suggestion from a fact, a draft from a live workflow, a test run from a real run, and "waiting for a yes" from "done".

## 3. Information architecture

The menu doesn't change from version 3.

| Role | Menu | Home is |
|---|---|---|
| Operator | Home, Workflows, Software watchlist, Agent library | The Planner's box, plus Needs you when something needs action |
| Operator and Approver | The same | The same. Their approvals are part of Needs you. |
| Approver only | Home, Workflows, Software watchlist | Their approvals. No box, no creation actions. |

The header keeps Teams, Settings and the signed-in person. The Workflows tab keeps its amber count, and it counts the same list as Needs you everywhere else.

**Single sources.** Three functions feed every place that shows the same fact, so no two places can disagree:

| Fact | One source | Shown on |
|---|---|---|
| What needs this person | `needs()`, sorted by urgency | Home's Needs you, the Workflows section, the tab count, the Planner's "what needs me" answer |
| What a set-up card still lacks | `setupLeft()` | The card's footer and the reason Turn it on is disabled. The chat sentence no longer repeats a count. |
| What the platform can do | `CAPS` and `capState()` | The Planner's answers, "What can I ask for?", the Tools tab, Settings Connections, the watchlist sources, the Agent library |

## 4. The capability registry

One table, `CAPS`, is the single source of what the platform can do and in which state. It replaced version 3's `ABILITIES` list and the separate health and state flags in `CANT`, `TOOLS`, `CONNS` and `SOURCES`. Those tables still hold their own facts (a connection's key, a tool's inputs, a source's name) and read every state from `CAPS`. Each entry has a plain name in the Operator's words, the system it reaches, whether it reads, writes or only notifies, a base state, and the agents and tools that use it.

### States

| State | Shown as | Means | Comes from |
|---|---|---|---|
| Ready | "I can" | Works now and was checked | The base state, with a working connection |
| Needs setup | "Needs setup" with the fix | Built, but its connection is missing or its key ran out | The connection |
| Temporarily down | "Not working right now" with when it was last seen working | Built, but the system isn't answering | The connection's last check |
| Planned | "Not yet" with "Planned" | On the team's plan, with an ADR or a sponsor request behind it | The base state |
| Unsupported | "Not yet" | Not on any plan. Ask the team. | The base state |

`capState(id)` works out the shown state from the base state and the connection. Every screen asks it. None keeps its own copy.

### What is in the registry today

Taken from `agent-runtime/src/agent_runtime/tools.py` and `abilities.py` on 6 Nov.

| Capability | Kind | Base state | Why |
|---|---|---|---|
| Read Jira tickets | read | Ready | `jira.search`, `jira.read_ticket`. An agent sees a ticket's key, project, title, status (To Do or Done), created and done dates, and body (`jira.py`). A search returns the 50 newest tickets and filters by words, status and closed date only (`orchestration/jira.py`). |
| Find older tickets, beyond the newest 50 | read | Planned | Needs a created-date filter and paging in the Jira search. Agents also don't know when the last run was. |
| Find tickets by when they were last updated, their type, component or priority, or who owns them | read | Planned | Those fields never reach the agents. platform-api reads Jira's update date and drops it (`jira_rest.py`), so this is a small backend change (UX audit X2). A request that filters by one of them gets a Part I can do answer that names each missing part, never a set-up card that drops the filter. |
| Sum up what I find | none | Ready | Done by the model, no system access |
| Check software for new releases on GitHub | read | Ready | `github.read_releases` |
| Create a Jira ticket after a yes | write | Ready | `jira.create_ticket` |
| Ask Approvers for a yes in Teams | notify | Ready | The approval card (ADR 0036). The platform does this for every workflow, so the Planner never lists it as a step. |
| Post messages in Teams | write | Planned | The sponsor asked for information in Teams. Not built. |
| Change Confluence pages | write | Planned | The sponsor asked for approval before Confluence updates. Not built. |
| Read GitHub issues | read | Planned | No tool |
| Check who has access in Entra ID, admin tools and GitLab | read | Planned | Phase 2, the quarterly access review |
| Check package registries and security advisories | read | Planned | ADR 0025 |
| Set a field such as a component on new Jira tickets | write | Planned | Needs a new tool, which needs an ADR (ADR 0023, ADR 0037) |
| Send email or Slack messages | write | Unsupported | No plan |
| Close, edit, move or delete tickets | write | Unsupported | A deliberate rule. Only people do that here. |

**Backend dependency.** In the built app the registry is `abilities.py` plus connection health. A `GET /capabilities` route would let the Portal read it instead of copying it. See `IMPLEMENTATION-PLAN.md`.

## 5. Home

### 5.1 Operator, a normal week

From top to bottom:

1. **Greeting and a one-line state.**
   - "Good morning! Alice", the greeting the built app uses since commit 8a2a549. The line under it is computed from `needs()` and the workflows. It names what needs her without repeating the count the section heading already shows, for example "Here's what needs you. Your other workflows are on."
   - When nothing needs her, the line says when the next run is.
2. **The box.** One large text box, with the Visor bot beside it.
   - Placeholder: "What would you like to automate, check or fix?"
   - Enter sends. The send button is labelled for screen readers.
3. **Three suggestions,** chosen from her state, never fixed:
   - "Check my workflows"
   - "Why did Morning new-ticket check stop?" when a workflow is stopped and that stop isn't already the first Needs you row, otherwise "What can I ask for?"
   - "Set up another workflow". It answers with three starting points she can pick from.
4. **Needs you,** shown only when `needs()` has items:
   - Up to three rows, most urgent first. Stopped runs come first, then approvals (urgent ones first), then connection keys that are running out, then confirmations.
   - Each row says what happened, why in one line, and offers one action, such as "Retry the run" or "Review and decide". Only the first row's action is primary, so the screen keeps one primary action (rule 1).
   - "See all on Workflows" appears when there are more than three.

Hidden by default: "What can I ask for?" (the capability lists) and New chat. Needs you is hidden while a conversation is on screen. The tab count still shows it.

Once she sends something, the page becomes the thread (version 3's behaviour): her message, then the Planner's answer, then the box at the bottom with the placeholder "Ask for something else".

### 5.2 Operator, day one

- Heading: "What does your team do again and again?"
- One sentence on what the platform does: "Tell me a task in plain English. I'll set it up to run by itself. Anything that changes data waits for a yes from an Approver in Teams."
- The box, then three concrete starting points:
  - "Every Friday, sum up the tickets we closed this week" (automate). Version 3's first example asked for tickets with no update for 10 days, which today's Jira tool can't see (UX audit X2).
  - "Keep track of the React version" (monitor)
  - "What can you do?" (learn)
- The "I can" list, from the registry, with "What can't I do yet?" collapsed under it.
- No warning counts. Day one starts with fresh connection keys, so Needs you is empty. Version 3 showed a GitHub key running out in 9 days on a brand-new account (inconsistency I5). If something real comes up on day one, such as Jira not answering, it shows in Needs you like any other day, so Home and the tab count never disagree.

### 5.3 Approver only

- Greeting with "1 request is waiting for your yes" or "Nothing needs you right now".
- Needs you in full, each request with Review and decide.
- When nothing waits, one quiet line with the next scheduled run.
- One note: "You're an Approver, so you decide on requests. Operators set up workflows."
- No box, no suggestions, no creation actions.

### 5.4 When there is no AI model

When Settings has no working AI model (a test control can switch this), the Planner can't read new requests, and Home says so instead of pretending:

- An Operator sees the Visor bot in its sorry pose, the line "I can't read new requests until an AI model is connected", and **Connect a model**, which opens Settings, AI model.
- It says what the built app says: agent workflows can't run and new ones can't be planned until a model is connected. Only the Software watchlist's summary uses a simple template instead.
- Capabilities that need the model show as Needs setup.
- The capability lists and Ask the team still work, because they don't need the model.
- Needs you still shows, because it is read from the platform, not the model. Its "No AI model connected" row is left out while the hero already offers Connect a model.

Version 3 let the Planner work on day one with no model (I5). ADR 0037's Consequences already describe this offline answer.

### 5.5 States

| State | What shows |
|---|---|
| Empty (no workflows) | Day one, 5.2 |
| Nothing needs you | The greeting line gives the next run. No Needs you section. |
| Planner thinking | The Visor bot's thinking pose and three dots in the thread. The box is disabled with "The Planner is answering". |
| Planner can't reach the model | 5.4 |
| Error sending | Design only; the prototype can't fail to send. The message stays in the box and an inline line reads "That didn't send. Try again." |

## 6. The Planner's answers

### 6.1 Every answer covers four things

1. What I understood: one line, in her words, only when it adds something.
2. What I can do: the verdict.
3. What I need from you: at most one question, or the one choice left on the card.
4. What happens next: one primary button, and at most one other.

The reply sentence carries 1 and 2. The card carries 3 and 4. Technical words stay out unless she asks.

### 6.2 The answers

| Kind | When | Reply, shortened | Next |
|---|---|---|---|
| Set-up card | A repeated task the registry can do | "Here's what I understood. I filled in what I could." | The card (7) |
| Watchlist card | A release check | "Kubernetes is software, so it belongs on the Software watchlist, which checks all your software every Monday." | Add to the watchlist |
| Which software | A release word with no name | "Which software should I watch?" | Never mind |
| Already listed | It's on the watchlist | "React is already on the Software watchlist." | Open it |
| Can't, with an alternative | A Planned or Unsupported capability | "I can make that list, but I can't send email. Email isn't connected to the platform." | Set up the alternative (primary), Ask the team |
| Part I can do | A request where only part is possible | "I can find these Jira tickets, but I can't change their components yet." | Set up the part I can do, Ask the team |
| Refusal | Asks to skip a yes | "I can't set that up. Anything that changes data waits for a yes, every time." | Set it up with a yes |
| Abilities | "What can you do", or anything off-topic | The I can and Not yet lists | Ask the team |
| **Check my workflows** (new) | "Check my workflows", "is X running" | "You have 3 workflows. 1 stopped, 1 is waiting for a yes, 1 is running." | A row per workflow with its status, next run and one action |
| **Why it stopped** (new) | "Why did X stop", or tapping the suggestion | The AI troubleshooter's four answers (10.3) | Retry the run, or Report to support, and See the run |
| **What needs me** (new) | "What needs me", "anything to approve" | "2 things need you." | The Needs you rows |
| **Offline** (new) | No AI model | 5.4 | Connect a model |

An alternative is offered only when it is a real near-equivalent that the Planner would set up with every part Ready. Otherwise the only next step is Ask the team. For an Unsupported capability the answer says it isn't on the team's plan, for example "Email isn't on the team's plan. Ask the team if you need it." The reply sentence of the new answers is recomputed on every redraw, like the card under it.

The three new kinds answer from platform state, so code decides them and fills them in. In the prototype, simple word rules pick them. In the built app, the model picks the kind and code fills it from platform-api (`IMPLEMENTATION-PLAN.md`).

### 6.3 Asking back

- Ask only for what blocks turning it on, and only one thing at a time.
- Show guesses in grey as "Filled in by me", and never ask her to confirm each one. A guess that changes what gets written, such as the Jira project, is shown as a choice, not filled in silently.
- Every question offers "Never mind".

### 6.4 When the Planner is unsure

It says what is unclear in one line, asks one focused question, and offers the nearest thing it can do. It never invents an agent, tool or system. Every capability it names comes from the registry.

## 7. The set-up card

### 7.1 Layout

The card is titled with the workflow's name and has Rename beside it. It has three sections, then one collapsed section, then the footer.

**What will happen**
- One plain sentence that reads as a whole, for example "Every Friday at 16:00, find the tickets closed this week in Jira project MOCK, sum them up, and put the summary in one new Jira ticket."
- Each part she can change is a chip in the sentence:
  - A part is marked as hers only when the words came from her request. Version 3 marked parts green as "from your words" when the Planner had dropped or added words (UX audit SC1).
  - Grey chips are "Filled in by me".
  - Amber chips need a choice.
  - A red chip names something the platform can't do, with the nearest alternative.
- Tapping a chip opens its small editor in place.
- A similar existing workflow gets one line with a link.

**When**
- "Every Friday at 16:00, Singapore time" and **Change**.
- The guessed ticket set follows the schedule: a daily run reads tickets created in the last day, a weekly run this week. When it can't follow, it becomes a choice.
- The time picker opens only after Change, or by itself when the time is the one thing missing.
- It never guesses a time. "Choose when it runs" stays amber until she picks one.

**What needs a yes**
- Example: "Creating the Jira ticket changes data, so each run waits for a yes in Teams. Any Approver on your team except you can say yes."
- This is today's rule. With Planned features shown, the named Approvers of ADR 0024 appear here, tagged Planned.

**How this workflow works** (collapsed)
- The steps, each marked Reads, Writes after a yes, or No system access.
- The agents as Orbs with their jobs. A new agent is marked "New agent, saved to the Agent library when you turn this on".
- The tools, and the systems each step reads or writes.

**Footer**
- **Turn it on** is the one primary button.
- When disabled, the line beside it names exactly what is missing, for example "1 choice left: the Jira project". When nothing is missing it reads "Nothing is unclear. Turn it on when you're ready." "A yes" always means an Approver's decision, never the Operator's own click.
- After turning it on, the card becomes a short confirmation: the first run time, who will be asked for a yes, and **Do a test run**.

### 7.2 Rules

- Editing a chip redraws the sentence, the footer and the disabled reason from the same state. No other text on the card or in the chat keeps a stale count (I8).
- The promises line (pause, change or delete any time; the AI troubleshooter explains stops) moves into the confirmation, where it matters, and leaves the card.
- "Turn it on" keeps its name. The brief suggested "Turn on automation", but the glossary calls these workflows.

## 8. Workflows

From top to bottom, each section shown only when it has something:

1. **Needs you,** in full: the first item as a card and the rest as rows. It is the same `needs()` list as Home.
2. **Drafts.** Each row has:
   - the name and why it can't be turned on yet ("Needs the Jira project");
   - **Resume**, which reopens the card on Home;
   - **Discard**, which removes it with an Undo in the message.
   
   A draft for something the platform can't do can always be discarded.
3. **Waiting on others,** when she is waiting on someone's yes.
4. **Following up,** when she reported a stop to support.
5. **All workflows.** One row each, with:
   - the name;
   - a one-line purpose;
   - a status (Running, Waiting for a yes, Stopped, Paused, Test run);
   - the next run;
   - at most one action, such as Retry, Review and decide, or Resume. A workflow whose action already shows under Needs you keeps only its status here, so no page offers the same button twice.
   
   No agent faces and no step details in the list. A search button in the section header opens a search box and the All, Stopped and Paused filters. They stay hidden until then.

Empty: "Nothing here yet. Ask the Planner on Home, and your first workflow shows up here." Approver only: "Operators set up workflows, and you approve their changes."

## 9. Workflow page

Order:
1. what it does;
2. current status;
3. the next action;
4. schedule;
5. approval;
6. recent activity.

- **Header.** The name, its status pill, and the plain sentence of what it does.
- **Status banner.** One sentence and one primary action, for example:
  - "Stopped today at 8:00. Jira didn't answer, and it's working again now." with **Retry the run**;
  - "Running. Next run Wed 28 Oct, 8:00." with no button;
  - "Paused. It won't run until you resume it." with **Resume**. Resume shows only here.
- **Pause,** a button beside More actions while the workflow isn't paused. It is hidden while paused, because the banner holds Resume.
- **Schedule.** "Every weekday at 8:00, Singapore time" with **Change**.
- **Approval.** "Each run's ticket waits for a yes from any Approver except you." Named Approvers and Change who approves appear only with Planned features shown.
- **Recent activity.** The runs, newest first, each opening its run page.
- **More actions menu,** a button labelled "More actions" with these items:
  - Run now
  - Change schedule
  - Open in n8n (Operators, and only when the workflow allows it)
  - Delete, last and in red, after a divider
  
  Delete always asks first and names what is lost. Undo stays in the message.
- **Technical details** (collapsed): the steps with what each reads or writes, the agents and tools, who holds it in n8n, and its change history.

## 10. Run page

### 10.1 Default: progress in plain words

- A headline state: Running, Waiting for a yes, Done, Stopped, or No answer.
- The progress list in plain words, for example:
  1. Reading Jira tickets
  2. Preparing the summary
  3. Waiting for a yes
  4. Creating the ticket
  
  Each step shows done, now, waiting, skipped or failed, with the face of the agent doing it. This is the live activity view's station strip, kept visible because it shows who is doing what.

### 10.2 On request: detailed activity

**Show what each agent did** opens:
- the agents' conversation;
- the tool results;
- timestamps;
- errors;
- the replay controls.

It stays open for the rest of the visit.

### 10.3 When a run stops: the AI troubleshooter's four answers

| Question | Example (Jira was down) |
|---|---|
| What happened? | Jira didn't answer at 8:00. It was down for maintenance. |
| What was affected? | Today's check didn't run. Nothing was written. |
| Can it be fixed safely? | Yes. A retry reads the tickets again, and its ticket still waits for a yes. |
| What should you do? | **Retry the run** |

- When she can't fix it herself (a platform bug), the last answer is **Report to support**, with a note box. The case then appears under Following up on Workflows.
- Retry is on the run page itself, not only on Home.

### 10.4 The approval panel

Shown when this person can decide. It lists:

- **What will change:** each write, its target and its content, for example "Create 3 tickets in Jira project MOCK", with each title.
- **Why:** what the agents found, with links to the evidence.
- **Who asked:** the workflow, who owns it, and whether a schedule or a person started this run.
- **What happens:**
  - "Nothing is written until you say yes." The panel says it once. The rest of the line says who was asked and what a decline means, for example "If you decline, the run stops there."
  - Under today's rule, a request waits until someone decides. A stop time and a backup appear only with ADR 0024's named Approvers, which are Planned. Version 3 stopped today's-rule requests at the next run, which the built app doesn't do.
- **Your part:**
  - "You can decide because you didn't set this up or start this run."
  - When she owns it, started this run or retried it, the panel says which, for example "You retried this run, so another Approver must decide." She sees no buttons. One function, `partiesOf(id)`, gives the owner, the starter and the retriers, the same set the built gate refuses (`service.py`).
  - For a two-Approver step: "Bob said yes. Your yes is the second of two."
- **Approve** and **Decline**.

The platform checks the decision again on the server. The panel's summary is help for the reader, not the check.

## 11. Software watchlist

From top to bottom:

1. **Needs attention.** The weekly upgrade request waiting for a yes, with Review and decide. Also any software the check couldn't read, with the AI troubleshooter's fix. Example: "GitHub can't find langchain-ai/langserve. It moved to langchain-ai/langchain." with **Use the new address**.
2. **Software we watch.** A row each with:
   - the name;
   - the version we run;
   - the newest version;
   - the status (Up to date, New version, Can't check). A Can't check with no fix the person can make, such as a rate limit that clears by itself, stays in the table with its reason instead of becoming a Needs attention card;
   - the source.
   
   **Add software** takes plain words ("Kubernetes"). It finds the GitHub project and shows where the guess came from. When more than one project matches, she chooses. She never needs to know what a package registry is.
3. **How it's checked.** "Every Monday at 9:00, Singapore time. One approval covers all the upgrade tickets." Sources:
   - GitHub releases, which works now;
   - package registries, security advisories and support end dates, each shown as "Not yet" by default, and tagged Planned with Planned features on (section 1).
   
   With Planned features shown, the version 3 security findings and their severity appear, tagged Planned. Severity is shown only when a real source backs it.

## 12. Agent library

An advanced area.

- **What it can do.** The opening tab. The registry in plain words, grouped as I can, Needs setup, Not working right now, and Not yet. Each line names the agents that use it.
- **Agents.** The agent cards, each with a plain one-line job. Steps, tools and permissions are inside Details.
  - Changing an agent in plain English shows the exact difference before saving.
  - It is marked as not built in the Portal under the test control.
- **Tools.** Each tool with its plain name, what it reads or writes, and its health from the registry.
  - Asking for a new tool gets the same answer as on Home: the team decides, with Ask the team (I3).
  - Drafting a tool from a published API appears only with Planned features shown.

## 13. Settings

Four groups:
- Connections
- People and permissions
- AI model
- Usage (marked not built)

Each connection says in plain words whether it works, what uses it (from the registry), and the one fix. Examples:
- "Jira is working. Checked today at 9:00."
- "The GitHub key runs out in 9 days. Replace it before then, or the Software watchlist stops."
- "Jira needs attention. The saved key is no longer accepted." with **Replace the key**.

Keys show only their last two characters.

Teams is described as "Sends approval requests to Approvers". Nothing else promises a Teams message (I1).

## 14. The Teams approval message

The Teams drawer shows the card ADR 0036 describes:
- what needs approval;
- which workflow and who owns it;
- each change it would make;
- what the agents found;
- who can decide, and who can't and why ("Carol can't, because she set it up");
- one button, **Open in AI Workflow Builder**.

It has no Approve or Decline. After a decision, the drawer shows the request's state read from the platform, for example "Approved by Bob at 9:14". A notification never authorizes anything.

## 15. Rules for every screen

1. **One primary action per state.** Other actions are quieter or sit in a menu.
2. **Decisions first, details on request.** The plan, agents, tools and logs live in sections named for what they hold.
3. **Infer, but show it.**
   - A guess is grey and editable.
   - A guess that changes what is written becomes a choice.
   - A time is never guessed.
4. **One source per fact** (3).
5. **Say what the AI is doing.** Faces and plain step names, not agent internals.
6. **The person stays in control.** They can review, correct, pause, retry, discard, undo and delete.
7. **Not chat-only.** Chips, menus and buttons where they are faster than typing. The box is for intent.
8. **Accessible.**
   - Every action is reachable by keyboard, with a visible focus ring.
   - Status is never shown by colour alone.
   - The Planner's replies are announced politely.
   - Menus and collapsed sections use the right roles and expanded states.
   - Nothing scrolls sideways at 390 px, and touch targets are at least 44 px.
   - Reduced motion stops every loop.
9. **Honest states.** The same words everywhere:

| State | Shown as |
|---|---|
| AI suggestion | Grey chip, "Filled in by me" |
| Draft | Listed under Drafts, never runs |
| Waiting for a yes | Amber pill |
| On | Pill, with the next run beside it, for a workflow that is switched on and between runs |
| Running | Pill with the step now running, only while a run is in progress |
| Done | Green pill, with what was written and who said yes |
| Stopped | Red pill, with the troubleshooter's reason |
| Test run | Marked "Test run" everywhere it appears |

## 16. Test controls (not part of the product)

They stay in the corner panel, apart from the product screens.

| Control | Choices | Why |
|---|---|---|
| Show | A normal week, Day one | As in version 3 |
| Act as | Alice (Operator and Approver), Bob (Approver only) | As in version 3 |
| AI model | Connected, Not connected | Shows the offline Planner (5.4) |
| Planned features | Hidden, Shown and tagged | Lets reviewers see planned designs without the product claiming them: named Approvers (ADR 0024), more watchlist sources and security findings (ADR 0025), Open in n8n and its history (ADR 0026, 0027), drafting a tool, changing an agent in plain English, coding agents preparing a fix in a support case, replacing a key in Settings, monthly schedules, AI usage, and the access review with its two Approvers in turn |
| Mark what isn't built | Off, On | Outlines the screen parts the built Portal doesn't have yet, taken from `IMPLEMENTATION-PLAN.md` section 1, so a reviewer can tell the prototype from the product |
| Make something happen | As in version 3, plus "Jira stops answering" and "Jira works again" | Shows Temporarily down and its recovery |

"About this prototype" keeps saying the data is sample data and requests are read with simple word rules, not a model.

## 17. The nine inconsistencies

Each was found in version 3 (`03b-PROTOTYPE-UI-INVENTORY.md`, section 8).

| ID | Source in version 3 | Correct current behaviour | Version 4 |
|---|---|---|---|
| I1 | Teams posting is "Not yet" on Home, but "Stale ticket nudge", the Tools tab, Settings, support updates, AI usage and three more lines the audit found all send Teams messages | Teams carries approval requests only (ADR 0036) | Post messages in Teams is Planned in the registry. "Stale ticket nudge" becomes "Weekly closed-ticket summary". A stale-ticket list isn't possible either, because the agents can't see a ticket's update date or owner. Support updates show under Following up. The AI usage warning shows on Home. Settings describes Teams as approval requests only. Needs you loses its "Open in Teams" button. |
| I2 | Samples read GitHub issues, Entra ID, the admin tools and GitLab | Four tools: GitHub releases and Jira. Jira gives title, status, created and done dates, and body, for the 50 newest tickets. | "Morning bug report check" becomes "Morning new-ticket check", which reads tickets created in the last day from the 50 newest. The quarterly access review is Planned and appears only with Planned features shown, where it still shows two Approvers in turn. A request that needs the update date, type or owner gets the Part I can do answer. |
| I3 | A new Jira tool is "the team's decision" on Home, but has a Draft button in the Tools tab and the agent dialog | Tools are built by the team (ADR 0023). Drafting one needs its own ADR (ADR 0037). | One answer everywhere: "I can't add that yet. The team decides on new tools." with Ask the team. The draft flow appears only with Planned features shown. |
| I4 | The set-up card uses today's rule, but the samples and the watchlist card show named Approvers with a backup | Today's rule. ADR 0024 isn't built. | Today's rule everywhere by default. Named Approvers appear only with Planned features shown. |
| I5 | Day one has no model, but the Planner works. Day one also shows a key running out. | No model means the Planner can't read new requests | The AI model control drives the offline answer (5.4). Day one starts with a model connected and fresh keys. |
| I6 | The Agent library says the Planner drafts new agents, but no card ever does | The built Planner drafts an agent card when no saved agent fits (`drafting.py`) | "Every Monday, compare last week's new tickets with the week before" drafts a new agent, shown under How this workflow works and saved when it's turned on |
| I7 | "You can also follow it on Home" and "Check what I understood" point to places that no longer exist | Following up is on Workflows. The card section is What will happen. | Both texts corrected |
| I8 | "I need 2 more answers" is computed once and goes stale | One count, recomputed on each redraw | The chat sentence drops the count. The card footer is the only count. |
| I9 | Home lists GitHub releases only, but the watchlist shows ADR 0025's sources and vulnerability checks as working | GitHub releases only | Other sources and vulnerability checks are Planned, shown only with Planned features shown and tagged |

## 18. Changes to recorded decisions

If the team accepts this spec, these need updating:

1. **ADR 0037.**
   - Needs you also appears on Home, only when it has items. This reverses an option ADR 0037 considered and rejected, "The box on Home with Needs you under it", because in a normal week the box pushes approvals down and a long conversation pushes them further. This spec answers that concern in three ways. The list sits right under the box and shows at most three rows, so the most urgent items stay above the fold. The list is hidden while a conversation is on screen, and the tab badge keeps the count visible. An Approver who can't set up workflows still gets approvals as the whole of Home. The gain is that an experienced Operator, or an Operator who is also an Approver, sees what needs her without knowing to open Workflows (UX audit HM1). The built Home already has Needs you, so this also keeps a working part of the built app.
   - The Planner gains three answers (check my workflows, why it stopped, what needs me) and the offline answer.
2. **The design note.**
   - The placeholder.
   - The set-up card's sections.
   - The drawer's buttons.
   - The run page's two levels.
   - The workflow page's menu.
   - The watchlist's order.
   - The sample workflows.
3. **The prototype's role.** Version 3 showed planned designs as if they worked. Version 4 shows them only on request, tagged Planned.
4. **Glossary.** Add "Capability" (a thing the platform can do, in one of five states). Keep "Needs you" as the one name, rather than the brief's "Needs attention".

## 19. What is simulated in version 4

Everything in the prototype is simulated. Specifically:
- Requests are classified with word rules, not a model.
- The four new answer kinds read sample state.
- Runs are scripted replays.
- Connections, keys and Teams are sample data.
- Time stands still at Tuesday 27 October, 9:10.

"Mark what isn't built" shows which screen parts the built Portal lacks. `IMPLEMENTATION-PLAN.md` lists what each needs from the backend.

## 20. How it was checked

All results below are for commit 513b95a. Their files are in `checks/results/`. `USER-JOURNEY-COMPARISON.md` compares each scenario.

- **Scenarios.** The same harness (`checks/run.cjs`) ran scenarios A to H and the 15 tasks of version 3 on both versions, counting clicks, typed fields, choices and pages.
  - Version 3 passed 27 of 27. Removing a draft was not possible in version 3.
  - Version 4 passed all 40 of its scenarios. These include 12 new ones: acting from Home, the Planner's status answers, no AI model, Jira down, Planned features shown, and scenarios A and C done by keyboard only.
  - A second run gave identical counts for all 40.
- **The judge's checks.** An independent judge wrote `checks/paths-v4.cjs` and `checks/validate-v4.cjs`, separate from the builders. `validate-v4.cjs` passed 31 of 31, and its seeded control failed as it should. The checks cover:
  - counts that agree across Home, Workflows, the tab badge and the Planner;
  - the set-up card agreeing with itself;
  - roles and the two Approvers in turn;
  - no approving in Teams;
  - refusals;
  - no Planned or Unsupported capability shown as working;
  - alternatives that set up cleanly (15 offered across 18 requests);
  - no long dashes;
  - zero console errors.
- **Planted defects.** The judge planted 14 defects, each in its own copy of the prototype. The judge's checks caught all 14, each with the expected message. Examples:
  - an Approve button in Teams;
  - self-approval;
  - count drift;
  - a retry that succeeds while Jira is down;
  - three primary buttons on Home.

  The builders' gates caught fewer. At b6cc589 they missed the count drift, an alternative offered without checking it sets up, and a Planner crash. Fix round C added gate checks that fail on the crash and on count drift. No builder gate yet catches the unchecked alternative. Only the judge's `alternatives-set-up-cleanly` does.
- **The builders' gates.** `gates-p0.cjs` passed 36 checks, `gates-p1a.cjs` 58, `gates-p1b.cjs` 54 and `gates-p2.cjs` 63. Each gate's seeded controls still fail. The gates check I1 to I9 by name.
- **Quality.** `checks/quality.cjs` checked 26 screens at 1280 and 390 px.
  - axe found 0 critical and 0 serious problems. It found 12 moderate (heading order, regions) and 2 minor.
  - Nothing scrolls sideways at 390 px.
  - No animation runs under reduced motion.
  - The keyboard reaches the Operator's box in 9 Tab presses and Bob's Review and decide in 8, with visible focus at every stop.
- **Screenshots.** 32 before and 52 after, all shot by `checks/shots.cjs` at 1280 and 390 px (`screenshots/README.md`).
- **The build target is untouched.** `git diff main -- docs/design/portal-routines` is empty.

These are automated checks, not user research. A study with real CODESparks support staff should come next. It would measure:
  - task success;
  - time to finish;
  - errors;
  - confidence;
  - perceived effort.
  
  It would use the same scenarios A to H.
