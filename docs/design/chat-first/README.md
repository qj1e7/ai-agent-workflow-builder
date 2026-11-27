# Chat first, on the desktop

**Status:** the design target since 13 Nov 2026. The team lead chose it on that day, and the app is built from it. Since 22 Nov 2026 it is drawn in the Mission control look, light (ADR 0052).

`prototype.html` is the clickable sketch "Chat first, on the desktop", version 3. Its shared copy is https://claude.ai/artifact/76LFBEeXhPxGKYdwB6EsRg. Open the file in a browser. It needs no server.

## How to use it

- It is the source of truth for screens, flows, words and motion. Build what it shows, in its words.
- Use the controls above the app window:
  - "View as" switches between Alice, Alice with n8n access, and Bob, an Approver.
  - "Play" runs each flow: Morning check, Ask in my words, Change by talking, Something it can't do, Bob declines, Browse, Edit in n8n, Draft a workflow, Bob approves a draft, Second Approver, and Explain.
  - "Speed" set to Instant is best for screenshots.
  - "Tracing" turns the thumbs under each Planner answer on or off, as the capability registry will (ADR 0050).
  - "New words" set to Show marks every label or sentence that is new against the sketch of 13 Nov, in place, and counts them. The team lead approves or changes them there.
- The lists under the window say what each flow is meant to show. The first, "Redrawn on 22 Nov 2026", covers the new look. "What's new in version 3" covers the flows, and its second part covers the workflow drafter screens from ADR 0051, added on 16 Nov 2026.
- The sketch uses sample data only. The demo bar, Play, Speed, Tracing and New words are for the sketch, not the app.

## Matched to the app, 27 Nov 2026

The team lead asked for the sketch to match what main decided since 13 Nov. These changed:

- **No Watchlist in the rail.** The Software watchlist is a workflow (ADR 0053, item 4, and #361). It shows on Home's board, in the slim list and on Workflows like any other workflow, with its state, its next run and its last run. Its page is a workflow page, as the app's:
  - its title and state, with Run now and Pause on top (Resume while paused, and no Run now while the list is empty);
  - When with its quiet Change, Who approves and Next run;
  - its steps "with the last run": Read versions reads GitHub, Maven Central and npm;
  - "The list" with Add software, the filter chips and the rows, problems first;
  - Recent runs and Versions, and, for people with n8n access, the In n8n tab and Open in n8n.

  It has no Change button and no Delete. A software opened from the list goes back to it. The Planner's "See the watchlist" opens it beside the chat, and its card for the watchlist is titled "Software watchlist", with Open it.
- **Checked by, as the app's list says it.** While the watchlist is on, every software on it reads "checked by Software watchlist", FastAPI and React included. While it is paused, every one reads "not checked automatically". A software's page says Checked by "Software watchlist" (a link) or "Not checked automatically", with "last checked Mon 9:00". Its buttons are the app's: History, Remove from watchlist with Undo, and Ask the team for one GitHub can't find. "Watch for new releases" is gone. "Open the last check" opens the watchlist's Monday check, whose history says what OSV found.
- **Run now and More actions.** A workflow page has "More actions" last in its title row, with Run now while it is on, and Delete. Delete asks first, in the app's words, then goes to Workflows with "Deleted React release check." and Undo, which says "Put back.". Run now opens the run it starts. Its page leads with what was found, then the steps and the folded run history, and it joins Recent runs and the last run. A FastAPI run started while GitHub doesn't answer stops the same way.
- **Changing the watchlist from the chat**, as the app's edit card does. "Make the software watchlist run at 13:00" gets the change card, with "This changes when all 6 software on the watchlist are checked. Saving makes you the owner of this schedule. Its checks then count as your work, so you won't be able to approve them." Once saved: "Saved. Next run Monday, 13:00. You now own this schedule, so you can't approve its checks."
- **Practice systems** (ADR 0054, #372 and #376), in the app's words:
  - the set-up card says "Trying it on practice systems. Each case can take up to 2 minutes." while it builds, then "Tried 6 cases on practice systems: 6 passed.", each case, and "Turn on still runs the real test, which writes nothing.";
  - a drafted workflow's card shows the same result under In short, or "It will be tried on practice systems once every setting is filled." while a setting is missing;
  - a drafted workflow's page shows it while it is a Draft.
- **Drafted workflows on Home** say where they stand, as Workflows does, such as "Sent for approval at 9:05".
- **The Planner's cards in the app's words** (#353, #354, #356):
  - The release check card's Watch row reads "New releases of LangGraph", then the repository with "Found on GitHub" and Change, then "You run 0.2.60". Then reads "Create 1 Jira ticket", with no choice box.
  - Asking for a release check the person already has gets "You already have this one.": the workflow, "It already watches fastapi/fastapi, every day at 8:00.", and Set up another, which opens the card as "FastAPI release check 2", or Open it.
  - Any software, a package included, gets its own release check card. The package card is gone.
  - "Add Grafana to the watchlist" gets "Grafana is software, so it belongs on the Software watchlist, which checks the software on it for new releases.", where it is published, Version we run for a package, and Add Grafana or Never mind. Software already on the list gets "LangGraph is already on the Software watchlist." with its line and Open it.
  - "Add Kubernetes to the watchlist and check it every day" gets "Kubernetes isn't on your Software watchlist yet. The watchlist is a workflow that checks 6 software, every Monday at 9:00, and you asked for every day.", then "How should I add Kubernetes?" with "Add it, and check all 7 every day" and "Add it, keep Mondays".
  - "Can you check if React has a new release?" and "Check the latest version of LangGraph" get the version answer, not a card.
  - Add software on the watchlist's page hands "Add Grafana to the watchlist" to the Planner.
- **Jira at the rail's foot.** Teams, Jira, Settings and the person sit at the rail's foot. Jira opens the practice Jira, and shows only while no real Jira is set up, as the app has it. The sketch draws no Jira page, only its title and lead.
- **Four states** (ADR 0053, item 2, and #355). A workflow shows Needs you, On, Paused or Draft, on the board, the slim list, Workflows and its page. Needs you is only for the person who has something to do, the same rule as their Needs you list. Alice reads Needs you on a stopped run and "On · waiting for approval" while Bob decides. Bob reads Needs you while he can decide and "On · last run stopped" on a stop. A drafted workflow is a Draft, and Needs you for an Approver who may decide its set-up. The filter chips are All, Needs you, On, Paused and Draft. Run results (Stopped, Waiting for approval, Done, Declined) stay on runs, as before.
- **One Turn on** (ADR 0053, item 1, and #352). The set-up card's one button is Turn on. It runs the test, which writes nothing, and turns the workflow on if it passes, with no second button. How to start says "Press Turn on. I do a test run, which writes nothing, and turn it on if the test passes."

Already in the sketch, so unchanged: the Explain page's removal (#386), the run page that leads with the decision (#388), the set-up questions in their rows (#387), the Teams dialog, the build title and Change (#390), the approval words (#391), the Home heading "What can I help you with today?", Explain's plain sentence (#393), one Change button in the title row, with the When row's Change as a quiet text link, and the troubleshooter's white card with Retry under its answers (#396). The run page's boxed steps and folded history in #396 are the Portal's, and the light stage stays the target.

The 19 Nov and 22 Nov notes under "Since version 3" describe the package card, which this replaces.

New words, for the team lead to confirm:

- "The list", "with the last run", "Read versions", "Reads GitHub, Maven Central and npm" and "Create tickets".
- The watchlist's sentence: "Every Monday at 9:00, check each software on the list for a new release. If there is one, create an upgrade ticket in Jira project MOCK, after approval."
- On a run: "Today's run, just now", "Monday's run, 9:00", "Running now.", "Nothing new since the last check.", "Started by Alice with Run now.", "Found nothing new, so nothing was written.", "Version checker asked GitHub, Maven Central and npm for the newest version of 6 software." and "Couldn't read LangServe on GitHub: GitHub answered 404 Not Found.".
- In Recent runs: "Today, just now", "Mon, 9:00" and "Last Mon, 9:00".
- For the sketch only: "In the app, this page stays as it is today.".

Everything else added here is the app's own words: the state words, "Jira", "Practice Jira", More actions and the delete dialog, the software page, the practice systems lines, the edit card's note, and the Planner's answers.

## A run's page, decision first, 25 Nov 2026

The team lead chose this layout on 25 Nov 2026. A run's page and its side panel lead with the decision and fold the history.

- **Top line.** The workflow name and who ran it on the left, the status on the right in approval words: "Waiting for approval", "Approved by Bob", "Declined", "Stopped", "Done".
- **What was found.** One line built from the run's own facts, such as "FastAPI 0.121.0 is out (18 Nov).", never the agents' words.
- **What it wants to do.** "This run wants to create 1 Jira ticket in MOCK:", then the ticket as a small preview, its title and a one-line gist. "Show full text" opens the whole ticket exactly as it will be written.
- **Who decides.** "An Approver decides in Teams (asked 9:01)." The person who started the run reads "You can't approve your own run." An Approver gets Approve, Decline and "Ask Alice" in the same block.
- **Run history (n steps).** Folded. Plain steps with their times: "Checked GitHub: found 0.121.0", "Drafted 1 Jira ticket", "Asked an Approver in Teams", "Bob approved", "Created MOCK-22". "Show agent messages" opens the agents' own words, for support.
- **Gone from this page.** "Summary by AI" and "Not checked". The AI's words live only under "Show agent messages".
- **A stopped run** keeps "What happened", "Affected", "Safe to retry" and Retry, so the folded history is "Run history", and the page never has two "What happened" headings.
- **A request opened from the chat** has the same shape in the side panel: the same found line, preview and decision, and no "Not checked".
- **A read that failed** says so in the steps ("Couldn't read Express on npm: npm answered 404 Not Found."), named for its source (npm, Maven Central or GitHub) and its software. It never reads "no releases found".

New words, for the team lead to confirm: "Waiting for approval", "Approved by Bob", "Show full text", "Run history (3 steps)", "Show agent messages", "Hide agent messages", "An Approver decides in Teams (asked 9:01).", "You can't approve your own run." and the found and wants lines above. Switch "New words" to Show to see them in place.

## Four fixes from the 25 Nov walk-through, 26 Nov 2026

- **Approval page.** The "Why you" line is gone. The person who started the run still reads "You can't approve your own run."
- **Teams practice drawer.** A "Teams" button in the rail's foot opens a dialog. It has a Close button with its word on it, closes on a click outside it, keeps focus inside and gives it back to the Teams button. A message that needs an approval shows Approve and Decline to an Approver who may decide it, and "Open in AI Workflow Builder" to everyone else.
- **Build panel title.** "Setting it up…" while it builds, "Set up. Version 1." when it is on. No title names n8n. The "Open in n8n" buttons stay.
- **Change on a workflow's page.** A secondary "Change" button, before Pause. It opens the Home chat with that workflow's edit card, which asks the day and the time with buttons and saves only on "Save change", as a saved draft reopens as its card.

New words, for the team lead to confirm: "Setting it up…", "Set up. Version 1.", "Change", "Close", "You approved this.", "You declined this." and "I couldn't open that workflow just now. Try Change again from its page."

## Mission control, light, 22 Nov 2026

The team lead chose this look on 22 Nov 2026 (ADR 0052). These are the Portal's style rules from now on. The earlier Calm look, on the branch `docs/sketch-calm-look`, was not merged.

### Layout

- **The rail** is dark navy and 92 px wide. It holds Home and Workflows, then Teams, Jira, Settings and the person at its foot (ADR 0052, amended 27 Nov 2026). The top bar is gone. Home's count is the Needs you count, red while anything needs the person. Workflows shows a quiet total. Jira shows only while no real Jira is set up. In a window 860 px wide or narrower the rail is a bar across the top.
- **Home, before a question**, is a board. It has a centred greeting and heading, the Planner's box with the Visor bot in it, three chips, then Needs you, then the person's workflows as tiles. Needs you shows as bright tiles in Do now and Set up, each with one button. When nothing needs the person, one line says so, with the next run. Each workflow tile shows its state, its next run and its last run as a small line of steps. The last tile points back to the box.
- **Home, after a question**, is a chat. The thread fills the left column, with "‹ Home" at its top and the box docked at its foot with the chips under it. A slim list docks on the right: the Needs you count, which opens Needs you beside the chat, then each workflow's name with its state mark, and See all. The full tiles stay on Home's board. "‹ Home", or Home in the rail, goes back to the board. The chat is kept, and typing in the box carries it on.
- **Narrower windows.** When the app is under 1080 px wide, the slim list gives way to the pinned line at the top of the chat.
- **The side panel** still shows what is opened from a card in the chat, beside the chat, in the slim list's place. Close brings the list back. More details opens the full page.
- **Full pages** open from the rail, a tile, or the side panel, with a back link at the top that names where it goes.
- **Workflows** is a title with filter chips, then Needs you, then one table: state, workflow, last run as steps, when and next run.
- **A workflow page** has its title, state and actions on top, then When, Who approves and Next run, then its steps as a light diagram with today's run on it, then Recent runs and Versions side by side.
- **A run's full page** is the light stage, with a side card for Now, what will be written, and the timed log. When the app is under 1240 px wide, the side card moves under the stage. The side panel stays a summary with the small run line.
- **The Software watchlist** is a workflow with no rail tab (#361). Its workflow page has The list: Add software by name, filter chips, then one list, problems first.
- **Settings** opens on Connections: one tile per system, with what uses it and Check now. The other tabs stay as the app has them.

### Tokens

- **Type.** Atkinson Hyperlegible Next only, in six sizes: 36 for the Home heading, 26 for page titles and the gate's timer, 18 for section heads, tile names and the Planner's lead line, 16 for body text, 14 for labels and buttons, and 13 for counts, the stage's key and the labels on a small step line. Weights 400, 600 and 700, with tabular numbers.
- **Neutrals.** Text is `#0f1a2b`, secondary text `#475569` and `#5d6a7e`, page `#f1f4f8`, surfaces `#ffffff`, lines `#dbe1ea` and `#c2cad7`. The main button is ink. Focus is a 3 px ink ring, white on the rail.
- **Status has one meaning per colour, always with a word and an icon.** Green `#1e9e58` is fine (On, Done, Working, Up to date), amber `#f0a21b` means a person needs to act (its text `#7a4500`, its lines on the stage `#c27803`), red `#e2483c` is stopped (its text `#b0261c`), blue `#3e6ff6` is at work right now, and grey `#5d6a7e` is paused, draft, declined or not reached.
- **Identity is never a status.** The faces keep today's agent colours. Violet `#7b5cff` marks the AI's hand-off lines and the agents' talk on the stage. The logo uses NCS blue, darkened to `#0b78a8` so its letters keep 4.5:1.
- **The stage** is a `#fbfcfe` card with a `#dfe5ee` dot grid. A done line is `#5d6a7e`, and a not-reached line is `#7d8899` and dashed.
- **Shape.** Radius 8, 12 and 16, soft shadows instead of borders, buttons 38 and 32 px high.

### Components

- **One pill** shows every state, as an icon and a word on a tint.
- **The small step line** draws a workflow's steps as circles, coloured by the last run. A step that was not reached is dashed.
- **The Needs you tile** has a coloured edge, a mark, what waits, and one button such as "Open the run" or "Review and decide".
- **The workflow tile** is on the board only. Beside the chat a workflow is one row, a state mark and its name. The mark's shape says the state as well as its colour: a filled dot for On, a clock for a wait, a cross for a stop, and a ring for paused or draft. Its word shows on hover and is read out.
- **The flow diagram** on a workflow page draws a box per step, with a short note under a stop or a wait.
- **The light stage** has the tries, the Planner at the top, the agents' talk as bubbles, the steps with the agents' faces on them, the gate with Bob's initial and a timer while it waits, a red line to the system that failed, and the AI troubleshooter's card under a stop.
- **Faces** are today's Visor bot for the Planner and today's Orbs for the other agents. The Version checker is teal with a magnifier, the AI troubleshooter violet with a wrench. On the stage a face keeps its state: the Planner looks up with an amber clock while it waits, a done step smiles with a tick, and a stopped one frowns with a red mark.
- **Filter chips** with a dot and a count, the table, the connection tile, and one tab bar.

### Motion

- **Every movement has a purpose.** It shows a hand-off, a wait or a change, never decoration.
- **The stage plays once when it opens,** in about five seconds: a glowing dot runs along each hand-off, each step turns blue while at work and green when done, and each agent's words rise in. Replay plays it again.
- **After that, only the waiting gate moves.** Its amber ring pulses every 2.2 s, and the timer counts up. A stop is red and still. When the run moves on, only what changed moves: a dot into the next step, a flash on the step, and the new words.
- **Elsewhere, motion shows work and waits.** The thinking dots and the faces move while an agent works, dashes flow into a step at work, and a waiting step pulses. New cards rise in with a short fade. Buttons press to 0.96. The Visor bot on Home breathes twice, then holds still.
- **Reduced motion** stops every animation, and the final state shows at once.

### Checks it keeps

Text is 4.5:1 or more, every focus stop shows a ring, nothing moves with reduced motion, the chat and its box work at 200% zoom, and nothing scrolls sideways from 800 px to 1920 px wide.

### New words

Approved by the team lead, 22 Nov 2026.

Switch "New words" to Show to see each one in place. Each is listed once, under the first screen that shows it.

- **The rail and Home.** "Home" (the rail's Chat, and the back link "‹ Home"), "Your workflows", "See all on Workflows", "See all", "Describe a new task in the box above", and the next run under "Next run" when nothing needs the person, such as "FastAPI release check, tomorrow, 8:00".
- **Workflows.** "All" on the filter chips, and the column "State".
- **A workflow page.** "with today’s 8:00 run" after Steps, and the key's "Stopped here" and "Not reached".
- **A run's page.** "Replay", "Tries", "Try 1 · 8:00", "Try 2 · 9:01", "GitHub, no answer", the steps' "Started 8:00", "Retried 9:01" and "Found 0.121.0", the key's "At work", "Waits for a person" and "Not reached yet", the bubble heads such as "Planner → Version checker" and "Bob → Planner", and two bubble lines: "Check FastAPI on GitHub for a new release." and "Asked for approval of 1 Jira ticket."
- **The Software watchlist.** The page title "Software watchlist" (the glossary's name for it), "Add software", the example "Grafana", and "Find it".
- **Settings.** The page is new to the sketch, so every word on it is marked. Most come from the Portal's Connections tab: the tabs "Connections", "People and permissions", "AI model" and "How it works", "A check only reads, so it never changes anything.", "Checked today, 8:02", "Practice copy", "Working", "Not set up", "What uses it", "Check now", and the uses "Read Jira tickets", "Create a Jira ticket after approval", "Check software for new releases on GitHub" and "Ask Approvers for approval in Teams". New in this look: "3 of 4 working.", "Never checked", "What would use it", "Read the Confluence pages the team allows" and "Ask whoever set up the platform to connect Confluence.". For the sketch only: "In the app, this tab stays as it is today."

## Approval words, 25 Nov 2026

The team lead's rule: "yes" is never a noun in anything a person sees. A run "Waits for approval", a write happens "After approval", a person "Needs your approval", "Bob approved.", and the gate block for a new workflow is "Ask for approval". Workflows already in n8n keep "Ask for a yes", and the platform knows the block by its type, so both names work. Home's heading for an Operator is "What can I help you with today?".

## Since version 3

- 15 Nov 2026, ADR 0025's first part: a software can be published on GitHub, Maven Central or npm. Log4j core is now its Maven Central package, and Express is a known npm package. The Watch answer, the Source fact and the check's sentence name the source. The security can't says known vulnerabilities are looked up only for the Maven Central and npm packages on the watchlist.
- 19 Nov 2026: a release check of its own reads GitHub only, so asking to watch or check a Maven Central or npm package answers that the Software watchlist checks it, with Add to the watchlist or Open it, and builds no workflow. A package's watchlist row says it is checked by the Software watchlist.
- 22 Nov 2026: the package card asks for the version we run, optional, since known vulnerabilities are looked up only in a version someone gave; without one it says they aren't. A package's page has a Known vulnerabilities row: Open the last check, whose run says how many there are and names the worst, while an upgrade ticket lists each one; or, for a version nobody gave, that they aren't looked up. Its Checked by says the Software watchlist.
- 25 Nov 2026: the Explain page is gone, as the team lead asked. No row of Workflows, workflow page, version or side panel has Explain, an old Explain address opens the workflow's page, and a version that needs a fix says what to fix on its banner, in the safety checker's words. The draft card has no See the report: See them lists its flags. "Explain the FastAPI release check" still answers in the chat.
- 25 Nov 2026: a version no check has looked up yet, as one just added, says "Not looked up yet. The next check looks them up in this version." with no Open the last check, so the link never leads to a run without them.
- 26 Nov 2026: "Explain the FastAPI release check" answers in the chat with the sentence the workflow's page shows and Open the workflow, and no report. Code reads the request and builds the answer, with no model call. A name that matches none of the person's workflows, or several, is answered as before.

## Where the sketch is silent

The Jira page, sign-in, and the Settings tabs other than Connections keep what the app has today. The Teams drawer is drawn since 26 Nov 2026.

The workflow drafter screens don't yet show these parts of ADR 0051's first build step:

- the sender's note on each flag;
- the Teams card for a set-up approval;
- adding a write key in Settings.

The "Draft it as an n8n workflow" button is gone. The Planner now picks how to build a workflow, and the quiet "Build it with any n8n block" link on the card is drawn in `docs/design/simple-flow/prototype.html` (ADR 0053, item 5).

## Decisions for the workflow drafter screens

The team lead reviewed the drafter screens (ADR 0051) and the thumbs (ADR 0050) on 16 Nov 2026 and chose these. Build them as written.

1. **The report is a summary that opens.** In short comes first, then one row per section with a short gist, such as "3 for an Approver · 6 fixed for you · 6 passed". A row opens on a click, and Settings opens by itself while anything is still needed. Since 26 Nov 2026 no screen shows the whole report: the Explain page is gone, and the chat's Explain answer is the workflow's sentence. We also considered one page with every section open. It was easy to read once, but in a chat card it ran to several screens.
2. **A reason takes the place of a button that can't work yet, never a disabled button** (principle 9). A drafted workflow's Turn on shows "Answer 2 questions first", Approve shows "Accept 2 more flags first", the Planner's set-up card shows "Answer 1 question first", and a change card shows the same until its question is answered.
3. **Declining a set-up approval needs a reason,** picked from a short list, as ADR 0051 says. Declining a run keeps its optional reason, as before.
4. **The channel question uses Slack.** n8n's Microsoft Teams block can't run, because it posts only with a person's own sign-in (ADR 0051, section 2), and the ADR's examples use Slack.
5. **The draft card shows the workflow on the sketch's small step line,** not on an n8n canvas. "Start from the Portal" is a second trigger, so it appears only in the report's Step by step.
6. **A guess shows "I guessed" and Change,** as ADR 0051's settings table says, in place of principle 4's "Filled in by me".
7. **A key that the person asked an Operator for waits, and the next question comes up.** When only that key is left, the card says "Waiting for an Operator to add a key".
8. **A change asked for in the chat, or Done in n8n, makes a new revision card.** The older card settles into one line, so only the newest card asks anything. A new revision cancels a set-up approval that is still waiting.
9. **The optional reason under a thumbs down goes in the Langfuse score's comment,** masked as ADR 0050 masks traces. ADR 0050 itself writes only the rating. The drafter's own cards have no thumbs, because drafts have their own review queue (ADR 0051, section 10).
10. **Two new state words:** "Drafting" while the drafter works, and "In n8n" while a draft is open in the person's own n8n space. A sent draft is "Waiting for approval" on its card, and an approved one is a "Draft" on Workflows until someone turns it on. Since 23 Nov 2026 (ADR 0053), Workflows, Home and the page show four states: a drafted workflow is a Draft there, and Needs you for an Approver who may decide it.
11. **In the sketch, Dan approves first and Bob second,** because "View as" has no second Approver. If Bob approves first, the card says "You approved it. A second Approver decides next."
12. **"What I can do" lists drafting and Explain,** because the sketch shows them working. In the Portal they stay Planned until their pull requests land (ADR 0051).
13. **The set-up approval shows what the Approver decides on:** In short, the line about the steps that won't ask for approval on each run, the flags to tick, what it reads, writes and posts, who approves each write, its settings (the key for each write block among them, and every guess marked as guessed), and the safety checks, as Fixed for you and Passed. All of it is in view. Since 25 Nov 2026 there is no More details, and the steps and Approval rows of the report are not on it.
14. **The approval step line says who approves and where.** When Set up adds the approval step, the chat says "I added an approval step. Before each ticket is made, an Approver must approve it in Teams." (the team lead's choice of 25 Nov 2026), with the write's own noun for other writes, such as "each page update", or "each change".
15. **The Planner's set-up card shows every open question at once, in its own row, answered with buttons** (the team lead's design of 25 Nov 2026). Above the card the Planner says "Here's what I understood. Pick the 3 missing parts." ("Pick the missing part." for one). When asks "How often?" with Every day, Every weekday, Every week and Only when I run it, and on the same row "At what time?" with 8:00, 9:00, 13:00, 17:00 and Another time. The time is never guessed, and Only when I run it has no time. Then asks "Create 1 Jira ticket in which project?" with the platform's Jira projects as buttons (MOCK on the local stack) and Another project, which opens a small key box with the existing check, and says under it "Each ticket needs an Approver’s approval in Teams." The free-text Then box is gone from this path. The Watch row never asks the person to look up a repository: the software finder fills it only with exactly one match from its reviewed list (tick, the repository, "Found on GitHub" and Change), offers every other answer as buttons with what each is, its stars and, for a search result, "found by searching GitHub" (a search result is never picked for the person, even alone), or, when it knows none, shows only "Another repository" (the prototype's Repository finder control draws one match, several, none, looking, slow, can't reach GitHub, not checked and not an Operator, each in its own words) with "The public repository to watch, as owner/name." Picking a button ticks its row at once and moves the keyboard on. The footer reads "Pick 2 more to finish" beside Never mind, and Turn on shows when nothing is left. It runs the test and turns the workflow on if it passes (ADR 0053, item 1). Change on a filled row puts that row's buttons back.

## The n8n login line

Under every Open in n8n button the sketch says `Opens in n8n as {login}.`, with a made-up email. The Portal and n8n sign in separately, and Open in n8n moves the workflow into the n8n space of one account, so only that account can see it. The line names it. It shows nothing while the platform does not know the login. The sketch's Edit in n8n flow for a draft has no Open n8n button, and the Portal's has the same line under it.

## What it replaces

Prototype version 4 in `docs/design/ai-native-redesign/`, with its spec and build plan, is kept only as a record. So is version 3 of the earlier prototype in `docs/design/portal-routines/`.

## What still holds

- The product safety rules in `AGENTS.md`.
- The principles in `docs/design/ai-native-principles.md`.

Where following the sketch literally would break one of them, the rule wins, and the pull request says why.
