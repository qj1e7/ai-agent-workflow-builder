# Staff maintain workflows in n8n

This page proposes letting CODESparks staff maintain their workflows in n8n after handover, without weakening any safety rule. Nothing in the code changes until the team agrees and prototype P6 answers the open questions about n8n.

**Status:** proposal for team review, 28 Oct 2026. The decisions are in [ADR 0026](../adr/0026-every-write-is-checked-when-it-is-made-so-n8n-may-hold-the-wait.md) and [ADR 0027](../adr/0027-staff-maintain-each-workflow-in-n8n-and-the-portal-keeps-every-published-version.md).

## Why change

The sponsor's biggest concern is maintenance after we hand over, and he is set on using n8n for it. He wants his staff to do three things in n8n:

1. Change how a workflow runs, for example a step, a schedule or a message.
2. Build new workflows.
3. See the agents.

Today n8n is deliberately thin (ADRs 0002, 0007, 0012 and 0020).

- Every n8n node calls our API, and our API holds the run state, the approvals and the safety rules.
- One generic n8n workflow serves every use case of a template. It is a file in git, and each deploy reloads it, so an edit made in n8n's editor is lost.
- ADR 0012 left one question open: "Whether the sponsor accepts that the editor is read-only in practice is an open question for him." The answer is no.

If the sponsor opened n8n today, he would see short n8n workflows that each call one endpoint, with nothing in them his staff could usefully change.

## The idea

> **n8n holds the steps. Our platform holds the keys and the rules. Staff can change any step in n8n, but nothing can be written without a yes.**

## Who owns what

| Part | What it owns | Where staff change it |
|---|---|---|
| **n8n** | Each n8n workflow's steps and their order, triggers and schedules, retries, error alerts, reading from Jira, Confluence and GitHub, and waiting for a yes | n8n's editor, as a draft. A change goes live when someone publishes it |
| **Our API** | The approval rules, every write key, carrying out approved changes, the activity log, and a copy of every published version | Nowhere in n8n. Approvers are named in the Portal (ADR 0024) |
| **Agent runtime** | The Planner and the specialist agents | In plain English, in the Portal (agent cards, ADR 0023) |
| **Portal** | The plain-English builder that drafts the first n8n workflow, the live activity view, approvals, the AI troubleshooter and undo | The Portal |

**The one hard line:** nothing in n8n can change Jira, Confluence or Teams by itself. Posting a Teams message counts as a change. n8n's own Jira and Confluence nodes stay usable for reading, with read-only keys.

## The node pack

Staff see these nodes in n8n, beside n8n's own:

| Node | What it does | What it can never do |
|---|---|---|
| **Agent** | Runs one of our agents, picked from a list (Version checker, Ticket writer…). It shows the agent's name and face, returns the agent's result, and adds any change the agent wants to the run's proposal | Make a change itself |
| **Propose a change** | For workflows without AI. Staff fill in a change by hand, such as "Post this text in CODESparks Support", and it joins the proposal | Make a change itself, or target a place outside the team's allowed list |
| **Ask for a yes** | Sends the proposal to the workflow's Approvers in Teams, then waits. It has three exits: **Yes**, **No** and **No answer** | Decide anything. Our API applies every approval rule |
| **Make the approved changes** | Carries out exactly the approved proposal, using write keys held by our API | Change anything that wasn't approved, or was edited after the yes |

The software check would read in n8n as:

**Every Monday 9:00 → Version checker → Vulnerability checker → Ticket writer → Ask for a yes → Make the approved changes**

Three choices keep the pack easy to maintain:

- **One Agent node with a list,** not one node per agent. A new agent card saved in the Portal appears in n8n with no new install.
- **The Planner lays out the agents when the workflow is built,** and every run follows them. Staff can see in n8n exactly who runs. The run chat still opens with the Planner stating the plan.
- **Each node only calls our API.** The pack holds no rules, so there is little in it to break.

## How the safety rules hold

**The path of one change:**

1. An agent, or a Propose a change node, adds a write action to the run's proposal. Our API stores the proposal under our own run ID, with a digest of its content (ADR 0008).
2. **Ask for a yes** asks our API to send the request to the named Approvers. n8n waits. When someone decides, or the request expires, our API wakes the run.
3. **Make the approved changes** asks the write gateway to carry out the proposal. The gateway checks only our own records:
   - the right people said yes, nobody approved their own work, and two Approvers answered in order where a tool needs two;
   - the digest still matches;
   - it hasn't been done already;
   - the request hasn't expired.
4. The gateway makes the change with keys from Key Vault and logs who approved it.

**What a careless edit does:**

| Edit in n8n | Result |
|---|---|
| Deletes Ask for a yes, or moves it after the write | The write refuses: "No yes for this run." The AI troubleshooter says which edit caused it |
| Copies the n8n workflow | Approvals don't carry over. They belong to one run |
| Adds n8n's own Jira node to create tickets | Fails, because n8n only has read-only keys |
| Wakes a waiting run early | Nothing happens, because the write checks our records |
| Changes where Propose a change posts | Only places on the team's allowed list work, and the Approver sees the exact target |

**The one real gap:** someone with enough rights in n8n could paste their own write key into it. Three things close it:

- Only n8n's owner role can add keys.
- Our API checks n8n's keys every day and alerts on any key that isn't on the read-only list.
- The handover guide explains why.

The lessons from the October sandbox stay. Our API checks every day that the error workflow is published and active, and retries wait a short delay first.

## Build, edit, publish and undo

**Building a new workflow (in the Portal):**

1. The Operator describes the task, and step 2 reads it back as a sentence.
2. The Planner drafts an n8n workflow. It may only use nodes from an allowed list: our node pack, n8n's triggers, n8n's read-only Jira, Confluence and GitHub nodes, and simple flow nodes such as IF. It may never use Code or HTTP Request nodes.
3. Step 3 sets the schedule and the Approvers.
4. **Turn it on** runs our check, then creates and publishes the n8n workflow through n8n's API. The Portal records who turned it on and keeps a copy of that version.

**Editing (in n8n):**

- Each workflow's page in the Portal has an **Open in n8n** button. Staff change the draft and publish it.
- Our API notices newly published versions within about a minute and runs the same check. If an edit breaks something, the Portal and Teams warn at once, for example "Bob's change removed Ask for a yes". Safety holds either way, so this check is about the workflow still doing its job.
- The Portal rebuilds "What the workflow will do" from the published version, with a line such as "Changed in n8n by Bob, Tue 10:02".
- A copy made in n8n that uses our nodes appears on Workflows, marked **Made in n8n**. Its requests go to any Approver on the team until an Operator names Approvers.

**Undo:**

- The Portal keeps every published version, with who published it and when. **Undo this change** publishes the previous version again, and the undo is logged too.
- When a run stops soon after a new version, the AI troubleshooter says so: "This stopped after Bob's change at 10:02. Undo it?"

**Who counts as having started a scheduled run:** the person who published the version it used. They can't approve that run. This replaces ADR 0020's schedule owner. It needs n8n users to match our users by email.

## Live activity view and AI troubleshooter

The run line is built from the published version's nodes, so it matches what staff see in n8n.

- Our nodes report to our API at each step. That feeds the group chat: the Planner's plan, each agent's message, the proposal, the ask, the yes and the write.
- n8n's own nodes, such as the schedule, Jira reads or anything staff add, come from n8n's execution history. They show as quiet lines in the chat.

Our error workflow tells our API when a run fails. The AI troubleshooter then reads n8n's error, our activity events and the version history, and sorts the failure into one of three kinds:

1. **You can fix it,** for example a GitHub project that moved.
2. **A recent edit broke it.** It offers Undo. This kind is new.
3. **Only support can fix it.** It offers Report to support.

## Safety rules the design keeps

ADR 0026 changes where the approval gate is enforced: at the write, not along the route. Every rule still holds:

- No write action runs without a yes in Teams. The safety checker still denies by default, and only the write gateway holds keys.
- Nobody approves their own work. Runs from a published version count as the publisher's work.
- The access review still needs two Approvers, one after the other.
- Approval requests key off our own request ID, never n8n's execution ID.
- The error workflow must be active. Our API checks this every day.
- A retry waits a short delay first, and never writes twice.
- Every change is logged with who approved it.

## Goals

- A CODESparks staff member can change a step or a schedule in n8n, without code and without asking us.
- No edit in n8n can make a write happen without a yes.
- When an edit breaks a workflow, the Portal says which edit, and one click undoes it.

## Non-goals

- Staff writing code in n8n. Code and HTTP Request nodes are allowed but flagged, and the Planner never uses them.
- Agents built with n8n's AI Agent node. Agents stay in our runtime so they can go into NCS's agent hub (ADR 0002).
- Choosing agents fresh on every run. The Planner lays them out when a workflow is built.
- n8n's paid features. The design must work on the free Community edition.

## What changes in each context

| Context | Change |
|---|---|
| Use case builder | Turn it on creates and publishes an n8n workflow. The Planner drafts its layout from the allowed nodes. Workflow pages gain Open in n8n, the version list and Undo. |
| Agent runtime | No change to agents. The Agent node calls the same runtime through our API. |
| Orchestration | New: the node pack, the publish check, the daily key check, and keeping published versions. The write gateway (`WriteGateway` in `orchestration/write_actions.py`) checks approvals itself. The two-leg step API (ADR 0007), `release_check.n8n.json` and `schedule_tick` retire once the new path passes the same end-to-end tests. |
| Run monitoring | The run line comes from the published version. n8n's own nodes come from n8n's execution history. The AI troubleshooter learns "a recent edit broke it". |

## First slice, for the presentation (27 Nov to 5 Dec)

| When | What |
|---|---|
| First week of November | Prototype P6 on the four open questions about n8n's Community edition. The team reviews ADRs 0026 and 0027 |
| Next two weeks | The first three nodes: Agent, Ask for a yes and Make the approved changes. Move the software check onto them. Today's path keeps running until the new one passes the same end-to-end tests |
| The demo | A staff member moves a node and changes the schedule in n8n. Then they delete Ask for a yes and the write refuses |

## Later

- Propose a change.
- The Portal reading plans back from n8n, Undo, and Made in n8n.
- The daily checks of n8n's keys and of where HTTP Request nodes connect.

## Risks

| Risk | What we do |
|---|---|
| NCS maintains TypeScript as well as Python | Each node only calls our API, so the pack stays small |
| An n8n upgrade breaks our nodes | We pin n8n and bake the pack into our own n8n image, which also works offline in DevNet. CI tests the pack before the pin moves |
| A careless edit stops a workflow | The publish check warns, the AI troubleshooter names the edit, and Undo restores the last version |
| Read keys plus an HTTP Request node could send data elsewhere | Network rules limit where n8n can connect, and our check flags HTTP Request nodes to unknown hosts |
| n8n doesn't catch up on schedules it missed while down | The Portal shows a missed run with "Run now" |

## Open questions

**For prototype P6 (n8n 2.42.6, Community edition):**

1. Can we install our node pack?
2. Can one of our nodes pause an execution, and can our API wake it?
3. Can "can edit" be kept apart from "can publish"? Our logs show a publish permission, but custom roles may need a paid plan.
4. Can we read who published each version?

**For the sponsor:**

- Is it acceptable that n8n holds read-only keys, and that only the platform holds write keys?
- Who on his team should be able to publish changes in n8n?
- Does n8n's licence (the Sustainable Use License) fit NCS? This question was already open.
