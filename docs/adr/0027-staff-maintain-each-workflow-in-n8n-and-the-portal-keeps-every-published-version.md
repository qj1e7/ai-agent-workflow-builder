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
| Ask for a yes | Sends the run's proposal to its Approvers and waits (ADR 0026). With nothing proposed, it asks nobody and leaves by "Nothing to change". |
| Make the approved changes | Asks the write gateway to carry out the approved proposal (ADR 0026). |
| Start from the Portal | A trigger. It starts a run when our API calls it, for Run now and test runs, and accepts only calls that our API signed. |
| Report a failure | Tells our API that an n8n workflow failed. The platform's error workflow uses it. |

Each node only calls our API. There is one Agent node with a list, not one node per agent, so a new agent card appears in n8n without a new node pack.

Our API's address, and the secret that Start from the Portal checks, come from n8n's environment in our own image, never from a field in a node. Each node also sends only fixed fields. Otherwise staff could point one of our nodes elsewhere and send data out, and our nodes are the only way out of n8n. P6's throwaway nodes had an editable address field. A security review found this, and [the findings](../evidence/prototypes/p6-n8n-node-pack/findings.md) record it.

**n8n loads only an allowed list of node types.** Its `NODES_INCLUDE` setting holds:
- our node pack;
- n8n's Schedule, Manual and Error triggers;
- simple flow nodes (IF, Merge, No Op, Sticky Note).

n8n's Webhook trigger is left out. It needs no sign-in unless someone sets one, and it can answer a call with the last node's data. So anyone who knew its address could read what a run had read. Start from the Portal replaces it.

n8n then has no node that can reach another system, call an outside address, answer an outside call or run code, for anyone, in any n8n workflow. ADR 0023 rejected letting the model write n8n workflows, because a generated n8n workflow can do anything n8n can. With the allow list, an n8n workflow can only do what our node pack lets it, so the Planner may draft n8n workflows, and so may staff.

**How a workflow is built and changed:**

- The Portal's builder drafts the first n8n workflow. The Planner lays out the agent nodes when the workflow is built, and every run follows them.
- The Planner makes the n8n workflow explain itself. It names each node by what it does, such as "Check LangGraph for new releases". It adds a Sticky Note that holds:
  - the workflow's purpose;
  - a link to its page in the Portal, where its Approvers are set;
  - what is safe to change.

  The note links to the Approvers instead of naming them, because they change in the Portal without a new version.
- Our API checks the draft. The check also confirms two settings: the n8n workflow runs on Singapore time, and it still names our error workflow. Through n8n's API, the platform's account (n8n's owner) creates the n8n workflow and publishes it. The Portal says the workflow is on once n8n reports every trigger as activated.
- An Operator may also start a new workflow in n8n instead, from New workflow. The Planner doesn't draft it.
- To change it, an Operator presses **Open in n8n**. The platform moves the n8n workflow into that person's own space in n8n, and they edit and publish it there.
- The Portal keeps a copy of every published version, with who published it and when. It shows the plan read back from the published version, warns when a newly published version fails our check, and can undo a change by publishing an earlier version again.
- A run checks its version before it reads anything. On the run's first call, our API checks the version it uses: the published one for a triggered run, the current draft for one started by hand. If that version fails, the run stops there. This covers the minute between a publish and our check of it, and drafts that nobody published.

None of this carries the safety rules. ADR 0026 does.

[Prototype P6](../evidence/prototypes/p6-n8n-node-pack/findings.md) tested this on n8n 2.42.6 Community edition, the free one:
- n8n loaded the node pack, and the Agent node's list came from our API.
- The free edition cannot share an n8n workflow between people or make anyone an admin. It can move an n8n workflow into one person's space. That person can then edit it, and also publish it.
- n8n records who published each version.
- Staff can add their own keys. With the allow list, no node could use them, and an HTTP Request or Jira node could not be published or run by hand.

The [n8n workflow patterns review](../evidence/usability/2026-10-28-design-skill-audits.md#n8n-design-proposals-now-drafted-into-adrs-0026-and-0027) on 28 Oct found two gaps:
- the allow list broke our own error workflow;
- it left the Webhook trigger open.

It also added these parts of the decision:
- Start from the Portal and Report a failure;
- Singapore time;
- the check at the start of a run;
- n8n workflows that explain themselves;
- long lists;
- data nodes.

Prototype P7 will test the new trigger and the data nodes before they are built.

## Considered options

- **Keep ADR 0012.** Git is the source, and every change is reviewed and linted. But staff cannot maintain anything in n8n, which is what the sponsor asked for.
- **Turn each edit in n8n into a change request.** A draft goes live only after a second person OKs it in the Portal, and the deploy then saves it to git. Review and git history stay. But there are two copies to keep in step, and staff wait for a reviewer before every fix.
- **Keep the template n8n workflows and open up only their settings,** such as schedules and message text. This is the smallest change. But staff could not build new workflows or see the agents.
- **Allow n8n's own Jira, Confluence and HTTP nodes with read-only keys.** Staff would have n8n's full set of nodes for reading. But P6 showed that staff can add their own keys, so any node that can use a key can write or send data out.
- **Buy n8n's paid features: sharing, admins, and roles that can edit without publishing.** Several people could edit one n8n workflow, and publishing could be kept to a few. But it costs money and needs NCS procurement, and safety doesn't depend on it. The sponsor can decide this later without changing the design.
- **n8n's own AI Agent nodes.** ADR 0002 and ADR 0023 rule these out, because agents built there cannot go into NCS's agent hub.
- **Keep n8n's Webhook trigger and turn on its own sign-in.** No new node would be needed. But sign-in is a setting that anyone who edits the n8n workflow can switch off.
- **Put HTTP Request back on the allow list, for our error workflow.** The error workflow would work unchanged. But the allow list applies to every n8n workflow, so staff could use HTTP Request too.

## Consequences

- **Saving a use case now writes an n8n workflow.** This reverses ADR 0012's "saving a use case never touches n8n". Git keeps only the platform's own n8n workflows, such as the error workflow `run_failure_reporter`, and bootstrap still loads those. `release_check.n8n.json` gives way to one n8n workflow per use case, and `schedule_tick` retires.
- **Failures are reported through our node pack.** Today `run_failure_reporter` is an Error Trigger followed by an HTTP Request node, and the allow list blocks HTTP Request, so failed runs would go unreported. It becomes Error Trigger, then Report a failure.
- **The daily check sends a test failure all the way through.** Today our API only checks that the error workflow is published and active. Instead, each day our API runs a small n8n workflow that fails on purpose, and checks that its report arrives.
- **n8n runs on Singapore time.** n8n's default time zone is America/New_York. Our image sets `GENERIC_TIMEZONE=Asia/Singapore`. The check flags an n8n workflow whose own time zone setting differs. ADR 0024's working hours are Singapore time too.
- **One editor at a time, and whoever edits can publish.** On the free edition, an n8n workflow sits in one person's space. Open in n8n moves it to the person who asks, and the Portal shows who has it. Our API reads n8n's publish history for every publish, so the warning and undo cover every change.
- **Schedules move into n8n (changes ADR 0020).** A use case's schedule is the Schedule Trigger in its n8n workflow, and the Portal changes it by publishing a new version. A run counts as the work of whoever published the version it used, and ADR 0026 adds runs started by hand or from the Portal. If this ADR is accepted, that person replaces the glossary's schedule owner. n8n does not catch up on slots it missed while it was down, so the Portal shows a missed run with "Run now".
- **Agents stay in our runtime (extends ADR 0002).** They remain reusable in NCS's agent hub, and staff see them as Agent nodes. ADR 0023's "one generic n8n workflow carries every card's runs" no longer holds.
- **"Read" and "Propose a change" can only reach the team's allowed places,** meaning the Jira projects, Confluence spaces, GitHub projects and Teams channels set in the Portal. This is `bind()`'s rule applied to steps that staff set up by hand. The Approver still sees the exact target of every change.
- **Long lists (Phase 2).** Read pages through results up to a cap, and says when it stopped at the cap. Propose a change adds one action per item, up to a limit per proposal, so an Approver never gets a request too long to read.
- **Each of n8n's other nodes is a decision.** Staff may ask for one, such as Slack or email. We either add a node to our pack, or put n8n's node on the allow list after checking what it can reach.
- **n8n's data nodes come first.** Some nodes only reshape data already in the run:
  - Filter, Switch, Edit Fields and Limit;
  - Remove Duplicates, Summarize, Aggregate and Split Out;
  - Compare Datasets, Date & Time, Loop Over Items and Stop and Error.

  They join the allow list once P7 shows that none of them can send data out. Wait stays off, because it can resume on an outside call.
- **A workflow made in n8n that uses our nodes, new or copied, is registered as a new use case.** It is marked "Made in n8n". Its requests go to any Approver on the team (ADR 0024) until an Operator names Approvers in the Portal.
- **n8n users must match our users by email,** so that a published version maps to a person.
- **NCS maintains a small TypeScript node pack beside the Python.** P6's nodes were plain JavaScript loaded from a folder. The real pack is baked into our own n8n image at the pinned version, which also works offline in DevNet (ADR 0006). CI tests the pack and the allow list against a new n8n version before the pin moves.
- **n8n's licence** (the Sustainable Use License) still needs the sponsor's confirmation, as ADR 0002 says.
