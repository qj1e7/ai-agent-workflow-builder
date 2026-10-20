---
extends: feature
when: Building new or changed behavior in this repository.
---

# Team feature rules

Our additions to pstack's Feature playbook. `AGENTS.md` gives the reasons.

- **After** "`how` over the affected subsystem." Name the bounded context that owns the change (`AGENTS.md`, Architecture). When the change crosses contexts, go through the other context's public interface, not its internals.
- **After** "`architect` for parallel design exploration." When the design makes a big decision (a new service, data store, cloud service or external dependency, or any change to the approval gate or the safety checker), write an ADR in `docs/adr/` with the `domain-modeling` skill before you implement. Add new domain terms to `GLOSSARY.md`.
- **In** "Verify on the matching surface." When the change adds or touches a write action, also show that the run stops at the approval gate, and that the safety checker denies the action without approval.
