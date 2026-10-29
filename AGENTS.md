# Team rules for humans and AI agents

This file is the single source of team rules. Claude Code reads it through `CLAUDE.md`. Codex, Copilot and Cursor read it directly. When a tool's default behavior disagrees with this file, this file wins.

## The project

Our sponsor is CODESparks, a team in NCS. Their support staff are not technical and repeat the same Jira and Confluence work. We are building a platform where they describe a task in plain English, a Planner agent decides which specialist agents to bring in, and the work runs with human approval in Microsoft Teams before any write action.

- The AI workflow builder is the main product.
- The live activity view shows agents talking, hand-offs, and where a run failed. It is the demo layer for the professor.
- The November MVP is a public release check, for example new releases of a public GitHub repo such as LangGraph. The sponsor's real use cases (quarterly access review, patch housekeeping) are Phase 2.

Use the names in `GLOSSARY.md`. Never use the old themed names (Flint, Forge, Striker, Spark Map, Scout, Analyst, Messenger, Clerk, Fixer, Kindling, Firebreak, Ember). They confused the sponsor.

## Architecture

Four bounded contexts. Code in one context does not reach into another context's internals.

| Context | Owns | Commit scope |
|---|---|---|
| Use case builder | Blocks, templates, use case definitions | `builder` |
| Agent runtime | LangGraph agents, the Planner, tools | `runtime` |
| Orchestration | n8n workflows, Teams approvals, triggers | `orchestration` |
| Run monitoring | Event stream, live activity view, AI troubleshooter | `monitoring` |

Other commit scopes: `infra`, `ci`, `docs`.

- n8n workflows do the plumbing. Our own code goes into the builder, the Planner, the live activity view and the AI troubleshooter.
- Agents use LangChain and LangGraph, traced with LangSmith. The backend is Python.
- PostgreSQL is the relational store.
- Infrastructure as code is Terraform, kept working under OpenTofu (ADR 0013).
- Azure first (Container Apps, Static Web Apps, PostgreSQL, Azure OpenAI, Key Vault, App Insights), behind ports and adapters so it can move to AWS.
- Build and prove everything on the open internet first. DevNet (the NCS private network) comes later.
- Keep agents clean and reusable, so they can go into NCS's internal agent hub.

### Open decisions

Do not assume an answer. Ask, or propose an ADR.

- Which NoSQL store (Cosmos DB was suggested).
- Which AI model provider (decide after testing in early sprints).
- Who owns the code and the reuse rights (waiting on the sponsor).

## Product safety rules

These come from the sponsor and from our October feasibility test. Do not weaken one without an ADR.

- No write action runs without approval in Teams. The safety checker denies write actions by default.
- An Approver can never approve their own work. The access review needs two Approvers, one after the other.
- Approval tokens key off our own request ID, never n8n's execution ID.
- n8n error workflows must be active, or n8n skips them.
- Wait a short delay before a retry.
- Log every agent action with who approved it.

## How we work with AI: pstack

Everyone uses pstack, at the version locked in `.claude/settings.json`. `CONTRIBUTING.md` explains the setup for each tool.

Use the `poteto-mode` skill when a task:

- touches more than one file, or changes a signature that other files call
- involves a design or architecture choice
- is a bug whose cause is not yet known, or a performance issue

For a smaller task, such as one file with an obvious test, a question or a one-line edit, work directly and verify on the real thing. When the intent is already clear, go straight to `tdd`, `architect`, `how`, `why`, `arena` or `interrogate`.

Our additions to pstack's playbooks are in `.agents/playbooks/`. Claude Code, Codex and Copilot apply them automatically. Cursor's pstack does not read them, so Cursor users follow those steps by hand.

## Team rules

### Branches and pull requests

- `main` is always in a working state. Work on a short-lived branch and open a PR to `main`. Never push to `main` directly.
- PR titles use Conventional Commits with a scope from the Architecture table, for example `feat(runtime): add Planner routing`.
- PR descriptions use pstack's sections: Why, What changed, Scope, Tradeoffs (only when needed), Blast Radius, Verification. The PR template has them.
- Start the description with `Closes #<issue>` when the PR closes an issue.
- Verification names real commands or runs and what they showed. "It compiles" is not verification.
- Agents never approve PRs. A PR merges (squash) only when a human asks for the merge.

### Decisions and names

- A big decision gets an ADR in `docs/adr/` before its code lands: a new service, data store, cloud service or external dependency, or any change to the approval gate or the safety checker. Use the `domain-modeling` skill.
- Add new domain terms to `GLOSSARY.md`.
- In the app, "workflow" means the task an Operator sets up (a use case in the code). In code and docs, write "n8n workflow" or "Jira workflow" for those, never "workflow" alone.

### Evidence

- Save rubric evidence (pipeline runs, SAST and DAST reports, load test results) in `docs/evidence/`, or link it from the PR.

### Secrets

- Never commit secrets, keys or tokens. Use Azure Key Vault or GitHub Actions secrets. `.env` files stay out of git.

### Writing for the sponsor or the professor

- Use plain language and short sentences, with no jargon and no em dashes. Run `unslop` on anything that leaves the team.

## What always needs a human

- Merging to `main`, deploying, and changing cloud resources or repository settings.
- Any message to the sponsor or the professor.
- Deleting data, or force-pushing a shared branch.
