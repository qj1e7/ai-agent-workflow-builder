# Prototype handover: AI workflow builder

Prepared on 27 Oct 2026 by the project's development assistant (Claude), for an independent, operator-focused usability evaluation by another AI (ChatGPT).

**Version to test:** prototype A, version 2, published on 27 Oct 2026 at the same link. Later the same day it gained named Approvers, a backup Approver, and requests that stop when nobody answers, followed by fixes from a review of those. Its words also changed: "routine" became "workflow", the "Room lead" agent became the "Planner", and the header name changed from "Portal" to "AI Workflow Builder". Version 1 is kept in the repository for comparison (see section 7).

This document gives context and access only. It is not an evaluation, and it makes no claim that the prototype is easy to use. Where it describes the design, it describes what exists, not whether it works well for people.

**Note to the evaluator.** Section 3 (the feature list) and section 5 (the screen descriptions) name screens and controls. To keep your test independent, you may want to try the workflows in section 4 before you read sections 3 and 5.

**A note on the word "workflow".** In prototype A, a *workflow* is a repeated task that an Operator sets up, listed on the Workflows page. Sections 4 and 8 also use "workflow" in its everyday sense: a piece of work an operator does, such as W1 to W9 in section 4.

## Contents

0. [Summary of what you can test](#0-summary-of-what-you-can-test)
1. [Project background](#1-project-background)
2. [Prototype access](#2-prototype-access)
3. [Functional inventory](#3-functional-inventory)
4. [Operator's daily workflows](#4-operators-daily-workflows)
5. [Current UI/UX design](#5-current-uiux-design)
6. [Known issues and incomplete areas](#6-known-issues-and-incomplete-areas)
7. [Evidence and supporting materials](#7-evidence-and-supporting-materials)
8. [Independent evaluation instructions for ChatGPT](#8-independent-evaluation-instructions-for-chatgpt)
- [Appendix A: User stories](#appendix-a-user-stories)

---

## 0. Summary of what you can test

There are two things, and they are not the same.

| | **A. Redesign prototype** (main test target) | **B. Current Portal MVP** (optional) |
|---|---|---|
| What it is | A clickable mock of the next version of the Portal | The working app the team has built so far |
| Data | Sample data, simulated in the browser | Real local database, real reads from GitHub, practice copies of Teams and Jira |
| Access | A public link in any modern browser. No install, no sign-in. | Runs only on a computer with Docker, at `http://localhost:8080` |
| Reachable by a cloud AI agent | Yes, through the public link | No. `localhost` is only reachable from the machine running it. |
| Design | New structure: Home, Workflows, Software watchlist, Agent library, New workflow | Older structure: Runs, Builder, Software, Approvals, Teams, Jira |

The redesign prototype (A) shows how the team intends the product to work next. The current MVP (B) is what actually runs today. Most features in A are simulated. Section 3 marks the status of every feature.

---

## 1. Project background

### 1.1 Project name and objectives

- **Name:** AI workflow builder. The current MVP's web app is called the **Portal**. Prototype A shows the name **AI Workflow Builder** in its header.
- **Context:** an NUS-ISS MTech Software Engineering final year project, sponsored by CODESparks, a support team inside NCS.
- **Objective:** let non-technical support staff describe a repetitive task in plain English. AI agents then do the work on a schedule, and a person approves every change before anything is written to another system.
- **Sponsor's main concern:** the team must be able to keep it running after the students hand it over, without coding, and fix common problems without a technical person.

### 1.2 Real-world problems the application aims to solve

CODESparks support staff spend time on repeated, rule-based chores in Jira, Confluence and other admin tools. Two pain points the sponsor named:

1. **Software version and patch housekeeping.** Keeping track of which version of each tool the team runs, noticing when a new release comes out, and raising an upgrade ticket for it. Today this means visiting each project's release page, comparing versions by hand and raising Jira tickets one by one.
2. **Quarterly access review.** Checking who can use Entra ID, internal admin tools and GitLab, asking managers to confirm each person still needs access, and removing access nobody confirms. It needs two Approvers, one after the other. This is planned for Phase 2 and is **not** in the prototype, except as a sample entry.

### 1.3 Target users and their roles

| Role | Who | What they do in the app |
|---|---|---|
| **Operator** | A support staff member. Non-technical, uses Jira and Teams daily. | Sets up repeated tasks ("workflows"), keeps the software list up to date, and deals with tasks that stop |
| **Approver** | Usually a senior team member or lead. A person can be both an Operator and an Approver. | Says yes or no before anything changes in another system. Can never approve their own work. |
| Support developer | An NCS developer after handover. Not a user of the app. | Fixes platform bugs that Operators report |

Demo people: **Alice** (Operator and Approver), **Bob** (Approver only) and **Carol** (Operator). In prototype A, Carol only appears as the owner of a schedule, **Siti** and **Arun** are two more Approvers, and Dana appears as the support developer.

### 1.4 Typical daily responsibilities of an operator

These are the team's understanding from talking to the sponsor. They have not been confirmed by watching staff work.

- Start of day: check what needs attention, such as tickets waiting, failed jobs and requests from colleagues.
- Keep track of the versions of tools the team runs, and raise upgrade tickets when they fall behind.
- Raise, update and close Jira tickets, and post summaries or updates in Confluence pages and Teams channels.
- Chase stale tickets and ask owners whether work is still needed.
- Ask a colleague or lead to approve changes, and approve colleagues' changes.
- Report problems with internal tools to the people who maintain them.
- Four times a year: the access review.

### 1.5 Existing manual processes and pain points

- Release checks are done by visiting each project's release page and comparing versions by hand. It's easy to forget, and there is no single view of where things stand.
- Every upgrade needs its own Jira ticket, typed by hand.
- Approvals happen in Teams chats and are not linked to the actual change made.
- Nobody can see at a glance what is behind, what failed, or what is waiting for whom.
- When an automated script fails, staff need a technical person to find out why.
- The sponsor is cautious: they want to automate the boring parts but never critical changes without a person's approval.

### 1.6 Expected benefits

These are the team's intended benefits. None of them has been measured.

- Less manual checking and ticket typing for repeated chores.
- One place to see what needs a person.
- Every change approved by someone other than the person who started it, with the exact change shown.
- Failures explained in plain language, with a way to get help.
- Fewer approvals: for example, one weekly approval covers all of that week's software upgrade tickets.

### 1.7 Scope of the current prototype

**In scope, in prototype A:**
- Home ("what needs you")
- Workflows
- Software watchlist: the version list, history for each tool, and adding software
- New workflow: a 4-step set-up that shows what it understood from the request and flags anything unclear, with a drafted "tool" that needs an Approver's OK
- Changing a workflow's schedule, pausing it and deleting it, and finding workflows and software
- Watching a run, and approving or declining
- Fixing a stopped workflow
- Reporting a platform problem to support
- A practice Teams panel
- A first-day empty state
- A phone layout

**In scope, in MVP B:**
- Release checks on public GitHub projects
- The software watchlist, with a weekly scheduled check and one approval per check
- Building and running agent cards from a plain-English task
- Approvals, with the self-approval rule
- The live activity view of a run
- Rule-based troubleshooting advice on failures, and retry
- Practice Teams and Jira pages
- Connecting an AI model
- A guided in-app tour

**Out of scope for both:**
- Real Microsoft Teams, Confluence, Entra ID or GitLab
- The quarterly access review
- Deployment inside the NCS private network (DevNet)
- An audit page

### 1.8 Assumptions, constraints and known limitations

- Built and tested on the open internet first. DevNet comes later.
- Two roles only: Operator and Approver.
- Nothing is written to another system without an Approver's yes. Writes go only to a practice Jira inside the app.
- The AI model provider is not final. The team tests providers during development.
- The team has 5 part-time students, and the first presentation is in late Nov 2026.
- Prototype A is a design mock: its behaviour is scripted, not computed. See section 6.

---

## 2. Prototype access

### 2.1 Target A: redesign prototype (recommended)

**Public link (no sign-in expected):**
https://claude.ai/artifact/KDxZZkF6BjHmW92YPa2XzU

- It opens in any modern browser. It's hosted inside a claude.ai page.
- **If the link asks you to sign in or doesn't load,** use the file copy below.

**File copy (the same prototype):**
- Path in the team's repository: `docs/design/portal-routines/prototype.html`. It is one self-contained file.
- **Open it directly:** double-click the file, or open it with `file://` in a browser.
- **Or serve it locally:** from the folder that holds the file, run `python3 -m http.server 8765`, then open `http://127.0.0.1:8765/prototype.html`.
- **Or host it:** the team can put it on any static host (for example GitHub Pages) to give you an http address.

**Environment:**
- Any current Chrome, Edge, Firefox or Safari. Only Chromium has been used so far.
- An internet connection is optional. Without it, the text font falls back to the system font.
- Desktop at 1280 px or wider. The layout also works at phone width, around 375 to 390 px.

**Accounts and test controls:**
- There are no passwords. The prototype starts signed in as **Alice** (Operator and Approver).
- A dark purple **Test controls** button at the bottom left opens test scaffolding. It is not part of the product, and it's closed when the prototype starts:
  - **Show:** *A normal week* (sample workflows already running) or *Day one* (a new team with nothing set up)
  - **Act as:** *Alice* or *Bob* (Approver only)
  - **Make something happen:** stands in for another person or for time passing, for example "Bob OKs the new tool" or "4 working hours pass with no answer". A number on the closed button shows how many of these are available.
  - **About this prototype** and **Start over** (resets the prototype)

**Test data already present (A normal week):**
- **Workflows:**
  - "Keep our software up to date" (needs a yes)
  - "Morning bug report check" (stopped)
  - "Stale ticket nudge" (stopped)
  - "Quarterly access review" (sample, running)
- **Software watchlist:** 14 tools, read from GitHub, Maven Central, PyPI or Docker Hub. Log4j core, LangGraph and FastAPI are behind, and Log4j core 2.14.1 has a critical, actively exploited known vulnerability. Grafana couldn't be checked, 10 are up to date, and the support for 2 (PostgreSQL 14 and Node.js 22) ends soon.
- **Practice systems:** Jira project MOCK, Teams channel CODESparks Support.
- **Fixed date:** Tuesday 27 October 2026.

**Data safety:** everything lives in the browser tab. Reloading the page or pressing "Start over" resets it. Nothing reaches a server or another system.

### 2.2 Target B: current Portal MVP (optional, local machine only)

Use this only if the evaluation can run a browser on the same computer as the app, or if a person can operate it for you. A cloud agent cannot reach `localhost`.

**Option B1: full stack (needs Docker).**
1. Install Docker Desktop and start it.
2. From the repository root, run `scripts/up.sh`. The first run creates `deploy/.env` with random local secrets and builds the images, which takes a few minutes. Later runs take under a minute.
3. Open `http://localhost:8080`. The API's documentation page is at `http://localhost:8000/docs`, or 18000 if 8000 was taken.
4. To stop and **delete all local data**, run `scripts/down.sh`.

**Option B2: Portal with recorded sample data (no Docker, no backend).**
1. Install Node.js 22.
2. Run `cd portal`, then `npm ci`, then `npm run dev`.
3. Open the address Vite prints, usually `http://localhost:5173`. The header shows "Demo data". The Portal uses recorded runs, and nothing is saved.

**Accounts (B1):**
- There is no password sign-in in the local setup. Pick the user from the menu at the top right:
  - **alice:** Operator and Approver
  - **bob:** Approver
  - **carol:** Operator
- The team's rule for testing: start runs as alice, and approve as bob.

**Credentials and secrets:**
- No credentials are needed for testing, and none are in this document.
- `deploy/.env` holds locally generated secrets (database and n8n passwords, signing keys). It is created on each machine and must not be shared.
- **AI model key:** some B features need an AI model (see section 3). The key belongs to the team and is entered by a team member on the Settings page before a session. **Do not ask for it or record it.**
- **GitHub:** B reads public GitHub release data. Without a GitHub token, GitHub may rate-limit it. A team member can add their own token to `deploy/.env`.

**Test data already present (B1, the team's own machine, as of 27 Oct 2026):**
- About 12 runs, several of them test runs with similar names, such as "Release check", "Release checker copy" and "LangGraph release (real model check)".
- 6 use cases, and a software watchlist with LangGraph.
- 5 messages in the practice Teams channel and several tickets in the practice Jira project MOCK.
- **Warning:** pressing "Mark Done" on the practice Jira page changes this data.

### 2.3 Features that need backend services or external integrations

| Feature | A (prototype) | B (MVP) |
|---|---|---|
| Release data from GitHub | Simulated | Real GitHub API (public data) |
| AI understanding of a new task | Simulated with simple word rules, and shown to the operator to check | Real AI model, needs a key connected by the team |
| AI summary of a release check | Not shown | Real AI model if connected, otherwise a built-in sentence |
| Scheduled checks | Simulated | n8n workflow engine, inside Docker |
| Approvals, runs, history | Simulated in the browser | platform API and PostgreSQL, inside Docker |
| Microsoft Teams | Practice panel | Practice page inside the Portal, no real Teams |
| Jira | Simulated ticket numbers | Practice Jira page inside the Portal, no real Jira |
| Confluence, Entra ID, GitLab | Simulated mentions only | Not implemented |

### 2.4 Limitations affecting browser-based testing

- **No addresses per screen in A.** Every screen has the same URL, so screens can't be bookmarked. Browser Back and Forward do not move between screens.
- **A resets on reload.** Plan tasks that build on earlier ones as one session.
- **The Test controls button in A sits at the bottom left** and can cover a small part of the page. Scroll if something is under it.
- **A reads typed tasks with simple word rules.** It handles tasks about Jira tickets; anything else is flagged rather than guessed. See section 6.1.
- **B on `localhost` can't be reached by a cloud browser.**
- **B's first run of `scripts/up.sh` takes several minutes,** and the AI-dependent features need a team member to connect the model first.

---

## 3. Functional inventory

**Status key:**
- **Working:** does the real thing end to end in that target.
- **Partial:** works, but with real gaps.
- **Mocked:** behaviour is simulated with sample data.
- **Not implemented:** not there.

### 3.1 Target A: redesign prototype

In prototype A, **every feature is Mocked**: it runs on sample data inside the browser, with no backend. The Known limits column says how far each simulation goes.

| Feature | Business purpose | User | Entry point | Actions | Expected outcome | Status | Known limits |
|---|---|---|---|---|---|---|---|
| Home | Show what needs the person now | Both | Opens first; "Home" in the menu | Read; act on each item | Each item leads to its decision or fix | Mocked | Fixed date; items depend on earlier actions in the session |
| Day one start | Help a new team begin | Operator | Test controls, "Show: Day one" | Pick a ready-made workflow or describe your own | Starts New workflow, or opens the Software watchlist | Mocked | Keeps anything added earlier in the session |
| Workflows list | See every workflow and its state | Both | "Workflows" | Find by name; filter (All, Needs you, Stopped, Paused); open a workflow | Workflow page | Mocked | No sort |
| Workflow page | Details and control of one workflow | Both; changes by Operators | A workflow's title | Change schedule; Pause or Resume; Delete (with Undo); open the latest run | Schedule, next run and state update | Mocked | The plan can't be edited after the workflow is on; only the latest run opens; the software check is managed from the Software watchlist |
| Software list | One list of all software versions | Operator | "Software watchlist" | Find; open History; Remove (with Undo); add software | Status for each tool | Mocked | A tool's details can't be edited |
| Known vulnerabilities | See which tools have a known security flaw, and how serious it is | Operator, Approver | "Security risks" at the top of the Software watchlist; "Critical security risk" on the tool's row; the urgent ticket in the weekly check's approval panel | Jump from the row to the risk; See all; open NVD, CISA, Apache or OSV | Four answers: how serious (score out of 10), whether attackers are using it, how many known vulnerabilities, and the fix. "See all" lists each one with its score and a plain-English line | Mocked | Sample data. Only Log4j core has one. The 4 CVEs are the real ones for 2.14.1 |
| Support ending | See which versions stop getting security fixes soon | Operator | Software watchlist | Open the dates on endoflife.date | Name, end date, time left | Mocked | Sample data: PostgreSQL 14 and Node.js 22 |
| Software history | How a tool reached its version | Operator | "History" on a row | Show or hide | Dated list of events | Mocked | Only for 3 sample tools and tools added in the session |
| Add software | Start tracking a tool | Operator | Software watchlist page form | Name; where it's published (GitHub, Maven Central, npm, PyPI, NuGet, Docker Hub, or "Not sure"); the reference for that source; optional version | Tool appears under "Not checked yet", with the next check time. With "Not sure", the Version checker suggests a source to confirm, or says it found none | Mocked | The suggestion only works for a few well-known names |
| Software schedule | When the software check runs | Operator | Software watchlist, "Change schedule" | Choose how often, the day and the time | Saved; the person who saves becomes the schedule owner | Mocked | |
| Check now | Check versions immediately | Operator | Software watchlist page | Press | A status message only | Mocked (message only) | No check happens |
| New workflow | Set up a repeated task from plain English | Operator | "+ New workflow" | Describe; check and correct what was understood; choose when and who; turn on | "Your workflow is on", with the next run time | Mocked | Understands only tasks about Jira tickets (see 6.1) |
| Understanding check | Show how the request was read, and stop a wrong workflow | Operator | New workflow, step 2 | Correct any line; see flags for unclear or unsupported parts | Next stays disabled until every flag is resolved | Mocked | Simple word rules, not an AI model |
| Similar workflow notice | Avoid building the same workflow twice | Operator | New workflow, step 2 | Open the existing workflow, or carry on | | Mocked | Only for requests like "Stale ticket nudge" |
| Schedule for a new workflow | Run at the time asked for | Operator | New workflow, step 3 | How often (day, weekday, week, month), day, any time | Filled in from the request; blank when the request didn't say | Mocked | Singapore time only |
| Release check redirect | Keep release checks in one list | Operator | New workflow, describing a release check | Add the software, or open the Software watchlist | Software added to the list | Mocked | Recognises a fixed list of about 14 well-known names |
| New tool that needs an OK | Let the AI prepare a missing ability, for an Approver to check | Operator, Approver | New workflow, step 2, when the result goes to Confluence | Ask an Approver; the Approver OKs it | The operator is told on Home; Next unlocks | Mocked | Always the same Confluence tool; "Not now" shows a message only |
| Drafts | Leave set-up and come back | Operator | "Save draft and close", or asking for a tool | Resume from Home | Back at the same step | Mocked | One draft at a time |
| Who approves | Name who is asked, and a backup | Operator | New workflow, step 3; "Change who approves" on a workflow page and on the Software watchlist | Asked first; backup (or nobody else); under "More approval options": when to ask the backup, when to stop waiting, an optional second Approver | Shown on the workflow page as names and times | Mocked | The workflow's owner isn't offered; nobody can be named twice in one workflow |
| Test run | Try a new workflow once | Operator | After turning it on | Do a test run | Waits for the named Approvers, then simulates the write | Mocked | |
| Waiting and no answer | What happens while a request waits | Both | Home, run page, Teams panel | Watch who has been asked; let time pass with the test controls | The backup is asked after the set wait; if nobody answers by the stop time, the request stops and nothing is written | Mocked | Time passes only for a new workflow's test run |
| Run view (live activity view) | Show what agents did and where a run is | Both | From Home, Workflows, Software watchlist or Teams | Watch; change speed (1x, 2x, Instant) | Steps, agents' messages, final state | Mocked | Each opening replays from the start, headed "Replaying" until it catches up |
| Approve or decline | Human yes or no before any change | Approver | Run page, Teams panel | Approve; Decline; open release notes and project pages on GitHub | Simulated tickets created, or nothing written | Mocked | Whole check only (ADR 0019); no undo |
| Ticket view | See a ticket the platform created | Both | Ticket labels on the run page and on the Software watchlist | Open; watch the run that made it | Ticket details | Mocked | Practice Jira data |
| Self-approval block | Nobody approves their own work | Approver | Run page or Teams panel on your own run | (Blocked) | A lock message naming who can approve | Mocked | |
| Not-named block | Only the named people decide | Approver | Run page or Teams panel, as an Approver the workflow doesn't name | (Blocked) | A lock message naming who can decide | Mocked | |
| Troubleshooter: fixable | Explain a stop and offer a fix | Operator | Home item or run page | Apply the suggested fix and retry | Run completes; the workflow shows the fix | Mocked | One scripted case (a renamed GitHub project) |
| Troubleshooter: platform fault | Say when the operator can't fix it | Operator | Home item or run page | Report to support | Report dialog | Mocked | One scripted case |
| Report to support | Get help with the details attached | Operator | Home item, Workflows card, run page | Send, with an optional note | A case with a number, owner, reply-by time and your note; a 4-stage tracker on Home, the workflow page and the run page | Mocked | One sample case; stages move only through the test controls |
| Teams panel | Where approvals and notices arrive | Both | "Teams" button in the header | Approve; decline; open in Portal; review a tool | Same effect as in the Portal | Mocked | Practice copy only |
| Approver's view | Approver sees their decisions | Approver | Test controls, "Act as: Bob" | Decide on approvals and tool requests | Items cleared | Mocked | |
| Agent library | See every agent the Planner can use, and change how one works | Both (changes: Operator) | "Agent library" in the menu ("Agents" on phones) | Open an agent; open a workflow that uses it | Each card: what it does, whether it only reads or changes data after a yes, and which workflows use it | Mocked | New agents come from New workflow |
| Tools | See every tool the agents use, and whether each is working | Both (asking: Operator) | Agent library, Tools tab | Open a tool; ask for a new tool in plain English | Tools that change data (with how many Approvers each needs) and tools that only read, which agents use each, and Working or Had a problem. Also tools waiting for an OK, and requests sent to the team | Mocked | Asking uses scripted replies (see 6.1) |
| Tool details | Check one tool, and see what it did | Both (OK: Approver) | Click a tool, or a tool on an agent's details | Check it works; open an agent that uses it; Back; for a new tool: Ask an Approver to OK it, OK this tool, Not now; Give it to the Ticket writer | Status, what it can change or reach, what it can't do, agents and workflows that use it, recent changes with who said yes, and where it came from | Mocked | "Check it works" is simulated |
| Agent details | See how one agent works, and change it in plain English | Both (changes: Operator) | Click an agent card | Suggest a change (typed or an example); Save as a new version; Discard; Go back to an earlier version; Draft the tool; Send to the team; open a tool | Its numbered steps, its tools, the rules it always follows, where it's used, its last run, and version history. A suggested change shows the changed step, three safety checks, and what would have been different on the last run | Mocked | Replies are scripted (see 6.1). The Planner and AI troubleshooter can't be changed |
| Settings: AI model | Connect the AI model the agents use, or replace its key | Both (changes: Operator; confirming a new address: Approver) | Icon-only button in the header | Test now; choose a provider; type an address (for Azure OpenAI or another address); paste the API key, with Show or Hide; Connect; choose a model; Test and save; Cancel; Confirm address or Not now (Approver) | What's connected (provider, model, the key's last 2 characters, last test and answer time), errors next to the field, a new address waiting for an Approver, and the change history | Mocked | Nothing is sent anywhere. Any key of 20 or more characters connects, and the model lists and answer times are samples. Follows ADR 0022 |
| Settings: Connections | See the systems the platform signs in to, and replace a key before it expires | Both (replacing a key: Operator) | Settings, Connections tab; Home shows a key that expires within 14 days | Test; Replace key, with Show or Hide; Test and save; Cancel; open a tool that uses it | For GitHub, Jira and Teams: the account, what it's used for, the key's last 2 characters, when it expires, the last test, and the tools that use it. Jira and Teams are marked as practice copies | Mocked | The GitHub key expires in 9 days in the sample data. A replaced key gets a 90-day expiry |
| Settings: People and roles | See who is an Operator or an Approver, and change roles | Both (changes: Operator; confirming a new Approver: another Approver) | Settings, People and roles tab | Tick or untick Operator and Approver; Confirm or Not now (Approver); Add a person | Each person, their roles, and how many workflows name them as an Approver. Errors explain why a change isn't allowed | Mocked | Rules: making someone an Approver needs another Approver to confirm it; someone named on a workflow keeps the Approver role; at least 2 Approvers; nobody removes their own Operator role. A new Approver becomes choosable on workflows |
| Settings: AI usage | See how much the AI model is used this month, and set a monthly limit | Both (limit: Operator) | Settings, AI usage tab | Save limit | Questions sent, estimated cost, the limit with a bar (amber from 80%, red at 100%), and questions by workflow | Mocked | Sample numbers. Reaching the limit is shown, but nothing stops |
| Phone layout | Use on a phone or small tablet | Both | Browser width under 900 px | Bottom tab bar | Same features | Mocked | Tested in Chromium only |

### 3.2 Target B: current Portal MVP

| Feature | Business purpose | User | Entry point | Actions | Expected outcome | Status | Known limits |
|---|---|---|---|---|---|---|---|
| Runs page (home) | Show the latest run and earlier runs | Both | Opens first; "Runs" | Watch the latest run; open earlier runs | Run page | Working | Shows the latest run, not a to-do list |
| Run page (live activity view) | Show steps, hand-offs and failures | Both | A run | Speed 1x, 2x, Instant; Minutes; Technical details | Full record of the run | Working | |
| Troubleshooting advice | Explain a failed run | Operator | Failed run page | Read; Retry run | A new attempt | Partial | Fixed advice for each of 8 failure types, not written per failure; retry only where the platform allows |
| Builder: describe and plan | Turn a plain-English task into a plan | Operator | "Builder" | Plan it; Plan the example | The Room lead picks or drafts an agent card | Working (needs an AI model) | Without a model, only starter cards are offered |
| Agent library | Saved agent cards | Operator | Builder | Run; Copy and edit; Edit | A run, or an editable card | Working | |
| Use cases list | Saved tasks with inputs | Operator | Builder | Run now | A run | Working | Shows internal IDs and versions |
| Software watchlist | One list of software versions | Operator | "Software" | Add; Remove; Check now; Change schedule | Weekly check with one approval | Working (real GitHub reads) | No history timeline; rate limits without a token |
| Version from closed ticket | Update "our version" on its own | Operator | Practice Jira "Mark Done" | Mark a ticket Done | Our version updates | Working (practice Jira) | |
| Approvals list and page | Decide on waiting runs | Approver | "Approvals" | Approve; Decline; Copy link | Practice Jira ticket written, or nothing | Working | |
| Self-approval block | Nobody approves their own work | Approver | Approval page on your own run | (Blocked) | Lock message | Working | |
| Teams page | Where approval requests arrive | Both | "Teams" | Open the approval page; watch the run | Navigation only | Mocked | Practice copy, not Microsoft Teams |
| Jira page | Where approved tickets are written | Both | "Jira" | Mark Done; watch the run | Ticket status changes | Mocked | Practice project MOCK, not real Jira |
| Settings: AI model | Connect the model used for planning and summaries | Operator | Gear icon | Choose provider; enter key; Connect; Turn off | Model used; change logged | Working | Key held by the team |
| Guided tour | Teach a newcomer the Portal | Both | Flag icon | Follow the quests | Steps tick off as done | Working | Written for the B layout |
| Theme | Light or dark | Both | Moon or sun icon | Toggle | Theme changes | Working | |
| User switcher | Act as alice, bob or carol | Both | Name at the top right | Pick a user | Roles change | Working (local only) | No real sign-in locally; company sign-in configured only for Azure |
| Phone layout | Use on a phone | Both | Narrow browser | Bottom tab bar | Same features | Working | |
| Home "what needs you", Workflows page, history timeline, report to support, tool cards, drafts, release check redirect | See A | | | | | Not implemented | These exist only in prototype A |
| Quarterly access review, Confluence, Entra ID, GitLab, real Teams | Phase 2 | | | | | Not implemented | |

---

## 4. Operator's daily workflows

These scenarios describe goals, not click paths. Discover the route yourself. Each is marked with the target that supports it.

**Business rules that apply throughout:**
- No change is written to another system without an Approver's yes.
- An Approver can never approve their own work. This includes work started by a schedule they own.
- In A, each workflow names who is asked first and a backup. Only they can decide. If nobody answers in time, the request stops and nothing is written.
- An approval covers exactly the change shown, and nothing else.
- While an upgrade ticket for a tool is open, no second ticket is raised for it.
- One weekly software check sends one approval request covering all of its tickets.
- A new capability that changes data in another system needs an Approver's OK once before anyone can use it. This rule is in A only.
- Access changes need two Approvers, one after the other. This is Phase 2, and shows as a sample only.

### Frequent tasks

**W1. Start of day (A, B)**
1. Objective: know what needs your attention today, and deal with what's urgent.
2. Starting information: you have just opened the app, as Alice.
3. Expected result: you can say what needs you and why, and each item is dealt with or knowingly left.
4. Rules: none beyond the general rules.

**W2. Approve this week's software upgrade tickets (A, B)**
1. Objective: approve the upgrade tickets this week's check proposed, and confirm they were created.
2. Starting information: you are an Approver, and you did not start or schedule the check.
3. Expected result: the tickets exist in the (practice) Jira, and the software list reflects it.
4. Rules: you see exactly what will be written; you approve or decline the whole set; you can't approve your own run.

**W3. Look up a tool's version (A, B)**
1. Objective: answer a colleague: "Which version of LangGraph do we run, and how did it get there?"
2. Starting information: the tool's name only.
3. Expected result: the current version, the newest version, and the events that led to the current version.
4. Rules: "our version" changes when an upgrade ticket is marked Done.

### Occasional tasks

**W4. Start tracking a new tool (A, B)**
1. Objective: your team now runs Kubernetes and wants to know when it falls behind.
2. Starting information: the tool's name. Its public GitHub project is kubernetes/kubernetes, but assume at first that you don't know this.
3. Expected result: the tool is on the list, and it's clear when it will first be checked.
4. Rules: all release checks belong in one software list, and there should be no duplicate entries.

**W5. Set up a new weekly task (A; B in a different form)**
1. Objective: every Friday at 5pm, sum up the Jira tickets your team closed that week and put the summary on your team's "Weekly summary" Confluence page.
2. Starting information: what you want done, when, and which page.
3. Expected result: the task is switched on, you know when it next runs, and a trial has been approved by someone else.
4. Rules: changes to Confluence need an Approver who isn't you. A capability that doesn't exist yet needs an Approver's OK first.

**W6. Handle every decision waiting for you, as Bob (A, B)**
1. Objective: as Bob (Approver only), clear everything waiting for your decision.
2. Starting information: you're Bob, and colleagues have sent requests.
3. Expected result: every waiting decision is made, and each requester can tell it was made.
4. Rules: Bob can't set up workflows; Bob can't approve his own work.

**W7. First day for a new team (A)**
1. Objective: your team has just been given the app and nothing is set up yet. Get started.
2. Starting information: an empty account (use the test control "Show: Day one").
3. Expected result: at least one workflow or tracked tool set up, and an understanding of what happens next.
4. Rules: nothing runs until set up and switched on.

### Time-sensitive tasks

**W8. A morning task stopped (A; B with a different failure)**
1. Objective: a task that runs every morning stopped today. Find out why and get it working again.
2. Starting information: you learn about it in the app.
3. Expected result: the task works again, and you know what was wrong.
4. Rules: some failures can be fixed by the operator and some can't.

**W9. Check and approve from a phone (A, B)**
1. Objective: you're away from your desk and want to see what needs you and approve one item.
2. Starting information: a phone-sized screen (about 390 x 844).
3. Expected result: the approval is done on the phone.
4. Rules: as in W2.

### Exceptions and recovery

**W10. A task stopped and you can't fix it (A)**
1. Objective: get the problem to the people who can fix it, and know where to follow progress.
2. Starting information: the app tells you a task stopped.
3. Expected result: support has the details, you can see progress, and the task runs again once it's fixed.
4. Rules: the operator can't change the platform.

**W11. You disagree with a proposed change (A, B)**
1. Objective: decline a proposed change, and understand what happens next.
2. Starting information: a change is waiting for your decision.
3. Expected result: nothing is written, and you know whether and when it will come back.
4. Rules: declining writes nothing.

**W12. Interrupted set-up (A)**
1. Objective: you start setting up a new task, are interrupted, and need to continue later without losing work.
2. Starting information: a half-finished set-up.
3. Expected result: you resume where you stopped.
4. Rules: none.

**W13. Waiting on a colleague (A)**
1. Objective: your set-up needs a colleague's OK. Find out whether they have given it, and continue when they do.
2. Starting information: you've asked for the OK.
3. Expected result: you know the status and finish the set-up.
4. Rules: the OK must come from an Approver who isn't you.

### Searching, filtering and updating

**W14. Find what's broken or behind (A, B)**
1. Objective: list every task that is currently stopped, and every tool that is behind.
2. Starting information: none.
3. Expected result: two short lists.
4. Rules: none.

**W15. Change an existing task (A, B)**
1. Objective: move an existing weekly task to a different day, or pause it for two weeks.
2. Starting information: the task's name.
3. Expected result: the change is saved, and the next run time reflects it.
4. Rules: none known.

**W16. Change how an agent works (A)**
1. Objective: your team only wants to hear about software whose support ends within 3 months, not within a year. Then undo the change.
2. Starting information: the agent that reads support dates. You don't know its name at first.
3. Expected result: the change is saved, you know which workflows it affects and from when, and you can put it back.
4. Rules: no change may skip an approval or add a tool.

**W17. Find out why the software check missed a tool (A)**
1. Objective: Monday's software check couldn't check Grafana. Find which tool had the problem, and whether it works now.
2. Starting information: the name Grafana.
3. Expected result: you know what went wrong, whether it's working now, and whether you or support need to do anything.
4. Rules: checking must not change anything.

**W18. Get a tool the agents don't have (A)**
1. Objective: your team wants new upgrade tickets put in the Platform component in Jira. Make that happen for the agent that drafts tickets.
2. Starting information: what you want. You don't know which agent or tool is involved.
3. Expected result: the agent drafts tickets in the Platform component from its next run.
4. Rules: a new tool that changes data needs an OK from an Approver who isn't you (act as Bob for that part). No tool may skip a yes.

**W19. The AI key has expired (A)**
1. Objective: your provider has given you a new API key because the old one expired. Put it in, and make sure the agents can still answer. (Use the test control "Make the next key fail" first, to see what an expired key looks like.)
2. Starting information: the new key. Any made-up key of 20 or more characters works in the prototype.
3. Expected result: the new key is saved, a test answer came back, and you know when agents start using it.
4. Rules: nobody, including you, can read a saved key back.

**W20. A new colleague joins as an Approver (A)**
1. Objective: Mei Ling has joined the team and will approve changes. Give her access, and make sure she can be named on a workflow.
2. Starting information: her name.
3. Expected result: Mei Ling is an Approver and can be chosen as a backup on a workflow.
4. Rules: making someone an Approver needs a second Approver to confirm it (act as Bob for that part).

### Tasks currently reported as difficult or time-consuming (from the sponsor, before the app)

- Checking many tools for new versions one by one.
- Typing an upgrade ticket for each tool.
- Getting and recording approvals in Teams.
- Finding out why an automated job failed without a technical person.

---

## 5. Current UI/UX design

This section describes the design as built. It makes no claim about how well it works for users.

### 5.1 Main navigation structure

**A, desktop:**
- Header, left to right: the name "AI Workflow Builder", then **Home**, **Workflows**, **Software watchlist**, **Agent library** and **+ New workflow**. On narrower screens the name shortens to "Workflow Builder" or to its mark alone, and the signed-in person's role shows on hover only. Approvers who aren't Operators don't see New workflow.
- On the right: a **Teams** button with a number badge (approval requests waiting for you), an icon-only **Settings** button, and the signed-in person's name. Their role shows on hover.

**A, phone and small tablet (under 900 px):** the menu moves to a bottom tab bar: Home, Workflows, Watchlist, Agents, New workflow.

**B, desktop:**
- Header: **Runs**, **Builder**, **Software**, **Approvals**, **Teams**, **Jira**.
- On the right: a tour flag, a theme toggle, a Settings gear and the user menu.

**B, phone:** a bottom tab bar.

### 5.2 Screen inventory

```
A. Redesign prototype
Home
  ├─ Needs you (approval, no answer, stopped workflow, platform fault, tool OK, fix ready)
  ├─ Following up (report to support tracker)
  ├─ Waiting on others · Your drafts · Coming up
  └─ Day one: Start your first workflow · How it works
Workflows (find, filters, cards)
  └─ Workflow page (facts, change schedule, change who approves, pause or resume, delete, support case, what it does, recent runs)
      └─ Run page (live activity view)
          ├─ Approval panel (evidence links, who has been asked, approve / decline, own-work and not-named locks)
          ├─ Troubleshooter panel (fix and retry, or report)
          └─ Result panel
Software watchlist (schedule and change, who approves and change, this week's approval, find, needs a person, not checked yet, up to date, add software, history and remove per tool)
New workflow (1 Describe it · 2 Check what I understood · 3 When and who · 4 Turn it on) → Your workflow is on → test run
OK a new tool? (Approver)
Agent library (platform agents and specialist agents, each with what it may do and the workflows that use it)
  Agent details dialog (how it works, change it in plain English, tools, rules, where it's used, version history)
  Tools tab (tools that change data, tools that only read, waiting for an OK, asked the team, need a tool that isn't here?)
  Tool details dialog (status and Check it works, what it can and can't do, agents that use it, recent changes, or a new tool's draft for an OK)
Settings, in 4 tabs: AI model (provider, API key, model, Test and save), Connections (GitHub, Jira, Teams keys), People and roles, AI usage (this month and the limit). Each tab has its change history
Overlays: Teams panel (practice), Report to support dialog, agent details, ticket view, delete confirmation, toasts (some with Undo)
Test scaffolding (not the product): Test controls panel

B. Current MVP
Runs (latest run, earlier runs) → Run page (tracker, minutes, technical details, troubleshooting advice, retry)
Builder (describe task, Room lead's plan, agent library, card editor, your use cases)
Software (schedule, check now, needs a person, add software)
Approvals → Approval page
Teams (practice)
Jira (practice)
Settings (AI model)
Guided tour overlay
```

### 5.3 Dashboard information

**A, Home:**
- The date and a greeting, with a count of things needing you.
- "Needs you" cards. Each has an icon, a title, context, a short explanation, and one main button plus secondary buttons.
- "Following up", "Waiting on others", "Your drafts" and "Coming up" (next runs).

**B, Runs:** the latest run's live activity view, then a list of earlier runs with status pills and coloured dots for their steps.

### 5.4 Forms and data entry

**A:**
- **New workflow:**
  - Step 1: an empty free-text task box with an example as a placeholder, plus 3 suggestion chips.
  - Step 2: a dropdown on each understood line to correct it.
  - Step 3: how often, day (or day of the month) and a free time field, in Singapore time. Who is asked first and a backup (or "Nobody else"), with the resulting rule in one sentence. Under "More approval options": a checkbox for 2 Approvers one after the other, when to ask the backup and when to stop waiting, in working hours.
  - Step 4: a name field, a one-sentence summary, separate lines for where approval requests go and where the result goes, and a check of the workflow against the request.
- **Add software:** name, where it's published (GitHub, Maven Central, npm, PyPI, NuGet, Docker Hub, or "Not sure: let the Version checker find it"), the reference for that source, and an optional version.
- **Change schedule** and **Change who approves:** on a workflow page and on the Software watchlist.
- **Find:** search boxes on Workflows and Software watchlist.
- **Report to support:** an optional note.

**B:**
- **Builder:** a task box, and a card editor with fields for the plan, tools and inputs.
- **Software:** add software.
- **Settings:** provider choice and key.
- **Run inputs:** for example the Jira project.

### 5.5 Notifications and status indicators

**Status pills:**
- A: two separate facts. Whether a workflow is switched on ("On" or "Paused"), and whether its latest run needs someone ("Needs a yes" or "Stopped"). Run pages show "Replaying", "Waiting for a yes", "No answer", "Stopped" or "Done".
- B: Done, Waiting, Failed, and others.
- Each pill has an icon and text.

**Other indicators:**
- **A:** a badge on the Teams button; short-lived toasts at the bottom, some with Undo; coloured card borders on Workflows; run-line steps with icons; a feed of agents' messages; a Home item when someone else's decision lets you carry on.
- **Practice Teams messages** show approval requests in both A and B.
- **No email or browser notifications** in either.

### 5.6 Search and filtering

- **A:** a search box and four filters (All, Needs you, Stopped, Paused) on Workflows, and a search box on the Software watchlist. No sort.
- **B:** none found by the developer. Long lists are split into groups instead.

### 5.7 Error handling and validation

**A:**
- Inline errors under fields, for example a missing name, a GitHub repository that doesn't look right, a duplicate tool, an empty task, a missing time, a missing Approver or backup, or a backup wait that isn't shorter than the stop time. Focus moves to the field with the problem.
- The understanding check flags parts of a request it couldn't tell or can't do, and keeps Next disabled until they're resolved.
- Disabled buttons explain why, for example "Next opens when you choose which tickets".
- Delete asks for confirmation, and Delete and Remove offer Undo.
- A troubleshooter panel on stopped runs.

**B:**
- Inline messages.
- Rule-based troubleshooting advice and Retry on failed runs.
- Errors from the API are shown in plain words.

### 5.8 Mobile and responsive support

- **A:** bottom tab bar; the run line turns vertical; no sideways page scrolling at 375 px. Checked by the developer in Chromium only.
- **B:** bottom tab bar on narrow screens. There are browser tests for this.

### 5.9 Accessibility features

These are claimed by the developer and have not been independently verified.

**A:**
- Visible keyboard focus.
- Headings for page sections.
- The Teams panel and report dialog keep keyboard focus inside them, and Escape closes them.
- Status changes and new agent messages are announced to screen readers through a live region.
- Animations are turned off for people who ask for reduced motion.
- Text contrast is designed to be at least 4.5:1, with secondary text at 7:1. Measured by the developer.
- Buttons are at least 44 px tall on touch screens.

**B:**
- Keyboard and reduced-motion browser tests (`keyboard.spec.ts`, `reduced-motion.spec.ts`).
- Automated accessibility checks with axe.

**Neither has been tested with a real screen reader user.**

### 5.10 Visual style

- **A:** light theme only on a white page; Atkinson Hyperlegible Next font; one main dark button per screen; coloured agent faces.
- **B:** light and dark themes.

---

## 6. Known issues and incomplete areas

The confirmed issues below describe version 2. They come from the developer's knowledge of how the prototype was built, and from one internal automated walkthrough on 27 Oct 2026. That walkthrough also produced usability opinions. **Those have been left out on purpose,** so that your evaluation stays independent. Only factual, reproducible behaviour is listed here.

### 6.1 Confirmed: Target A (redesign prototype)

**Simulation and placeholders**
1. All data is simulated in the browser tab. A reload, closing the tab or "Start over" loses everything.
2. Every screen shares one address, so Back and Forward don't move between screens and screens can't be bookmarked.
3. The date and time are fixed at Tue 27 Oct 2026, 9:10, Singapore time. Ticket numbers, people and release details are sample values.
4. Typed tasks are read with simple word rules, not an AI model. It handles tasks about Jira tickets in project MOCK: tickets closed this week, open tickets with no update for a number of days, or all open tickets; writing a summary or asking each owner; and posting in Teams or adding to a Confluence page. Anything else is flagged "Please choose" or "Can't do this yet". Unusual wording may be misread, and the understanding check shows what was read.
5. Release-check recognition uses a fixed list of about 14 well-known names. Other names get a general message.
6. Some dropdowns have a single option: Jira project "MOCK", the Confluence page and the Teams channel.
7. These buttons only show a message: "Check now" and "Not now" (on a tool request).
8. GitHub, registry, NVD, CISA, Apache and endoflife.date links open the real public pages. The versions, release notes and vulnerability counts shown in the prototype are samples, so they may not match those pages.
9. Connecting an AI model in Settings is simulated: nothing is sent, any key of 20 or more characters connects, and the test control "Make the next key fail" shows an expired key. The connections, people and AI usage in Settings are sample data too, and their tests and key replacements are simulated. The agents and their tools are sample data. Changing an agent in plain English uses scripted replies, not an AI model. Each agent understands the 1 to 3 kinds of request shown as its examples, and refuses any request to skip a yes. Anything else gets "I couldn't turn that into a safe change", with an example. On Tools, "Need a tool that isn't here?" works the same way: it understands a few kinds of request (its examples, plus questions about tools that exist), and "Send to the team" only adds the request to the list. "Check it works" is simulated and always gives the same result for each tool.
10. The "Quarterly access review" workflow is a static sample. It can be paused or deleted, but none of its runs can be opened.
11. Report to support creates one sample case (SUP-1042) with a sample owner and reply time. Its stages move only through the test controls.
12. Only one new workflow can exist in a session. Turning on a second one replaces the first.
13. Only Alice and Bob can be acted as. Carol, who owns the software schedule at the start, can't. Siti and Arun can't either; their answers are under "Make something happen".

**Not available**

14. A workflow's plan can't be edited once it's on. Its schedule can be changed.
15. A tool's details on the Software watchlist can't be edited. It can be removed.
16. There is no sort. Search exists on Workflows and Software watchlist only.
17. Time passes only through the test controls, and only for a test run of a new workflow. This week's software check already went to its backup on Monday, and it never stops by itself. Working hours don't skip public holidays.
18. An Approver can't approve part of a check. The approval covers the whole check (ADR 0019).
19. The software check can be rescheduled but not paused.

**Known inconsistencies**

20. On a workflow page, only the most recent run can be opened.
21. The Teams badge counts approval requests, so one request covering 2 tickets shows "1".
22. The "Day one" view keeps any software added earlier in the same session.
23. The Test controls button stays at the bottom left and can cover a small part of the page. It's closed by default.

### 6.2 Confirmed: Target B (current MVP)

1. The troubleshooting advice is a fixed explanation for each of 8 failure types. It is not generated for the specific failure.
2. AI planning in the Builder and AI-written summaries need a model key connected by the team. Without one, the Builder offers only starter cards and summaries use a built-in sentence.
3. Teams and Jira are practice pages inside the Portal. Nothing reaches real Microsoft Teams or Jira.
4. There is no password sign-in in the local setup (user switcher only). Company sign-in is configured only for the Azure deployment, which is started by hand and isn't available to external testers.
5. Release checks can be created in more than one place: the Software page, the "Release checker" starter card, and use cases. The local data contains several test use cases and runs with near-identical names.
6. GitHub may rate-limit release reads when no token is set, which can make runs fail.
7. "Mark Done" on the practice Jira page changes data and updates "our version".
8. `scripts/down.sh` deletes all local data.
9. None of the prototype A features listed as "Not implemented" in section 3.2 exist in B.

### 6.3 Suspected or unverified

- The public link for A hasn't been tested from a signed-out browser. It may ask for a claude.ai sign-in depending on account settings.
- A has only been used in Chromium (Chrome). Safari and Firefox are untested.
- Neither A nor B has been tested with a screen reader such as NVDA or VoiceOver.
- During internal automated testing, the test browser once returned to the start screen unexpectedly. It wasn't reproduced and is believed to be caused by the shared test browser, not the app.
- A's behaviour with large amounts of data (for example 50 or more tools or workflows) is untested, because its sample data is small.
- A's fonts load from Google Fonts. Offline, the system font is used, and layout may shift slightly.
- A's word rules have been tested by the developer on a small set of phrasings only. Other phrasings of a supported task may be flagged as unclear.

### 6.4 Features that need future development

- **Phase 2:**
  - The quarterly access review with two Approvers in order.
  - Connectors for Confluence, Microsoft Teams, Entra ID and GitLab.
  - Patch housekeeping inside the NCS private network (DevNet).
- **Turning the A design into the real Portal:**
  - Home, Workflows with search and filters, workflow controls (schedule, pause, delete), the understanding check, the history timeline, report to support with case tracking, drafts and the release check redirect.
  - Tool cards, which need a formal design decision (ADR). The prototype shows them in New workflow and on Tools.
  - Tool status and "Check it works", which need a harmless check for each tool.
  - Named Approvers, backups and escalation, which also need an ADR because they change the approval gate.
  - Changing agents in plain English. ADR 0023 already covers AI-drafted cards and card versions, but it needs the AI model, whose choice is still open.
- **AI-assisted fixes by coding agents,** reviewed by a developer. This needs the sponsor's agreement.
- **An audit page,** if time allows.

---

## 7. Evidence and supporting materials

### 7.1 Screenshots

**Target A, version 2** (1280 px wide, light theme, test controls hidden), in `docs/design/portal-routines/`:

| File | Screen |
|---|---|
| `home.png` | Home, normal week |
| `day-one.png` | Home on day one |
| `routines.png` | Workflows, with find and filters |
| `software.png` | Software watchlist, with the security risk at the top and LangGraph's history open |
| `security-risk.png` | The Log4j core security risk, with all 4 known vulnerabilities shown |
| `new-routine-understood.png` | New workflow, step 2: a request read correctly, with a similar workflow noticed |
| `new-routine-flags.png` | New workflow, step 2: unclear and unsupported parts flagged |
| `new-routine-plan.png` | New workflow, step 2: the Confluence example, with the new tool that needs an OK |
| `new-routine-schedule.png` | New workflow, step 3: when, and who is asked first with a backup |
| `new-routine-review.png` | New workflow, step 4: checked against the request, with one change marked |
| `release-check-redirect.png` | New workflow, release check sent to the Software watchlist |
| `run-approval.png` | Run page waiting at the approval gate, with evidence links and who has been asked |
| `run-escalated.png` | A test run after the first Approver didn't answer in time, so the backup was asked too |
| `home-no-answer.png` | Home after nobody answered a test run in time |
| `report-to-support.png` | Run page after reporting to support, with the case |
| `routine-manage.png` | Workflow page, changing the schedule |
| `routine-approvers.png` | Workflow page, changing who approves |
| `agent-library.png` | Agent library: each agent, whether it only reads or changes data after a yes, and the workflows that use it |
| `agent-details.png` | Agent details for the Version checker: how it works, its tools and rules |
| `agent-change.png` | A plain-English change to the Version checker, with the changed step marked and the safety checks |
| `agent-change-refused.png` | The Planner refusing a change that would skip the approval |
| `agent-library-tools.png` | Agent library, Tools tab: tools that change data and tools that only read, who uses each, and whether it's working |
| `tool-details.png` | Tool details for Read package registries, after Monday's problem with Docker Hub |
| `tool-draft.png` | A new tool drafted by the Planner for the Ticket writer, before asking an Approver to OK it |
| `tool-ask.png` | Asking the Planner for a tool that isn't there yet |
| `settings.png` | Settings, AI model tab: what's connected, and the form to change the provider, key or model |
| `settings-connections.png` | Settings, Connections tab: GitHub's key expires in 9 days |
| `settings-people.png` | Settings, People and roles tab |
| `settings-usage.png` | Settings, AI usage tab: this month's questions, cost, limit and questions by workflow |

Version 1 of the prototype and its screenshots are in `docs/design/portal-routines/v1/`.

**Target B** (1440 px wide), in `docs/handover/screens/`:

| File | Screen |
|---|---|
| `current-runs.png` | Runs |
| `current-builder.png` | Builder |
| `current-software.png` | Software |
| `current-approvals.png` | Approvals (empty at capture time) |
| `current-teams.png` | Teams, practice copy |
| `current-jira.png` | Jira, practice copy |

The Settings screen was not captured, because it shows part of the team's AI key.

### 7.2 Requirements and design documents

**Read these after testing if possible.** They contain the designers' reasoning, which could bias the evaluation.

| File | What it is |
|---|---|
| `README.md` | What the project is, and how to run it |
| `GLOSSARY.md` | The names used in the product |
| `docs/design/software-watchlist-prfaq.md` | Product brief for the software list |
| `docs/design/agent-builder.md` | One-page design for AI-drafted agents |
| `docs/design/portal-routines.md` | Design note for prototype A, with its rationale |
| `docs/evidence/usability/2026-10-27-chatgpt-v1-evaluation.md` | An earlier independent evaluation of version 1 |
| `docs/evidence/usability/2026-10-27-chatgpt-v2-approvers-review.md` | An earlier independent review of the named Approvers in version 2 |
| `docs/design/walking-skeleton.md` | The first end-to-end design |
| `docs/adr/` | 25 recorded design decisions. 0008 (approvals), 0019 and 0020 (software list), 0022 (AI model), 0023 (agent cards), 0024 (named Approvers, proposed) and 0025 (more sources and vulnerability lookups, proposed) are the most relevant. |
| Appendix A | User stories |

### 7.3 Existing tests

All existing automated tests cover **B, the current MVP**. **There are no automated tests for prototype A.**

| Area | Location | Count |
|---|---|---|
| Portal unit tests | `portal/src/**/*.test.ts(x)` | 53 files |
| Portal browser tests | `portal/e2e/*.spec.ts` | 15 specs: approvals, builder, guards, inboxes, inventory, keyboard, overview, reduced motion, run, settings, smoke, software, steady, tour, video |
| platform-api tests | `platform-api` (`test_*.py`) | 45 files |
| agent-runtime tests | `agent-runtime` (`test_*.py`) | 21 files |
| End-to-end scenarios (whole stack) | `e2e/tests/` | 7: happy path, rejected, failure and retry, safety, schedule, watchlist, agent cards |
| AI evaluation golden sets | `agent-runtime/evals/` | |
| Security scan (OWASP ZAP) and load test (k6) results | `docs/evidence/dast/`, `docs/evidence/load-test/` | |

### 7.4 Architecture overview

Plain terms, for B:
- **Portal:** the web page people use.
- **platform API:** the Python service that decides everything about runs, approvals and safety.
- **n8n:** a workflow engine that carries each run step by step, and every 5 minutes asks the platform which scheduled runs are due.
- **Agent runtime:** where the AI agents (built with LangGraph) read data and propose changes.
- **PostgreSQL:** stores runs, approvals and the activity log.
- **Safety:** agents only propose changes. Only the platform writes, and only after an Approver says yes.

Diagrams: `docs/design/diagrams.md`.

A is a single HTML file with no backend.

### 7.5 Demo data

| | A | B |
|---|---|---|
| People | Alice, Bob, Siti, Arun; Carol (schedule owner), Dana (support developer) | alice, bob, carol |
| Workflows or use cases | 4 sample workflows, plus 1 you can create | About 6 use cases and about 12 runs from team testing |
| Software | 14 tools on GitHub or Maven Central (3 behind, 1 with a critical known vulnerability, 1 can't check, 10 up to date) | Watchlist with LangGraph |
| Practice systems | Jira project MOCK, Teams channel CODESparks Support | Jira project MOCK, Teams channel CODESparks Ops |
| Date | Fixed: Tue 27 Oct 2026 | Real clock |

### 7.6 Installation instructions

See section 2, and `README.md` ("Run it locally").

---

## 8. Independent evaluation instructions for ChatGPT

### Independent Operator Usability Evaluation

You are acting as an independent usability evaluator, not a software developer.

Your primary responsibility is to simulate the experience of an actual operator using this application to perform daily work.

You must evaluate whether the application genuinely helps users complete their responsibilities efficiently, accurately, and with minimal frustration.

Do not assume the implementation is good simply because the features exist.

Do not rely on the developer's intended navigation when testing.

Approach the application as a first-time operator who understands the job responsibilities but has never used this system before.

Where browser interaction is available:

1. Open the prototype.
2. Explore the interface without looking at the implementation code.
3. Identify what tasks appear possible.
4. Attempt realistic daily operator workflows.
5. Observe navigation, terminology, feedback, information availability, and interaction friction.
6. Record unexpected behavior and points of confusion.
7. Evaluate whether the application meaningfully reduces the operator's workload.
8. Identify unnecessary actions, missing features, and opportunities for automation.
9. Test common exception scenarios and recovery paths.
10. Produce an independent usability evaluation report.

For each workflow, record:

* Task objective
* Expected user behavior
* Actual interaction path
* Task completion status
* Number of actions or steps taken
* Confusing or inefficient interactions
* Errors or unexpected behavior
* Missing information
* Impact on daily operations
* Recommended improvement

Evaluate the prototype across these dimensions:

A. Learnability

Can a new operator understand how to use the application without extensive training?

B. Efficiency

Can common tasks be completed with minimal effort, navigation, and manual input?

C. Workflow Suitability

Does the application support the way an operator actually works, rather than forcing the operator to adapt to the system?

D. Information Architecture

Is information logically organized and easy to locate?

E. Error Prevention and Recovery

Does the system help operators avoid mistakes and recover when something goes wrong?

F. Operational Productivity

Does the application genuinely save time, reduce repetitive work, and improve daily operations?

G. Visibility and Feedback

Does the operator always understand the current status, what happened after an action, and what to do next?

H. Missing Capabilities

What features or workflows are absent that an actual operator would reasonably expect?

Provide severity ratings, evidence, and actionable recommendations.

Distinguish between issues observed through actual interaction and concerns inferred from the supplied documentation.

Do not invent test results. If direct prototype interaction is unavailable, clearly state that the assessment is limited to documentation and screenshots.

The final report should prioritize improvements based on their effect on operators' daily tasks, rather than visual appearance alone.

---

## Appendix A: User stories

These stories were drafted by the development assistant on 27 Oct 2026, from the sponsor's stated needs. The team hasn't reviewed them yet. Acceptance criteria are left out so they don't suggest a route through the screens.

**Priority:** MVP means the first presentation (late Nov 2026). Phase 2 means later.

**Know what to do**
- US-01 (MVP): As an Operator, I want to see only what needs me today, so that I know my next step without searching.
- US-02 (MVP): As a new Operator on a team with nothing set up, I want to be shown how to start, so that I can set up my first workflow without training.
- US-03 (MVP): As an Approver, I want to see only the decisions waiting for me, so that I don't wade through other people's work.

**Set up a workflow**
- US-04 (MVP): As an Operator, I want to describe a repeated task in plain English, so that I can automate it without a technical person.
- US-05 (MVP): As an Operator, I want a saved agent reused when it fits, so that the same kind of task doesn't create duplicates.
- US-06 (MVP): As an Operator, I want to choose when a workflow runs and who approves it, so that it runs on its own after that.
- US-07 (MVP): As an Operator, I want a clear confirmation that my workflow is on, so that I know I'm done.
- US-08 (MVP, nice to have): As an Operator, I want to save a half-finished workflow and come back to it, so that I don't lose work while waiting for someone.
- US-09 (MVP): As an Operator, I want to connect our AI model myself, so that the agents work without a developer changing configuration.

**Keep software up to date**
- US-10 (MVP): As an Operator, I want all our software in one list with our version and the newest version, so that I can see what's behind at a glance.
- US-11 (MVP): As an Operator, I want every listed tool checked weekly with one approval for all its tickets, so that many tools don't mean many approvals.
- US-12 (MVP): As an Operator, I want "our version" to update by itself when the upgrade ticket is marked Done, so that nobody types versions by hand.
- US-13 (MVP): As an Operator, I want to see each tool's history, so that I can answer how we got to this version.
- US-14 (MVP): As an Operator, when I ask for a release check, I want it added to the software list instead of creating a separate task, so that release checks stay in one place.

**Approve changes**
- US-15 (MVP; real Teams later): As an Approver, I want approval requests in Teams, so that I can decide without opening another app.
- US-16 (MVP): As an Approver, I want to see exactly what will be written before I approve, so that I never approve something vague.
- US-17 (MVP): As an Approver, I want to be blocked from approving my own work, so that every change gets a second pair of eyes.
- US-18 (MVP): As an Approver, I want to decline a change and know what happens next, so that saying no is safe.
- US-19 (Phase 2): As an Approver of access changes, I want two Approvers one after the other, so that removing access is never one person's decision.

**Watch a run**
- US-20 (MVP): As an Operator, I want to watch a run step by step and see what each agent said, so that I understand what happened and where it stopped.

**When something goes wrong**
- US-21 (MVP): As an Operator, I want a plain-language explanation of why a run stopped and whether I can fix it, so that I don't need a technical person.
- US-22 (MVP, filing only): As an Operator, I want to report a platform problem in one step, so that support gets everything without me writing it up.
- US-23 (Phase 2): As a support developer, I want each report to arrive as an issue with the failed run attached, so that I can reproduce it quickly.
- US-24 (Phase 2): As a support developer, I want coding agents to draft a fix with tests for me to review, so that fixes take less time. Only a person merges and deploys.

**Grow what agents can do**
- US-25 (Phase 2): As an Operator, when my task needs a capability we don't have, I want the AI to draft it for an Approver to OK, so that the team can grow without a developer.

**Across the product**
- US-26 (MVP): As the sponsor, I want every agent action logged with who approved it, so that we can show what happened later.
- US-27 (Should have): As an Operator or Approver, I want the Portal to work on my phone, so that I can check and approve away from my desk.
