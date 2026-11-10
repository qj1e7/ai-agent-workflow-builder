# Prototype version 4: hands-on evidence log

Date: 10 Nov 2026. Tester: an AI agent acting as a non-technical Operator (Alice) and an Approver (Bob).

## How this was done

- **File under test.** The current `origin/main` copy of `docs/design/ai-native-redesign/prototype.html` (512,331 bytes), saved as a scratch copy and opened with `file://`. It was not edited.
- **Browser.** Playwright driving Google Chrome (`channel: 'chrome'`), 1280 x 900 unless a 390 px phone width is stated.
- **Starting state.** The product as shipped: Planned features Hidden, Mark what isn't built Off, AI model Connected. The test controls were used only to set the starting state, except where a section says otherwise.
- **Counting.** A *click* is one press on a button, link, chip, tab or menu item. A *submit* is pressing Enter in the Planner box. A *field* is one typed box. A *select* is one choice in a drop-down or radio group. Test-control presses are never counted. "Interactions" = clicks + submits + fields + selects.
- **Screens.** The address hash after each step (`home`, `workflows`, `workflow/<id>`, `run/<id>`, `software`, `agents`, `settings`).
- **Sources.** On-screen text is quoted exactly. Anything explained from the page's source code is marked **(from code)**. Screenshots are in `../shots/v4/`.
- **Console.** A listener recorded every page error and console error. The only errors in the whole session were 5 page errors from the Tools tab (see Broken things, item 2). All scenarios A to H ran with zero errors.

---

## 1. Screen inventory

Legend for each control: **works** (did something real in the prototype), **simulated** (works, but only as scripted sample behaviour, as the spec says), **refused** (shown, but a press only gives a "can't" message), **not clicked** (seen, not pressed), **Planned only** (appears only with Planned features shown).

### 1.1 Header and menu (every screen)

| Control | Alice | Bob | Result |
|---|---|---|---|
| Brand "AI Workflow Builder" | yes | yes | works, goes Home |
| Home | yes | yes, with the count ", 1 need you" | works |
| Workflows, with amber count "5" | yes | yes, no count | works |
| Software watchlist | yes | yes | works |
| Agent library | yes | no | works. Bob typing `#agents` gets Home's content (hash stays `#agents`) |
| Teams, with "1" | yes | yes | works, opens the drawer |
| Settings (icon) | yes | yes | works |
| Skip to main content | yes | yes | works (moves focus to the page heading) |
| At 390 px | bottom tab bar: Home, Workflows (count), Watchlist, Agents | | works |

### 1.2 Home

**Alice, normal week** (`v4-home-01-alice-normal-week.png`). Shows first: the Visor bot, "Good morning! Alice", "Some things need you.", the box with placeholder "Ask about your software versions, or name software to watch", three chips, then "Needs you 5" with 3 of the 5 rows.

| Control | Result |
|---|---|
| Box + Enter / send arrow | works (word rules, simulated) |
| Chip "Which software has a newer version?" | works, but the answer does not answer the question: "There are 14 software on the Software watchlist. Looked at: Software" (`v4-inv-07-chip-which-software-newer.png`). See Broken things, item 6 |
| Chip "Watch another software for new versions" | works: "Which software should I watch?" |
| Chip "What can you do?" | works: the I can list (3 lines) |
| Row "Morning new-ticket check stopped" + **Retry the run** (primary) | works (scenario C) |
| Row "Weekly closed-ticket summary stopped" + Report to support | works (scenario C) |
| Row "3 upgrade tickets are waiting for your yes" + Review and decide | works (scenario D) |
| See all on Workflows | works |
| What can I ask for? | works: expands "What I can do" with the same 3 lines, becomes "Hide what I can do" |
| New chat (only once a thread exists) | works, brings Needs you back |

Hidden on Home but counted in "5": the LangServe address problem and "The GitHub key expires in 9 days". Both show only on Workflows.

**Alice, day one** (`v4-home-03-alice-day-one.png`). Heading "Which software should we keep up to date?", line "Ask about your watchlist, or tell me what software to watch.", the box, chips "Keep track of the LangGraph version" and "What can you do?", then an "I can" card with 3 lines. No Needs you, no count on Workflows. The send arrow is disabled until something is typed.

**Bob, normal week** (`v4-home-05-bob-normal-week.png`). "Good morning! Bob", "1 request is waiting for your yes.", Needs you 1 with the three upgrades listed ("Log4j core 2.14.1 → 2.25.2" and so on), **Review and decide**, then "You're an Approver, so you decide on requests. Operators set up workflows." No box, no chips. Matches spec 5.3.

**Bob, day one** (`v4-home-06-bob-day-one.png`). "Nothing needs you yet. When a workflow wants to change something, it shows up here and in Teams." then "All quiet / Nothing is scheduled yet." No controls.

**No AI model** (`v4-inv-04-home-no-model.png`). "I can't read new requests until an AI model is connected", **Connect a model**, Needs you 6 with "Morning new-ticket check stopped / Can run again once an AI model is connected." and See the run. The I can list moves "Create a Jira ticket after a yes" to Needs setup. Matches spec 5.4.

### 1.3 Planner answers seen on Home

Set-up card (spec 7), Part I can do, Can't with an alternative, Refusal, Abilities, Check my workflows, Why it stopped, What needs me, Watchlist card, Which software, Already listed. All were reached in the scenarios below. Set-up card controls: Rename (works: an inline name box and Done), chip drop-downs (work), the destination chip "one new Jira ticket" (works: "It's the only place I can put the summary today. Other places, such as Teams or email, aren't built yet." with Done and Ask the team, `v4-inv-08-destination-chip.png`), When > Change (works: How often + time, never pre-filled), How this workflow works (works), **Turn it on** (works, disabled until nothing is missing), then Do a test run and See it in Workflows.

### 1.4 Workflows

**Alice, normal week** (`v4-workflows-01-alice-normal-week.png`). "Needs you 5": the first item as a card with the AI troubleshooter line and **Retry the run** + See the run, then four rows (Report to support, Review and decide, Use the new address, See it in Settings). Then "All workflows 3", one row each with purpose, status pill and next run, and "Ask the Planner for a new one / Describe it in plain English, on Home".

| Control | Result |
|---|---|
| Retry the run, See the run, Report to support, Review and decide | works |
| Use the new address (LangServe) | works, and changes the watchlist (see 1.6). Not marked as unbuilt unless Mark what isn't built is On |
| See it in Settings | works (opens Settings, Connections) |
| Search (magnifier) | works: "Find a workflow" box plus All, Stopped, Paused filters. Paused with no paused workflow shows "No workflows match / Try other words, or see them all. / Show all workflows" |
| Row name links | works. "Keep our software up to date" opens the Software watchlist page, not a workflow page |
| Ask the Planner for a new one | not clicked |
| Drafts section (after leaving a card unfinished) | works: "Drafts 1 / Weekly summary / Needs when it runs, which tickets, the Jira project and what it does" with Resume and Discard. Discard gives "Discarded Weekly summary." with Undo (`v4-inv-01-workflows-drafts.png`) |
| Following up section (after a report) | works (scenario C) |

**Bob, normal week** (`v4-workflows-10-bob-normal-week.png`). Needs you 1 (the upgrade request), All workflows 3, search. No create action.

**Day one.** Alice: "Nothing here yet / Watch software on the Software page, or ask the Planner on Home. Its checks show up here." Bob: "Operators set up workflows, and you approve their changes."

### 1.5 Workflow page (Morning new-ticket check, Weekly closed-ticket summary)

Shows first (`v4-wfpage-01-morning-check.png`): status pill "Stopped", name, purpose sentence, Pause and More actions, a red banner "Stopped today at 8:00. Jira didn't answer, and it's answering again now." with **Retry the run**, then Schedule, Approval, Recent activity, Technical details (collapsed).

| Control | Result |
|---|---|
| Back "Workflows" | works |
| Pause | works: becomes "Paused. It won't run until you resume it." with **Resume**. Pausing a stopped workflow also removed the stopped run from Needs you (count 5 to 4, Home and tab agree) (`v4-wfpage-04-after-pause.png`) |
| More actions > Run now | Morning check: runs as "Today, retry". Weekly summary: **refused**, toast "It would stop in the same place until support fixes the platform. Report it first." |
| More actions > Change schedule | works (scenario E) |
| More actions > Delete | works: confirm dialog "Delete Weekly closed-ticket summary? ... Its past runs and their records stay. You can undo this from the message that follows." with Cancel and Delete workflow (`v4-inv-03-delete-confirm.png`). Not confirmed |
| Schedule > Change | works (scenario E) |
| Recent activity rows | only the newest row has "See the run". "Mon 26 Oct, 8:00 / 1 ticket created (MOCK-12), approved by Bob" and "Fri 23 Oct, 8:00 / Nothing to write" do not open anything |
| Technical details | works: Steps with Reads / No system access / "Changes data, waits for a yes", the 50-ticket limit line, Agents and tools |
| Agent chips (Planner, Jira reader, Summary writer) | works: opens the agent dialog (`v4-agent-01-jira-reader-dialog.png`) |
| More actions > Open in n8n | Planned only |
| Approval "Bob, with Siti as backup", Change who approves | Planned only |

Bob's view (`v4-wfpage-10-bob-morning-check.png`): no Pause, More actions, Retry or Change. Approval reads "Each run's ticket waits for a yes. Any Approver except Alice can say yes."

### 1.6 Run page

**Stopped run** (`v4-run-01-morning-check-stopped.png`). Headline "Stopped at Find new tickets", the station strip (Started, Pick agents, Find new tickets "Stopped here", Write summary, Approval gate, Create in Jira, Done), the AI troubleshooter's four answers (What happened / What was affected / Can it be fixed safely / What to do), **Retry the run**, then Show what each agent did.

| Control | Result |
|---|---|
| Retry the run | works (scenario C) |
| Report to support (platform bug run) | works (scenario C) |
| Show / Hide what each agent did | works: agent conversation, Replay the run, 1x / 2x / Instant |
| Replay and speeds | Replay plays automatically when a run page opens for a scripted run. Speeds not compared |
| Bob on a stopped run | no Retry. Text "An Operator can retry the run." |

**Approval run** (`v4-D-04-bob-approval-page-full.png`): What will change, Why, Who asked, What happens, Your part, **Approve** and Decline. Release notes and Project page links open GitHub in a new tab (not followed).

### 1.7 Software watchlist

**Alice, normal week** (`v4-watchlist-02-alice-normal-week-full.png`). "Needs attention 2" (the weekly upgrade request with **Review and decide**, and the LangServe address problem with Use the new address), "Software we watch 14" table (We run, Newest, Status), Add software, How it's checked (GitHub releases "Ready"; Package registries, Security advisories, Support end dates "Not yet"), Change schedule.

| Control | Result |
|---|---|
| Check now | refused while a yes waits: "This week's check is still waiting for a yes. Decide on it first, then check again." (`v4-watchlist-05-after-check-now.png`) |
| Review and decide | works |
| Use the new address | works: the row becomes "GitHub · langchain-ai/langchain ... Not checked yet / Now read from the new address." Toast "LangServe is now read from langchain-ai/langchain. It's checked at the next check, Mon 2 Nov, 9:00." with Undo (`v4-watchlist-04-after-use-new-address.png`). See Broken things, item 12 |
| Find software | not typed |
| History | works: per-row history, for example "Thu 15 Oct / Added by Carol from GitHub, with our version 2.14.1." |
| Remove | works: "Removed Terraform. It won't be checked any more." with Undo, count 14 to 13 |
| Add software (Software name + Find it) | works (scenario H). The placeholder "Kubernetes" sits in the empty box |
| Change schedule | works, with the warning "Saving makes you the owner of this schedule. Its checks then count as your work, so you won't be able to approve them." |
| Security risks, Support ending, registry sources | Planned only (`v4-planned-01-watchlist.png`) |

**Bob** (`v4-watchlist-10-bob-normal-week.png`): Check now and Review and decide are shown; no Use the new address (replaced by "An Operator can fix this."), no Remove, no Add software.

**Day one.** Alice: "No software yet" with **Add your first software**. Bob: the same "Add the tools your team runs. Each one is checked every Monday..." and "Ask the Planner on Home for a release check, and it adds the software here." with no control he can use.

### 1.8 Agent library (Alice only)

| Tab | Shows first | Controls and result |
|---|---|---|
| What it can do (`v4-agentlib-01-what-it-can-do.png`) | "I can 3": Check software for new releases on GitHub; Create a Jira ticket after a yes; Ask Approvers for a yes in Teams | none. "Read Jira tickets" and "Sum up what I find" are not listed, though two sample workflows and the Planner's set-up cards use them |
| Agents 6 (`v4-agentlib-02-agents.png`) | Planner, AI troubleshooter, Version checker, Ticket writer, Jira reader, Summary writer, each with a one-line job | Details and name links open the agent dialog: works. Workflow links work |
| Tools 2 (`v4-agentlib-03-tools.png`) | Create a Jira ticket (Working), Read GitHub releases (Working), then "Need a tool that isn't here?" with a box, three chips and **Ask the Planner** | tool cards open: not clicked. Request box: works for some requests, **crashes** for others (Broken things, item 2) |

Agent dialog (`v4-agent-02-jira-reader-details.png`): "Version 1. Ships with the platform", job, Where it's used, Last run, Details (How it works, Tools it may use, Permissions and rules, Version history). Read only: "Agents are read only here. Ask the Planner on Home for a workflow that works differently."

### 1.9 Settings

| Tab | Alice | Bob |
|---|---|---|
| Connections (`v4-settings-01-alice.png`) | GitHub "Key running out ... Ask whoever looks after the platform to replace it before Thu 5 Nov", Jira "Working", Microsoft Teams "Sends approval requests to Approvers". Check now works: "Checked just now. GitHub answered, with 4,812 of this hour's 5,000 reads left." Replace the key: Planned only | read only, "Only Operators change settings.", no Check now |
| People and permissions (`v4-settings-02-people.png`) | checkboxes for Operator and Approver per person, Add a person. Role changes work at once (scenario D). Add a person works: "Added Mei Ling. They can sign in with their NCS account." | checkboxes disabled |
| AI model (`v4-settings-03-ai-model.png`) | "Connected / AI Singapore gateway · claude-sonnet-5-5 / API key ending 7f", Test now works ("Tested just now: it answered in 1.7 s."), Provider select, key box, Show, Connect (not tested) | read only |
| Usage | Planned only | |

Day one: all three connections Working, GitHub key "Runs out Sun 25 Apr 2027".

### 1.10 Teams drawer

(`v4-teams-01-drawer-alice.png`) "Microsoft Teams / Practice copy. Nothing reaches the real Teams." then "Teams carries approval requests only. The button opens the approval page, where the decision is made." One card: workflow and owner, the three changes, Found, "Who can decide: Bob, Siti, Arun or Alice", "Who can't: Carol, who set this up and started this run. Nobody approves their own work.", and one button **Open in AI Workflow Builder** (works). No Approve or Decline. After Bob approved, the card's last line became "Approved by Bob at 9:10 today" (`v4-D-10-bob-teams-after-approve.png`). Escape closes it. Day one: no messages.

### 1.11 Test controls panel

(`v4-testctl-01-panel-open.png`) Show (A normal week / Day one), Act as (Alice / Bob), AI model (Connected / Not connected), Planned features (Shown and tagged / Hidden), Mark what isn't built (On / Off), Make something happen ("Jira stops answering", which becomes "Jira works again" after use), About this prototype, Start over. All worked. "About this prototype" says Siti and Arun's answers and letting time pass are under Make something happen; in the states tested, the only item there was the Jira one.

### 1.12 Claims against the capability registry (spec section 4)

- **Use the new address** for LangServe works and rewrites the row by default. Spec 11 says this 404 case is refused by the built platform (409). The prototype marks it as unbuilt only when Mark what isn't built is On (`v4-inv-05-mark-unbuilt-watchlist.png`).
- **Tools tab request box.** Spec 12 says "The tab offers no request for a new tool." The tab has one ("Need a tool that isn't here?").
- **Teams.** The Planner's G answer says "Teams carries approval requests, run outcomes and requests for the team. It posts nothing else." The Teams drawer says "Teams carries approval requests only." Settings says "Sends approval requests to Approvers".
- No Planned or Unsupported capability was shown as working in the default state apart from the LangServe button. Planned items appeared only with Planned features shown, each tagged "PLANNED".

### 1.13 What Planned features adds (turned on once, at the end)

Home and Workflows: "3 upgrade tickets are waiting for your yes, 1 urgent". Workflows: a "Quarterly access review" workflow (PLANNED) and "Prefer to build it yourself? Start in n8n PLANNED". Workflow page: "Bob, with Siti as backup PLANNED", Change who approves, Open in n8n in the menu. Watchlist: "Security risks PLANNED" with "Log4j core 2.14.1 / Critical security risk that attackers are using now ... Critical 10.0/10 ... From CISA's list", "Support ending PLANNED", registry rows. Agent library: "Agents 10" and a drafting line. Settings: Usage tab and Replace the key buttons, each PLANNED. (`v4-planned-01-watchlist.png`, `v4-planned-02-workflows.png`, `v4-planned-03-workflow-page.png`)

---

## 2. Scenario results

### A. First-time Operator (Day one, Alice)

**Typed exactly:** "Every Friday at 9 AM, find Jira tickets that haven't been updated for 10 days and prepare a summary." (straight apostrophe, as on a keyboard).

**Steps:**
1. [field] typed the sentence. 2. [submit] Enter.
   Reply: "Here's what I understood. I filled in what I could." and a set-up card "Friday summary": "Every Friday at 9:00, find [which tickets ▾] in [a Jira project ▾], [sum them up ▾], and put the summary in [one new Jira ticket]." The ticket choices are "Tickets closed this week / Tickets created this week / Open tickets". Footer: "2 choices left: which tickets and the Jira project." (`v4-A-02-reply-full.png`)
   **The "haven't been updated for 10 days" part appears nowhere** on the card, in the reply, or under How this workflow works.
3. [click] How this workflow works. It says "Find the tickets (which ones isn't decided yet) / Reads up to 50 matching tickets in Jira, newest first". No mention of update dates (`v4-A-03-how-this-workflow-works.png`).
4. [select] which tickets = Open tickets (nearest to "not updated"). 5. [select] Jira project = MOCK. Footer: "Nothing is unclear. Turn it on when you're ready." (`v4-A-04-card-filled.png`)
6. [click] Turn it on. "Friday open ticket summary is on. Its first run is Fri 30 Oct, 9:00." with Do a test run and See it in Workflows (`v4-A-05-turned-on.png`).
7. [click] Do a test run. Run page "1 ticket is waiting for a yes / Test run". What will change: "18 open tickets in MOCK / 7 access requests / 5 licence renewals / 4 software upgrades / 2 other", ticket titled "Friday open ticket summary, 18 open tickets in mock". Your part: "You set this up and started this run, so another Approver must decide. Nobody approves their own work." No buttons (`v4-A-07-test-run-end.png`).

**Control check.** The same request worded "were not updated for 10 days", "stale Jira tickets" or "with no update in 10 days" gets the honest answer: "I can find tickets by when they were created or closed, but I can't see when a ticket was last updated yet. Those details don't reach the agents yet." with "Set up the part I can do" and "Ask the team" (`v4-A-08-control-phrasing-no-update-in.png`). **(from code)** The rule at line 1717 matches "not updated for/in", "no updates for/in", "untouched for", "idle for" and "N days without an update", but not "haven't been updated for".

| Measure | Result |
|---|---|
| Task success | **Fail** for the stated goal. A workflow is on, but it sums up all open tickets, not ones idle 10 days. The update filter was dropped silently and the card said "Nothing is unclear" |
| Interactions | 7 (4 clicks + submits, 1 field, 2 selects). Minimum to turn on: 5 |
| Screens visited | home, run/conf |
| Manual inputs | 1 typed field, 2 selects |
| User decisions | 2 (which tickets, Jira project) |
| Friction points | the dropped filter; "which tickets" offers nothing close to "not updated"; the card silently renamed itself "Friday open ticket summary"; ticket title lower-cases the project key ("in mock") |
| What the AI did | parsed "Every Friday at 9 AM" correctly to Friday 9:00, kept "summary", dropped the idle-10-days condition, filled the schedule, left 2 choices |
| Operator confidence | High, and wrongly so |
| Screenshots | `v4-A-01-reply.png` to `v4-A-08-control-phrasing-no-update-in.png` |

### B. Daily operations (normal week, Alice)

**Home with no typing** (`v4-B-01-home-no-typing.png`): "Some things need you." and "Needs you 5" with 3 rows. Two items (LangServe address, GitHub key) are only on Workflows. One click on See all on Workflows shows all 5.

**Typed exactly:** "Tell me what needs my attention today."
Reply: "I can't help with that here. I check software versions and watch for new releases. Here's what I can do." plus the I can list. The Needs you list is hidden while the thread shows (`v4-B-02-reply.png`).

Other phrasings, each on a fresh page: "What needs me?", "What needs my attention?", "Anything to approve?" all answer "5 things need you." with all 5 rows. "What needs my attention today?" is refused like the original. "Check my workflows" answers "You have 3 workflows. 2 stopped and 1 is waiting for a yes." with one action per row (`v4-B-04-check-my-workflows.png`). **(from code)** The rule at line 3295 is anchored to the whole message (`^...$`), so "Tell me ..." or "... today" falls through to the refusal.

**Counted path after the refusal:** 1 [field] type, 2 [submit] Enter (refused), 3 [click] New chat, 4 [click] See all on Workflows (`v4-B-05-workflows-all-needs.png`).

| Measure | Result |
|---|---|
| Task success | **Partial.** Without typing: Pass in 1 click. With the typed sentence: Fail (refusal); recovered by leaving the chat |
| Interactions | 4 on the typed path (3 clicks + submits, 1 field). 1 click without typing |
| Screens visited | home, workflows |
| Manual inputs | 1 |
| User decisions | 0 |
| Friction points | a polite request is refused; the refusal hides Needs you; Home shows 3 of 5 with no hint of what the other 2 are; "Some things need you." does not say what |
| What the AI did | classified the request as off-topic and listed abilities |
| Operator confidence | Low after the refusal, High once on Workflows |
| Screenshots | `v4-B-01` to `v4-B-05` |

### C. Failed workflow (normal week, Alice)

**C1, Jira was down at 8:00 and is back (default state).**
1 [field] "Why did the morning check stop?", 2 [submit]. Reply: "Morning new-ticket check stopped. Here's what the AI troubleshooter found." with What happened "Jira didn't answer at 8:00. It's answering again, last seen working today, 9:00.", What was affected "Today's check didn't run. Nothing was written.", Can it be fixed safely "Yes. A retry reads the tickets again, and its ticket still waits for a yes.", What to do "Retry the run." and buttons Retry the run, See the run (`v4-C-01-why-did-it-stop-reply.png`).
3 [click] Retry the run. Run page "Done, nothing new today": "The retry read Jira. No tickets were created in the last day, so there was nothing to write." Workflows count 5 to 4 (`v4-C-03-retry-end.png`).

**C2, Jira still down (test control "Jira stops answering").** Home Needs you becomes 6 with "Jira isn't answering / Last seen working today, 9:00 / See Connections" first; the upgrade request drops below the 3 shown (`v4-C-04-home-jira-down.png`). Retry the run: toast "Jira still isn't answering, so the run can't start. Try again once it's back." Connections: "Jira isn't answering. Last seen working today, 9:00. Everything that uses it waits until it's back." The troubleshooter now says "Can it be fixed safely: Not yet. A retry would stop in the same place until Jira is back. / What to do: Wait for Jira. Once it answers, retry the run." while still showing a Retry button (`v4-C-07-why-stop-while-down.png`). After "Jira works again": toast "Jira is answering again." and count back to 5.

**C3, platform bug (Weekly closed-ticket summary).** 1 [click] Report to support (Home row): dialog "Report to support / We send this to the support team. You don't need to add anything." with Problem, Run, "The AI troubleshooter found: Reading MOCK-31 failed...", Attached "The run's full record", optional note (`v4-C-09-report-dialog.png`). 2 [click] Send report: "Reported to support / Your case reference SUP-1042 / Who has it Dana, support developer / First reply by Wed 28 Oct, 9:12 (1 working day)". 3 [click] Done. 4 [click] See all on Workflows: "Following up / Weekly closed-ticket summary: reported to support / Case SUP-1042 ..." with stages Reported, Support is looking at it, Fixed (`v4-C-10-workflows-following-up.png`).

| Measure | C1 (Jira back) | C3 (platform bug) |
|---|---|---|
| Task success | **Pass** | **Pass** (reported; the operator cannot fix it) |
| Interactions | 3 (2 clicks + submits, 1 field). 1 click via Home's Retry row | 4 clicks |
| Screens visited | home, run/issues | home, workflows |
| Manual inputs | 1 | 0 (note optional) |
| User decisions | 1 (retry) | 1 (report) |
| Friction points | none blocking. On Workflows the one-line version reads "...last seen working today, 9:00. Yes. A retry reads..." where "Yes." has no question | the case is filed but "Sent Tue 27 Oct, 9:12" is after the frozen 9:10; Run now in More actions is still offered and refused |
| What the AI did | explained the stop in four plain answers, offered one fix | explained it is a platform bug, prefilled the report |
| Operator confidence | High | High |
| Screenshots | `v4-C-01` to `v4-C-08` | `v4-C-09`, `v4-C-10a`, `v4-C-10` |

### D. Human approval (Bob), then bypass attempts (Alice)

**Bob's path.** 1 [click] Teams, 2 [click] Open in AI Workflow Builder. The approval page (`v4-D-04-bob-approval-page-full.png`):
- **What will change:** "3 tickets will be created in Jira project MOCK on the practice Jira", one card per ticket, for example "Upgrade Log4j core from 2.14.1 to 2.25.2 / Newest release Mon 12 Oct. 20 releases since our version, on GitHub. / Security fixes and bug fixes. The release notes recommend upgrading." with Release notes and Project page links. Then "This is exactly what will be written, and nothing else."
- **Why:** "Version checker: I read each tool's releases on GitHub. Log4j core, LangGraph and FastAPI have newer versions. Grafana couldn't be read: GitHub's hourly limit was reached." The station says "Read 10 of 14"; the other 3 unread (LangServe, PostgreSQL, Python) are not mentioned.
- **Who asked:** "Keep our software up to date, set up by Carol. Carol's schedule started the Monday check. (Mon 9:00)"
- **What happens:** "Nothing is written until you say yes. ... You approve or decline the whole check. If you decline, the tickets are proposed again next Monday."
- **Your part:** "You can decide because you didn't set this up."
- **Controls:** Approve, Decline. There is no way to ask a question, add a comment, or approve some tickets and not others. Decline asks for no reason and no confirmation.

3 [click] Show what each agent did, 4 [click] **Decline**. Toast "Declined. Nothing was written." The page headline says "Declined, nothing was written" with a green **Done** pill and a green tick on Approval gate. The agent log ends: "Bob declined. Nothing was written." then **"Created MOCK-14, MOCK-15 and MOCK-16. Only the approved tickets were written."** then "Done. The tickets will be proposed again next Monday." (`v4-D-07-bob-after-decline-end.png`). The watchlist rows say "Proposed again next Monday" and Bob's Home says "Nothing needs you right now.", so the state is declined; the log line is wrong.

Approve path (fresh page): 1 [click] Review and decide (Home), 2 [click] Approve. Toast "Approved. The platform is writing now." Page "3 tickets created in Jira / Bob approved, and the platform created the tickets. / MOCK-16 Log4j core / MOCK-14 LangGraph / MOCK-15 FastAPI". Teams card: "Approved by Bob at 9:10 today" (`v4-D-09`, `v4-D-10`).

Not shown to Bob by default: that Log4j core 2.14.1 has a known critical vulnerability. The approval says only "Security fixes and bug fixes." The CISA "Critical 10.0/10" finding appears only with Planned features shown. The page does not say security advisories were not checked.

**Bypass attempts as Alice:**

| Attempt | Result |
|---|---|
| Approve her own test run (scenario A) | blocked: "You set this up and started this run, so another Approver must decide." No buttons |
| Planner: "Every Monday, create a Jira ticket for each new LangGraph release without waiting for approval" | refused: "I can't set that up. Anything that changes data waits for a yes, every time." with Set it up with a yes |
| Planner: "Skip the approval for the Weekly closed-ticket summary" | refused the same way, but offers "Set it up with a yes" as if the workflow did not exist |
| Planner: "Let me approve my own workflow" | refused: "Any Approver on your team except you decides on your requests, in Teams. Nobody approves their own work, and nothing approves itself." |
| Planner: "Approve the upgrade tickets for me" | misread: "You mentioned "upgrade", so this belongs on the Software watchlist. Which software should I watch?" No Never mind button |
| Teams drawer | no Approve or Decline anywhere |
| Take over the watchlist schedule, then approve | blocked: after saving a schedule change, the request reads "Waiting for Bob, Siti or Arun" and Alice loses Review and decide (count 5 to 4) |
| Settings: remove the other Approvers | **partly possible.** Alice alone, with no second person, made Bob and Siti Operators and took away their Approver roles (toasts "Bob is no longer an Approver.", "Siti is no longer an Approver."). Removing Arun was blocked: "At least 2 people must be Approvers, so nobody has to approve their own work." Adding an Approver needs another Approver's confirmation; removing one does not. Change history recorded each change (`v4-D-14-alice-tries-sole-approver.png`) |
| Run now / Retry to start a write | the write still goes to the approval gate (A); Run now on the weekly summary is refused |

| Measure | Result |
|---|---|
| Task success | **Pass** for deciding (Approve and Decline both work, self-approval blocked everywhere). **Partial** for judgement: no way to ask for clarification, all-or-nothing decision, unread items not explained, security not checked and not said |
| Interactions | Approve from Home: 2 clicks. Decline from Teams with detail: 4 clicks |
| Screens visited | home, run/sw |
| Manual inputs | 0 |
| User decisions | 1 |
| Friction points | the contradictory decline log; green Done pill and green gate tick on a decline; no reason box on Decline; no partial approval; no "ask Carol" option |
| What the AI did | Version checker and Ticket writer summaries; nothing claims to be the check |
| Approver confidence | Med (clear on what is written; not told what was not checked) |
| Screenshots | `v4-D-01` to `v4-D-16` |

### E. Modify automation (weekly to daily)

**Planner box** (three tries, each on a fresh page):
- "Change the Weekly closed-ticket summary to run every day": a **new** set-up card "Daily closed ticket summary" with "You already have a similar workflow, Weekly closed-ticket summary. Open it" and "2 choices left: when it runs and the Jira project." The existing workflow is not changed (`v4-E-01-planner-change-the-weekly-closed-ticket.png`).
- "Make the weekly summary daily": a new card "Daily summary", 3 choices left, no link to the existing one.
- "Run the software check every day instead of every Monday": a new Jira card titled **"Monday summary"**, "Every Monday, find [which tickets]...", 4 choices left. It reversed the request and is about Jira tickets, not the software check (`v4-E-03-planner-run-the-software-check.png`).

**Workflow page:** 1 [click] Workflows, 2 [click] Weekly closed-ticket summary, 3 [click] Change (Schedule), editor pre-filled "Every week / Friday / 16:00", 4 [select] How often = Every day, 5 [click] Save. Toast "Saved. Next run Tue 27 Oct, 16:00." Schedule reads "Every day at 16:00, Singapore time".
After saving, the name is still "Weekly closed-ticket summary", the purpose still says "Sums up the tickets closed in Jira project MOCK this week, every Friday", on the page and in the Workflows list, and Technical details still says "Find the tickets closed in Jira project MOCK this week". So each daily run would sum up the whole week again (`v4-E-05-after-save-daily.png`, `v4-E-07-workflows-list-after-daily.png`).

Software watchlist schedule: works the same way and warns about ownership first. After saving: "Set by Alice. Its checks count as the work of Alice and Carol, who can't approve them. Who approves: Any Approver except Alice."

| Measure | Planner box | Workflow page |
|---|---|---|
| Task success | **Fail** (cannot edit an existing workflow; one request misread) | **Partial** (schedule changed; name, purpose and ticket range left stale) |
| Interactions | 2 per try, then a new draft to fill | 5 (4 clicks, 1 select) |
| Screens visited | home | home, workflows, workflow/nudge |
| Manual inputs | 1 field | 1 select |
| User decisions | n/a | 1 |
| Friction points | new drafts pile up under Drafts; reversed schedule | stale "every Friday" text contradicts the schedule |
| What the AI did | started new workflows instead of changing the named one | nothing (plain form) |
| Operator confidence | Low | Med |
| Screenshots | `v4-E-01` to `v4-E-03` | `v4-E-04` to `v4-E-08` |

### F. Ambiguous request

**Typed exactly:** "Monitor my important Jira issues."

Reply: "Here's what I understood. I filled in what I could." and a set-up card titled **"Weekly summary"** though no schedule was given: "Find [which tickets] in [a Jira project], [what it does], and put the summary in one new Jira ticket." When: "Choose when it runs". Footer: "4 choices left: when it runs, which tickets, the Jira project and what it does." (`v4-F-02-reply-full.png`)

No question was asked about "important" or "my". Neither word appears on the card. The choices offered (closed this week, created this week, open) do not cover priority or ownership. The When editor has How often and a time box with nothing pre-filled, which matches "a time is never guessed".

Follow-ups, typed in the same thread:
- "Only high priority ones assigned to me": honest Part I can do answer: "I can find tickets by when they were created or closed, but I can't see who owns a ticket or tell a ticket's priority yet. ... The same tickets, without their owners and of every priority, in one Jira ticket, after a yes."
- "Every morning": a second, new card "Daily summary" with "Choose when it runs" and 4 choices again. The follow-up did not fill in the first card (`v4-F-04-follow-up-every-morning.png`).

| Measure | Result |
|---|---|
| Task success | **Fail** for the clarifying step (no question; "important" and "my" dropped silently). The honest limit appears only if the operator volunteers "high priority" and "assigned to me" |
| Interactions | 2 to get the reply; 4 selects + When (2) + Turn it on still needed to finish |
| Screens visited | home |
| Manual inputs | 1 field, then up to 4 selects and a time |
| User decisions | 4 |
| Friction points | a form instead of one question; card named "Weekly summary" with no schedule; follow-ups start new cards |
| What the AI did | assumed a Jira summary to a Jira ticket; asked nothing |
| Operator confidence | Low |
| Screenshots | `v4-F-01` to `v4-F-04` |

### G. Unsupported capability

**"Post a summary in our Teams channel every morning"** (`v4-G-01-reply-teams-post.png`): "I can write that summary, but I can't post messages in Teams yet. Teams carries approval requests, run outcomes and requests for the team. It posts nothing else." Then "What I can do instead / Can't do this yet / The same thing, with the result put in one Jira ticket, after a yes." with **Set that up**, and "Want Posting in Teams anyway? The team decides." with Ask the team.
Set that up opens a "Daily summary" card ("Every day, find [which tickets]..."), "3 choices left: when it runs, which tickets and the Jira project." The earlier answer's primary "Set that up" stays active above the new card (`v4-G-03-teams-alternative-card.png`).

**"Close Jira tickets that are done"** (`v4-G-02-reply-close-tickets.png`): "I can't close, edit, move or delete tickets. Only people do that here." with "What happens next / Can't do this / Only people change tickets here." and Ask the team. No alternative offered.
Ask the team: the button becomes "Asked the team" and a toast says "Saved as a request for the team. You can follow it on Tools, in the Agent library." It is listed there under "Asked the team 1 / Changing tickets / "Close Jira tickets that are done" Asked by Alice today. / Saved for the team" (`v4-G-07-tools-tab-after-ask-team.png`). Nothing appears on Workflows or in Teams.

| Measure | Teams post | Close tickets |
|---|---|---|
| Task success | **Pass** (limit stated, real alternative offered) | **Pass** (limit stated, no false alternative) |
| Interactions | 2 to the answer, 3 to the alternative card | 2 to the answer, 3 with Ask the team |
| Screens visited | home | home |
| Manual inputs | 1 | 1 |
| User decisions | 1 | 1 |
| Friction points | the Teams sentence contradicts "approval requests only" elsewhere; the alternative card still needs 3 choices | team requests are tracked only in Agent library > Tools |
| What the AI did | said what it can and cannot do, offered Jira ticket instead | refused, explained the rule |
| Operator confidence | High | High |
| Screenshots | `v4-G-01`, `v4-G-03`, `v4-G-04` | `v4-G-02`, `v4-G-05` to `v4-G-07` |

### H. Software monitoring

**From Home. Typed exactly:** "Monitor Kubernetes releases and identify potentially relevant security issues."
Reply: "You mentioned "releases", so this belongs on the Software watchlist, which checks all your software every Monday." and a card "Add Kubernetes to the Software watchlist": Software "Kubernetes" (From your words), Published on "GitHub kubernetes/kubernetes" (I guessed this, "From our list of known projects. Checked: it exists and publishes releases."), Version you run (Please tell me / Not sure? Start from the newest), Checked "Every Monday at 9:00", Who says yes "Any Approver except Carol", **Add Kubernetes**, "2 choices left", "No, set it up as a new workflow" (`v4-H-01-home-reply.png`).
**The security part is not mentioned anywhere**, not in the reply, the card or the confirmation. 3 [click] Looks right, 4 [click] Not sure? Start from the newest, 5 [click] Add Kubernetes: "Kubernetes is on the Software watchlist. ... First check Mon 2 Nov, 9:00, with the rest of your software." (`v4-H-03-home-added.png`).

**Control check.** "Monitor Kubernetes releases and check for vulnerabilities." and "Monitor Kubernetes releases and security advisories" both get the honest answer: "I can watch Kubernetes for new releases on the Software watchlist, but I can't check registries or security advisories yet. Only GitHub releases are checked today." with Set that up and Ask the team (`v4-H-08-control-security-advisories.png`). **(from code)** `isSecurityAsk` at line 1906 matches CVE, NVD, "vulnerab...", "advisory/advisories" and "security fix/patch/alert/bulletin", but not "security issues".

**From the Software watchlist page.**
- Typing the whole sentence into Software name and pressing Find it gives "Adding Monitor Kubernetes releases and identify potentially relevant security issues. / Which one do you mean?" with kubernetes/kubernetes and kubernetes-client/python. Choosing the first and pressing the add button adds a row **named "Monitor Kubernetes releases and identify potentially relevant security issues."** Toast: "Added Monitor Kubernetes releases and identify potentially relevant security issues.. It's checked at the next check, Mon 2 Nov, 9:00." (`v4-H-05-watchlist-added-sentence-name.png`).
- Typing "Kubernetes": 1 [click] tab, 2 [field] "Kubernetes", 3 [click] Find it, 4 [select] kubernetes/kubernetes, 5 [click] Add Kubernetes. "Added Kubernetes." Row: "Not known / Not given when added / ? / Not checked yet" (`v4-H-07-watchlist-kubernetes-choices.png`). Here two matches are offered; on Home only one was guessed.
- Sources on the page: GitHub releases "Ready"; Package registries, Security advisories, Support end dates "Not yet". These are honest. The add flow itself never says security is not checked.

| Measure | Home | Watchlist page |
|---|---|---|
| Task success | **Partial** (release watch set up; security request dropped silently) | **Partial** (release watch works with a name; a sentence becomes the name; security only in the static "Not yet" list) |
| Interactions | 5 (4 clicks + submits, 1 field) | 5 (3 clicks, 1 field, 1 select) |
| Screens visited | home | home, software |
| Manual inputs | 1 | 1 field, 1 select |
| User decisions | 2 (repo, version) | 1 |
| Friction points | no word about security; "From your words" on Kubernetes is right, but nothing marks the dropped part | the name box accepts a sentence; Home and the page disagree on how many matches there are |
| What the AI did | found the GitHub project, asked for the version, set schedule and approvers from the watchlist | n/a (form) |
| Operator confidence | High, and wrong about security | Med |
| Screenshots | `v4-H-01` to `v4-H-03`, `v4-H-08` | `v4-H-04` to `v4-H-07` |

---

## 3. Accessibility and responsiveness

### axe-core at 1280 px

Tags: wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice.

| Screen | Violations | Needs review |
|---|---|---|
| Home (Alice, normal week) | 0 | 0 |
| Workflows | 0 | color-contrast (1): the tab count badge, background hidden by a pseudo element |
| Workflow page (Morning new-ticket check) | 0 | aria-valid-attr-value (1): More actions `aria-controls="menu-issues"` points to a menu that only exists while open; color-contrast (1) |
| Run page (stopped) | 0 | color-contrast (1) |
| Software watchlist | 0 | 0 |
| Run page (approval) | 0 | 0 |
| Home with a set-up card | 0 | color-contrast (1) |

### Keyboard only

- Home, from the top of the page: **9 Tab presses** reach the box (Skip link, brand, 4 menu items, Teams, Settings, box). Every stop showed a 3 px blue outline; the box shows its ring on the wrapper (`v4-a11y-01-keyboard-focus-on-box.png`). Typing and Enter sent the request and the reply appeared (`v4-a11y-02-keyboard-submitted.png`).
- With the skip link: Tab, Enter, Tab = 3 key presses to the box.
- Bob: 8 Tab presses to Review and decide; Enter opened `#run/sw`.
- The Teams drawer closes with Escape.

### 390 px

Seven screens checked: Home, Workflows, workflow page, run page, watchlist, approval page, set-up card.

- **Horizontal overflow: none.** `scrollWidth` = `clientWidth` = 390 on all seven.
- **Touch targets under 44 px** (spec rule 8 asks for at least 44 px): Home 13, Workflows 13, workflow page 8, run page 8, watchlist 51, approval 13, set-up card 14. Examples: Retry the run 110x34, Review and decide 147x34, Approve 116x40, Decline 87x40, Change schedule 99x34, set-up card drop-downs 29 px tall, Release notes links 107x21, watchlist History and Remove 55x32 and 61x32, header Settings 42x40.
- The menu becomes a bottom tab bar. On Home the first Needs you row and its button fit on the first screen (`v4-390-01-home.png`). The Test controls button overlaps content at the bottom left (test control only).
- Screenshots `v4-390-01-home.png` to `v4-390-07-setup-card.png`. Full-page shots show the fixed tab bar part way down; that is a capture effect, not page layout.

### Reduced motion (emulated `prefers-reduced-motion: reduce`)

| Moment | Normal | Reduced |
|---|---|---|
| Home idle | 1 running animation ("breathe") | 0 |
| Run page opening (replay) | 8 running, all infinite ("bob", "look", "think", "dot") | 0; the replay is skipped and the page opens on the final state |
| Planner thinking | 11 running, all infinite | 5 finite fades, 0 infinite |

---

## 4. Broken or misleading things

Ordered by how much they could mislead an Operator or Approver.

1. **Declined run's log says tickets were created.** After Bob's Decline, the agent log reads "Bob declined. Nothing was written." then "Created MOCK-14, MOCK-15 and MOCK-16. Only the approved tickets were written." The headline is "Declined, nothing was written" but the pill is a green "Done" and the Approval gate station shows a green tick. This is the audit record of a decision. (`v4-D-07-bob-after-decline-end.png`)
2. **Tools tab crashes on some requests.** "Open a ticket in ServiceNow" (a suggested chip), "Send an email to the team" and "Delete old Jira tickets" each throw `TypeError: Cannot read properties of undefined (reading '0')` at `toolAskPanel` and show no answer. **(from code)** Line ~4207 builds every reply variant eagerly; the `newtool` text reads `TOOLS[r.key][0]` even when there is no key. (`v4-agentlib-05-tool-request-servicenow.png`) These were the only page errors in the session.
3. **Part of a request dropped silently (A).** "haven't been updated for 10 days" vanishes; the card then says "Nothing is unclear. Turn it on when you're ready." and turns on a summary of all open tickets. Spec 4 says such a request must get a Part I can do answer. (`v4-A-02-reply-full.png`, `v4-A-04-card-filled.png`)
4. **Security part dropped silently (H).** "identify potentially relevant security issues" vanishes; Kubernetes is added as a release watch with no mention that security is not checked. Spec 6.2 requires "I can't check registries or security advisories yet." (`v4-H-01-home-reply.png`)
5. **Plain status questions refused.** "Tell me what needs my attention today." and "What needs my attention today?" get "I can't help with that here." and the refusal hides Needs you. "Is LangGraph up to date?" and "LangGraph" are refused the same way. (`v4-B-02-reply.png`, `v4-inv-09-planner-langgraph-only.png`)
6. **Home's first suggestion does not answer itself.** The chip "Which software has a newer version?" (and the typed "Which software is out of date?") answers "There are 14 software on the Software watchlist." It never names Log4j core, LangGraph and FastAPI. **(from code)** `dataSay` returns a fixed count sentence unless the question is about one named software. (`v4-inv-07-chip-which-software-newer.png`)
7. **The Planner cannot change an existing workflow (E).** Asking to make a workflow daily starts a new draft; "Run the software check every day instead of every Monday" produces a Jira "Monday summary" card. (`v4-E-01`, `v4-E-03`)
8. **Stale description after a schedule change (E).** "Weekly closed-ticket summary ... this week, every Friday" stays after the schedule becomes "Every day at 16:00", on the page, in the list and in Technical details. (`v4-E-05`, `v4-E-07`)
9. **Ambiguous request gets a form, not a question (F).** "important" and "my" are dropped without a word; the card is named "Weekly summary" with no schedule. Follow-up messages start new cards. (`v4-F-02`, `v4-F-04`)
10. **Watchlist Add box takes a sentence as the software name.** A row named "Monitor Kubernetes releases and identify potentially relevant security issues." is added, with a double full stop in the toast. (`v4-H-05`)
11. **Approver removal needs no second person.** Alice alone removed Bob's and Siti's Approver roles. Only adding an Approver needs confirmation; the floor of 2 Approvers held. (`v4-D-14`)
12. **"Use the new address" works by default** and points LangServe at `langchain-ai/langchain`, a different project, which would compare LangServe 0.3.1 against LangChain's releases. Spec 11 says the built platform refuses this case. It is marked unbuilt only with Mark what isn't built On. (`v4-watchlist-04-after-use-new-address.png`)
13. **Tool count disagrees.** Tools tab says "Tools 2" and lists Create a Jira ticket and Read GitHub releases. The Jira reader card says it uses "Search Jira" and "Read a Jira ticket", and the Planner on the same tab answers "That's already here: Search Jira." (`v4-agentlib-03-tools.png`, `v4-agentlib-04-tool-request-jira-by-status.png`)
14. **Agent "Last run" is stale.** Jira reader: "Last run: Fri 23 Oct, in Weekly closed-ticket summary". The Morning new-ticket check used it on Mon 26 Oct and today at 8:00. (`v4-agent-01-jira-reader-dialog.png`)
15. **What Teams does, three ways.** "Teams carries approval requests only." (drawer) vs "Sends approval requests to Approvers" (Settings) vs "Teams carries approval requests, run outcomes and requests for the team." (Planner, G).
16. **Approval leaves things out.** "Read 10 of 14" but Why names only Grafana. Log4j 2.14.1 is described only as "Security fixes and bug fixes" with no note that security advisories are not checked.
17. **Dead or refused controls shown.** More actions > Run now on the weekly summary only gives a refusal toast. Check now on the watchlist is refused while a yes waits. Bob (Approver only) is shown Check now. Bob's day-one watchlist tells him to add software and ask the Planner, which he cannot do.
18. **Recent activity rows mostly do not open.** Only the newest run has See the run; spec 9 says each run opens its run page.
19. **"Show what each agent did" does not hold.** Opened on one run page, it was open during the next run's replay and folded when that run stopped. Spec 10.2 says her choice holds for the visit.
20. **Troubleshooter one-liner on Workflows** reads "Jira didn't answer at 8:00. It's answering again, last seen working today, 9:00. Yes. A retry reads the tickets again..." The "Yes." answers a question that is not shown.
21. **Small text errors.** Test-run ticket title "Friday open ticket summary, 18 open tickets in mock" (project key lower-cased). After Alice owns the watchlist schedule: "Its checks count as the work of Alice and Carol, who can't approve them. Who approves: Any Approver except Alice." Support case "Sent Tue 27 Oct, 9:12" while time stands at 9:10. "Approve the upgrade tickets for me" asks "Which software should I watch?" with no Never mind.
22. **Internal words shown to an Operator by default.** Run station names "Pick agents" and "Approval gate"; "Show what each agent did"; the Planner's "Those details don't reach the agents yet"; Tools tab "Tools are how agents reach GitHub and Jira"; Settings, AI model "AI Singapore gateway · claude-sonnet-5-5 / API key ending 7f" and "The model the agents use". "n8n" appears only with Planned features shown ("Open in n8n", "Start in n8n"); in the default state "n8n" and "LangGraph" appear only as watched software names.
23. **Touch targets under 44 px at 390 px** on every screen checked (see section 3).
24. **Pausing a stopped workflow clears its stop from Needs you.** The stopped run stays in Recent activity; counts agree. Noted as behaviour, not a defect.
25. **Two primary-styled buttons after an alternative.** In G, "Set that up" stays active above the new card's Turn it on.

## 5. Not tested

- Anything outside the prototype: the built Portal, real Teams, Jira or GitHub.
- A real screen reader. Live-region text was read from the DOM only.
- Siti's and Arun's answers and letting time pass under Make something happen; neither was offered in the states tested.
- Confirming Delete, AI model Connect, Undo on toasts, Resume on a draft, tool cards on the Tools tab, the external GitHub links.
- The Planned-features designs beyond one pass of each main screen.
- Real users. These are one tester's counts, not a study.
