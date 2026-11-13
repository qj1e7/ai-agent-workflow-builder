---
extends: feature
when: Building new or changed behavior in this repository.
---

# Team feature rules

Our additions to pstack's Feature playbook. `AGENTS.md` gives the reasons.

- **After** "`how` over the affected subsystem." Name the bounded context that owns the change (`AGENTS.md`, Architecture). When the change crosses contexts, go through the other context's public interface, not its internals.
- **After** "`architect` for parallel design exploration." When the design makes a big decision (a new service, data store, cloud service or external dependency, or any change to the approval gate or the safety checker), write an ADR in `docs/adr/` with the `domain-modeling` skill before you implement. Add new domain terms to `GLOSSARY.md`.
- **After** "`architect` for parallel design exploration." When the change adds or changes something a person sees, read `docs/design/ai-native-principles.md` and walk its checklist. Design a new screen or component in the chat-first sketch, `docs/design/chat-first/prototype.html`, first.
- **In** "Verify on the matching surface." When the change adds or touches a write action, also show that the run stops at the approval gate, and that the safety checker denies the action without approval.
- **In** "Verify on the matching surface." When the change adds or changes something a person sees, check it against each principle in `docs/design/ai-native-principles.md` that applies. Run `portal/e2e/live/design-rules.spec.ts` once it exists, and say in the PR's Verification which principles you checked and how.
