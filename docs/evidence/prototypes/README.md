# Prototype evidence for the walking skeleton design

P1 to P4 back every claim marked "verified" in the [walking skeleton design](../../design/walking-skeleton.md). Each one answered a question about n8n or LangGraph before we designed around it. P5 backs [ADR 0013](../../adr/0013-write-infrastructure-in-terraform.md), the choice of infrastructure-as-code tool. P6 backs [ADR 0026](../../adr/0026-every-write-is-checked-when-it-is-made-so-n8n-may-hold-the-wait.md) and [ADR 0027](../../adr/0027-staff-maintain-each-workflow-in-n8n-and-the-portal-keeps-every-published-version.md), letting staff maintain workflows in n8n. P1 to P5 ran once each on 20 Oct 2026, and P6 on 28 Oct, against mock services or with no cloud account at all. None of them is product code, and none of them should be built on.

Start with each folder's `findings.md`. The other files are the scripts and raw output that its findings cite.

| Prototype | Question | Ran on |
|---|---|---|
| [P1](p1-n8n-approval-pause/findings.md) | Can n8n's Wait node hold an approval, and what reaches its error workflow? | n8n 2.42.6 as a local Node process, SQLite |
| [P2](p2-langgraph-events/findings.md) | What events does a LangGraph agent emit, and can we send our own clean events instead? | Python 3.14, LangGraph 1.2.16, a fake chat model |
| [P3](p3-n8n-docker-compose/findings.md) | Does n8n run in Docker Compose on PostgreSQL, and does a paused run survive a restart? | n8n 2.42.6 and PostgreSQL 17 in Docker |
| [P4](p4-n8n-two-legs/findings.md) | Does the two-leg design in [ADR 0007](../../adr/0007-n8n-carries-runs-our-api-decides.md) work on n8n? | n8n 2.42.6 and PostgreSQL 17 in Docker |
| [P5](p5-iac-terraform-vs-bicep/findings.md) | Can Terraform and Bicep both express our Azure setup, and how do they compare? | Terraform 1.16.5, OpenTofu 1.12.7 and Bicep 0.48.1 in Docker, offline |
| [P6](p6-n8n-node-pack/findings.md) | On n8n's free Community edition, does our node pack load, can it pause a run, can editing be kept apart from publishing, and who published? | n8n 2.42.6 in Docker, no licence key |

## What each one showed

**P1.**
- n8n's resume URL works like a password. Anyone who has it can resume the run.
- n8n does not check who approved.
- When parallel resumes arrive, one gets a 200 and the rest get 500s.
- The error workflow's payload does not carry our run ID.
- `n8n import:workflow` cannot load a workflow as active, so workflows load through the REST API.

**P2.** LangGraph's `astream_events` gave 31 events for a three-step graph and exposed internals. `stream_mode="custom"` let the agent send only the events we define.

**P3.** n8n 2.42.6 warns on PostgreSQL 16, so we use 17. A paused run survived `docker compose restart`, and also `down` then `up` with the volumes kept. `N8N_ENCRYPTION_KEY` must never change.

**P4.**
- Two Webhook triggers in one workflow start independent executions.
- The 202 reply can carry n8n's execution ID.
- The step key credential can be created through the API.
- n8n retried a 503 about 2 seconds apart.
- n8n retried a 409 three times, then sent the error workflow a generic message.
- Updating an active workflow with `PUT` switched to the new version in under a second with no 404s. Deactivating and reactivating left the webhooks answering 404 for about 0.6 seconds.

**P5.**
- Both tools expressed every resource in the design's list with no workaround. That includes the Container Apps Job and a Key Vault secret reference through a managed identity.
- Terraform passed `validate` and `fmt -check`. The same files, unchanged, passed `validate` under OpenTofu. Bicep passed build and lint with no warnings.
- Terraform took 233 lines and Bicep 259.
- Checkov scanned both. Semgrep's Terraform rules scanned the Terraform files and found no Bicep files to scan.
- Neither tool could plan or preview without an Azure login. Nothing touched a cloud account.

**P6.**
- n8n loaded our three nodes from a folder, and the Agent node's list came from our API.
- Our "Ask for a yes" node paused a run, and our API woke it. A run woken with only the resume URL, or with "Ask for a yes" deleted, reached the write, and the write refused because our records had no yes.
- The free edition cannot share an n8n workflow or make anyone an admin. The platform can move an n8n workflow into one staff member's space. That person can then edit it and also publish it, so editing can't be kept apart from publishing.
- n8n records who published each version.
- Ordinary staff can add their own keys, including a Jira key.
- With `NODES_INCLUDE` limited to our nodes and simple flow nodes, an HTTP Request or Jira node could not be published, run by hand or run from an old published version. Our nodes still worked.

## What was removed before commit

- **Local n8n API keys and login cookies.** These are the files `apikey`, `apikey_resp.json` and `cj`. Two workflow files had a key inside, which now reads `<redacted: local n8n API key>`.
- **Resume URL signatures.** They now read `signature=<redacted-N>`. The same number means the same URL, so the restart tests still show which URL was reused. `signature=deadbeef` is the deliberately wrong signature from the rejection test, so it stays.
- **The test step key.** It now reads `<redacted-step-key>`.
- **The database password and n8n encryption key.** In the compose files and findings they are now `${PROTO_DB_PASSWORD}` and `${PROTO_ENCRYPTION_KEY}`.
- **P6's local logins, API key and n8n encryption key** (`p6-secrets.json`, `p6-encryption-key`). They were never committed and were deleted after the run.
- **Installed packages, n8n's local data folder, process ID files and `package-lock.json`.** Local machine paths in the logs now read `./` or `<scratch>`.

Every key above worked only on local containers or processes that were deleted after each test.

## Running one again

Each `findings.md` lists the setup steps that worked. For P3 or P4, set `PROTO_DB_PASSWORD` and `PROTO_ENCRYPTION_KEY` in your shell before `docker compose up -d`. The scripts read the n8n API key from a file named `apikey` beside them. The `.gitignore` in this folder keeps that file, the cookie jar and the installed packages out of git.
