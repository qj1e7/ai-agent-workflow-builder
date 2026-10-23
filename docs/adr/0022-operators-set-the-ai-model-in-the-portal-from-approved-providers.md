---
status: proposed
---

# Operators set the AI model in the Portal, from approved providers only

The sponsor wants staff to fix routine problems without a technical person. With ADR 0021, changing the model or replacing an expired key means editing `deploy/.env` and restarting containers, or changing Key Vault on Azure. So the Portal gets a Settings page behind a gear icon, and the AI model is its first section. An Operator picks a provider and a model, pastes the key and presses Test and save. platform-api asks the agent runtime for one real answer with those settings and saves them only when it gets one. The key is write-only: after saving, the Portal shows only its last two characters.

Operators choose from approved providers and never type an address. Each approved provider is an entry in git with its name, its LangChain provider, its address and its models, and adding one is a PR. So nobody can send the platform's prompts, and later Phase 2's access-review data, to an address typed into a form, or point the agent runtime at a service inside our own network.

platform-api keeps the setting in PostgreSQL, with the key encrypted using Fernet from the `cryptography` package under `SETTINGS_ENCRYPTION_KEY`. `make-env.sh` makes that key locally, and Key Vault holds it on Azure. When a run reaches its agents, platform-api adds the model, key included, to the task it sends. The agent runtime uses it for that task only and never stores it. With no model saved, the runtime falls back to its own settings (ADR 0021), and then to the template.

## Considered options

- **The Portal writes `deploy/.env`.** The containers read that file only when they start, so every change would need a restart. A web app that writes server files and restarts containers is a serious hole, and Azure has no such file.
- **Any address and key, typed in.** The most flexible option, but anyone with Operator access could send every prompt to their own server, or at a service inside our network.
- **An Approver confirms every model change.** Safer, and it matches the approval gate. But the address cannot change from the Portal, so the worst a change can do is stop the model summaries (runs fall back to the template) or bill a different key, and the change log records who did it. The sponsor can still ask for this.
- **Each key in Key Vault, written by platform-api.** It works only on Azure, platform-api would need write access to Key Vault, and local runs would need a stand-in.
- **The agent runtime fetches the setting from platform-api.** The task would stay free of the key, but the runtime would depend on our platform, against ADR 0008's aim that agents go into NCS's agent hub unchanged. With the model in the task, whoever calls an agent supplies its model.

## Consequences

- Only Operators change settings. Approvers see them read-only, so the platform keeps its two roles.
- Every change is recorded with who made it, when, and what changed. The record never holds the key, only its last two characters. Turning the model off deletes the saved key.
- The task contract in `contracts/` gains an optional model block. The agent runtime leaves it out of the fingerprint that spots a reused task ID, or a key replaced between two tries of one task would look like a different task.
- The task request now carries a key, so it must never be logged or stored. Today platform-api builds it just before the call and keeps no copy, and that has to stay true.
- `cryptography` 50.0.2 is already installed through `pyjwt[crypto]`. platform-api names it as a direct dependency, so nothing new enters the image.
- `SETTINGS_ENCRYPTION_KEY` joins the other generated secrets. If it is lost, an Operator pastes the model key again, and nothing else is lost.
- Settings belong to orchestration, which already owns the connections to outside systems through the write gateway's connectors. GitHub, Jira, Teams and the schedule can follow the same pattern later.
- The approved list is where the sponsor's answer on DevNet lands: a DevNet build lists only the providers allowed there.
