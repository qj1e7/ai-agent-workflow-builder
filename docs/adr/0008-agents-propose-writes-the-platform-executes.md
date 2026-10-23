---
status: proposed
---

# Agents propose write actions, and only the platform's write gateway executes them

This changes how the approval gate and the safety checker work, so `AGENTS.md` requires an ADR. Agents return the writes they want as data and hold no write tools or write credentials. Our API binds each proposed write to a connector and a target from the use case, so the agent never picks the target system. The bound actions form a proposal with a digest, and the Approver's decision must quote that digest. The safety checker is a pure function that denies by default. It is the only code that can create the `AuthorizedWrite` value the write gateway needs, and the write gateway is the only code that holds connectors.

## Considered options

- **Agents write through tools, guarded by a safety call to our API.** Agents could act directly, but they would depend on our API, so they could not go into NCS's agent hub unchanged. The safety rule would also live in two places.
- **A signed approval receipt that the agent runtime checks before it writes.** Agents that need write tools would work, but key handling and the safety rule would spread across two deployables.

## Consequences

- An agent can go into the agent hub with no credentials and no knowledge of runs, n8n or Jira.
- An Approver approves exactly the actions that will run. If the stored actions change, the digest no longer matches, and the write is denied.
- The safety checker covers every write. Reads are safe because agents have no way to write, which is narrower than the glossary's "every agent action". The sponsor should confirm that reading.
- Each write is recorded before and after the connector call, with an idempotency key. A retry while a call is still in flight waits for that call instead of calling again, so a slow Jira cannot produce two tickets. If the run fails while a write is in flight, the write still records its result, and the Operator's retry returns that result without writing again.
