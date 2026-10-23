---
status: proposed
---

# n8n workflow files live in git, and a bootstrap job lints and loads them

The sponsor wants staff to maintain the platform without code, and n8n's editor invites people to change workflows in place. But our October sandbox showed that n8n silently skips an error workflow that is not active, and that an edit can remove a safety step. So run workflows are JSON files in git, one per template. A one-shot bootstrap job runs the workflow lint, loads the error workflow first, loads the run workflows through n8n's REST API, reads them back, and lints them again. It exits with an error if any check fails. In Docker Compose, platform-api then does not start. On Azure, the deploy stops before traffic moves to the new version, and platform-api's health check reports not ready. [Prototype P4](../evidence/prototypes/p4-n8n-two-legs/findings.md) showed that updating an active workflow in place with `PUT` switches to the new version in under a second without the webhooks failing. Deactivating and reactivating left them answering 404 for a moment, so bootstrap never does that.

## Considered options

- **The n8n database is the source of truth, with an export to git.** Staff could edit in n8n's editor, but a bad edit would run before anyone reviewed it, and the lint would only catch it on the next export.
- **The CLI command `n8n import:workflow`.** It refuses to set workflows active in n8n's regular mode, so it cannot load a workflow that runs.

## Consequences

- Edits made in n8n's editor are overwritten by the next bootstrap. A workflow change is a PR that the lint checks.
- One workflow serves every use case of a template, so saving a use case never touches n8n.
- Bootstrap uses n8n's owner setup and API key endpoints, which are internal to n8n, so the n8n version stays pinned.
- Whether the sponsor accepts that the editor is read-only in practice is an open question for him.
