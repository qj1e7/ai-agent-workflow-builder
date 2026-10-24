# AI agent workflow builder

A platform where non-technical support staff describe a repetitive task in plain English, and AI agents do the work with human approval before any write action.

Never use the old themed names (Flint, Forge, Striker, Spark Map, Scout, Analyst, Messenger, Clerk, Fixer, Kindling, Firebreak, Ember) for any term below.

## Language

### Building

**AI workflow builder**:
The product where an Operator describes a task and turns it into a use case.

**Use case**:
A saved definition of a repetitive task, made from blocks and templates.
_Avoid_: Job, recipe

**Block**:
One reusable step that a use case is built from.

**Template**:
A ready-made use case that an Operator starts from and adjusts.

**Portal**:
The web app where Operators build use cases and start runs, watch the live activity view, and Approvers decide on approval requests.
_Avoid_: Frontend, dashboard

### Keeping software up to date

**Watchlist**:
The list of software a team runs and keeps up to date. It is checked on a schedule, and one approval request covers each check.
_Avoid_: Inventory, software list

**Watched software**:
One piece of software on the watchlist, with its source and our version.
_Avoid_: Item, package, repo

**Check**:
One run of the watchlist that compares every watched software's newest version with our version.
_Avoid_: Scan, poll

**Source**:
Where a watched software's releases are published, such as its GitHub releases.
_Avoid_: Feed, link

**Our version**:
The version of a watched software that the team runs now.
_Avoid_: Current version, installed version

**Newest version**:
The latest release at the source.
_Avoid_: Latest, current version

**Schedule owner**:
The person who last saved a watchlist's schedule. Every scheduled check counts as their work.

### Running

**Run**:
One execution of a use case, from trigger to result.
_Avoid_: Job, execution (n8n uses "execution" for its own internal runs)

**Room lead**:
The agent that reads a task and decides which specialist agents to bring in.

**Specialist agent**:
An agent that the Room lead brings in to do one part of a run.

**Leg**:
The part of a run that n8n carries in one execution. A run has a work leg up to the approval request and an act leg from the approval to the end. Our platform owns the pause between them.

**Write action**:
Any action that changes data in an external system, such as Jira, Confluence or GitLab.

**Proposal**:
The set of write actions that agents propose for one run. One approval request covers exactly one proposal, and the Approver approves it as a whole.
_Avoid_: Plan, draft

**Approval gate**:
The step that pauses a run before a write action until an Approver approves it in Teams.

**Safety checker**:
The check that every agent action passes before it runs. It denies write actions by default.

### Watching

**Live activity view**:
The animated view of a run that shows agents talking, hand-offs, and where something failed.

**Activity event**:
One recorded thing that happened in a run, such as an agent step, an approval decision or a failure. The live activity view and the AI troubleshooter both read activity events.
_Avoid_: Log line, n8n event

**AI troubleshooter**:
The agent that explains why a run failed and helps the Operator fix it.

### Roles

**Operator**:
A support staff member who describes tasks and starts runs.

**Approver**:
A person who approves write actions. An Approver can never approve their own work.
