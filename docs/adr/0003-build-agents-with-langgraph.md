---
status: proposed
---

# Build agents with LangGraph and trace them with LangSmith

Agents are the part of the platform that NCS may reuse. The sponsor wants them clean enough to go into NCS's internal agent hub. We build them in Python with LangChain and LangGraph, and trace them with LangSmith. LangGraph keeps an agent's state in a graph with checkpoints, so an agent can pause, resume and stream its steps. The October sandbox showed pause, resume and event streaming working for the AI troubleshooter.

## Considered options

- **n8n's built-in AI agent nodes.** They are quick to start with, but the agents live inside n8n workflows and cannot be reused elsewhere.
- **Other agent frameworks, such as CrewAI or AutoGen.** We did not test them. LangGraph was already proven in the sandbox, and LangSmith traces it with no extra code.

## Consequences

- An agent must not depend on n8n or on our API's internals, so that it can move to the agent hub unchanged.
- The AI model provider stays open. Agents call models through LangChain, so a later ADR can pick the provider after testing.
- LangSmith is a hosted service, so traces leave our environment. Before the move to DevNet, check whether NCS allows this.
