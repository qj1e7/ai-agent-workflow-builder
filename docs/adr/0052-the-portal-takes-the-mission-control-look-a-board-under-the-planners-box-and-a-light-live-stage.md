---
status: accepted
---

# The Portal takes the Mission control look: a board under the Planner's box, and a light live stage

On 22 Nov 2026 the team lead chose a new look for the Portal, called "Mission control, light". The chat-first sketch, `docs/design/chat-first/prototype.html`, is redrawn in it first, and the Portal follows in later pull requests. This ADR records the choice and what it changes.

It amends ADR 0043. It keeps the rail that leads to full pages, the Planner first, the side panel for things opened from the chat, and every approval in Teams. It changes how Home looks before and after a question, and how a run is drawn.

## Context

The team lead found the Portal unappealing and wordy. Three interface reviews with the better-interface skills (Home, Workflows, and the other screens) traced it to the same causes on every screen: boxes inside boxes, too many type sizes and weights, and answers that say the same thing twice.

A first answer kept today's layout and restyled it. The "Calm look" had fewer borders, five type sizes and one press effect, and three bolder variants of it followed. The team lead found these not enough. They asked for a full new look, with as little change to the backend as possible.

Three designers then drew three directions from one brief, each with the same eight screens and real content: Workspace, Conversation and Mission control. The team lead picked Mission control, then asked for its run view to be light instead of dark, and for Home to behave like a chat after a question. That second version is "Mission control, light", in the sketch's README. The team lead chose it on 22 Nov 2026.

## Decision

- **A dark rail.** A 92 px navy rail holds Home, Workflows and the Watchlist, with Settings and the signed-in person at its foot. The top bar goes. Home's count is the Needs you count, and it turns red while anything needs the person. Below 860 px the rail is a bar across the top, as ADR 0043 has it.
- **Home is a board under the Planner's box.** Before a question, Home is the greeting, the heading, the Planner's box with the Visor bot in it, three chips, then Needs you as bright tiles, then a board of the person's own workflows. Each tile shows its state, its next run and its last run as a small line of steps. When nothing needs the person, one line says so, with the next run.
- **After a question, Home becomes a chat.** The conversation fills the left column, and the box docks at its foot with the chips under it. A slim list docks on the right: the Needs you count, then each workflow's name with its state mark, so the glance stays in view. The full tiles stay on Home's board. The team lead trimmed it to this on 22 Nov 2026, to keep the chat's words down. "‹ Home" at the top of the chat, or Home in the rail, goes back to the board. The conversation is kept, and typing in the box carries it on. In a narrower window the slim list gives way to the pinned line.
- **The side panel takes the slim list's place.** Something opened from a card in the chat still opens beside the chat, as ADR 0043 decided. It shows where the slim list was, and Close brings the list back.
- **Workflows is one table.** Filter chips with counts, Needs you, then every workflow with its state, its last run as steps, when it runs and its next run.
- **A workflow page draws its steps as a light diagram,** with today's run on it: done, stopped here, waiting, or not reached. A stop or a wait has a short note under its step. Recent runs and versions sit side by side under it.
- **A run's full page is a light stage.** The agents' faces sit on the steps: today's Visor bot for the Planner and today's Orbs for the other agents. Each hand-off is a glowing dot: violet from the Planner, ink along the steps, and amber into the approval gate. The gate pulses while it waits, with a timer. A stop is red and still, with a line to the system that failed and the AI troubleshooter's card beside it. A side card shows Now, what will be written, and the timed log. The side panel stays a summary with the small run line.
- **Tokens.** Atkinson Hyperlegible Next only, in six sizes and three weights. Neutrals from `#0f1a2b` ink to a `#f1f4f8` page. One meaning per status colour, always with a word and an icon: green is fine, amber means a person needs to act, red is stopped, blue is at work on the stage, grey is paused, draft or not reached. Violet marks the AI's hand-offs and is never a status. NCS blue stays on the logo.
- **Motion has a purpose.** The stage plays once when it opens, in about five seconds, and Replay plays it again. After that only the waiting gate moves, and a change of state moves only what changed. With reduced motion nothing moves, and the final state shows at once.
- **Words.** The sketch keeps its words. Where the new look needs new ones, the sketch marks them, and "New words" in the sketch's controls shows each one in place for the team lead to approve.

Nothing here changes the approval gate or the safety checker. Every write still waits for an Approver's yes in Teams, and nobody approves their own work.

## Considered options

- **The Calm look, a restyle of today's layout.** It was the smallest change and kept every screen where it was. The team lead found it, and its three bolder variants, not enough.
- **Workspace.** A left sidebar lists every workflow with its live state, the work fills a wide canvas, and details open in an inspector on the right, with the Planner one keystroke away. It suits someone who works in the app all day. It moves the Planner off the first screen after Home, and it replaces the side panel and the full pages that ADR 0043 chose.
- **Conversation.** The whole Portal is one conversation with the Planner, and Workflows, runs and Settings open as wide sheets over it. It is the purest chat. Checking many workflows means scrolling or opening sheets, and ADR 0043 found that scanning beats asking for overview tasks.
- **Mission control with a dark stage.** The same board, with the run on a dark stage. It was the most dramatic for the demo. The team lead preferred the run on the same light ground as every other page.

## Consequences

- **ADR 0043 changes in one place.** Before a question, Home is no longer only the box and Needs you rows. It is the board: the box, Needs you, then the person's workflows. After a question it is the chat, as before, with the board docked beside it. The rail is renamed from Chat to Home, and it gains Settings and the person at its foot, because the top bar goes. The rail still leads to full pages, the Planner still comes first, and approvals still happen in Teams.
- **The sketch is redrawn first.** Every screen and Play flow of the chat-first sketch keeps its behaviour in the new look. The sketch's README records the layout, tokens, components and motion rules as the Portal's rules from now on, and lists every new word by screen. The Calm look branch was not merged.
- **The Portal follows in about 12 pull requests,** one area each: tokens and shell, the step line and the pill, the Home board, the chat with the slim list, the answer and set-up cards, Workflows, the workflow diagram and page, the light stage, the stop and the troubleshooter, the Watchlist, and Connections. Each is checked as the sketch was: axe, 4.5:1 text, visible focus, reduced motion, 200% zoom, and 800 px to 1920 px wide.
- **The glossary follows the Portal.** When the first Portal pull request lands, the Rail entry in `GLOSSARY.md` names Home instead of Chat, with Settings and the person at its foot.
- **Backend impact: none.** Every tile, diagram and stage element comes from data the Platform API already serves: the workflows and Needs you, each run's events, approval and troubleshooter answer, the watchlist and the connections. Filters on `GET /runs` by workflow would save the Portal some work later, and are not needed now.
- **Risks.** The slim list puts a second thing on Home after a question, so a narrow window drops it for the pinned line. A light stage is less dramatic than a dark one on a projector, so the glow on each hand-off and the amber gate carry the drama. The stage is drawn for one line of up to six steps. Branches or longer workflows need a rule, such as two rows or the plain step line. The faces need a rule for which agent sits on which step, and a step with no agent shows its icon.
- **It is our judgement, not tested with users.** The same check as ADR 0043 applies. Give the redrawn sketch to 2 or 3 people outside the team with three tasks: see what needs them this morning, fix a stopped run, and decline an approval with a reason.
