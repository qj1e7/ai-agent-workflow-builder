---
status: proposed
---

# Agents are cards that the model drafts and an Operator saves, and they use only tools we build

The sponsor wants CODESparks staff to automate their repetitive work without a technical person. Today the builder only offers templates we ship, so each new kind of task needs a developer. So the AI workflow builder becomes an agent builder. An Operator describes a task in plain English, the AI model drafts an agent card, and the Operator reviews, edits and saves it. A card is data, not code. It holds a name, a purpose, a plan, the tools each step may use, the inputs an Operator gives for each run, and how many Approvers each write needs. For each new task, the Room lead compares it with the team's saved cards. It brings in one saved agent, or several that work in order, or asks for a new card when none fits.

The line between the model and the platform is the tool list. Tools are code that the team builds, tests and reviews. A card can only name tools on the list, and a running agent is given only its own card's tools. Write tools change nothing. They return proposals, as ADR 0008 already requires. The platform, not the model, decides everything the approval gate depends on:
- The target of each write comes from the card's saved inputs through `bind()`, so an agent can never choose where a ticket goes.
- Who approves comes from roles, and never includes the person who started the run.
- The minimum number of Approvers comes from a rule for each tool. A write that changes someone's access needs 2 Approvers, one after the other. The model may ask for more Approvers, never fewer.

Asking people a question in Teams, such as asking managers in the access review whether someone still needs access, is a write. The Approver approves the whole list of questions once per run, not each message.

Two throwaway prototypes back this, on the branch [`prototype/agent-cards`](https://github.com/qj1e7/ai-agent-workflow-builder/tree/prototype/agent-cards/agent-runtime/prototypes/agent_cards). Both used Claude Haiku 5.5 through the AI Singapore gateway.

- **Drafting cards.** The model drafted 5 cards in 3 to 8 seconds each. It used no tool outside the list and made up no project, page or person; it asked instead. At first it added its own "ask the Approver" steps and chose who approves. Once the platform owned both, 6 of 8 drafts passed every check. The 2 that failed were the Teams questions this ADR now settles.
- **Running saved cards.** 8 of 8 runs of two saved cards did the right thing, and every proposal passed the real `bind()` and `check()`. The agents ignored instructions planted in release notes and in a Jira comment, and warned the Approver about them. Had they obeyed, the release card had no Teams tool, and `bind()` kept the ticket in the saved Jira project.

## Considered options

- **Keep templates and add more of them.** Templates are predictable and already built. But every new kind of task needs a developer, which is the maintenance load the sponsor wants to avoid after handover.
- **Let the model write code or n8n workflows for each agent.** This is the most flexible option. But generated code can do anything its runtime can, non-technical staff cannot review it, and deny-by-default would then rest on the model instead of on our code.
- **Let the model plan from scratch on every run, with no saved card.** Nobody would review a plan before it runs, and the same task could do different things each time. In the prototype, two drafts of the same task agreed on the main steps but differed in the extras. A reviewed, saved card fixes the plan.
- **n8n's AI agent nodes.** ADR 0003 already rules these out, because agents built there cannot go into NCS's agent hub.

## Consequences

- **Templates and use cases change meaning.**
  - Templates become starter cards that ship with the platform, such as the release checker. The software watchlist keeps its own page (ADR 0019).
  - A use case becomes a saved task: which card runs, with which input values, and when. Schedules work as in ADR 0020.
  - A run uses the card version saved when it started, as use case versions work today.
- **The contract changes.**
  - `TaskRequest.inputs` gains a kind that carries a card and its input values.
  - The agent runtime gets one LangGraph card runner beside the release checker.
  - `FixedRoomLead` gets a model-backed Room lead behind the same `RoomLead` interface.
  - platform-api, agent-runtime and the Portal change together.
- **Each tool on the list states four things:**
  - whether it reads or writes;
  - for a write, which input fills its target;
  - how its proposal reads to an Approver;
  - its minimum number of Approvers.

  In the prototype, `describe()` could only describe Jira tickets, so a Teams post read as "post_message on teams".
- **Cards need two more fields: when the agent runs, and what it remembers between runs,** such as the last release it saw. The platform keeps what an agent remembers as facts, as it keeps our versions in ADR 0019. In the prototype, the agent said it had no record of its last run.
- **One generic n8n workflow carries every card's runs.** The steps `run_agents`, `ask_approval` and `write_action` already do not depend on the task.
- **A tool that reaches a new external system is a new external dependency** and gets its own ADR. That covers Confluence, Teams, Entra ID and GitLab. The first slice uses only GitHub and the practice Jira.
- **The model decision stays open.** Operators connect a model as in ADR 0022. Drafting cards and the Room lead need a model, so without one the builder offers only the starter cards.
- **The prototypes' cases become golden sets in `agent-runtime/evals`.** They cover drafted cards passing the checks, Room lead choices and card runs. The AI Singapore gateway returns a stored answer when it gets the exact same request again, so repeats must be sent at the same time or carry a per-run marker. Otherwise they measure the cache, not the model.
- **The Room lead needs a clearer line between "can't do" and "new agent".** "Can't do" means outside the tool list or too risky to automate. "New agent" means in scope, with no saved card that fits. The prototype mixed them up.
- **A team's saved cards are its agent library.** It is not NCS's agent hub. Because cards are data, a card and the tools it names could later be offered to the hub. That is out of scope here.
