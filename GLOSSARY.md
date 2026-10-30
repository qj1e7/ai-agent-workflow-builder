# AI agent workflow builder

A platform where non-technical support staff describe a repetitive task in plain English, and AI agents do the work with human approval before any write action.

Never use the old themed names (Flint, Forge, Striker, Spark Map, Scout, Analyst, Messenger, Clerk, Fixer, Kindling, Firebreak, Ember) for any term below.

## Language

### Building

**AI workflow builder**:
The product where an Operator describes a task and turns it into agent cards and use cases.

**Agent card**:
A saved definition of an agent: its purpose, its plan, the tools it may use, the inputs an Operator gives each run, and how many Approvers each write needs. The AI model drafts it, and an Operator reviews and saves it.
_Avoid_: Agent config, bot, prompt

**Plan**:
The ordered blocks on an agent card.

**Block**:
One step of an agent card's plan. A block uses at most one tool.

**Tool**:
One thing an agent can do in another system, such as reading GitHub releases or creating a Jira ticket. The team builds and tests every tool, and an agent can use only the tools on its card.
_Avoid_: Plugin, skill, integration

**Agent library**:
The agent cards a team has saved. The Planner chooses from it.
_Avoid_: Agent hub (NCS's agent hub is a separate thing)

**Use case**:
A saved repetitive task: which agent card runs, with which inputs, and when. Operators see it as a **workflow**.
_Avoid_: Job, recipe, routine

**Workflow**:
What Operators see a use case called in the app. Always write "n8n workflow" for n8n's own workflows, and "Jira workflow" for a ticket's statuses.
_Avoid_: Routine

**Template**:
A ready-made agent card that ships with the platform, such as the Version checker.

**Portal**:
The web app where Operators build use cases and start runs, watch the live activity view, and Approvers decide on approval requests. Users see it under the product's name, AI Workflow Builder.
_Avoid_: Frontend, dashboard

**Node pack**:
Our own n8n nodes. With them, an n8n workflow can run an agent card, read from another system, add write actions to a proposal, ask for approval and carry out an approved proposal. They are the only way an n8n workflow reaches another system.
_Avoid_: Plugin, integration, custom nodes

**Published version**:
The version of a use case's n8n workflow that runs. Staff change a draft in n8n, and publishing the draft makes it the published version.
_Avoid_: Live version, active version

### Keeping software up to date

**Watchlist**:
The list of software a team runs and keeps up to date. It is checked on a schedule, and one approval request covers each check. In the app it is the **Software watchlist**.
_Avoid_: Inventory, software list

**Watched software**:
One piece of software on the watchlist, with its source and our version.
_Avoid_: Item, package, repo

**Check**:
One run of the watchlist that compares every watched software's newest version with our version.
_Avoid_: Scan, poll

**Source**:
Where a watched software's releases are published: a package registry such as Maven Central, npm, PyPI, NuGet or Docker Hub, or its GitHub releases.
_Avoid_: Feed, link

**Our version**:
The version of a watched software that the team runs now.
_Avoid_: Current version, installed version

**Newest version**:
The latest release at the source.
_Avoid_: Latest, current version

**Known vulnerability**:
A published security flaw, with a CVE number, that affects a version of a watched software.
_Avoid_: Bug, issue

**End of life**:
The date after which a version of a watched software gets no more fixes, including security fixes.
_Avoid_: EOL, deprecated

**Schedule owner**:
The person who last saved a watchlist's schedule. Every scheduled check counts as their work.

### Running

**Run**:
One execution of a use case, from trigger to result.
_Avoid_: Job, execution (n8n uses "execution" for its own internal runs)

**Test run**:
A run an Operator starts by hand to try a workflow. It asks for a yes and writes like any other run.
_Avoid_: Dry run (nothing is skipped)

**Planner**:
The agent that reads a task, says what it understood, and decides which saved agents to bring in, or that a new agent card is needed.
_Avoid_: Room lead (the old name), orchestrator

**Specialist agent**:
An agent, defined by an agent card, that the Planner brings in to do one part of a run.

**Version checker**:
The specialist agent that reads each watched software's releases at its source, compares the newest version with our version, and suggests an upgrade ticket for each one that is behind. It ships as a template.
_Avoid_: Release checker (the old name), scanner

**Leg**:
The part of a run that n8n carries in one execution. A run has a work leg up to the approval request and an act leg from the approval to the end. Our platform owns the pause between them.

**Write action**:
Any action that changes data in an external system, such as Jira, Confluence or GitLab.

**Proposal**:
The set of write actions that agents propose for one run. One approval request covers exactly one proposal, and the Approver approves it as a whole.
_Avoid_: Plan, draft

**Approval gate**:
The step that pauses a run before a write action until an Approver approves it in Teams.

**Named Approvers**:
The people a use case names for one approval step: who is asked first and, if the Operator chooses one, a backup. Only they can decide that step.
_Avoid_: Assignee, reviewer

**Escalation**:
Asking a step's backup because the first Approver has not answered in time. It changes who is asked, never who may decide.
_Avoid_: Reassignment, handover

**Expired request**:
An approval request that nobody answered in time. Nothing is written, as when it is declined, and it never approves itself.
_Avoid_: Timed out (that means the workflow engine stopped answering)

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

### Setting up

**Connection**:
The platform's account in another system, such as GitHub, Jira or Teams, with its key. Agents read through it. Only the write gateway holds a key that writes.
_Avoid_: Integration, credential

**Practice copy**:
A stand-in for Jira or Teams that the platform runs itself, so demos and tests write without touching a real system.
_Avoid_: Mock (in the app), sandbox

**Confirmation**:
A second person's yes to a setup change before it takes effect, such as making someone an Approver or using a new AI model address. Any Approver may confirm, except the person who asked and the person it is about.
_Avoid_: Approval (that is for a run's proposal), sign-off

### Roles

**Operator**:
A support staff member who describes tasks and starts runs, and looks after Settings: the AI model, and the People list. An Operator adds people, makes someone an Operator or stops them being one at once, and asks for a new Approver. Nobody can remove their own Operator role.

**Approver**:
A person who approves write actions, and who confirms a new Approver and a new AI model address. An Approver can never approve their own work, and never confirms a change they asked for or that is about them. At least two people are Approvers.

**People list**:
The platform's own record of who may use it and which roles they hold. Sign-in only says who someone is; the People list gives them their roles. Someone who signs in but is not on it is told to ask an Operator.
_Avoid_: Users, accounts, app roles
