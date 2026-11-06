---
status: proposed
---

# Home is the Planner's chat box, and it replaces New workflow

On 6 Nov the team said that people opening the app for the first time don't know what to do, because there are too many things on screen. The in-app tour (#34) and the 27 Oct reshape both added guidance on top of the screens, and the complaint stayed. The team lead asked for one place to start. People tell the Planner what they want there. The Planner knows what the platform and the AI model can and can't do, suggests the right feature, and fills it in once they agree. For example, "keep track of the React version" becomes a filled-in row on the Software watchlist.

Part of this exists behind the screens. The Planner's read-back (`understand_task` in `agent-runtime/src/agent_runtime/planner.py`) splits a request into when, what to look for, what to do and where. It marks each part as understood, changed, missing or can't do, and it already sends version and release requests to the Software watchlist. The `ABILITIES` list in `agent-runtime/src/agent_runtime/abilities.py` overrules the model when it claims something no tool can do. Today all of this sits behind the New workflow tab and its 4 steps. The rest, listed under Consequences, is new work.

We decided:

- **Home is the Planner's box, every day.** It is a large box in the middle of the page, under the Planner's face. On day one it asks "What does your team do again and again?" and lists what the Planner can do and what it can't do yet. After that it asks "What else should run by itself?", and the list folds into a "What can I ask for?" link. Three example requests sit under the box, and each one is something the platform can do today. Home shows nothing else. A person who is both an Operator and an Approver sees this Home too, and what waits for their yes is on Workflows, counted on its tab.
- **The New workflow tab goes.** The Planner answers with a set-up card instead of 4 steps. The card holds what steps 2 to 4 held. It shows each thing once, and a form opens only for something being chosen:
  - its name, with Rename;
  - one sentence of what it understood, with a mark on each part. Every number, name or default the Planner read in or filled in is marked as its own guess, never as the person's words;
  - the plan. Each step names its agent. A new agent the Planner drafted is marked as new, and is saved to the Agent library when the workflow is turned on;
  - who says yes;
  - the promises the old review step made. Nothing changes without a yes. You can pause, change or delete it at any time. If it stops, the AI troubleshooter says why.
  
  It fills in everything it can and asks only for what it can't know, such as the Jira project. Every part it can't fill is a question on the card. The chat itself asks at most one question, such as which software to watch. Its button stays off until nothing is unclear, and one yes turns the workflow on.
- **Every request gets one of five answers.** Each answer that can't do the request also offers the nearest thing the Planner can do, and that suggestion passes the same abilities check.
  - *I can do this.* A set-up card.
  - *Another page does this.* A version or release request gets a filled-in Software watchlist row. If the software is already listed, the Planner says so.
  - *This needs a new tool* in a system that is already connected, such as setting a component on Jira tickets. A drafted tool needs its own ADR, because it changes ADR 0023 and widens what the safety checker allows. Until that ADR is accepted, this answer says the tool is the team's decision and offers **Ask the team**.
  - *This needs a new system or source,* such as Teams messages, email or Confluence today. **Ask the team** sends the request to the team.
  - *Never.* A request to skip a yes is refused, with the reason.
  
  A request that is none of these, such as an unrelated question, gets the list of what the Planner can do.
- **Code decides the answer, and the reply text is fixed.** The model reads the request back. Code then decides which answer applies, from the read-back and the abilities check. Each answer's sentence is fixed text, filled in from the structured answer, so the model's own words never promise anything on screen.
- **What the Planner says it can do is the platform's abilities as they are now.** The list on Home, the answers and every suggestion come from `ABILITIES`, the same list the code holds the model to. Today that is reading Jira tickets, summing up what it finds, checking software for new releases, and creating a Jira ticket after a yes. So a workflow's result goes into one Jira ticket, and Teams, email and Confluence show under "Not yet". When a tool with its own ADR adds an ability, it moves from "Not yet" to "I can" without changing the front door.
- **Refusing to skip a yes is a courtesy, and the approval gate is the control.** The refusal catches the request early and explains the rule. A request that slips past it still can't skip a yes, because every write waits at the approval gate. The refusal must not catch the product's own words, such as "run it by itself every Monday".
- **A guessed source is checked before anyone confirms it.** A watchlist row's GitHub project comes from the package registry's own link to it, or from a list of known projects. It is never a name the model made up. The Planner checks that the project exists and publishes releases, and says where the guess came from. The row records who confirmed it.
- **The chat is not the record.** What the Planner sets up becomes a workflow or a watchlist row, with its own page. The workflow keeps the request it came from, and which parts the Operator accepted or changed, in the activity log. A set-up card that isn't turned on yet is saved as a Draft. Drafts are listed on Workflows, and opening one returns to its card on Home. Starting a new chat keeps the draft. The box sends new requests, and changes to an open card happen in the card.
- **New things start in the box. Changes happen where the thing lives.** Changing an agent stays in its dialog in the Agent library. A workflow's schedule and Approvers stay on its page. Software can still be added on the Software watchlist page.
- **Needs you moves to the top of Workflows.** The Workflows tab shows an amber count when something is waiting. Waiting on others, drafts and Following up move there too.
- **An Approver who can't set up workflows sees their approvals on Home, with no box.** Their menu has Home, Workflows and Software watchlist.
- **Who says yes follows today's rule until ADR 0024 is accepted.** The card says "Any Approver on your team except you, in Teams". Named Approvers, a backup and wait times come with ADR 0024, set on the workflow's page.
- **The Planner is drawn as the Visor bot, and every other agent as a flat Orb.** The Visor bot is a white egg-shaped robot with a dark visor and glowing eyes. Each Orb is a glowing ball in its agent's colour, with a badge for its job at 32 px and above. The AI troubleshooter is an Orb too. In the chat the Planner has three more states, and each comes from a real event. It listens while you type, speaks while its reply appears, and looks sorry when it can’t do something. Nothing waits for these, and the card shows as soon as the answer is ready. The run states in the design note stay. The prototype draws the faces in SVG and CSS. In the Portal only the Planner would move to Rive, and Rive needs its own ADR because it is a new external dependency.

The [design note](../design/portal-routines.md) and the prototype show the result. [ADR 0028](0028-rebuild-the-portal-from-the-prototype-and-reshape-the-backend-in-place.md) still stands. The Portal is built from the prototype, and this ADR changes what the prototype shows.

Nothing here changes the approval gate or the safety checker. The card's yes turns a workflow on, as Turn it on did. Every write still waits for an Approver's yes in Teams, and nobody approves their own work. Drafted tools would widen what the safety checker allows, so they wait for their own ADR.

## Considered options

- **Keep the tabs and add more tips.** Little work, but it is the third try at the same fix, and the first two didn't remove the complaint.
- **Add the chat beside New workflow.** Two ways to do the same thing put more on screen, which is the opposite of the goal.
- **The box on Home with Needs you under it.** One page for new and daily users. In a normal week the box pushes approvals down, and a long conversation pushes them further.
- **A big box on day one only, then a drawer from the header.** The clearest first visit. After day one the box hides behind a header button, and the card's fields stack in a narrow drawer.
- **The chat is Home.** It feels the most like an AI product. Urgent items scroll away as the conversation grows, and pinning them rebuilds Home inside the chat.
- **Needs you in its own tab.** Easy to find, but one more tab. The count on Workflows does the same job.
- **No Needs you at all, relying on Teams.** One page fewer, but the AI troubleshooter's Fix it and Report to support show there, and Teams can't carry them.
- **One look for every agent.** Simpler, but the Planner wouldn't stand out as the one you talk to, and the Portal would need a Rive character for every agent.
- **A video avatar, like Meta's Muse.** It needs GPUs, we can't call it, and it would be another external dependency.
- **Show the target platform on Home now,** with Teams posting and drafted tools. It looks complete, but the Planner would promise what the platform refuses, which is the one thing this front door must never do.

A clickable sketch of the first five options, with 15 face designs, helped the team lead choose. It is private and throwaway, so this ADR records what it showed. Four AI models reviewed this ADR on 6 Nov, and their findings shaped the rules above.

## Consequences

- **The agent runtime's answer becomes a contract.** It returns which answer applies (the five plus "not something I do") and the filled-in card, with each part's mark. For a release request it returns the watchlist row with the checked GitHub project and where the guess came from. Each request is read on its own; the one chat question is sent back with its answer. The reply sentences are fixed text per answer.
- **platform-api serves what the agent runtime can't see.** It gives the Portal the "I can" and "Not yet" lists from `ABILITIES`, through a route in the contract stories. It matches a request against the watchlist ("already listed") and against existing workflows ("similar workflow"), because it owns both. It keeps Ask the team requests, shown under "Asked the team" on Tools, and it keeps Drafts without the old step number.
- **The no-model answer changes.** Without an AI model, or when it is too slow, the Planner says it is offline and shows what it can do and Ask the team. The old fallback, which answers with the starter workflows, goes.
- **The Portal's New workflow screens go.** `portal/src/screens/new/`, its route, and its tests (`NewWorkflow.test.tsx`, `draft.test.ts`, and the live e2e lanes for New workflow and the first screen) are replaced. Its read-back rows move into the set-up card. Home and Workflows are rebuilt to the prototype.
- **The evals' golden set grows.** It covers the five answers, requests that must be refused and ones that must not ("run it by itself every Monday"), suggestions that must pass the abilities check, and requests that mix a watchlist item with a workflow.
- **A chat box invites requests the platform can't do.** The "Not yet" list, the sorry face and Ask the team answer this. Every guess is marked, and nothing runs before the card's yes.
- **The front door depends on the AI model reading requests well.** The golden set above is the check.
- **Typing is slower than picking for people who know what they want.** The examples under the box take one tap, and the Software watchlist keeps its own Add.
- **It is our judgement, not tested with users.** Give the prototype to 2 or 3 people outside the team with two tasks, "keep track of the React version" and "every Friday, list bug tickets with no update for 10 days", and note where they stop.
- **ADR 0024 is updated in one line.** It said the Operator names Approvers in the "When and who" step of New routine. That step is gone, so it now says they are named on the workflow’s page.
- **The previous prototype is kept** in `docs/design/portal-routines/v2/`, because the usability evidence from 27 and 28 Oct describes it.
