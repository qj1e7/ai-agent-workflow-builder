# AI-native UX redesign of the AI Workflow Builder

Status: the build target since 7 Nov 2026. ADR 0043 (proposed) redrew the prototype as a chat with a rail, in four steps. Steps 1 to 3 merged on 10 and 11 Nov (#204, #205, #206), and this spec follows them. Step 4, roles, is still being built, and the paragraphs it may change are marked.

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
2. **One source of truth for what the platform can do.** A capability registry decides what the Planner offers, what Home lists, what How it works and Settings show, and which watchlist sources appear. A capability is in exactly one state.
3. **Decisions first, details on request.** Each screen leads with what the person must understand or decide. The plan, the agents, the tools and the logs sit one click away, under plainly named sections.
4. **Honest states.** The person can always tell a suggestion from a fact, a draft from a live workflow, a test run from a real run, and "waiting for a yes" from "done".

## 3. Information architecture

ADR 0043 replaced the tabs with a rail and made Home a chat. Where an item opens depends on where it was opened from.

### 3.1 The rail and the header

A slim rail on the left holds three items. Each can carry a count, with words for screen readers such as ", 5 need you". The current item is marked.

| Item | Opens | Count |
|---|---|---|
| Chat | Home, the chat (5) | What needs this person, for someone who isn't an Operator |
| Workflows | The Workflows page, full width (8) | What needs this person, for an Operator |
| Watchlist | The Software watchlist, full width (11) | What needs action on the watchlist |

- **Going back to Chat** returns the conversation where it was, scroll position included.
- **The header** keeps AI Workflow Builder (to Home), Teams with its own count of approvals waiting for this person, Settings, and the signed-in person.
- **How it works,** the old Agent library, is a tab in Settings, for Operators only (12). No daily task needs it.
- **Every role sees the three items** today.

<!-- step 4: confirm against the prototype -->
ADR 0043 makes the rail's lists read only for an Approver who can't set up workflows.

### 3.2 Where an item opens

| Opened from | A workflow, run, approval or software opens |
|---|---|
| The rail, or a page | As a full page. A workflow page's Back says Workflows. A run page's Back names its workflow, or Software watchlist. |
| A card in the chat, or the pinned line | In the side panel beside the chat, so the conversation stays in view |
| Inside the side panel | "Open the run" and More details open a full page with "Back to the chat". The panel is still there on return. |

A list opened from the chat, such as "N more" on the pinned line or a link to Settings, also opens as a full page with Back to the chat. "Keep our software up to date" always opens the Software watchlist page.

### 3.3 The side panel

- **One item, as a summary.** The panel shows what the item is, its state and the next step, and the chat keeps the width. It keeps no history: opening another item replaces it.
- **Its bar** has the title, More details when the item has a page, and Close. Escape closes it too, and focus goes back to what opened it.
- **What each kind shows.**
  - Workflow: its status, its sentence, a stop's three answers (10.3) with Retry, the last and next run, Open the run, and Pause or Resume.
  - Run: its state, headline and the run line, small (10.1), with a stop's three answers and Retry, or the questions asked on it.
  - Approval: everything that will be written (10.4).
  - Software: its status, the version you run, the newest, and "Checked by The Version checker, every Monday, on GitHub". More details opens the Software watchlist.
- **Actions stay in the panel,** because they change something rather than go somewhere: Approve, Decline, Ask a question, Retry, Pause and Resume. After one, the panel goes back to its top and focuses its heading. The schedule is changed on the workflow's page, or by asking in the chat (6.7).
- **A flow shows once.** While an item is open in the panel, the chat hides the buttons that open it and its own copy of the steps. Both come back when the panel closes.
- **Width.** It is 400 px wide, or 40% of the window when that is less. It opens by itself only while the Planner builds (6.8).

### 3.4 One breakpoint, 900 px

The layout changes once, at a window 900 px wide or narrower:

- the rail becomes a bar across the top, with the three items side by side;
- the side panel opens over the whole window with Close, only when the person presses Open, and the chat behind it can't be reached until it closes;
- the side panel never opens by itself;
- the header stops sticking to the top, and the page loses its frame.

### 3.5 Needs you, pinned and grouped

- **The pinned line.** During a conversation, one line at the top of the chat names the most urgent item, with Open and "N more". For example "Morning new-ticket check stopped. Jira didn't answer at 8:00." with Open and "4 more". Screen readers hear it as the region "Most urgent".
  - Open opens that item. A stop or a request opens its run in the side panel. Anything else follows the item's own first action.
  - "N more" opens Workflows, with Back to the chat.
  - It shows only while there is a conversation and something needs the person. A "can't" answer never hides it.
- **Two groups.** Wherever Needs you is listed in full, it is grouped:
  - **Do now:** stops, approvals, questions to answer, a declined test run, a fix from support that is live, and anything that stops all runs, such as no AI model or Jira not answering.
  - **Set up:** keys that are running out, software whose source moved, and confirmations. With Planned features shown, AI usage near its limit too.

  Within that, the most urgent comes first.

### 3.6 Addresses

A typed or shared address opens its screen: `#home`, `#workflows`, `#watchlist` (shown as `#software`), `#software` and `#agents`. `#agents` opens Settings on How it works for an Operator, and Home for anyone else. `#faces` opens a hidden page of the agents' faces. Any other address opens Home, `#settings` included. A workflow, run or approval has no address of its own in the prototype.

### 3.7 Single sources

One function feeds every place that shows the same fact, so no two places can disagree:

| Fact | One source | Shown on |
|---|---|---|
| What needs this person | `needs()`, sorted by urgency | Home's Needs you, the pinned line, the Workflows section, the rail count, the Planner's "what needs me" answer |
| What needs action on the watchlist | `swAttnCount()` | The Watchlist count on the rail |
| A workflow's last run | `status()` | The Workflows rows, the Planner's check card |
| A stopped run's three answers | `TROUBLE` | Needs you, the pinned line, the chat's card, the side panel, the run page |
| A declined run's record | `declinedWords()` | Every place a declined run shows (10.5) |
| What a set-up card still lacks | `setupLeft()` | The card's footer, the reason Turn it on is off, and the draft's line on Workflows. The chat sentence repeats no count. |
| What the platform can do | `CAPS` and `capState()` | The Planner's answers, "What can I ask for?", How it works, Settings Connections, the watchlist sources, the approval's Not checked line |

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
| Read Jira tickets | read | Ready | `jira.search`, `jira.read_ticket`. An agent sees a ticket's key, project, title, status (To Do or Done), created and done dates, and body (`jira.py`). A search filters by words, status and closed date, then returns up to 50 matching tickets, newest first (`orchestration/jira.py`, `jira_rest.py`). A busier week is cut short, and nothing tells the run yet (`IMPLEMENTATION-PLAN.md`, N4). Every workflow that reads Jira says this under How this workflow works, and no text promises "all" tickets. |
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

**Backend dependency.** In the built app the registry is `abilities.py` plus connection health, served by `GET /api/v1/capabilities`, so the Portal reads it instead of copying it. See `IMPLEMENTATION-PLAN.md`.

## 5. Home, the chat

### 5.1 Operator, a normal week

From 8 Nov 2026 Home is the front door for software versioning, and the general workflow builder is frozen. Everything Home and Workflows say without being asked is about software versioning only: watching software for new GitHub releases, asking Approvers for a yes in Teams, creating the upgrade Jira ticket after that yes, and the Software watchlist. The capability registry marks those lines as `focus`, and there is no Not yet list. When a person asks for something else, such as email, the Planner still says plainly that it can't, so no part of a request is dropped silently (principle 4).

**Before the first message,** Home is calm and keeps version 3's look. The user chose this on 7 Nov. From top to bottom:

1. **The Visor bot, then the greeting and a one-line state,** centred. The bot is 128 px (96 px on a phone).
   - "Good morning! Alice", the greeting the built app uses since commit 8a2a549.
   - The line under it is computed from `needs()` and the workflows. It never repeats the count the Needs you heading shows, for example "Some things need you. Your other workflows are on." When nothing needs her, it says what is next: "Nothing needs you. Next up: ...".
2. **The box.** One large text box.
   - Placeholder: "Ask about your software versions, or name software to watch".
   - Enter sends. The send button is labelled for screen readers.
3. **Three suggestions:** "Which software has a newer version?", "Watch another software for new versions" and "What can you do?".
4. **Needs you,** shown only when `needs()` has items:
   - The heading with its count, then up to three rows from the Do now and Set up groups (3.5), most urgent first.
   - Each row says what happened, why in one line, and offers one action, such as "Retry the run" or "Review and decide". Only the first row's action is primary, so the screen keeps one primary action.
   - "See all on Workflows" when there are more than three.
5. **"What can I ask for?"** opens the capability lists, and becomes "Hide what I can do".

**Once she sends something,** the page becomes the chat:

- The box moves to the bottom, with the placeholder "Ask for something else". The conversation fills the page.
- The pinned Needs you line (3.5) sits at the top, with **New chat** beside it. New chat clears the conversation and closes the side panel. A set-up card she hadn't finished is kept as a draft: "Your draft is saved. Find it on Workflows."
- The chat is still not the record. Every card is a live view of the same data the pages use (6.8), and what the Planner sets up becomes a workflow or a watchlist row with its own page.
- Leaving for Workflows or the Watchlist and coming back to Chat returns the conversation where it was.

### 5.2 Operator, day one

- Heading: "Which software should we keep up to date?"
- The line: "Ask about your watchlist, or tell me what software to watch."
- The box, then two suggestions: "Keep track of the LangGraph version" and "What can you do?".
- The "I can" list, open.
- No warning counts, and no Needs you. Day one starts with fresh connection keys and nothing has run. If something real comes up on day one, such as Jira not answering, it shows in Needs you like any other day, so Home and the rail count never disagree.

### 5.3 Approver only

<!-- step 4: confirm against the prototype -->
ADR 0043 gives an Approver who can't set up workflows the box, for questions only. It answers what waits for their yes and what they decided before. A request to set something up gets "Operators set up workflows."

<!-- step 4: confirm against the prototype -->
Until step 4 of the redraw, the prototype gives them no box and no chat. Home shows the greeting with "1 request is waiting for your yes", Needs you in full with the first request as a card and Review and decide, and the note "You're an Approver, so you decide on requests. Operators set up workflows." When nothing waits, it says "All quiet" with what is next.

### 5.4 When there is no AI model

When Settings has no working AI model (a test control can switch this), the Planner can't read new requests, and Home says so instead of pretending:

- An Operator sees the Visor bot in its sorry pose, the heading "I can't read new requests until an AI model is connected", the line "Without an AI model, the Planner can't answer questions. The Software watchlist keeps checking for new releases.", and **Connect a model**, which opens Settings, AI model. There is no box.
- A conversation that was open stays hidden until a model is connected again.
- It says what the built app says: agent workflows can't run and new ones can't be planned until a model is connected. Only the Software watchlist's summary uses a simple template instead.
- Capabilities that need the model show as Needs setup in the capability lists, which still show.
- Needs you still shows, because it is read from the platform, not the model. Its "No AI model connected" row is left out while the hero already offers Connect a model.
- A row whose action needs the model says so instead of offering it, for example "Can run again once an AI model is connected." with See the run. Actions that work without the model, such as Review and decide and Report to support, stay. The rule is the one every Retry and Run reads (`cantRunWhy`), and it also holds a run back while a key needs replacing. A system that is down may answer at any moment, so its Retry stays and says why if it still can't start.

Version 3 let the Planner work on day one with no model (I5). ADR 0037's Consequences already describe this offline answer.

### 5.5 States

| State | What shows |
|---|---|
| Empty (no workflows) | Day one, 5.2 |
| Nothing needs you | The greeting line gives what is next. No Needs you section, and no pinned line in the chat. |
| Planner thinking | The Visor bot's thinking pose and three dots with "Working on it…", then "Still working. Questions about your data take a little longer." The box is disabled with "The Planner is answering". |
| Planner can't reach the model | 5.4 |
| Error sending | Design only; the prototype can't fail to send. The message stays in the box and an inline line reads "That didn't send. Try again." |

## 6. The Planner's answers

### 6.1 What an answer holds

1. **A reply sentence.** It says what the Planner understood and what it can do. Technical words stay out unless she asks.
2. **A card, most of the time.** It shows each part of the request with its mark (6.5), asks at most one question (6.6), and offers the next step.
3. **One primary button.** Quieter buttons, such as See the run or Ask the team, sit after it.

A few answers have no card: the question about which software to watch, "No problem" after she backs out, and some answers about her data.

### 6.2 How a request is routed

Code reads a request in this order and stops at the first rule that fits. In the prototype, word rules do this. In the built app, the model reads the request and code decides (`IMPLEMENTATION-PLAN.md`, section 4).

1. A request to skip a yes is refused.
2. A reply to "Which software should I watch?" is read as the software's name. "Never mind", "cancel", "no", "forget it" or "skip" backs out, with "No problem. Ask for something else whenever you like."
3. A short follow-up such as "and FastAPI?" or "what about React?", right after an answer about software, is read against that answer.
4. A question about her workflows, her approvals or her software is answered from platform state (6.4).
5. A change to a workflow she already has gets the edit card (6.7). Only an Operator gets it.
6. A release word, a security word, or a known software name with watch, track or monitor goes to the Software watchlist answers.
7. Anything else is read as a task. It gets a set-up card, the part I can do, a can't, Jira not answering, or what the Planner can do.

"No, set it up as a new workflow" on a watch card skips step 6 and reads the request as a task.

### 6.3 The answers

| Kind | When | Reply, shortened | Card and next step |
|---|---|---|---|
| Set-up card | A repeated Jira task with at least one part in her own words | "Here's what I understood. I filled in what I could." With a cross: "Here's what I understood. I can't do every part of it." | The card (7) |
| Watch card | Software to watch | "LangGraph is software, so it belongs on the Software watchlist, which checks all your software every Monday." | "Add LangGraph to the Software watchlist", with its parts, **Add LangGraph**, and "No, set it up as a new workflow". Once added: "LangGraph is on the Software watchlist." with Open Software watchlist. |
| Already listed | The software is on the watchlist | "LangGraph is already on the Software watchlist." | Open it |
| Which software | A release word with no name | "You mentioned "releases", so this belongs on the Software watchlist. Which software should I watch?" | No card. She types the name. |
| Can't, with an alternative | A part the platform can't do, such as a destination other than one Jira ticket | "I can write that summary, but I can't send email. Email isn't on the team's plan. Ask the team if you need it." | "What I can do instead", with the part marked "Can't do this" or "Can't do this yet". **Set that up**, then Ask the team. A request to change tickets gets only "Only people change tickets here." and Ask the team. |
| Part I can do | A filter the agents can't see, or a new Jira tool | "I can find tickets by when they were created or closed, but I can't tell a ticket's type yet. Those details don't reach the agents yet." | "The part I can do", with **Set up the part I can do** and Ask the team |
| Refusal | A request to skip a yes | "I can't set that up. Anything that changes data waits for a yes, every time." | "What I can do instead", marked "Not allowed", with **Set it up with a yes**. When nothing is left to set up, "How approvals work" with no button. |
| What I can do | "What can you do?", or nothing to set up | "Here's what I can do for software versions." Off-topic: "I can't help with that here. I check software versions and watch for new releases. Here's what I can do." | The I can, Needs setup and Not working right now lists, and "Anything that changes data waits for a yes in Teams." There is no Not yet list. |
| Check my workflows | "Check my workflows", "how are my workflows doing" | "You have 3 workflows. 2 stopped and 1 is waiting for a yes." | A row per workflow: its name, status, next run, last run (8) and at most one action. Only the first action is primary. |
| One workflow | "When does the software check run next?", "is it paused" | "Morning new-ticket check stopped. Its next run is Wed 28 Oct, 8:00." | That workflow's row |
| Why it stopped | "Why did X stop?", "what went wrong" | "Morning new-ticket check stopped. Here's what the AI troubleshooter found." If it hasn't stopped: "... hasn't stopped. It's on, and its next run is ..." | The AI troubleshooter's three answers (10.3), Retry the run or Report to support, and See the run |
| What needs me | "What needs me?", "anything for me?", "my approvals" | "5 things need you." | Needs you, grouped Do now and Set up (3) |
| Her data | A question about her software (ADR 0042) | "LangGraph is behind. You run 1.2.14 and the newest is 1.2.17." | "Looked at: Software". For one software: Open it on the Software page, Stop watching (which asks first) and Check all software now. For software not on the list: Watch it. |
| Places to start | "Set up another workflow" | "Here are three places to start. Pick one, or tell me something else." | Today one chip, "Keep track of the React version" |
| Jira not answering | A Jira task while Jira is down (a test control) | "Jira isn't answering right now, so I can't check that. I'll be able to once it's back." | "Keep it for later?" with **Save as a draft** |
| Edit card | A change to a workflow she has | "Here's the change. Nothing changes until you save it." | The edit card (6.7) |
| No such check | A change to a check she doesn't have | "You don't have a React check. React isn't on the Software watchlist, which checks software every Monday." | Watch React |

With no AI model, the Planner gives no answer. Home says so instead (5.4).

An alternative is offered only when it is a real near-equivalent that sets up with every part Ready. Otherwise the only next step is Ask the team. For an Unsupported capability the answer says it isn't on the team's plan.

Code decides and fills in the answers that read platform state: check my workflows, one workflow, why it stopped, what needs me, and her data. In the prototype, word rules pick them. In the built app, the model picks the kind and code fills it from platform-api.

### 6.4 Questions in any wording, and changes that fail closed

- **Any wording.** A question about her workflows, approvals or software gets its answer from platform state, however she words it. "What needs my attention today?", "anything for me?" and "what's waiting on me" all get What needs me. "When does the software check run next?" gets that workflow's state and next run.
- **A change word makes it a command.** Code takes out the question's own words and the workflow's name. If a change word is left, from "make" to "monthly", the text goes to the edit card, never to a status answer. "What needs my attention? Pause the morning check" gets "From the chat I can only change when Morning new-ticket check runs."
- **A workflow's own name is neither.** A schedule word inside a name, such as "Weekly" in Weekly closed-ticket summary, is not read as a schedule or a command. "Make the weekly summary run at 10am" changes only the time.
- **"The run" is a noun.** Asking about "the run" is not a command to run something.

### 6.5 Every part shows what happened to it

The set-up card and the watch card list each part of the request with a mark:

| Mark | Means |
|---|---|
| A tick, "Will do" | The Planner will do this part |
| A cross, "Can't do", with its reason | It can't do this part, or didn't follow it |
| An amber question mark, "Question" | The one thing it is asking now (6.6) |
| A grey question mark, "Asked next" | A question that waits its turn |

- **Every clause gets a mark.** A clause ends at a comma or a full stop, or at "and", "then", "but", "also" or "plus". A clause no rule read is quoted whole, with "I didn't follow this part." In a clause a rule did read, only the unread words are quoted. Little words such as "the" don't count, but verbs do, so "let me know" still gets a cross.
- **Other crosses** name their reason:
  - "Ask this on its own, and I'll answer it." for a question inside a request;
  - "I can only set one day." or "I can only set one time.";
  - "I can't run things monthly yet.";
  - a source the platform can't read, such as GitLab;
  - on the watch card, a time: "The Software watchlist checks all your software together, every Monday at 9:00. I can't give one software its own time yet."
- **A cross changes the button.** While any part has a cross, the button says "Set up the part I can", the footer says "The part with a cross is left out.", and "Nothing is unclear" never shows.
- **What was left out stays visible.** After she turns it on, the confirmation and the workflow's page keep a Left out line, such as "Left out: "colour them by team". It was set up without that part."
- **No card of guesses.** A request with no part in her own words gets what the Planner can do, with its crosses, never a set-up card the Planner filled in alone.
- **Other answers mark their leftovers too.** The part, can't, no such check, her data, check my workflows, what needs me, why it stopped and one workflow answers show the clauses they didn't read above their card. The refusal, Jira not answering, which software and places to start don't.

### 6.6 One question at a time

- **Ask only what blocks turning it on, one thing at a time,** as choice buttons on the card. The order is how often, then the day for a weekly run, then the time, then which tickets, then the Jira project, then what it does:
  - "How often should it run?" Every day, Every weekday or Every week. Every month shows only with Planned features shown.
  - "Which day should it run?"
  - "What time should it run?" 8:00, 9:00, 13:00, 17:00 or Another time.
  - "Which tickets should it find?"
  - "Which Jira project should it use?"
  - "What should it do with them?"
- **A time is never guessed.** A bare hour asks "At 9:00 or 21:00?". Two days ask "Monday or Friday?" and two times ask "9:00 or 17:00?", and neither picks the first one.
- **The watch card** asks "Is this the right project?" with Looks right and Change, then "Which version do you run?".
- **Guesses show.** A value the Planner filled in is a grey chip, "Filled in by me", that she can change. A guess that changes what is written, such as the Jira project, is asked, not filled in.
- **Backing out.** The edit card has Never mind. The other questions have no Never mind button. She leaves one by asking for something else, or by typing "never mind" to the which-software question.

### 6.7 The edit card

A workflow can be changed by asking. In this first version, the edit card changes only the schedule.

- **When it shows.** A change word with a workflow she names: its full name, a short form such as "the morning check", a watched software such as "the React check", or "it" for the workflow just discussed. For example, "Make the morning new-ticket check run on Mondays only".
- **What it shows.** "Change Morning new-ticket check", then When it runs, with only what changes, Before and After. For the watchlist it adds who will own the schedule.
- **Save change and Never mind.** Never mind answers "No problem. Nothing changed."
- **Saving publishes a new version,** through the same path as the schedule editor on the workflow's page. The card says "Saved as version 2. Next run Mon 2 Nov, 8:00." with Undo. Undo publishes again, "Undone, as version 3.", and the workflow's page lists both versions (9).
- **After saving it says what follows.**
  - On the watchlist: "You now own this schedule, so you can't approve its checks."
  - On a paused workflow: "Saved. Morning new-ticket check is paused, so it won't run until you resume it."
  - If the workflow was changed again on its page: "Saved as version 2. Changed again since, on its page.", with no Undo.
- **What it can't change** gets an honest answer. Any other change gets "From the chat I can only change when Morning new-ticket check runs." with Open Morning new-ticket check. Monthly gets "I can't run things monthly yet."
- **A clash holds Save.** Two days or two times for one schedule get a cross and hold Save, with "Ask again without the part with a cross." A question asked alongside keeps its cross and doesn't hold Save.
- **A workflow she doesn't have is named.** "You don't have a workflow called "morning check"." "Make it daily" right after a set-up card asks "Which workflow?" with the draft above first. Picking the draft changes it there: "Changed on the draft above."

### 6.8 Live cards

- **Every card is a live view.** The prototype works out each answer's sentence and card again on every redraw, from the same state the pages read. A workflow turned on in the chat and then paused on its page reads as paused back in the chat. An approval decided on another page shows in the card.
- **The side panel opens by itself while the Planner builds,** only when the window is wider than 900 px. It shows "Draft", "Adding the steps…", the plain steps arriving one by one, and "It runs once you turn it on from the card in the chat." After Turn it on it becomes the workflow's panel. Focus stays on the card's heading. While the panel shows the steps, the card hides How this workflow works and its own Open button. The panel shows plain steps, not n8n blocks, and keeps its usual width.
- **Cards fit beside the panel.** A card lays out by its own width. In a narrow chat, the part rows go to two columns.

### 6.9 When the Planner is unsure

It says what is unclear in one line, asks one focused question, and offers the nearest thing it can do. It never invents an agent, tool or system. Every capability it names comes from the registry.

## 7. The set-up card

### 7.1 Layout

- **The title** is the workflow's name, the Planner's guess, with Rename beside it.
- **The parts,** one row each with its mark (6.5): When, Which tickets, Jira project, What it does and Where it goes. For example, When reads "Every Friday at 17:00, Singapore time" with Change.
- **Chips.** Each value she can change is a chip. Green means her words, blue means she chose it, and grey means the Planner filled it in, labelled "Filled in by me" for screen readers and on hover. A missing value is a question and a part the platform can't do is a cross, so the card has no amber or red chips.
- **Where it goes** is a grey chip, "one new Jira ticket", then "after a yes". Its editor says "One new Jira ticket in Jira project MOCK, created only after an Approver says yes." and "It's the only place I can put the summary today. Other places, such as Teams or email, aren't built yet.", with Done and Ask the team. It adds no step and no choice.
- **A similar workflow** gets one line: "You already have a similar workflow, Weekly closed-ticket summary. Open it".
- **What needs a yes.** "Creating the Jira ticket changes data, so each run waits for a yes in Teams. Any Approver on your team except you can say yes." This is today's rule. With Planned features shown, ADR 0024's named Approvers appear here, tagged Planned.
- **How this workflow works** (collapsed):
  - the steps, each marked "Reads up to 50 ...", "No system access" or "Changes data, waits for a yes";
  - the note that a read stops at the 50 newest tickets;
  - the agents as Orbs. A new one is marked "New agent, saved under How it works, in Settings, when you turn this on";
  - the tools.
- **The footer.** **Turn it on** is the one primary button, or **Set up the part I can** while a part has a cross. When it is off, the line beside it names what is missing, such as "1 choice left: the Jira project". When nothing is missing and nothing is crossed, it reads "Nothing is unclear. Turn it on when you're ready."
- **After Turn it on,** the card becomes a short confirmation:
  - "Weekly closed-ticket summary is on." with the first run, Singapore time, and "Before its ticket is created, any Approver on your team except you is asked for a yes in Teams.";
  - the Left out line, if a part had a cross;
  - the promises line: pause, change or delete any time, and the AI troubleshooter explains stops;
  - **Do a test run**, with "A test run does the real work once, so it still waits for a yes.", and See it in Workflows. The prototype has a sample run only for the first workflow made in a visit, so only that one offers Do a test run.

### 7.2 Rules

- **One source for what is left.** `setupLeft()` feeds the footer's line, the reason Turn it on is off, and the draft's "Needs ..." line on Workflows. The chat sentence repeats no count (I8).
- **The tickets follow the schedule.** A daily run reads tickets created in the last day, a weekly run this week.
- **Answering changes only what it answers.** Answering a question or editing a chip redraws the parts, the footer and the button from the same state.
- **"Turn it on" keeps its name.** The glossary calls these workflows, so it is not "Turn on automation".

## 8. Workflows

The page opens with "The jobs that run by themselves, such as the Software watchlist, and what needs you." From top to bottom, each section shown only when it has something:

1. **Needs you,** in full, grouped Do now and Set up (3). The first item is a card. A stopped run's card carries the AI troubleshooter's three answers (10.3). The rest are rows with one button each. It is the same `needs()` list as the pinned line and the rail.
2. **Drafts** (Operators only). Each row has:
   - the name and why it can't be turned on yet ("Needs the Jira project");
   - **Resume**, which reopens the card in the chat;
   - **Discard**, which removes it with an Undo in the message.

   A draft for something the platform can't do can always be discarded.
3. **Waiting on others,** when she is waiting on someone's yes, for example "A yes from any Approver on your test run".
4. **Following up,** when she reported a stop to support, with the case and how far it has got.
5. **All workflows.** One row each, with:
   - the name and a one-line purpose;
   - one status: On, Waiting for a yes, Stopped or Paused, and Test run when it is one. No answer shows only with Planned features shown;
   - the next run, hidden while paused;
   - at most one action, such as Review and decide, Resume, Retry the run or Report to support. A workflow whose action already shows under Needs you keeps only its status here, so no page offers the same button twice;
   - **its last run,** on one line, such as "Last run Mon 26 Oct · Declined by Bob", "Last run Today 8:00 · Stopped" or "Last run Mon 26 Oct · 3 tickets proposed", or "No runs yet". The chat's check card reads the same function, so the two never differ.

   A search button in the section header opens "Find a workflow" and the All, Stopped and Paused filters. They stay hidden until then. "Keep our software up to date" opens the Software watchlist, which is its page.
6. **"Ask the Planner for a new one"** (Operators only), a last row that goes to the chat.

Empty: "Nothing here yet. Watch software on the Software page, or ask the Planner on Home. Its checks show up here." Approver only: "Operators set up workflows, and you approve their changes."

<!-- step 4: confirm against the prototype -->
An Approver who can't set up workflows sees Needs you and All workflows, with no Drafts, no Waiting on others and no row to ask for a new one. ADR 0043 makes the rail's lists read only for them.

## 9. Workflow page

Order:
1. what it does;
2. what was left out, if anything;
3. current status;
4. the next action;
5. schedule;
6. approval;
7. recent activity;
8. versions.

- **Header.** Back to Workflows (or Back to the chat, 3), the status pill, the name, and the plain sentence of what it does.
- **Left out,** when a part had a cross: "Left out: "colour them by team". It was set up without that part."
- **Status banner.** One sentence and at most one primary action:
  - "Stopped today at 8:00. Jira didn't answer, and it's answering again now." with **Retry the run**. While Jira is still down: "... and it still isn't answering.";
  - "Stopped on Fri 23 Oct at 16:00, on a ticket the platform couldn't read." with **Report to support**, then "Reported to support as SUP-1042." once reported;
  - "On. Next run Wed 28 Oct, 8:00." with no button;
  - "Paused. It won't run until you resume it." with **Resume**.
- **Pause,** beside More actions, for Operators while the workflow isn't paused. It is hidden while paused, because the banner holds Resume.
- **Schedule.** "Every weekday at 8:00, Singapore time", the next run, and **Change**. The editor, "Change schedule", has How often, Day and Time, with Save and Cancel. Saving publishes a new version, as the edit card does (6.7), with "Saved. Next run ...".
- **Approval.** "Each run's ticket waits for a yes from any Approver except you." Then "Every Approver is asked in Teams. The request waits until one of them decides, and nothing changes before that." Named Approvers and Change who approves appear only with Planned features shown.
- **Recent activity.** The runs, newest first. The newest opens its run page with See the run. A declined run says so here.
- **Versions,** once there is more than one. Each published version with when, who and what changed, for example "Version 2. Today, 9:10. Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00. This is the version running now." Undo after a chat change is on the chat's card, and its new version shows here too.
- **More actions menu,** a button labelled "More actions" with:
  - Run now, where the workflow has a sample run;
  - Change schedule;
  - Open in n8n, only with Planned features shown, tagged Planned;
  - Delete, last and in red, after a divider.

  Delete always asks first: "It stops running and leaves Workflows. Its schedule and settings go with it. Its past runs and their records stay. You can undo this from the message that follows." Undo stays in the message.
- **Technical details** (collapsed): the steps with what each reads or writes, and the agents and tools. "In n8n" and "Change history" show only with Planned features shown.

<!-- step 4: confirm against the prototype -->
**n8n views.** ADR 0043 shows n8n views only to people with n8n access, and everyone else sees the plain steps. Today the prototype shows them to Operators with Planned features shown.

An Approver sees the page without Pause, More actions, Change or the banner's button.

## 10. Run page

### 10.1 Default: where the run is

- **Back.** The workflow's name, or Software watchlist. Opened from the chat it says "Back to the chat".
- **A headline and a status pill.**
  - Waiting for a yes: "3 tickets are waiting for a yes".
  - Stopped: "Stopped at Find new tickets", or "Stopped before changing anything" when an n8n change removed the yes step.
  - No answer, only with Planned features shown: "No answer, nothing was written".
  - Declined: "Declined, nothing was written".
  - Done: "3 tickets created in Jira", or "Done, nothing new today".

  While a finished run replays, the head says "Replaying the run".
- **The run line.** The steps in plain words, each with the face of the agent doing it, and a link into each step that shows its state without reading:
  - dashes march into the step at work;
  - slower amber dashes march into a step waiting for a yes;
  - red dashes lead to where it stopped;
  - faint dots lead into skipped steps;
  - a link turns solid once the step after it is done.

  Each step can carry a word under it: Stopped here, Waiting for a yes, No answer, Declined, Not needed, or Nothing written on a declined run's write step. A screen reader hears Done, Now or Not reached yet for each step. With reduced motion nothing moves, and the states still read. The side panel shows the same line, small and upright, without faces.

### 10.2 On request: what each agent did

**Show what each agent did** opens the agents' conversation, with "X and Y joined" where agents come in, and Replay the run once it has finished, at 1x, 2x or Instant. It is open while the run plays and folded at the end. **Hide what each agent did** folds it again.

What shows first follows the run's state:

| State | First |
|---|---|
| Waiting for a yes | The approval panel (10.4) |
| Stopped | The AI troubleshooter's three answers (10.3) |
| Declined or No answer | The record of what happened (10.5) |
| Done | The outcome |

### 10.3 When a run stops: the AI troubleshooter's three answers

| Question | Example (Jira didn't answer) |
|---|---|
| What happened | Jira didn't answer at 8:00. It's answering again, last seen working today, 9:00. |
| What was affected | Today's check didn't run. Nothing was written. |
| Safe to retry | Yes. A retry reads the tickets again, and its ticket still waits for a yes. |

- **The next step sits under the answers.** **Retry the run** when it is safe. **Report to support** when she can't fix it herself, such as a platform bug: "No. This is a problem in the platform, not in your workflow, so a retry would stop in the same place." While Jira is still down, Safe to retry says "Not yet", and Retry stays, saying why if it still can't start. The case then appears under Following up on Workflows.
- **A stop a person can fix keeps its fix button.** When an n8n change removed the yes step, the buttons are Undo Carol's change and Fix it in n8n (Planned features and a test control).
- **The same words everywhere.** One table gives the answers in Needs you, the chat's card, the side panel and the run page. A Needs you row and the pinned line give one line: the first sentence of what happened and the reason under Safe to retry.
- **An Approver sees the answers with no buttons,** and a note such as "An Operator can retry the run."
- **Retry stays where it was pressed.** A retry in the side panel stays in the panel. A retry on a page opened from the chat keeps Back to the chat, and the chat's card follows.

### 10.4 The approval panel

The panel shows while the run waits for a yes. Only someone who may decide sees the decision. It lists:

- **What will change:** each write, its target and its content, for example "3 tickets will be created in Jira project MOCK on the practice Jira", with each ticket. "This is exactly what will be written, and nothing else."
- **Not checked:** what this run couldn't check, built only from the run's own data and the capability registry. For example "Grafana, LangServe, PostgreSQL and Python couldn't be read, so no ticket is proposed for them." and "The platform can't yet check registries or security advisories." A ticket summary's request says "The platform can't yet see when a ticket was last updated, its type, component or priority, or its owner."
- **Why:** what the agents found, with links to the evidence.
- **Who asked:** the workflow, who set it up, and whether a schedule or a person started this run.
- **What happens:**
  - "Nothing is written until you say yes." The panel says it once.
  - When the Approvers were asked in Teams, that it waits until one of them decides, and what a decline means, for example "If you decline, the run stops there." Under today's rule a request waits until someone decides. A stop time and a backup appear only with ADR 0024's named Approvers, which are Planned.
- **Your part:**
  - "You can decide because you didn't set this up."
  - When she set it up, started this run or retried it, the panel says which, for example "You set this up and started this run, so another Approver must decide. Nobody approves their own work." She sees no buttons. One function, `partiesOf(id)`, gives the owner, the starter and the retriers, the same set the built gate refuses.
  - For a two-Approver step: "Bob said yes. Your yes is the second of two."
- **Questions,** when anyone has asked one.
- **Approve** and **Decline**, then "Not sure yet? Ask Carol a question".

**Asking the requester.** "Ask Carol a question" opens "Your question for Carol", with "Carol sees it on this request and can answer. It stays open, waiting for a yes." and Send question. After sending: "Sent to Carol. The request is still waiting for a yes." Carol finds "Bob asked you about Keep our software up to date" in Needs you, with Answer Bob. Her answer box says "It shows on this request. It doesn't decide anything." Once the request is decided, the questions stay on the record, read only, and one left open says "Not answered before the request was decided."

**Declining.** Decline asks "Why are you declining? Optional. Carol sees it with the record." It offers a few quick reasons, such as "Not this week", "Wrong version" and "Needs testing first" on the software check, and Decline and Back. No reason is needed. A half-picked reason doesn't survive leaving the page.

**In the side panel,** the approval shows everything that will be written: What will change, Not checked, What happens, any questions, and the decision. Only Why, Who asked and Your part wait for the full page. An Approver never decides on a trimmed change.

The platform checks the decision again on the server. The panel's summary is help for the reader, not the check. Asking a question and giving a reason add no way to approve. They are messages and notes on the request.

### 10.5 The declined record

A declined run reads the same everywhere it appears, and never looks as if it wrote something.

- **One record.** "Declined by Bob. Nothing was written. Reason: Wrong version." It shows on the run page, in the side panel, in the message after deciding, in Teams, in Needs you, on the watchlist, on the workflow page and in the Workflows row's last run. The run page adds what happens next, such as "The tickets will be proposed again next Monday."
- **A first yes is kept.** On the access review: "Approved by Bob, then declined by Alice. Nothing was removed."
- **The run shows no write.** A grey Declined pill. The write step says "Nothing written", and the last step is a plain "Ended". The agents never say they created anything.
- **The requester hears.** A declined test run shows in its owner's Needs you, for example "Bob declined your test run", with the reason, See the run and Do a test run again.

## 11. Software watchlist

The page title is Software watchlist, and the rail calls it Watchlist. Under the title, one count line, such as "3 have a newer version · 4 can't be checked", and **Check now**.

From top to bottom:

1. **Needs attention.**
   - The weekly upgrade request waiting for a yes: "This week's check wants to raise 3 upgrade tickets." with Review and decide.
   - Software the check couldn't read, with the AI troubleshooter's fix. Example: "GitHub can't find langchain-ai/langserve. It moved to langchain-ai/langchain." with **Use the new address**. Built today: only a GitHub rename, where GitHub redirects the old name to the new one and the platform can read the new name. This LangServe example is a 404, which names no new home, so the platform refuses the switch (409) and the button stays tagged as not built in the prototype. An Approver sees "An Operator can fix this."
2. **Software we watch,** with Find software. A row each, with:
   - the name, and what checks it, such as "Checked on GitHub · langchain-ai/langgraph";
   - the version we run, with where it came from, such as "From MOCK-6, marked Done". When nobody gave it, it says "Not known", and nothing is compared with it. "Not sure? Start from the newest" means watching for releases newer than today's. It never records the newest release as the version the team runs, which could hide an out-of-date install;
   - the newest version;
   - the status: New version, Can't check, Not checked yet, Up to date or Nothing newer yet. A Can't check with no fix the person can make, such as a rate limit that clears by itself, stays in the table with its reason instead of becoming a Needs attention card. Every row stays in this list, so its count is the real number even while a yes waits;
   - when nobody gave a version, the status says "Nothing newer yet" instead of "Up to date", because there is nothing to be up to date with. Once the first check has read the newest release, the We run cell says "Telling you about releases newer than 1.2.16, the newest the first check read". The same words appear in the history, in the approval and in the ticket;
   - History and, for Operators, Remove.

   Rows needing action come first: new version, then can't check, then not checked yet, then up to date. After a decline, each New version row notes the declined record (10.5).

   **Add software** takes plain words ("Kubernetes"). "Type the name. I'll find its GitHub project." It shows where the guess came from. When more than one project matches, she chooses. Two matches cannot be added, and the form says why: a project the list already holds, and a project that publishes no releases on GitHub, such as python/cpython.
3. **How it's checked.** "Every Monday at 9:00, Singapore time (SGT). One approval covers all the upgrade tickets." It says who set the schedule, that their checks count as their work, and who approves. Change schedule makes the person who saves it the owner. Sources:
   - GitHub releases, Ready;
   - package registries, security advisories and support end dates, each "Not yet" by default, and tagged Planned with Planned features on (section 1).

   With Planned features shown, security risks and support end dates appear under Needs attention, tagged Planned. Severity is shown only when a real source backs it.

Using the new address says "LangServe is now read from langchain-ai/langchain. It's checked at the next check, Mon 2 Nov, 9:00." with Undo.

## 12. How it works, in Settings

The Agent library moved into Settings as the How it works tab, because no daily task needs it (ADR 0043). It is for Operators. It has three tabs:

- **What it can do.** The opening tab. The registry in plain words, grouped as I can, Needs setup and Not working right now. Only the software versioning lines are listed, and there is no Not yet group. Each line names what uses it, for example "Check software for new releases on GitHub. Used by Version checker."
- **Agents.** Platform agents (the Planner and the AI troubleshooter) and specialist agents, each with a plain one-line job and Details.
  - Details shows where it is used, its last run, and its steps, tools, rules and versions.
  - A platform agent says "This agent is part of the platform, so only the team that runs the platform can change it." A specialist agent is read only here.
  - Changing an agent in plain English, which shows the exact difference before saving, appears only with Planned features shown.
- **Tools.** Each tool with its plain name, grouped as tools that change data and tools that only read, with its health from the registry.
  - "Need a tool that isn't here?" sends the person to the Planner, which gives the same answer as in the chat: the team decides, with Ask the team (I3). What they asked shows under "Asked the team".
  - Drafting a tool from a published API appears only with Planned features shown.

## 13. Settings

Settings opens from the header. "For whoever looks after the platform. Every change here is recorded with who made it." Its tabs:

- Connections
- People and permissions
- AI model
- How it works (Operators only, 12)
- AI usage, only with Planned features shown, tagged Planned

A tab that needs attention carries a dot.

**Connections.** Each connection says in plain words whether it works, what uses it (from the registry), who it signs in as, the key's last two characters, and the one fix. Operators get Check now. Examples:
- "Jira is working. Checked today, 9:00."
- "The GitHub key runs out in 9 days. Ask whoever looks after the platform to replace it before Thu 5 Nov, or the Software watchlist stops."

Replace the key appears only with Planned features shown. Teams is described as "Sends approval requests to Approvers". Nothing else promises a Teams message (I1).

<!-- step 4: confirm against the prototype -->
**People and permissions.** Everyone on the People list, each with Operator and Approver. Only Operators change them, and everyone else reads "Only Operators change settings." "Making someone an Approver needs another Approver to confirm it." and "At least 2 people are Approvers, so nobody has to approve their own work." ADR 0043 shows n8n views only to people with n8n access. The People list doesn't show n8n access yet.

**AI model.** The connected model and its address, with Test now and Change the model or key. Someone who isn't an Operator reads "Only Operators change the AI model. Approvers confirm a new address before runs use it."

## 14. The Teams approval message

The Teams drawer shows the card ADR 0036 describes:
- what needs approval;
- which workflow;
- each change it would make;
- what the agents found;
- who can decide, and who can't and why ("Carol, who set this up and started this run. Nobody approves their own work.");
- one button, **Open in AI Workflow Builder**.

It has no Approve or Decline. After a decision, the drawer shows the request's state read from the platform: "Approved by Alice at 9:10 today", or the declined record (10.5), "Declined by Bob at 9:10 today" with "Nothing was written. Reason: Wrong version." A notification never authorizes anything. The drawer says "Practice copy. Nothing reaches the real Teams."

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
| Paused | Pill. It won't run until someone resumes it. |
| Running | Pill with the step now running, only while a run is in progress. The prototype has no run in progress: it replays finished runs, marked Replaying. |
| Done | Green pill, with what was written and who said yes |
| Declined | Grey pill with a cross, with who declined, "Nothing was written" and any reason (10.5) |
| Stopped | Red pill, with the troubleshooter's reason |
| No answer | Pill for a request nobody decided in time. Nothing was written. Only with ADR 0024's named Approvers, which are Planned, because under today's rule a request waits until someone decides. |
| Test run | Marked "Test run" everywhere it appears |
| Nothing newer yet | Green pill, for software with no known version after a check that found nothing newer than the first one read. It is never called Up to date |

## 16. Test controls (not part of the product)

They stay in the corner panel, apart from the product screens, and never cover them. The panel says "Version 4, redesign proposal. For trying the prototype. Not part of the product."

| Control | Choices | Why |
|---|---|---|
| Show | A normal week, Day one | As in version 3 |
| Act as | Alice, an Operator and Approver; Bob, an Approver only | As in version 3 |
| AI model | Connected, Not connected | Shows the offline Home (5.4) |
| Planned features | Hidden, Shown and tagged | Lets reviewers see planned designs without the product claiming them: named Approvers (ADR 0024), more watchlist sources and security findings (ADR 0025), Open in n8n and its history (ADR 0026, 0027), drafting a tool, changing an agent in plain English, coding agents preparing a fix in a support case, replacing a key in Settings, monthly schedules, AI usage, and the access review with its two Approvers in turn |
| Mark what isn't built | Off, On | Outlines the screen parts the built Portal doesn't have yet, so a reviewer can tell the prototype from the product. The approval's Not checked line, Ask the requester, the questions, the decline reasons, and Show what each agent did with its replay are marked. |
| Make something happen | What can happen next from the current state | Jira stops answering and works again, a tool or key confirmed or failing, a yes to a test run, time passing with no answer, support moving a case on, the requester answering a question, and an n8n change |

"Start over" keeps the four switches. "About this prototype" keeps saying the data is sample data and requests are read with simple word rules, not a model.

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

### 18.1 Recorded on 7 Nov

When the team adopted version 4, ADR 0037 gained its "Changes on 7 Nov 2026" section: Needs you on Home, the Planner's state answers and offline answer, suggestions that send intents, one capability registry, and the old New workflow behind a flag. The glossary gained "Capability". The flag and New workflow have since gone.

### 18.2 ADR 0043's changes to ADR 0037

ADR 0043 (proposed) changes ADR 0037 in four places. They take effect when ADR 0043 is accepted.

1. **The chat is Home.** ADR 0037 rejected this because urgent items scroll away, and pinning them rebuilds Home inside the chat. The pinned line is one row, not Home again, and the rail keeps the lists one tap away (3).
2. **Changes happen where the thing lives,** and now also by asking. The edit card changes a workflow's schedule from the chat (6.7). Every other change keeps its editor on the workflow's page, where the schedule editor also stays.
3. **The Approver-only Home gains the box,** for questions only (5.3). This is step 4 of the redraw.
4. **The menu becomes the rail** (3.1). The Agent library moves into Settings as How it works (12).

### 18.3 Where the prototype and ADR 0043 differ

- **The side panel while the Planner builds** shows the plain steps going in, not n8n blocks, and keeps its width (6.8).
- **Schedule changes are not in the side panel.** The ADR lists changing the schedule among the panel's actions. The prototype changes it on the workflow's page or by asking in the chat (3.3).
- **The run page has no timed log.** The ADR's run page adds one. The prototype shows the agents' conversation without times (10.2).
- **The Watchlist's count line** reads "3 have a newer version · 4 can't be checked", where the ADR's example says "1 can't be found".

## 19. What is simulated in version 4

Everything in the prototype is simulated. Specifically:
- Requests are classified with word rules, not a model.
- The answers about workflows and data read sample state.
- Runs are scripted replays. Only the sample workflows and the first workflow made on Home have one, so another workflow made on Home has no Run now or test run. A test note on the page says so.
- Versions, questions on a request and their answers are sample data. A requester answers only through a test control.
- Connections, keys and Teams are sample data. Teams is a practice copy: "Nothing reaches the real Teams."
- Time stands still at Tuesday 27 October, 9:10, Singapore time.

"Mark what isn't built" shows which screen parts the built Portal lacks. `IMPLEMENTATION-PLAN.md` lists what each needs from the backend.

## 20. How it was checked

### 20.1 The redraw (ADR 0043, steps 1 to 3)

Each step was checked the way version 4 was, and its results are in `checks/results/` (`v4-shell-*`, `v4-answers-*`, `v4-runs-*`). The numbers below are for step 3, merge 98961ef, which includes steps 1 and 2.

- **Scenarios.** `checks/run.cjs` with `checks/paths-v4.cjs`: 127 passed, 0 failed and 1 not possible, with the control failing as it should (`results/v4-runs.md`). T1 is not possible, because since 8 Nov no starting point sets up a general Jira workflow. The redraw added these groups:
  - `SHELL-*`: the pinned line, the side panel, More details with Back to the chat, and the rail returning to the chat;
  - `ANS-*`: part marks, one question at a time, the edit card, questions in any wording, commands that fail closed, live cards and the panel while the Planner builds;
  - `RUN-*`, `APPR-*`, `DECLINED-*`, `WF-last-run`, `MARK-approval` and `KEYS-APPR`: the three answers, the run line, Not checked, questions on a request, the decline reason, the declined record and each workflow's last run.

  The builder showed each new scenario failing on the head before it, for the right reason.
- **The judge's checks.** `checks/validate-v4.cjs` passed 32 of 32, and its seeded control failed as it should. Step 2 changed the checks where the card changed on purpose (one question at a time, crosses read as a can't) and added `stop-words-are-function-words`, so a verb can't be skipped silently again.
- **Fit.** `checks/fit.cjs`, new in step 1, fails any screen where text spills, is cut off or overlaps, or where buttons side by side don't line up. It found 0 problems on 62 screens at 1440, 1280, 1024, 861, 768 and 390 px, and 0 at 901, 950 and 1000 px with the side panel open. Its seeded control was caught.
- **Quality.** `checks/quality.cjs` on the same 62 screens at 1280 and 390 px:
  - axe found no critical, serious or moderate problems, and 8 minor ones;
  - nothing scrolls sideways at 390 px;
  - no animation runs under reduced motion;
  - the keyboard reaches the Operator's box in 8 Tab presses and Bob's Review and decide in 8, with visible focus at every stop.
- **Independent reviews.** A Fable reviewer drove each step in a browser at several widths, tried its own wordings, and tried to break the approval gate. The builder fixed every finding, and the reviewer checked the fixes:
  - step 1: 6 should-fix;
  - step 2: three rounds, with 9 must-fix, 12 should-fix and 13 smaller findings;
  - step 3: no must-fix, 4 should-fix and 6 nits.
- **Screenshots.** `screenshots/shell/`, `screenshots/answers/` and `screenshots/runs/`, at desktop and 390 px widths. The step 1 shots show the shell before steps 2 and 3, so their troubleshooter and check card are older.
- **The redraw's reason.** An independent UX review on 10 Nov tested version 4 and a chat-first sketch with eight Operator tasks (`docs/evidence/usability/2026-11-10-ux-review/`). ADR 0043 records what it found.

The redraw's pull requests don't report the builders' gates (`gates-*.cjs`).

### 20.2 Version 4 as first checked (7 Nov)

These results are for version 4 after fix round D (merge a78daf1, 7 Nov), which answered the outside review. `USER-JOURNEY-COMPARISON.md` compares each scenario.

- **Scenarios.** The same harness ran scenarios A to H and the 15 tasks of version 3 on both versions. Version 3 passed 27 of 27. Version 4 passed all 40 of its scenarios, and a second run gave identical counts.
- **The judge's checks.** An independent judge wrote `checks/paths-v4.cjs` and `checks/validate-v4.cjs`, separate from the builders. `validate-v4.cjs` passed 31 of 31.
- **Planted defects.** The judge planted 14 defects, each in its own copy of the prototype, such as an Approve button in Teams, self-approval and count drift. The judge's checks caught all 14. The builders' gates caught fewer.
- **The builders' gates.** `gates-p0.cjs` passed 36 checks, `gates-p1a.cjs` 65, `gates-p1b.cjs` 55 and `gates-p2.cjs` 66. The gates check I1 to I9 by name.
- **Quality.** axe found no problems of any level on 26 screens at 1280 and 390 px.

These are automated checks, not user research. ADR 0043 asks for 2 or 3 people outside the team to try three tasks: start the morning, change a schedule by asking, and decline an approval with a reason. A study with real CODESparks support staff should come next. It would measure:
  - task success;
  - time to finish;
  - errors;
  - confidence;
  - perceived effort.
