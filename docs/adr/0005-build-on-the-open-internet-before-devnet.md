---
status: proposed
---

# Build and prove everything on the open internet before moving to DevNet

CODESparks runs inside DevNet, NCS's private network. Access to DevNet depends on the sponsor. We build, test and demo on the open internet first. We use public data, such as a public GitHub repo, and mock Jira, Confluence and Teams services where we lack real access. We adapt the platform to DevNet after it works end to end.

## Considered options

- **Build inside DevNet from the start.** It removes the later move, but every task would wait on DevNet accounts, and evidence for the school would be harder to share.

## Consequences

- No NCS data enters our environments before the move. Demos use public or synthetic data, which the school allows.
- Every external system gets a mock adapter and a real adapter.
- The DevNet move is planned work. Outbound access from DevNet to the AI model, LangSmith and GitHub needs checking.
