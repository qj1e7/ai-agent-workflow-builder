---
status: proposed
---

# Home is the Planner's chat box, and it replaces New workflow

On 6 Nov the team said that people opening the app for the first time don't know what to do, because there are too many things on screen. The in-app tour (#34) and the 27 Oct reshape both added guidance on top of the screens, and the complaint stayed. The team lead asked for one place to start. People tell the Planner what they want there. The Planner knows what the platform and the AI model can and can't do, suggests the right feature, and fills it in once they agree. For example, "keep track of the React version" becomes a filled-in row on the Software watchlist.

Most of this already exists behind the screens. The Planner's read-back (`understand_task` in `agent-runtime/src/agent_runtime/planner.py`) splits a request into when, what to look for, what to do and where. It marks each part as understood, changed, missing or can't do, and it already sends version and release requests to the Software watchlist. The `ABILITIES` list in `agent-runtime/src/agent_runtime/abilities.py` overrules the model when it claims something no tool can do. Today all of this sits behind the New workflow tab and its 4 steps.

We decided:

- **Home is the Planner's box, every day.** It is a large box in the middle of the page, under the Planner's face. On day one it asks "What does your team do again and again?" and lists what the Planner can do and what it can't do yet. After that it asks "What else should run by itself?", and the list folds into a "What can I ask for?" link. Three example requests sit under the box. Home shows nothing else.
- **The New workflow tab goes.** The Planner answers with a set-up card instead of 4 steps. The card holds what steps 2 to 4 held: the read-back with its marks, the plan with each step marked, when it runs, who is asked first and the backup, and the Teams channel. It fills in everything it can, marks every guess, and asks only for what it can't know, such as the Jira project. Its button stays off until nothing is unclear, and one yes turns the workflow on.
- **Every request gets one of five answers.** Each answer that can't do the request also offers the nearest thing the Planner can do.
  - *I can do this.* A set-up card.
  - *Another page does this.* A version or release request gets a filled-in Software watchlist row, with the guessed GitHub project marked for checking. If the software is already listed, the Planner says so.
  - *This needs a new tool.* If the system is already connected, the Planner drafts a tool card, and an Approver who isn't the person asking OKs it once. Tool cards still need their own ADR, as the design note says.
  - *This needs a new system or source.* **Ask the team** sends the request to the team.
  - *Never.* A request to skip a yes is refused, with the reason.
- **What the Planner says it can do comes from `ABILITIES`.** The list on Home and the Planner's answers use the same list that the code holds the model to. So the Planner can't promise what the platform would later refuse.
- **The chat is not the record.** What the Planner sets up becomes a workflow or a watchlist row, with its own page. A card that isn't turned on yet is a Draft.
- **New things start in the box. Changes happen where the thing lives.** Changing an agent stays in its dialog in the Agent library. A workflow's schedule and Approvers stay on its page. Software can still be added on the Software watchlist page.
- **Needs you moves to the top of Workflows.** The Workflows tab shows an amber count when something is waiting. Waiting on others and Following up move there too.
- **An Approver who can't set up workflows sees their approvals on Home, with no box.** Their menu has Home, Workflows and Software watchlist.
- **The Planner is drawn as the Visor bot, and every other agent as a flat Orb.** The Visor bot is a white egg-shaped robot with a dark visor and glowing eyes. Each Orb is a glowing ball in its agent's colour, with a badge for its job. The AI troubleshooter is an Orb too. In the chat the Planner has three more states, and each comes from a real event. It listens while you type, speaks while its reply is written, and looks sorry when it can't do something. The run states in the design note stay. The prototype draws the faces in SVG and CSS. In the Portal only the Planner would move to Rive, and Rive needs its own ADR because it is a new external dependency.

The [design note](../design/portal-routines.md) and the prototype show the result. [ADR 0028](0028-rebuild-the-portal-from-the-prototype-and-reshape-the-backend-in-place.md) still stands. The Portal is built from the prototype, and this ADR changes what the prototype shows.

Nothing here changes the approval gate or the safety checker. The card's yes turns a workflow on, as Turn it on did. Every write still waits for an Approver's yes in Teams, and nobody approves their own work.

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

A clickable sketch of the first five options, with 15 face designs, helped the team lead choose. It is private and throwaway, so this ADR records what it showed.

## Consequences

- **The Portal's New workflow screens go.** `portal/src/screens/new/` and its route are removed. Its read-back rows move into the set-up card on Home. Home and Workflows are rebuilt to the prototype.
- **The Planner's answer grows.** It says which of the five answers it is and returns the filled-in card. For a release request it proposes the watchlist row with the GitHub project. Today `WatchlistStep` in `portal/src/screens/new/StepCheck.tsx` only links to the watchlist page. It asks at most two short questions before the card. The Portal reads the list of what the Planner can do from the agent runtime instead of keeping its own copy.
- **A chat box invites requests the platform can't do.** The "Not yet" list, the sorry face and Ask the team answer this. Every guess is marked, and nothing runs before the card's yes.
- **The front door now depends on the AI model answering well.** The evals' golden set should cover the five answers, including "keep track of the React version" and "every Friday, list bug tickets with no update for 10 days".
- **Typing is slower than picking for people who know what they want.** The examples under the box take one tap, and the Software watchlist keeps its own Add.
- **It is our judgement, not tested with users.** Before the Portal work starts, give the prototype to 2 or 3 people outside the team with those two tasks, and note where they stop.
- **The previous prototype is kept** in `docs/design/portal-routines/v2/`, because the usability evidence from 27 and 28 Oct describes it.
