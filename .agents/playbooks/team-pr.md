---
extends: opening-a-pr
when: Opening or updating a pull request in this repository.
---

# Team PR rules

Our additions to pstack's Opening a PR playbook. `AGENTS.md` gives the reasons.

- **Before** "Run `/deslop` over the diff before commit" Check the diff for secrets, keys, tokens and `.env` files. If you find one, stop and tell the user.
- **After** "Scope is the area, such as `pstack` or `poteto-mode`." In this repo the scope is one of `builder`, `runtime`, `orchestration`, `monitoring`, `infra`, `ci` or `docs`.
- **After** "Use `##` headings, not bold lead-ins, in this order, and drop a section with nothing to say:" Start the body with `Closes #<issue>` when the PR closes an issue.
- **After** "Open every PR ready, never as a draft." Never approve a PR yourself. A PR merges only when the user asks for the merge.
