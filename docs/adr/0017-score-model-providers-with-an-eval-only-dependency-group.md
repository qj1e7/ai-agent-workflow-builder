---
status: proposed
---

# Score model providers with an eval-only dependency group

The AI model provider is still an open decision. To choose one on evidence, we score every candidate on the same golden set through LangChain's chat model interface. That needs one LangChain package per provider: `langchain-ollama` 1.1.0, `langchain-openai` 1.6.7 (for Azure OpenAI), `langchain-anthropic` 1.7.5 and `langchain-google-genai` 4.4.0. Each was at least two weeks old when we added it. We put them in an `evals` dependency group in `agent-runtime/pyproject.toml` and build them only into the `evals` stage of the agent runtime's Dockerfile. The runtime image does not get them. Once the team picks a provider, the PR that wires it in moves that one package into the runtime dependencies, with its own ADR.

## Considered options

- **A separate uv project for the evals.** That would give the evals their own lock file. But a second project is one more thing to keep in step with the runtime's LangChain pins, and the evals call the runtime's own summary prompt.
- **Install every provider in the runtime.** This would ship packages we will not use, and their dependencies, in the image that will run in DevNet.

## Consequences

- `google-genai` needs `tenacity` below 9.2, and the runtime uses 9.2.1. To keep the runtime unchanged, the `evals` group conflicts with the `dev` group (`[tool.uv] conflicts`). uv then resolves them apart, and the runtime and `dev` resolutions stay exactly as they were. The cost is that `evals` and `dev` cannot share one environment. Use `uv run --no-dev --group evals`, or `scripts/evals.sh`, which runs in Docker.
- Five transitive packages had releases newer than 2026-10-08. `exclude-newer-package` holds them back, so every package in the eval environment is at least two weeks old. Remove those dates when you upgrade the providers on purpose.
- The evals read keys only from environment variables. A provider with no key is reported as "not run".
- CI uploads `results.json` as a run artifact, and GitHub does not mask secrets inside artifacts. So the evals remove the keys, the Azure endpoint and the Ollama address from any error before they write it.
- The evals never run in the normal test suite. Only the scoring rules have unit tests there.
