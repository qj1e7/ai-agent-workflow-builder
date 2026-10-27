---
status: proposed
---

# Staff maintain each workflow in n8n, and the Portal keeps every published version

The sponsor's biggest concern is maintenance after handover, and he wants his staff to use n8n for it. He wants them to change how a workflow runs, build new workflows, and see the agents, all in n8n. ADR 0012 made n8n's editor read-only in practice: one generic n8n workflow per template, kept as a file in git and reloaded on each deploy. It left open whether the sponsor would accept that. He does not.

So each use case becomes its own n8n workflow. It is built from our **node pack** and a few of n8n's own nodes:

| Node | What it does |
|---|---|
| Agent | Runs one agent card, chosen from a list our API supplies. It returns the agent's result and adds the agent's write actions to the run's proposal. |
| Read | Reads from Jira, Confluence or GitHub through our API, for a read step without AI. |
| Propose a change | Adds a write action that staff fill in by hand, for workflows without AI. |
| Ask for a yes | Sends the run's proposal to its Approvers and waits (ADR 0026). |
| Make the approved changes | Asks the write gateway to carry out the approved proposal (ADR 0026). |

Each node only calls our API. There is one Agent node with a list, not one node per agent, so a new agent card appears in n8n without a new node pack.

**n8n loads only an allowed list of node types.** Its `NODES_INCLUDE` setting holds:
- our node pack;
- n8n's triggers (Webhook, Schedule, Manual, Error);
- simple flow nodes (IF, Merge, No Op, Sticky Note).

n8n then has no node that can reach another system, call an outside address or run code, for anyone, in any n8n workflow. ADR 0023 rejected letting the model write n8n workflows, because a generated n8n workflow can do anything n8n can. With the allow list, an n8n workflow can only do what our node pack lets it, so the Planner may draft n8n workflows, and so may staff.

**How a workflow is built and changed:**

- The Portal's builder drafts the first n8n workflow. The Planner lays out the agent nodes when the workflow is built, and every run follows them.
- Our API checks the draft. Through n8n's API, the platform's account (n8n's owner) creates the n8n workflow and publishes it. The Portal says the workflow is on once n8n reports every trigger as activated.
- To change it, an Operator presses **Open in n8n**. The platform moves the n8n workflow into that person's own space in n8n, and they edit and publish it there.
- The Portal keeps a copy of every published version, with who published it and when. It shows the plan read back from the published version, warns when a newly published version fails our check, and can undo a change by publishing an earlier version again.

None of this carries the safety rules. ADR 0026 does.

[Prototype P6](../evidence/prototypes/p6-n8n-node-pack/findings.md) tested this on n8n 2.42.6 Community edition, the free one:
- n8n loaded the node pack, and the Agent node's list came from our API.
- The free edition cannot share an n8n workflow between people or make anyone an admin. It can move an n8n workflow into one person's space. That person can then edit it, and also publish it.
- n8n records who published each version.
- Staff can add their own keys. With the allow list, no node could use them, and an HTTP Request or Jira node could not be published or run by hand.

## Considered options

- **Keep ADR 0012.** Git is the source, and every change is reviewed and linted. But staff cannot maintain anything in n8n, which is what the sponsor asked for.
- **Turn each edit in n8n into a change request.** A draft goes live only after a second person OKs it in the Portal, and the deploy then saves it to git. Review and git history stay. But there are two copies to keep in step, and staff wait for a reviewer before every fix.
- **Keep the template n8n workflows and open up only their settings,** such as schedules and message text. This is the smallest change. But staff could not build new workflows or see the agents.
- **Allow n8n's own Jira, Confluence and HTTP nodes with read-only keys.** Staff would have n8n's full set of nodes for reading. But P6 showed that staff can add their own keys, so any node that can use a key can write or send data out.
- **Buy n8n's paid features: sharing, admins, and roles that can edit without publishing.** Several people could edit one n8n workflow, and publishing could be kept to a few. But it costs money and needs NCS procurement, and safety doesn't depend on it. The sponsor can decide this later without changing the design.
- **n8n's own AI Agent nodes.** ADR 0002 and ADR 0023 rule these out, because agents built there cannot go into NCS's agent hub.

## Consequences

- **Saving a use case now writes an n8n workflow.** This reverses ADR 0012's "saving a use case never touches n8n". Git keeps only the platform's own n8n workflows, such as the error workflow `run_failure_reporter`, and bootstrap still loads those. `release_check.n8n.json` gives way to one n8n workflow per use case, and `schedule_tick` retires.
- **One editor at a time, and whoever edits can publish.** On the free edition, an n8n workflow sits in one person's space. Open in n8n moves it to the person who asks, and the Portal shows who has it. Our API reads n8n's publish history for every publish, so the warning and undo cover every change.
- **Schedules move into n8n (changes ADR 0020).** A use case's schedule is the Schedule Trigger in its n8n workflow, and the Portal changes it by publishing a new version. A run counts as the work of whoever published the version it used. If this ADR is accepted, that person replaces the glossary's schedule owner. n8n does not catch up on slots it missed while it was down, so the Portal shows a missed run with "Run now".
- **Agents stay in our runtime (extends ADR 0002).** They remain reusable in NCS's agent hub, and staff see them as Agent nodes. ADR 0023's "one generic n8n workflow carries every card's runs" no longer holds.
- **"Read" and "Propose a change" can only reach the team's allowed places,** meaning the Jira projects, Confluence spaces, GitHub projects and Teams channels set in the Portal. This is `bind()`'s rule applied to steps that staff set up by hand. The Approver still sees the exact target of every change.
- **Each of n8n's other nodes is a decision.** Staff may ask for one, such as Slack or email. We either add a node to our pack, or put n8n's node on the allow list after checking what it can reach.
- **A copy made in n8n that uses our nodes is registered as a new use case.** It is marked "Made in n8n". Its requests go to any Approver on the team (ADR 0024) until an Operator names Approvers in the Portal.
- **n8n users must match our users by email,** so that a published version maps to a person.
- **NCS maintains a small TypeScript node pack beside the Python.** P6's nodes were plain JavaScript loaded from a folder. The real pack is baked into our own n8n image at the pinned version, which also works offline in DevNet (ADR 0006). CI tests the pack and the allow list against a new n8n version before the pin moves.
- **n8n's licence** (the Sustainable Use License) still needs the sponsor's confirmation, as ADR 0002 says.
