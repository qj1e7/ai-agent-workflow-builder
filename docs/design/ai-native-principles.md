# AI-native design principles

Every new or changed screen, component or flow in the AI Workflow Builder follows these principles. They hold for the Portal and for the prototype. They come from the AI-native redesign (`docs/design/ai-native-redesign/AI-NATIVE-UX-REDESIGN.md`, sections 1, 2 and 15) and from the reviews of it.

**The aim.** People say what they want to get done, not how to operate the system. The AI handles the workflow's complexity. The screen shows only what the person must understand, decide or approve, and never claims more than the platform can do.

## How to use this

1. **Design a new screen or component in the prototype first.** The prototype is `docs/design/ai-native-redesign/prototype.html`, version 4, the build target since 7 Nov 2026. A change to an existing screen can go straight to the Portal.
2. **Before you build, walk the checklist below.** Write down any principle you break on purpose, and why, in the design note or an ADR.
3. **In the pull request,** say under Verification which principles applied and how each was checked. The PR template has the box.

## The principles

AGENTS.md lists these twelve in one line each, so every AI tool sees them. Change both together.

### 1. Start from intent

People say what they want in one place, Home's Planner box, and never have to choose a page first. A request is classified and routed by the platform. Suggestions come from what is going on now, not a fixed list.

- **Check:** can a first-time person start the task from Home without knowing the menu?
- **Example:** "Monitor Kubernetes releases" on Home ends with Kubernetes on the Software watchlist.

### 2. Decisions first, details on request

Each screen leads with what the person must understand or decide. The plan, the agents, the tools and the logs sit one click away, in sections named for what they hold.

- **Check:** cover everything below the first decision. Can the person still do the task?
- **Example:** the approval panel opens on "What will change", then why, who asked, what happens and your part.

### 3. One primary action per state

Each state of a screen has one main button. Other actions are quieter or sit in a menu. A destructive action sits last, after a divider, and always asks to confirm.

- **Check:** count the primary buttons in each state. The answer is 1, or 0 when there is nothing to do.

### 4. Infer, but show it

The AI fills in what it can and shows every guess:
- A guess is a grey chip, "Filled in by me", that the person can change.
- A guess that changes what is written, such as where a result goes, is always visible, and becomes a choice when there is more than one place.
- A time is never guessed.
- A part is marked as the person's own only when the words were theirs.
- No part of a request is ever dropped silently.

- **Check:** read the card's sentence against the request, word by word. Is every part there, each with its source?

### 5. Never claim more than the platform can do

One capability registry decides what every screen says the platform can do. A capability is in exactly one state: Ready, Needs setup, Not answering, Planned or Unsupported.

- Something not built is never shown as working.
- Planned features are hidden by default, and tagged Planned when shown.
- A "can't" answer names every missing part, and offers only an alternative that really sets up.
- No message claims a delivery, a completeness or a result the system can't back. Say "Saved as a request for the team", not "Sent". Say "Reads up to 50 matching tickets", not "all tickets".
- No invented causes. Say "Jira didn't answer", not "Jira is down for maintenance".

- **Check:** for each claim on the screen, name the code or registry entry that makes it true.

### 6. People approve every write, on the record

These are the product's safety rules, and no design may weaken them (AGENTS.md):
- No write runs without an Approver's yes. The safety checker denies by default.
- Nobody approves their own work. The access review needs two Approvers, one after the other.
- Teams only carries the request. Its one button opens the approval page, and nobody decides inside Teams.
- The approval page shows exactly what will be written, taken from the server.
- **The AI's summary is help for the reader, never the check.** A person approves only what they can judge.

- **Check:** for every path that ends in a write, who says yes, and where?

### 7. Honest states, one source per fact

The same words mean the same state everywhere: AI suggestion, Draft, Waiting for a yes, On, Running, Done, Stopped and Test run (spec section 15). A count or status comes from one function, so Home, Workflows, the tab badge and the Planner never disagree.

- **Check:** change the state once. Does every place that shows it change together?

### 8. Show what the AI is doing

Agents appear with their faces and plain step names, not their internals.
- While a run is going, the live activity view shows the agents at work.
- When a run stops, the AI troubleshooter gives three answers: what happened, what was affected, and whether a retry is safe. The next step, such as Retry or Report to support, sits under them.
- Waiting for a yes, the decision comes first.

- **Check:** at every point in a run, can the person say what the AI is doing now and why?

### 9. The person stays in control

People can review, correct, pause, retry, discard and delete. Anything that doesn't need the AI model keeps working without one, and a button that can't work right now is replaced by the reason, never shown dead.

- **Check:** turn the AI model off, then Jira. What still works, and does every disabled thing say why?

### 10. Not chat-only

The box is for intent. Chips, menus and buttons are used wherever they are faster than typing, for example a project picker on the set-up card. Correcting the AI never means starting again.

- **Check:** can each correction be made in place, in one or two taps?

### 11. Calm, plain and accessible

- **Calm.** Home keeps its calm centred look: the Planner on top, a large heading, the box and a few suggestions. It shows Needs you only when something needs the person.
- **Plain words.** Short sentences, no jargon, no long dashes, and the names in `GLOSSARY.md`.
- **Keyboard.** Every action is reachable by keyboard, with a visible focus ring.
- **Never colour alone.** Status always has words or an icon too.
- **Announcements.** The Planner's replies are announced politely.
- **Phones.** Nothing scrolls sideways at 390 px, and touch targets are at least 44 px.
- **Motion.** Reduced motion stops every loop.

- **Check:** the automated accessibility checks pass with no serious issue, and a keyboard-only pass of the main task works.

### 12. Evidence, not looks

A design is better when people finish tasks more easily, not when the screenshots look cleaner.
- Count the steps and decisions of the main tasks before and after.
- Say plainly when a count rose and why.
- Test with real support staff when you can (`docs/design/ai-native-redesign/usability/`).
- Never present a scripted check as a user study.

## Never

Each of these breaks a principle above. None of them ships:

- a write without an Approver's yes, self-approval, or approving inside Teams;
- an unbuilt feature shown as working, or a "Sent" or "all" the system can't back;
- part of a request dropped silently;
- the AI's summary used as the check;
- a time, a project or a destination guessed silently;
- a dead button, or a state shown by colour alone;
- a chat-only flow where a button would be faster.

## What checks these automatically

| Principle | Prototype | Portal |
|---|---|---|
| 3, 5, 7, 11 | `docs/design/ai-native-redesign/checks/gates-*.cjs` and `validate-v4.cjs` | `portal/e2e/live/design-rules.spec.ts`, planned in `docs/design/ai-native-redesign/IMPLEMENTATION-PLAN.md` section 7.6 |
| 6 | the gates' approval and Teams checks | `platform-api` approval tests and the safety checker's tests |
| 11 | `checks/quality.cjs` (axe, keyboard, 390 px, reduced motion) | plan section 8 |
| 1, 2, 4, 8, 9, 10, 12 | scenario paths in `checks/paths-v4.cjs`, and a person's review against this page | the same review, plus the click-through test |

When a review finds the same kind of mistake twice, turn it into a check here instead of adding more words.
