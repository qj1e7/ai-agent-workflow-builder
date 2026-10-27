---
status: proposed
---

# Staff maintain each workflow in n8n, and the Portal keeps every published version

The sponsor's biggest concern is maintenance after handover, and he wants his staff to use n8n for it. He wants them to change how a workflow runs, build new workflows, and see the agents, all in n8n. ADR 0012 made n8n's editor read-only in practice: one generic n8n workflow per template, kept as a file in git and reloaded on each deploy. It left open whether the sponsor would accept that. He does not.

So each use case becomes its own n8n workflow. It is built from n8n's own nodes plus our **node pack**:

| Node | What it does |
|---|---|
| Agent | Runs one agent card, chosen from a list our API supplies. It returns the agent's result and adds the agent's write actions to the run's proposal. |
| Propose a change | Adds a write action that staff fill in by hand, for workflows without AI. |
| Ask for a yes | Sends the run's proposal to its Approvers and waits (ADR 0026). |
| Make the approved changes | Asks the write gateway to carry out the approved proposal (ADR 0026). |

Each node only calls our API. There is one Agent node with a list, not one node per agent, so a new agent card appears in n8n without a new node pack.

**How a workflow is built and changed:**

- The Portal's builder drafts the first n8n workflow. The Planner lays out the agent nodes when the workflow is built, and every run follows them.
- Our API checks the draft, and the Portal publishes it through n8n's API.
- Staff edit a draft in n8n, and a change goes live when someone publishes it.
- The Portal keeps a copy of every published version, with who published it and when.
- The Portal shows the plan read back from the published version. It warns when a newly published version fails the check, and it can undo a change by publishing an earlier version again.

None of this carries the safety rules. ADR 0026 does.

**What the Planner may draft.** ADR 0023 rejected letting the model write n8n workflows, because a generated n8n workflow can do anything n8n can. This ADR narrows that. The Planner may only lay out nodes from an allowed list:

- our node pack;
- n8n's triggers;
- n8n's read-only nodes for Jira, Confluence and GitHub;
- simple flow nodes such as IF and Merge.

It may never use a Code or HTTP Request node. Our API checks every draft against that list before publishing it. Staff may add other nodes in n8n, and our check warns about them.

## Considered options

- **Keep ADR 0012.** Git is the source, and every change is reviewed and linted. But staff cannot maintain anything in n8n, which is what the sponsor asked for.
- **Turn each edit in n8n into a change request.** A draft goes live only after a second person OKs it in the Portal, and the deploy then saves it to git. Review and git history stay. But there are two copies to keep in step, and staff wait for a reviewer before every fix.
- **Keep the template n8n workflows and open up only their settings,** such as schedules and message text. This is the smallest change. But staff could not build new workflows or see the agents.
- **n8n's own AI Agent nodes.** ADR 0002 and ADR 0023 rule these out, because agents built there cannot go into NCS's agent hub.

## Consequences

- **Saving a use case now writes an n8n workflow.** This reverses ADR 0012's "saving a use case never touches n8n". Git keeps only the platform's own n8n workflows, such as the error workflow `run_failure_reporter`, and bootstrap still loads those. `release_check.n8n.json` gives way to one n8n workflow per use case, and `schedule_tick` retires.
- **Schedules move into n8n (changes ADR 0020).** A use case's schedule is the Schedule Trigger in its n8n workflow, and the Portal changes it by publishing a new version. A run counts as the work of whoever published the version it used. If this ADR is accepted, that person replaces the glossary's schedule owner. n8n does not catch up on slots it missed while it was down, so the Portal shows a missed run with "Run now".
- **Agents stay in our runtime (extends ADR 0002).** They remain reusable in NCS's agent hub, and staff see them as Agent nodes. ADR 0023's "one generic n8n workflow carries every card's runs" no longer holds.
- **"Propose a change" can only target the team's allowed places,** meaning the Jira projects, Confluence spaces and Teams channels set in the Portal. This is `bind()`'s rule applied to changes written by hand. The Approver still sees the exact target.
- **A copy made in n8n that uses our nodes is registered as a new use case.** It is marked "Made in n8n". Its requests go to any Approver on the team (ADR 0024) until an Operator names Approvers in the Portal.
- **n8n users must match our users by email,** so that a published version maps to a person.
- **Four things must be proved on n8n 2.42.6 Community edition in prototype P6 before any code:**
  1. Installing our node pack.
  2. Pausing and resuming an execution from one of our nodes.
  3. Keeping "can edit" apart from "can publish".
  4. Reading who published each version.

  If edit and publish cannot be kept apart, everyone who can edit can also publish. The safety rules still hold, and the warning and undo matter more.
- **NCS maintains a small TypeScript node pack beside the Python.** The pack is baked into our own n8n image at the pinned version, which also works offline in DevNet (ADR 0006). CI tests the pack against a new n8n version before the pin moves.
- **Read keys and a staff-added HTTP Request node could send data elsewhere.** ADR 0026 covers writes, not leaks. Network rules limit where n8n can connect, and our check flags HTTP Request nodes that call hosts not on a list.
- **n8n's licence** (the Sustainable Use License) still needs the sponsor's confirmation, as ADR 0002 says.
