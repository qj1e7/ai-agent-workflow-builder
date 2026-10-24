---
status: proposed
---

# The agent runtime reaches its model through a gateway named in its own settings

The team lead has a key for AI Singapore's LLM gateway, which answers Anthropic's Messages API, and wants the app to use it for development and the November demo. ADR 0017 says the PR that wires a provider in moves that one package into the runtime, with its own ADR. So `langchain-anthropic` 1.7.5 moves from the `evals` group into the runtime's dependencies. The gateway's address and key come from two settings of the runtime's own, `AGENT_MODEL_BASE_URL` and `AGENT_MODEL_API_KEY`, and `AGENT_SUMMARY_MODEL` names the model, for example `anthropic:<model>`. The final provider choice still follows the bake-off and the sponsor's answer on DevNet (decision memo, section 3).

## Considered options

- **The provider's own variables, `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL`.** No code would change, because the LangChain package reads them itself. But Claude Code reads the same family of names. If they reached a developer's shell, Claude Code would switch from that person's plan to the gateway and its billing. The names would also change with every provider.
- **Keep the package eval-only and call the gateway over plain HTTP.** One dependency fewer, but we would rebuild what LangChain already does, and the bake-off would score a different client from the one the product uses.

## Consequences

- The runtime image gains `langchain-anthropic` 1.7.5 and `anthropic` 1.12.0, still held back by `exclude-newer-package`. The `evals` group keeps the other three providers.
- The model stays optional. With `AGENT_SUMMARY_MODEL` empty, summaries come from the template. A wrong model name, key or address also falls back to the template, after a warning in the agent-runtime log ("summary model failed"). Check that log after setting the model.
- LangChain sends the key in the `x-api-key` header. The gateway's Claude Code setup uses `Authorization: Bearer`. The first live call shows whether the gateway accepts both.
- The key belongs to the team lead's AIxTech subscription and works only while that subscription is active. Before handover, CODESparks needs its own key or provider.
- Prompts go to AI Singapore's gateway and on to the model behind it. The MVP sends only public release tags. Phase 2 data needs the sponsor's written agreement first.
- On Azure the key belongs in Key Vault, as `GITHUB_TOKEN` does. The Terraform for that is a separate change.
