---
extends: shipping
when: Landing or merging pull requests in this repository.
---

# Team shipping rules

Our addition to pstack's Shipping playbook. `AGENTS.md` gives the reasons.

- **Before** "Land only the contiguous verified run rooted at the bottom." Check each PR with `gh pr view <pr> --json author,reviews` for an `APPROVED` review from a teammate who is not the author. A PR without one does not land, whatever its verdict.
