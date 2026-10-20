---
status: accepted
---

# Use pstack as the team's AI workflow, locked to one version

Five of us write code with AI agents, and we want one way of working: plan first, verify on the real thing, and ship small PRs that a teammate reviews. We use pstack (Lauren Tan's agent skills, through the pstack-claude port), locked to one release in `.claude/settings.json` and upgraded once per sprint in a PR that CI checks. `AGENTS.md` holds the team rules so that every tool reads them, and `.agents/playbooks/` adds our steps to pstack's own playbooks.

## Considered options

- **superpowers alongside pstack.** Both are full workflows that start every session with their own instructions, so the agent followed two competing processes. This repo turns superpowers off.
- **Always the latest pstack.** No upkeep, but pstack releases almost daily, so agent behavior could change mid-sprint for everyone with no review.
- **Lauren's original pstack in Cursor only.** Its version is set by Cursor and it does not read project playbooks. Cursor users are still supported, but follow the playbook steps by hand.

## Consequences

- One person upgrades pstack each sprint, following `CONTRIBUTING.md`.
- Claude Code can lock a plugin only to a tag, and a tag can be moved. CI records the commit we reviewed and checks every day that the tag still points at it. Forking pstack-claude would remove this risk, at the cost of syncing the fork ourselves.
- Copilot cannot lock a plugin version, so a Copilot user can run a newer pstack than the team.
- pstack's review skills run several models in parallel. Each person runs `setup-pstack` to pick models that fit their own plan.
