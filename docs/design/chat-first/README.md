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

## Mission control, light, 22 Nov 2026

The team lead chose this look on 22 Nov 2026 (ADR 0052). These are the Portal's style rules from now on. The earlier Calm look, on the branch `docs/sketch-calm-look`, was not merged.

### Layout

- **The rail** is dark navy and 92 px wide. It holds Home, Workflows and Watchlist, then Settings and the person at its foot. The top bar is gone. Home's count is the Needs you count, red while anything needs the person. Workflows and Watchlist show quiet totals. In a window 860 px wide or narrower the rail is a bar across the top.
- **Home, before a question**, is a board. It has a centred greeting and heading, the Planner's box with the Visor bot in it, three chips, then Needs you, then the person's workflows as tiles. Needs you shows as bright tiles in Do now and Set up, each with one button. When nothing needs the person, one line says so, with the next run. Each workflow tile shows its state, its next run and its last run as a small line of steps. The last tile points back to the box.
- **Home, after a question**, is a chat. The thread fills the left column, with "‹ Home" at its top and the box docked at its foot with the chips under it. A slim list docks on the right: the Needs you count, which opens Needs you beside the chat, then each workflow's name with its state mark, and See all. The full tiles stay on Home's board. "‹ Home", or Home in the rail, goes back to the board. The chat is kept, and typing in the box carries it on.
- **Narrower windows.** When the app is under 1080 px wide, the slim list gives way to the pinned line at the top of the chat.
- **The side panel** still shows what is opened from a card in the chat, beside the chat, in the slim list's place. Close brings the list back. More details opens the full page.
- **Full pages** open from the rail, a tile, or the side panel, with a back link at the top that names where it goes.
- **Workflows** is a title with filter chips, then Needs you, then one table: state, workflow, last run as steps, when, next run, and Explain.
- **A workflow page** has its title, state and actions on top, then When, Who says yes and Next run, then its steps as a light diagram with today's run on it, then Recent runs and Versions side by side.
- **A run's full page** is the light stage, with a side card for Now, what will be written, and the timed log. When the app is under 1240 px wide, the side card moves under the stage. The side panel stays a summary with the small run line.
- **The Software watchlist** has Add software by name, filter chips, then one list, problems first.
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
- **A run's page.** "Replay", "Tries", "Try 1 · 8:00", "Try 2 · 9:01", "GitHub, no answer", the steps' "Started 8:00", "Retried 9:01" and "Found 0.121.0", the key's "At work", "Waits for a person" and "Not reached yet", the bubble heads such as "Planner → Version checker" and "Bob → Planner", and two bubble lines: "Check FastAPI on GitHub for a new release." and "Asked for a yes to 1 Jira ticket."
- **The Software watchlist.** The page title "Software watchlist" (the glossary's name for it), "Add software", the example "Grafana", and "Find it".
- **Settings.** The page is new to the sketch, so every word on it is marked. Most come from the Portal's Connections tab: the tabs "Connections", "People and permissions", "AI model" and "How it works", "A check only reads, so it never changes anything.", "Checked today, 8:02", "Practice copy", "Working", "Not set up", "What uses it", "Check now", and the uses "Read Jira tickets", "Create a Jira ticket after a yes", "Check software for new releases on GitHub" and "Ask Approvers for a yes in Teams". New in this look: "3 of 4 working.", "Never checked", "What would use it", "Read the Confluence pages the team allows" and "Ask whoever set up the platform to connect Confluence.". For the sketch only: "In the app, this tab stays as it is today."

## Since version 3

- 15 Nov 2026, ADR 0025's first part: a software can be published on GitHub, Maven Central or npm. Log4j core is now its Maven Central package, and Express is a known npm package. The Watch answer, the Source fact and the check's sentence name the source. The security can't says known vulnerabilities are looked up only for the Maven Central and npm packages on the watchlist.
- 19 Nov 2026: a release check of its own reads GitHub only, so asking to watch or check a Maven Central or npm package answers that the Software watchlist checks it, with Add to the watchlist or Open it, and builds no workflow. A package's watchlist row says it is checked by the Software watchlist.

## Where the sketch is silent

The Teams drawer, the Jira page, sign-in, and the Settings tabs other than Connections keep what the app has today.

The workflow drafter screens don't yet show these parts of ADR 0051's first build step:

- the "Draft it as an n8n workflow" button on a can't answer;
- the sender's note on each flag;
- the Teams card for a set-up approval;
- adding a write key in Settings.

## Decisions for the workflow drafter screens

The team lead reviewed the drafter screens (ADR 0051) and the thumbs (ADR 0050) on 16 Nov 2026 and chose these. Build them as written.

1. **The report is a summary that opens.** In short comes first, then one row per section with a short gist, such as "3 for an Approver · 6 fixed for you · 6 passed". A row opens on a click, and Settings opens by itself while anything is still needed. The same layout serves the chat card, the side panel and the full page. We also considered one page with every section open. It was easy to read once, but in a chat card it ran to several screens.
2. **A reason takes the place of a button that can't work yet, never a disabled button** (principle 9). Send for approval shows "Answer 2 questions first", Approve shows "Accept 2 more flags first", the Planner's set-up card shows "Answer 1 question first", and a change card shows the same until its question is answered.
3. **Declining a set-up approval needs a reason,** picked from a short list, as ADR 0051 says. Declining a run keeps its optional reason, as before.
4. **The channel question uses Slack.** n8n's Microsoft Teams block can't run, because it posts only with a person's own sign-in (ADR 0051, section 2), and the ADR's examples use Slack.
5. **The draft card shows the workflow on the sketch's small step line,** not on an n8n canvas. "Start from the Portal" is a second trigger, so it appears only in the report's Step by step.
6. **A guess shows "I guessed" and Change,** as ADR 0051's settings table says, in place of principle 4's "Filled in by me".
7. **A key that the person asked an Operator for waits, and the next question comes up.** When only that key is left, the card says "Waiting for an Operator to add a key".
8. **A change asked for in the chat, or Done in n8n, makes a new revision card.** The older card settles into one line, so only the newest card asks anything. A new revision cancels a set-up approval that is still waiting.
9. **The optional reason under a thumbs down goes in the Langfuse score's comment,** masked as ADR 0050 masks traces. ADR 0050 itself writes only the rating. The drafter's own cards have no thumbs, because drafts have their own review queue (ADR 0051, section 10).
10. **Two new state words:** "Drafting" while the drafter works, and "In n8n" while a draft is open in the person's own n8n space. A sent draft is "Waiting for a yes", and an approved one is a "Draft" on Workflows until someone turns it on.
11. **In the sketch, Dan approves first and Bob second,** because "View as" has no second Approver. If Bob approves first, the card says "You approved it. A second Approver decides next."
12. **"What I can do" lists drafting and Explain,** because the sketch shows them working. In the Portal they stay Planned until their pull requests land (ADR 0051).
13. **The set-up approval in the side panel shows what the Approver decides on:** In short, the line about the steps that won't ask for a yes on each run, the flags to tick, and what it reads, writes and posts. More details adds the rest of the report.

## The n8n login line

Under every Open in n8n button the sketch says `Opens in n8n as {login}.`, with a made-up email. The Portal and n8n sign in separately, and Open in n8n moves the workflow into the n8n space of one account, so only that account can see it. The line names it. It shows nothing while the platform does not know the login. The sketch's Edit in n8n flow for a draft has no Open n8n button, and the Portal's has the same line under it.

## What it replaces

Prototype version 4 in `docs/design/ai-native-redesign/`, with its spec and build plan, is kept only as a record. So is version 3 of the earlier prototype in `docs/design/portal-routines/`.

## What still holds

- The product safety rules in `AGENTS.md`.
- The principles in `docs/design/ai-native-principles.md`.

Where following the sketch literally would break one of them, the rule wins, and the pull request says why.
