# n8n project bundle

A ready-to-run n8n setup carrying one automation: **Cert List expiry reminder** — it reads a
certificate list page in Confluence on a daily schedule, works out which TLS certificates are expiring
or expired, and delivers a Teams adaptive card (confirmed rows) plus a detailed email (rows needing a
human), including a failure notice when something breaks. This folder is the portable snapshot; the
live runtime it mirrors is `C:\n8n`.

## What is in this folder

| Path | What it is |
|---|---|
| `README.md` | this file |
| `docker-compose.yml` | runs n8n; `n8n_data` volume holds workflows, credentials **and the encryption key** |
| `scripts/parse-build.js` | **the report logic**: parses the page, builds the Teams card + email HTML. Source of truth for the parser Code node |
| `scripts/merge-ai.js` | source of truth for the `Merge AI Notes` Code node (inserts the model's table, or the "model unavailable" line) |
| `scripts/parse-test.js` | offline test of the logic above — fake table, prints the split, asserts counts. No n8n/Teams/Confluence needed |
| `scripts/set-code.mjs` | loads a `.js` file into a workflow's Code node and verifies the stored copy byte-for-byte |
| `scripts/clone-webhook.mjs` | runs the workflow over HTTP for real testing (dry, or `--send` which really posts) |
| `scripts/cert-dryrun.ps1` | older clone tool: proves both branches of `Anything to report?`, forces the error path |
| `scripts/show-run.mjs` | `node show-run.mjs <workflowId>` — which nodes ran in the newest execution and how many items each output produced (run it **before** deleting the clone) |
| `scripts/apply-gate.mjs` | (re-)applies the optional-AI gate (`Ollama Reachable?` + `Local Model Available?`) — exists because an open UI tab once autosaved an old draft over the API edits |
| `scripts/status.ps1` | "is everything alive?": container, `/healthz`, TLS-from-inside check, workflows, credentials |
| `scripts/backup.ps1` | exports workflows + credential metadata (secrets redacted) to `C:\n8n\backups` |
| `backups/` | last export of the workflows, `MANIFEST.txt`, credential metadata (no secrets) |
| `pack.ps1` / `unpack.ps1` | keep this bundle in sync with the live install, **redacting the placeholders above on every run** (`pack`) / install this bundle on a machine, dropping CA config when no pem ships (`unpack`) |

Two locations on purpose: the **live runtime is `C:\n8n`** (flat layout, that is what the scripts
expect), this folder is the **portable snapshot**. After changing anything live, run `pack.ps1` here.

**Placeholders you must fill in** (the original values are the author's, redacted on every `pack.ps1`
run — the live install keeps the real ones):

| Placeholder | Where | Replace with |
|---|---|---|
| `YOUR-TENANT.atlassian.net` | workflow export node URL + parser Code, `scripts/parse-build.js` (`PAGE_URL`) | your Confluence site |
| `PAGE_ID` | same places | your certificate-list page's content id |
| `sig=REDACTED` | workflow export, **Send Teams 1** node | your Power Automate trigger URL |
| `*.example-certs.internal` | `scripts/parse-test.js` fixtures | nothing — already fake test data |
| `EMAIL_TO` | top of `parse-build.js` | your report recipient, then `node C:\n8n\set-code.mjs` |

**Not in this bundle, by design:** the n8n API key, Confluence credentials, the Power Automate `?sig=`
signature (redacted to `sig=REDACTED` in the workflow export), and n8n's encryption key (lives only in
the `n8n_data` volume). Also **no CA certificate**: if your network intercepts TLS (corporate proxy that
re-signs certificates), export **your own** root CA to `C:\n8n\certs\gateway-ca.pem` and re-add the
`NODE_EXTRA_CA_CERTS` env line + `./certs` mount in the compose file — `unpack.ps1` strips both when no
pem ships, and without them n8n talks plain-TLS (fine outside intercepted networks, `SSL Issue` inside).

---

## Preparation

1. **Docker Desktop for Windows** (WSL2 backend) running.
2. **Node.js 18+** on the host (`node --version`) — the helper scripts are plain Node, no `npm install`.
3. **Confluence access** to your certificate-list page: e-mail + **API token** (used as Basic Auth),
   plus the **page URL / content id** — the bundle ships `YOUR-TENANT.atlassian.net/.../PAGE_ID`
   placeholders; you fill in your own page in step 3 of *Start*.
   **Optional:** if your network intercepts TLS, export your network's root CA (see above).
4. **A Power Automate flow** in your M365 account with:
   - trigger **When an HTTP request is received**, POST, JSON schema accepting `emailSubject` (string)
     and `emailHtml` (string) alongside the Teams card fields;
   - action **Post adaptive card in a chat or channel** → channel `cert-expiry-reminder`, card body from
     the incoming `content` (the flow is what actually has Teams permission — n8n never talks to Teams
     directly);
   - action **Send an email (V2)** → subject `@{triggerOutputs()?['body/emailSubject']}`, body
     `@{triggerOutputs()?['body/emailHtml']}` (HTML). Type those with the leading `@` or via the
     *Expression* tab, otherwise they arrive as literal text.
    - Copy the trigger **URL** (it contains `?sig=…` — that signature *is* the credential, treat it as a
      password).

5. **Optional — Sunny (opencode) with n8n MCP tools**, if you want an assistant to edit the workflow:
   `~\.config\opencode\opencode.jsonc` with two mcp servers (`@leonardsellem/n8n-mcp-server` — its URL
   must end in `/api/v1` — and `n8n-mcp` — its URL must be the instance root), and the API key in
   `~\.config\opencode\n8n-key` (referenced as `{file:~/.config/opencode/n8n-key}`). Restart Sunny after
   editing the config; if n8n was down at Sunny start, the n8n tools will be missing → restart again.

---

## Start

```
powershell -ExecutionPolicy Bypass -File .\unpack.ps1        # installs to C:\n8n, creates the volume, starts n8n
powershell -ExecutionPolicy Bypass -File C:\n8n\status.ps1   # expect {"status":"ok"} and "TLS ok"
```

Then, in http://localhost:5678 (first run: create the owner account):

1. **Settings → n8n API keys → Add API key**, save it to `%USERPROFILE%\.config\opencode\n8n-key`
   (one line, no quotes). `status.ps1` and every helper script read it.
2. **Credentials → Add credential → Confluence (Basic Auth)** — your e-mail + API token. Name it
   `Fetch Cert List Page - Confluence Basic Auth` so the imported workflow picks it up.
3. **Import `backups\workflows\PI5CBumIHtf59dIm__Cert_List_expiry_reminder__Teams_.json`**, open
   *Cert List expiry reminder (Teams)*, then: in **Fetch Cert List Page** replace the
   `YOUR-TENANT` / `PAGE_ID` placeholders with your own Confluence page, and in
   **Send Teams 1 - Incoming Webhook** paste your Power Automate trigger URL (the export has
   `sig=REDACTED`). Re-attach the Confluence credential to `Fetch Cert List Page` if n8n asks.
   Also set `EMAIL_TO` and `PAGE_URL` at the top of `C:\n8n\parse-build.js` to your own values, then
   push with `node C:\n8n\set-code.mjs`.
4. **Test without sending anything** — this clones the workflow, activates the clone, runs it over HTTP,
   prints what the report contains, then you delete the clone:
   ```
   node C:\n8n\clone-webhook.mjs create
   node C:\n8n\clone-webhook.mjs run <id printed above>
   node C:\n8n\clone-webhook.mjs delete <id>
   ```
   Expected: `HTTP 200 {"subject":"⚠️ … certificates need action", "confirmedCount":…,
   "aiUsed":false, "modelUnavailableNote":true, …}`.
   Add `--send` to `create` for a **real** card + email, then delete the clone. A clone left active is an
   open webhook on your laptop.
5. **Go live**: enable the `Every Day 09:00 (disabled)` trigger, then flip the workflow to **Active**.
   Timezone is `Asia/Singapore` (`GENERIC_TIMEZONE`/`TZ` in the compose file). `Manual Trigger` still
   works for ad-hoc runs from the UI.

### Stop

```
powershell -ExecutionPolicy Bypass -File C:\n8n\backup.ps1    # export workflows + manifest
powershell -ExecutionPolicy Bypass -File C:\n8n\status.ps1    # confirm no "TMP …(delete me)" clone is left
docker stop n8n
```
`restart: unless-stopped` brings n8n back when Docker Desktop starts; an explicit `docker stop` is
remembered, so it stays down until you start it again.

---

## Changing the report

Loop, no browser needed:

```
notepad C:\n8n\parse-build.js                 # thresholds, wording, tables, email recipient
node C:\n8n\parse-test.js                     # offline: prints the split, fails loudly on regressions
node C:\n8n\set-code.mjs                      # push into the parser Code node
node C:\n8n\set-code.mjs C:\n8n\merge-ai.js PI5CBumIHtf59dIm "Merge AI Notes"   # the AI/email section
node C:\n8n\clone-webhook.mjs create          # dry run to see the result end to end
```

Knobs at the top of `parse-build.js`: `WARN_DAYS` (60), `NEAR_DAYS` (30), `STALE_AFTER_DAYS` (365),
`EMAIL_TO`, `ACTION_STEPS`, `MAX_LIST_PER_ENV`, `MAX_ROWS_PER_SECTION`.

Parsing rules: a `Renewed on <date>` line wins, otherwise the last date in the cell; keyword rows
(non-expiring / stored elsewhere) are kept out of the alerting set; rows are grouped by `ENV`;
identical `env|name|validityEnd` rows are merged and reported as duplicates.

---