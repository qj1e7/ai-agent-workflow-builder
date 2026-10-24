---
status: proposed
---

# Operators connect an AI model in the Portal, and the platform detects its models

The sponsor wants staff to fix routine problems without a technical person. With ADR 0021, changing the model or replacing an expired key means editing `deploy/.env` and restarting containers, or changing Key Vault on Azure. So the Portal gets a Settings page behind a gear icon, and the AI model is its first section. An Operator picks a known provider or types another address, pastes the key and presses Connect. The agent runtime then works out how to talk to that address and which models the key can use. It reads the provider's model list (`GET /v1/models`, which most providers and gateways answer) and tries the two call styles we support until one answers. The Operator picks a model from the list and presses Test and save. The setting is saved only after one real answer that arrives within the summary's 10 seconds. The key is write-only: after saving, the Portal shows only its last two characters.

We support two call styles, through two LangChain packages. `langchain-anthropic` is already in the runtime (ADR 0021), and `langchain-openai` 1.6.7 moves in from the `evals` group. Together they reach OpenAI, Anthropic, Azure OpenAI's v1 API, Google Gemini's OpenAI-compatible endpoint, Ollama, vLLM, and gateways such as AI Singapore's and LiteLLM. A provider that speaks neither style needs its own package and its own ADR.

The model name is free, but where prompts go is not. Known providers are a list in git, reviewed in PRs, and need no further step. Any other address needs an Approver to confirm it once before runs use it, and until then runs keep the model they had. The person who entered the address cannot confirm it. Whatever the address, the agent runtime refuses plain `http` and refuses addresses that resolve to loopback, private or link-local ranges, unless the deployment lists them. DevNet's own model will sit on such a listed private address. Every connection the runtime makes to a model address goes through a guard that checks the IP it is about to use and connects to exactly that IP, keeping the real name for TLS. So neither a redirect nor a name that answers differently after the first check can reach an inside address.

platform-api keeps the setting in PostgreSQL, with the key encrypted using Fernet from the `cryptography` package under `SETTINGS_ENCRYPTION_KEY`. `make-env.sh` makes that key locally, and Key Vault holds it on Azure. When a run reaches its agents, platform-api adds the model, key included, to the task it sends. The agent runtime uses it for that task only and never stores it. The agent runtime is the only part of the platform that calls model providers, for Connect and Test as well as for runs. With no model saved, it falls back to its own settings (ADR 0021), and then to the template.

## Considered options

- **The Portal writes `deploy/.env`.** The containers read that file only when they start, so every change would need a restart. A web app that writes server files and restarts containers is a serious hole, and Azure has no such file.
- **A fixed list of approved providers and models** (the first draft of this ADR). Safe, but every new model would need a PR, which is the opposite of what Operators need.
- **Any address, with no confirmation.** The most flexible option, but one Operator could send every prompt, and later Phase 2's access-review data, to their own server. One confirmation per new address costs little.
- **Tell the provider from the key's format.** Gateways issue keys that look like OpenAI keys but serve other models, and the AI Singapore key is one of them. So the key alone cannot tell, and asking the address can.
- **Each key in Key Vault, written by platform-api.** It works only on Azure, platform-api would need write access to Key Vault, and local runs would need a stand-in.
- **The agent runtime fetches the setting from platform-api.** The task would stay free of the key, but the runtime would depend on our platform, against ADR 0008's aim that agents go into NCS's agent hub unchanged. With the model in the task, whoever calls an agent supplies its model.

## Consequences

- Operators change settings. Approvers see them and confirm new addresses, so the platform keeps its two roles.
- Every change is recorded with who made it, when, the address and the model. The record never holds the key, only its last two characters. Turning the model off deletes the saved key.
- The task contract in `contracts/` gains an optional model block: call style, address, model and key. The agent runtime leaves it out of the fingerprint that spots a reused task ID, or a key replaced between two tries of one task would look like a different task.
- The task request now carries a key, so it must never be logged or stored. Today platform-api builds it just before the call and keeps no copy, and that has to stay true.
- `langchain-openai` brings `openai` 3.26.0 and `tiktoken` 0.14.0 into the runtime image. `tiktoken` downloads files on first use, but only to count tokens, which the runtime does not do.
- Model lists can be long and can include models that cannot chat, such as embedding models. The Portal filters the list and suggests fast models, and the Test call catches a model that cannot answer or is too slow.
- `cryptography` 50.0.2 is already installed through `pyjwt[crypto]`. platform-api names it as a direct dependency, so nothing new enters platform-api's image.
- `SETTINGS_ENCRYPTION_KEY` joins the other generated secrets. If it is lost, an Operator pastes the model key again, and nothing else is lost.
- Because only the agent runtime calls model providers, DevNet's firewall needs outbound rules for one component.
- `langchain-anthropic` builds its own HTTP client and has no option to pass one in, so the runtime swaps the guarded client in through a small subclass. An upgrade of that package must keep the guard's tests passing.
- Because the guard connects to the IP it checked, an outbound proxy set through environment variables is not used. If DevNet requires one, the guard has to learn to go through it.
- Settings belong to orchestration, which already owns the connections to outside systems through the write gateway's connectors. GitHub, Jira, Teams and the schedule can follow the same pattern later.
