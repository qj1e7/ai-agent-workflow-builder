# AI agent builder: one-page design

This page explains how the AI workflow builder becomes an agent builder, and what we build first. The decision behind it is [ADR 0023](../adr/0023-agents-are-cards-the-model-drafts-and-use-only-tools-we-build.md). The prototypes that tested it are on the branch [`prototype/agent-cards`](https://github.com/qj1e7/ai-agent-workflow-builder/tree/prototype/agent-cards/agent-runtime/prototypes/agent_cards).

## What the Operator does

1. They type a task, for example "Every Friday, summarise the Jira tickets our team closed and post it in our Teams channel".
2. The Room lead checks the team's agent library.
   - **A saved agent fits:** it fills in the inputs it can find in the task, and asks for the rest.
   - **No saved agent fits:** the model drafts a new agent card.
   - **The task is outside our tools or too risky:** it says so and why.
3. The Operator reads the draft card in plain English: its purpose, its plan, the tools on each step, and which steps need approval. They edit the card and save it. Nothing runs before then.
4. The run works as it does today. Agents read, plan and propose writes. An Approver approves in Teams, then the platform writes.
5. The next similar task finds the saved card by its purpose.

## Goals

- Staff can automate a new kind of Jira, Confluence, GitHub, GitLab, Entra ID or Teams task without a developer.
- The approval gate and the safety checker are as strong as today, whatever the model writes.
- A saved card does the same thing on every run, and a person reviews a card before it first runs.
- Agents stay clean enough to go into NCS's agent hub later.

## Non-goals

- Agents that use tools we have not built. A missing tool is a request to the team, not something the model works around.
- Generated code or generated n8n workflows.
- Learning by itself. The Room lead finds a card by its purpose; it does not change cards on its own.
- Real Confluence, Teams, Entra ID and GitLab connectors before the first presentation. Each one needs its own ADR.

## What changes in each context

| Context | Change |
|---|---|
| Use case builder | Agent cards and their versions. The Builder page drafts, edits and saves cards. Templates become starter cards. A use case is a card, its input values and a schedule. |
| Agent runtime | A model-backed Room lead behind the existing `RoomLead` interface. One LangGraph card runner that is given only the card's tools. Tools with typed inputs. |
| Orchestration | The tool list: for each write tool, its target input, its minimum Approvers and its approval text. `bind()` and `check()` stay as they are. One generic n8n workflow. Facts an agent remembers between runs. |
| Run monitoring | The live activity view draws a run from the card's plan instead of a template's blocks. |

## First slice, for the presentation (27 Nov to 5 Dec)

- Type a task, get a draft card, edit it and save it.
- The Room lead picks between 2 or 3 saved cards, or drafts a new one.
- A saved card runs with GitHub reads and the practice Jira, and an Approver approves in the Portal.
- The live activity view shows the Room lead bringing agents in.
- The software watchlist stays as the reliable backup demo.

## Risks

| Risk | What we do |
|---|---|
| A drafted card is wrong or unsafe. | The platform checks every draft before it can be saved: only real tools, every write approved, and access changes need 2 Approvers. A person reviews every card. |
| Text in the data tries to steer an agent. | An agent only has its card's tools. `bind()` fixes every target, and an Approver sees the full text. In the prototype, both planted instructions were ignored and flagged. |
| The same task gives a different card each time. | Variation only matters at the draft. Runs use the saved card. |
| Claude Haiku is too weak to plan. | Drafting and running both worked in the prototypes. Golden sets in `agent-runtime/evals` watch for this, and the model can change in Settings. |
| Too much for 5 weeks. | The first slice uses tools we already have: GitHub and the practice Jira. |
| The sponsor finds open-ended agents too risky. | Every write still needs an Approver, and nothing runs before a person saves its card. We show the sponsor a draft card and its approval request before building further. |

## Open questions

- Should a card need an Approver's sign-off before its first run, as well as the Operator's save?
- Who in CODESparks may add a tool to the list?
- Should the sponsor see a demo of a drafted card before we build the first slice?
