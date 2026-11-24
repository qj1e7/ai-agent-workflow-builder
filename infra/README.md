# Azure infrastructure

This folder holds the Terraform code for the walking skeleton on Azure (ADR 0004, ADR 0013). It is written so it also runs under OpenTofu. Nothing here has been applied yet. Every check so far ran offline, without an Azure account.

> **The first deploy needs Entra ID sign-in and the first people.** platform-api runs with `AUTH_MODE=oidc` on Azure, so the deploy needs two Entra ID app registrations. [docs/auth/entra-setup.md](../docs/auth/entra-setup.md) has the steps, and the values it produces go into the variables below. Who is an Operator or an Approver lives in the platform's People list, and the first deploy names the first people with `FIRST_OPERATOR` and `FIRST_APPROVERS` (ADR 0030). The `AUTH_MODE=dev` guard stays as it is: dev sign-in only runs on localhost, so it can never reach a shared deployment. [docs/evidence/deploy/README.md](../docs/evidence/deploy/README.md) is the runbook for the rebuilt app's deploy.

## What gets created

One environment, `dev`, in the resource group `rg-wab-dev`. The region is Southeast Asia (`southeastasia`) unless `AZURE_LOCATION` says otherwise. The first deploy, on 31 Oct 2026, used East Asia (`eastasia`), because the Azure for Students policy does not allow Southeast Asia, and Korea Central (`koreacentral`) for Cosmos DB alone ([the first deploy](../docs/evidence/deploy/first-deploy.md)). Names follow `<type>-wab-<environment>`, plus a random 5-character suffix where Azure needs a globally unique name. Every resource carries the tags `project`, `environment` and `managed-by`.

| Resource | Name | Size and notes |
|---|---|---|
| Resource group | `rg-wab-dev` | The bootstrap script creates it, and Terraform only reads it. The deploy identity's rights end at this group |
| Log Analytics workspace | `log-wab-dev` | Pay as you go, 30 days, capped at 1 GB a day |
| Application Insights | `appi-wab-dev` | Uses the workspace. No app sends telemetry to it yet |
| Key Vault | `kv-wab-dev-<suffix>` | RBAC mode, purge protection, 7 days of soft delete |
| Container registry | `crwabdev<suffix>` | Basic SKU, admin user off |
| PostgreSQL Flexible Server | `psql-wab-dev-<suffix>` | Version 17, Burstable `B_Standard_B1ms`, 32 GB, TLS required, databases `platform` and `n8n` |
| Cosmos DB for NoSQL account | `cosmos-wab-dev-<suffix>` | Free tier, capped at its 1000 RU/s, one region, Strong consistency. Database `activity`, container `run_events` at 1000 RU/s, partitioned by `/runId` (ADR 0031). The account key cannot create or change databases and containers |
| Container Apps environment | `cae-wab-dev` | Workload profiles mode with the Consumption profile, logs to Log Analytics |
| Container App | `platform-api` | External ingress on 8000, 0.25 vCPU, 1 replica always on for the `tick` loop |
| Container App | `agent-runtime` | Internal ingress on 8100, 0.25 vCPU, scales to zero |
| Container App | `n8n` | Internal ingress on 5678, or external when `N8N_EDITOR_EXTERNAL` is `true` ([n8n's editor](#n8ns-editor)), 0.5 vCPU, exactly 1 replica. Port 5679, its task runner's broker, opens only inside the environment ([n8n's task runner](#n8ns-task-runner)) |
| Container App | `n8n-runners` | n8n's task runner, `n8nio/runners` at n8n's version. No ingress, 0.25 vCPU, exactly 1 replica. It holds none of n8n's secrets, and no container in it gets its identity ([n8n's task runner](#n8ns-task-runner)) |
| Container App | `portal` | External ingress on 8080, 0.25 vCPU, scales to zero |
| Container Apps Job | `db-init` | Creates the per-context database roles. Runs on every deploy |
| Container Apps Job | `migrate` | Applies the database migrations with the new platform-api image, before the apps change ([Migrations on a deploy](#migrations-on-a-deploy)). Runs on every deploy |
| Container Apps Job | `bootstrap` | Migrations again, which finds nothing to do on Azure, then n8n owner, workflow load and lint. Runs on every deploy |
| Managed identities | `id-<app>-wab-dev`, one per app and job | AcrPull on the registry, and Key Vault Secrets User on each secret it reads. platform-api's also has Cosmos DB's built-in Data Contributor role on the `activity` database |
| Langfuse VM and its parts | `vm-langfuse-wab-dev` and others | Only while `langfuse_enabled` is `true`. Off by default ([Langfuse](#langfuse)) |
| The simulation n8n and its parts | `cae-wab-dev-sim`, `sim-n8n` and others | Only while `enable_simulation` is `true`. Off by default ([The simulation n8n](#the-simulation-n8n)) |

PostgreSQL 17 matches Compose and is listed as supported in [Azure's version list](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/concepts-supported-versions). We did not check that the Southeast Asia region offers it, because nothing here contacts Azure. If the first deploy says it does not, set `version = "16"` in `modules/postgres/main.tf`.

The Portal runs its existing nginx image as a Container App, not on Static Web Apps. Static Web Apps stops each API request after 45 seconds, which breaks the live view's event stream. Proposed [ADR 0016](../docs/adr/0016-host-the-portal-as-a-container-app.md) explains the choice.

### Layout

```text
infra/
  envs/dev/            the dev environment: the app table, generated secrets, backend
  modules/
    observability/     Log Analytics and Application Insights
    key_vault/         the vault and its secrets
    registry/          the container registry
    postgres/          the server, its firewall rule and the databases
    cosmos/            the Cosmos DB account, its database and container, and its data roles
    container_env/     the Container Apps environment
    workload_identity/ one identity and its role assignments
    container_app/     one Container App
    container_app_job/ one Container Apps Job
    langfuse_vm/       the Langfuse VM, its network, storage, alerts and compose file (ADR 0050)
  sql/db-init.sql      the role setup that the db-init job runs
  sql/db-init-langfuse.sql  Langfuse's role, added to the db-init job only while Langfuse is on
  sql/db-init-simulation.sql  the simulation's two databases, which its own db-init job makes first
  public-images.json   the pins of n8n, its task runner and PostgreSQL. The runner and PostgreSQL are copied into our registry; our n8n image builds on the n8n pin
  bootstrap/           one-time setup by a person: state storage and the deploy identity
  scripts/             the offline checks, and the job runner the deploy workflow uses
```

`envs/dev/main.tf` describes the four apps and two jobs as one table. Each row names the image, size, replicas, plain settings and the secrets it reads. Adding an app is one more row.

## Secrets

- No secret value is in any `.tf` file or tfvars file in git. Terraform generates every secret with `random_password` and writes it to Key Vault. `SETTINGS_ENCRYPTION_KEY`, which seals the AI model keys that Operators save in Settings (ADR 0022), is one of them. The one secret Terraform does not generate is the Cosmos DB account key: Azure makes it with the account, and Terraform copies it into Key Vault.
- platform-api signs in to Cosmos DB with that key (`COSMOS_KEY`), because its Cosmos DB adapter has no managed identity sign-in yet. Its identity already has the data role, so moving to identity sign-in is a code change in platform-api plus `local_authentication_enabled = false` in `modules/cosmos/main.tf`. ADR 0031 describes that end state.
- The apps never hold a secret value in their own settings. Each Container App setting points at a Key Vault secret's URL, and Azure reads it with the app's own managed identity. Our code reads plain environment variables and never calls a Key Vault SDK, the same as in Compose.
- **The generated secrets are also in the Terraform state file, in plain text.** That is how Terraform remembers a value so the next run keeps it. The state lives in Azure Storage with access keys turned off, so only identities with a blob data role can read it. [bootstrap/README.md](bootstrap/README.md) explains who that is. We kept stored random values over Terraform's newer write-only arguments, because a write-only value is new on every run, and a run that fails halfway would leave the database and Key Vault with different passwords.
- The release checker in agent-runtime calls GitHub's API. Without a token, GitHub allows only 60 requests an hour per IP address. On the Consumption plan our outbound address can be shared with other Azure customers, so a demo could run out. A token raises the limit to 5,000 an hour. To use one, set the secret `GH_RELEASE_TOKEN` on the `azure-dev` environment (step 7 below). The deploy passes it to Terraform as `github_token`, Terraform stores it in Key Vault, and agent-runtime reads it as `GITHUB_TOKEN`. Leave the secret unset, and agent-runtime calls GitHub without a token. Where the token comes from is still open (placeholder: the team lead decides who owns it). A fine-grained personal access token with no extra permissions can read public repositories' releases.
- n8n's own Jira, GitHub and Slack blocks run with keys the platform makes in n8n from Key Vault (ADR 0045, as amended): `N8N_KEY_JIRA_TOKEN` with `N8N_KEY_JIRA_URL` and, for Jira Cloud, `N8N_KEY_JIRA_EMAIL`; `N8N_KEY_GITHUB_TOKEN` with `N8N_KEY_GITHUB_URL`; and `N8N_KEY_SLACK_TOKEN`. The deploy passes each to Terraform, which stores it in Key Vault. Leave one unset and that system's blocks have no key. The platform asks each system what the key may do before it makes it, and again each day, and refuses a key that can do more than read, or than post in Slack. **A test run reads with these keys**, so whatever the Jira account can see, any Operator can read through a test run. Use a Jira account that only browses, and sees only the projects Operators may see. Use a classic GitHub token with read scopes, or none, for public repositories only. Use a Slack bot token with `chat:write` and the read scopes for channel and people lists only.
- Approval cards go to a real Teams channel only when the secret `TEAMS_WEBHOOK_URL` is set (ADR 0036). The address carries its own signature, so the deploy passes it to Terraform as `teams_webhook_url`, Terraform stores it in Key Vault, and platform-api reads it as `TEAMS_WEBHOOK_URL`. **Before you set it, run a one-time check.** Nobody has yet confirmed how Teams shows markdown and web addresses in the card's text.
  1. In a test channel, not the real one, create a Workflows flow from "When a Teams webhook request is received" with "Post card in a chat or channel", and copy its address.
  2. From the repository root, run `TEAMS_TEST_WEBHOOK_URL='<that address>' scripts/teams-card-check.sh`. It should print `Teams answered 202`.
  3. In Teams, open the card. Its text must show exactly as typed: the `**` marks, the brackets, `<at>Bob</at>`, `# Heading` and the broken addresses such as `https[:]//example[.]com`. Nothing may be bold, a heading or a link, except the "Open in AI Workflow Builder" button. Look hardest at the four things the platform leaves as written, because only this check shows whether Teams makes them links: the bare name `example.com/approve`, the longer name `sub.example.com`, the bare email `someone@example.com`, and the look-alike name `аррӏе.com` in Cyrillic letters.
  4. If anything shows as formatting or as a link, stop and tell the team. Otherwise delete the test flow, and set `TEAMS_WEBHOOK_URL` to the real channel's address.

### How each setting maps from Compose

| Setting | Compose | Azure |
|---|---|---|
| `AUTH_MODE` | `dev` | always `oidc`, because dev mode refuses to start off localhost |
| `PUBLIC_BASE_URL` | `http://localhost:8080` | the Portal's HTTPS URL, `https://portal.<domain>`, built from the environment's domain |
| `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL` | not set | from secrets. `OIDC_JWKS_URL` only when it is not empty |
| `DATABASE_URL_*` | built from `.env` | Key Vault secrets, each a full URL with `sslmode=require` |
| `AGENT_API_KEY`, `STEP_KEY`, `CALLBACK_SIGNING_KEY` | `.env` | Key Vault secrets |
| `GITHUB_TOKEN` | `.env`, empty by default | a Key Vault secret from `GH_RELEASE_TOKEN`, only when that secret is set |
| `AGENT_RUNTIME_URL`, `N8N_BASE_URL`, `PLATFORM_INTERNAL_URL` | `http://<service>:<port>` | `https://<app>.internal.<domain>` or `https://<app>.<domain>` |
| n8n's `WEBHOOK_URL` | `http://n8n:5678/` | n8n's own address, internal or public |
| n8n's `N8N_PROTOCOL`, `N8N_HOST`, `N8N_EDITOR_BASE_URL`, `N8N_PROXY_HOPS` | not set | not set while n8n is internal. With its editor open, `https`, `n8n.<domain>`, `https://n8n.<domain>/` and `1` |
| n8n's `N8N_INSTANCE_OWNER_*` | not set | not set while n8n is internal. With its editor open, `MANAGED_BY_ENV=true`, the `N8N_OWNER_EMAIL` address, the names `Platform Bootstrap`, and `PASSWORD_HASH` as the app's own secret |
| `CALLBACK_ALLOWED_ORIGINS` | `http://platform-api:8000` | platform-api's HTTPS origin |
| `PLATFORM_JIRA_URL` (agent-runtime) | `http://platform-api:8000` | platform-api's HTTPS URL. It must be one of `CALLBACK_ALLOWED_ORIGINS` (ADR 0035) |
| `PLANNER_MODE` (agent-runtime) | `.env`, unset by default, so `rules`, today's Planner | the `planner_mode` variable, from the GitHub variable `PLANNER_MODE`, else `rules`. `ai_led` lets the model lead through checked tools on top of the rules (ADR 0049). The team lead turns it on after the eval runs ADR 0049 asks for. Any other value stops agent-runtime from starting, and Terraform's plan refuses it |
| `JIRA_BASE_URL`, `JIRA_API_FLAVOR`, `JIRA_EMAIL`, `JIRA_ISSUE_TYPE`, `JIRA_BROWSE_URL`, `WATCHLIST_JIRA_PROJECT` | `.env`, unset by default: the practice Jira, `datacenter`, `Task`, `MOCK` | the `JIRA_*` and `WATCHLIST_JIRA_PROJECT` variables, unset by default ([A real Jira](#a-real-jira)) |
| `JIRA_API_TOKEN` | `.env`, empty | a Key Vault secret, `jira-api-token`, from `JIRA_API_TOKEN`, only when that secret is set |
| `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_PAGES` | `.env`, unset by default, so Confluence is not connected | the `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL` and `CONFLUENCE_PAGES` variables, unset by default. The email names the account and is not secret. `CONFLUENCE_PAGES` lists the only pages platform-api reads, as `id=title` separated by `;` |
| `CONFLUENCE_API_TOKEN` | `.env`, empty | a Key Vault secret, `confluence-api-token`, from `CONFLUENCE_API_TOKEN`, only when that secret is set. With none, platform-api signs in with Jira's token when Jira is on the same site |
| `COSMOS_ENDPOINT` | `http://cosmos:8081`, the emulator | the account's endpoint |
| `COSMOS_KEY` | the emulator's published key | a Key Vault secret, copied from the account |
| `ACTIVITY_READER` | `cosmos` by default | always `cosmos` |
| `TEAMS_CHANNEL` | `CODESparks Ops` unless `.env` sets it | the `TEAMS_CHANNEL` variable when it is set, else platform-api's default, `CODESparks Ops` |
| `TEAMS_WEBHOOK_URL` | `.env`, empty by default, so the practice Teams copy | a Key Vault secret from `TEAMS_WEBHOOK_URL`, only when that secret is set (ADR 0036) |
| `TEAMS_REQUESTS_WEBHOOK_URL` | `.env`, empty by default, so new team requests go to the approvals channel's webhook, or nowhere | not wired in Terraform yet, so it is unset and new team requests use `TEAMS_WEBHOOK_URL` (ADR 0038) |
| `TEAMS_TELL_WEBHOOK_URL` | `.env`, empty by default, so a Tell's notice goes to the practice copy | a Key Vault secret, `teams-tell-webhook-url`, from the `teams_tell_webhook_url` variable, which the deploy takes from the GitHub secret `TEAMS_TELL_WEBHOOK_URL` (ENGINE-PLAN D1). "Posts in Teams and emails" stays planned until E14 |
| `TELL_EMAIL_TO` | `.env`, empty by default | the `tell_email_to` variable, from the GitHub variable `TELL_EMAIL_TO`. The team's email list, separated by commas. A plain setting, not a secret: Settings, Connections shows it to anyone signed in. Required with the Tell flow |
| `TEAM_TIME_ZONE` | `.env`, unset by default, so `Asia/Singapore`. platform-api gives it to the Portal in `/api/v1/me`, so every time the Portal shows is in it. A new schedule, the agents' today, the last run's day and the Jira days are in it, and every workflow's own n8n workflow and the daily self-test run on it. n8n's `GENERIC_TIMEZONE` takes the same value | the `team_time_zone` variable, from the GitHub variable `TEAM_TIME_ZONE`, else `Asia/Singapore`. It goes to platform-api, the bootstrap job and n8n's `GENERIC_TIMEZONE` |
| `MAX_BODY_BYTES` | not set, so 2 MiB (2097152). platform-api refuses a larger request body with 413 | not set, so the same 2 MiB |
| `SETTINGS_ENCRYPTION_KEY` | `.env` | a generated Key Vault secret. If it is lost, an Operator pastes the model key again |
| `FIRST_OPERATOR`, `FIRST_APPROVERS` | `.env`, empty by default | from `first_operator` and `first_approvers`, only when they are set |
| n8n database settings | `postgres` host, password from `.env` | the server's host name, TLS on, password from Key Vault |
| `N8N_ENCRYPTION_KEY` | `.env` | Key Vault secret. It must never change |
| `N8N_SECURE_COOKIE` | `false`, for plain HTTP | not set, so n8n's default `true` applies over HTTPS |
| Portal `API_UPSTREAM` | `http://platform-api:8000` | platform-api's HTTPS URL |
| Portal `OIDC_AUTHORITY`, `OIDC_CLIENT_ID`, `OIDC_SCOPE` | not set | from secrets, for `/config.json`. `OIDC_AUTHORITY` is the same value as `OIDC_ISSUER` |

Apps call each other over HTTPS, because Container Apps redirects plain HTTP and our HTTP clients do not follow redirects. Traffic between apps in one environment stays inside it.

Every app's address comes from the Container Apps environment's default domain: `https://<app>.<domain>`, or `https://<app>.internal.<domain>` for an internal app. So the Portal and platform-api can each know the other's address without waiting for the other app to exist. Azure picks the domain when it creates the environment, so a new environment gets a new one. n8n's address changes with `N8N_EDITOR_EXTERNAL`, and platform-api and the bootstrap job follow it.

## Migrations on a deploy

The deploy applies the database migrations before it changes the apps (issue #131). It updates only the `migrate` job to the new platform-api image, runs it, and only then applies everything, which starts the new platform-api. So the new code never runs on the old schema.

The old platform-api keeps running on the new schema until the new revision takes over, a few minutes later. If the full apply fails, the old code keeps running on the new schema until the next deploy. So every migration must keep the running code working:

- Add things: a table, an index, or a column that is nullable or has a default.
- Do not drop or rename a table or a column, or add a `NOT NULL` column without a default, in the same deploy as the code that stops using it or starts filling it. Do that in a later deploy, once no running code needs the old shape.

Compose starts platform-api only after its bootstrap has migrated the database, so the gap exists only on Azure.

## Known risk: the database is reachable from Azure

The PostgreSQL server has public access, with the firewall rule that lets Azure services in. That rule lets in any Azure customer's services, not only our apps. TLS and a 48-character generated password per role are what keep others out.

The Cosmos DB account has public access with no IP filter at all, like Key Vault, because the apps have no fixed outbound address and the checker reads items from a laptop. Its account key and Entra ID data roles keep others out. The key cannot change databases or containers, and the account holds only a copy of the activity log: PostgreSQL keeps every event.

The team lead accepted this for the dev and demo environment on 23 Oct 2026. Private networking comes with DevNet.

Changing it later is not a small edit. Private access needs the Container Apps environment inside a virtual network, and an environment cannot join one after it is created. So the move means recreating the environment, which also gives it a new domain and new app addresses.

## n8n's editor

n8n is internal unless the `N8N_EDITOR_EXTERNAL` variable is `true` ([ADR 0034](../docs/adr/0034-open-n8ns-editor-on-azure-with-an-optional-list-of-allowed-addresses.md)). Then its editor is at `https://n8n.<domain>`, the Portal's address with `portal` changed to `n8n`. `terraform output -raw n8n_editor_url` prints it.

- **Sign-in.** Use n8n's owner account: the email in `N8N_OWNER_EMAIL`, and the password in the Key Vault secret `n8n-owner-password`. Reading the secret needs a data role on the vault, such as Key Vault Secrets User, which no person has by default. While the editor is open, n8n refuses to change that account's password or email, because its settings manage the account. The password stays as Terraform holds it: n8n rewrites the owner from Terraform's bcrypt hash on every start, so a hand edit in Key Vault breaks the bootstrap's sign-in until the next apply. To rotate it, mark `random_password.generated["n8n-owner-password"]` for replacement and deploy with `allow_destroy`, while the switch is on.
- **Who can reach it.** With `N8N_EDITOR_ALLOWED_IPS` unset, every address reaches n8n's sign-in page. That is the operator's choice for now (1 Nov 2026). With it set, Container Apps lets in only those addresses and the ranges in `N8N_INTERNAL_ALLOWED_CIDRS`, and answers anyone else with "RBAC: access denied". n8n reads each visitor's own address (`N8N_PROXY_HOPS=1`), so its sign-in limit of 1000 tries in 5 minutes is per visitor. Its second limit, 5 tries a minute for one email, still lets anyone who knows the owner's email lock out the owner and the bootstrap, which waits up to three minutes and then fails the deploy. Only the list removes that. Set the list before the sponsor demo, and before any real credentials go into n8n. ADR 0034 lists the risks of running without it. Since every built-in block loads ([ADR 0051](../docs/adr/0051-a-workflow-drafter-may-propose-any-n8n-block-code-explains-every-workflow-and-an-approvers-yes-sets-up-a-flagged-workflow.md), step 12), the editor can also build workflows with Code, HTTP Request and Webhook, and a Webhook, Form, Wait or MCP Server Trigger that a member publishes answers anyone who reaches n8n, at `/webhook`, `/webhook-test`, `/webhook-waiting`, `/form`, `/form-test`, `/form-waiting`, `/mcp` and `/mcp-test`. The team lead kept the choice of 1 Nov on 18 Nov 2026, so nothing changes until the list is set. With the list set, the deploy checks that each of those paths refuses its runner.
- **No race for the owner.** Until n8n has an owner, its setup page lets the first visitor become the owner. Two things close that gap:
  - **The deploy's gate.** The step "Check that n8n may open" (`scripts/n8n-editor-gate.sh`) opens n8n only once the `bootstrap` job has a Succeeded execution in the resource group. On a new environment, n8n stays internal for the first deploy, and the run summary says: "n8n stays internal until the first bootstrap has created its owner. Run the deploy again to open the editor." Later deploys pass the check, so nothing flips. If `az` fails, the deploy stops rather than closing an open editor.
  - **n8n's own setting.** While the switch is on, n8n creates the owner from its settings (`N8N_INSTANCE_OWNER_MANAGED_BY_ENV`) before it registers any REST route. The password hash is the stored bcrypt hash of `n8n-owner-password`, kept as the n8n app's own secret.
- **Hand edits.** Each deploy's bootstrap reloads the platform's own n8n workflows, `run`, `schedule_tick` and `run_failure_reporter`, from git. Edits to those three are lost. Other n8n workflows stay.
- **The plan.** Turning the switch or the list on or off updates the n8n app, platform-api and the bootstrap job in place. In azurerm 5.7.0, no ingress field forces a replace, so the plan guard lets the deploy go ahead. n8n restarts once. The apply changes n8n and platform-api side by side, so for about a minute platform-api can still call n8n's old address. Deploy while no run is in progress.

### What the deploy must confirm

The offline checks cannot show these:

1. **Switch on, no list.** The editor opens at `n8n_editor_url`, which the run summary prints, and the owner can sign in. n8n's log says "N8N_INSTANCE_OWNER_MANAGED_BY_ENV is enabled". The bootstrap job succeeds and logs "owner <email>: signed in", and a test run completes, so platform-api reaches n8n at its new address.
2. **The gate on a new environment, if one is made.** The first deploy keeps n8n internal and writes the note to the run summary. The second deploy opens it.
3. **With a list, from a listed address.** The editor opens.
4. **With a list, from any other address,** such as a phone on mobile data. The answer is "RBAC: access denied". This also shows that the inside ranges do not let outsiders in. The deploy's step "Check that n8n's public paths refuse an address outside its list" (`scripts/n8n-paths-closed.sh`) does the same for each path above, from its runner, and runs only while the list is set.
5. **With a list, the platform's own calls.** The bootstrap job succeeds, and a test run completes. This is the one check of the inside ranges. If either fails with HTTP 403 ("RBAC: access denied"), unset `N8N_EDITOR_ALLOWED_IPS` and deploy again, which restores runs. Then find where the calls come from. If they leave through the environment's public address, `az containerapp show --name platform-api --resource-group rg-wab-dev --query properties.outboundIpAddresses` lists it, and it goes in `N8N_INTERNAL_ALLOWED_CIDRS`. That address can be shared with other Azure customers, so n8n's sign-in matters again.

## n8n's task runner

n8n runs the code of Code, AI Transform, the Code Tool, Sort and Item Lists in its external task runner, the app `n8n-runners` ([ADR 0051](../docs/adr/0051-a-workflow-drafter-may-propose-any-n8n-block-code-explains-every-workflow-and-an-approvers-yes-sets-up-a-flagged-workflow.md), spike P9). Spike P9 showed that code which gets out of the runner's sandbox reads every secret n8n holds when the runner is n8n's own child, and none when it runs in a container of its own. So:

- **n8n's guards.** `local.n8n_guards` gives n8n `N8N_RUNNERS_MODE=external`, keeps `$env` closed, refuses the deprecated blocks that run code in n8n's own process, and keeps the file blocks in `/home/node/.n8n-files`. The bootstrap job gets the same map and fails the start unless each holds. `tests/n8n.tftest.hcl` checks the map.
- **The token.** n8n and the runner both read the Key Vault secret `n8n-runners-auth-token` as `N8N_RUNNERS_AUTH_TOKEN`. It lets a client take n8n's tasks, so only those two apps hold it. Giving n8n's identity that one more secret replaces its role wait, which the plan guard counts as a change, since a wait holds nothing.
- **No identity in the runner.** The runner's identity pulls its image and reads its token. `identitySettings` with `lifecycle` `None` keeps it out of every container, so code in the runner can't ask Azure for a token. azurerm 5.7.0 can't set that, so `modules/task_runner` makes the whole app with azapi, and its first revision already has it.
- **The broker.** The runner calls `http://n8n:5679`. n8n's app opens 5679 only inside the environment, through `additionalPortMappings`, which azurerm 5.7.0 can't set either. `modules/container_app`'s `internal_ports` sends that PATCH, and sends it again whenever n8n's ingress or revision changes, because azurerm writes the ingress whole, without the extra port, when the ingress changes. Container Apps reaches the container on an address n8n can't know before it starts, so the broker listens on every address, and any app in the environment can reach it. Only the token guards it. Locally, compose binds it to n8n's address on the runners network alone.
- **What never loads.** `local.n8n_guards` gives n8n `NODES_EXCLUDE`, which leaves out every block that reaches n8n's own secrets, disk or host: Execute Command, Local File Trigger, Function, Function Item, LangChain Code, Git and Git's tool. `tests/n8n.tftest.hcl` checks the list.
- **Changing the token.** Mark `random_password.generated["n8n-runners-auth-token"]` for replacement and deploy with `allow_destroy`, as for the owner's password above. That writes a new version of the Key Vault secret. Then restart both apps, so each reads the new version: `az containerapp revision restart` for `n8n` and for `n8n-runners`, n8n first. Runs that wait on the runner fail until both have restarted.
- **What checks it offline.** Checkov reads no azapi body, so it checks nothing in the runner app or the broker's port. `tests/n8n.tftest.hcl` checks both: the runner gets only its own settings and token, no container gets its identity, and 5679 is internal.
- **No network fence.** The environment isn't in a virtual network, so the runner app has open egress to the internet, and reaches every app's internal address. Code would have to get out of the runner's sandbox first, and then it holds only the token. Narrowing either needs the environment recreated in a virtual network, a decision for the team lead (the pull request for ADR 0051 step 12 lists the options).

### What the deploy must confirm

Spike P9 could not answer these, and the offline checks cannot either:

1. **No identity in the runner.** `az containerapp exec --name n8n-runners --resource-group rg-wab-dev --command env` lists neither `IDENTITY_ENDPOINT` nor `IDENTITY_HEADER`, nor `MSI_ENDPOINT` or `MSI_SECRET`. If any shows, stop the `n8n-runners` app, so no code runs, before anything else.
2. **The runner reaches the broker.** The runner's log says it registered with n8n's broker, and a Code block in a test workflow runs. `az containerapp show --name n8n --resource-group rg-wab-dev --query properties.configuration.ingress.additionalPortMappings` lists 5679, internal.
3. **Who else reaches the broker.** Call `http://n8n:5679` from platform-api's console (`az containerapp exec --name platform-api ...`). If it answers, any app in the environment reaches the broker, and only the token guards it. Note which apps can, and whether n8n's address list also limits the extra port.

## A real Jira

With no `JIRA_BASE_URL`, platform-api serves a practice Jira at `/practice-jira` and calls it over HTTP, the way it would call a real one ([ADR 0035](../docs/adr/0035-reach-jira-through-one-rest-adapter-and-let-the-practice-jira-speak-jiras-api.md)). To switch to a real Jira, set these on the `azure-dev` environment and deploy:

- the variable `JIRA_BASE_URL`, an https address such as `https://jira.example.com`;
- the variable `JIRA_API_FLAVOR`, `datacenter` (REST v2) or `cloud` (REST v3);
- the secret `JIRA_API_TOKEN`, a personal access token for Data Center or an API token for Cloud;
- for Cloud, the secret `JIRA_EMAIL`, the account's email;
- if needed, `JIRA_ISSUE_TYPE` (default `Task`), `JIRA_BROWSE_URL` (default `JIRA_BASE_URL/browse/{key}`) and `WATCHLIST_JIRA_PROJECT` (default `MOCK`).

Before you deploy, wait until no run is between an Approver's yes and its write, or expect those runs to stop. A write approved for the practice Jira is never made in the real one: the safety checker stops it, and the run says that Jira's settings changed after the yes ([ADR 0041](../docs/adr/0041-an-approved-jira-write-is-made-only-in-the-jira-it-was-approved-for.md)). The same holds for a move to another Jira address. A new token for the same address changes nothing.

The plan updates platform-api and the Portal in place, and adds the `jira-api-token` secret to Key Vault. The practice Jira's routes are then not served. The Portal gets `JIRA_BROWSE_URL` too, so ticket keys with no address of their own link to the real Jira, and the Portal hides its Practice Jira page. `platform-api/tests/test_jira_contract.py` runs against the real Jira first, with `JIRA_CONTRACT_URL` and the settings its docstring names.

## Langfuse

[ADR 0050](../docs/adr/0050-trace-the-planner-in-self-hosted-langfuse-and-people-decide-what-it-learns.md) traces the Planner in self-hosted Langfuse. On Azure, Langfuse runs on one small VM, not on Container Apps. **It is off.** `langfuse_enabled` defaults to `false`, and then plan makes nothing for it and agent-runtime and platform-api get no Langfuse setting, so tracing stays off. **Nothing here is applied until the team lead approves the monthly cost,** as the ADR says.

### What it creates

With `langfuse_enabled = true`, `modules/langfuse_vm` and `envs/dev` add:

- **One VM**, `vm-langfuse-wab-dev`, `Standard_B2as_v2` (2 vCPUs, 8 GiB), Ubuntu 24.04 with Secure Boot and vTPM. SSH password sign-in is off, and nobody holds a key: the key Azure requires had its private half deleted. People reach the VM with `az vm run-command`.
- **One disk**, the VM's own 32 GiB Standard SSD, the one E4 disk the ADR prices. ClickHouse keeps its data there. A separate data disk would be a second E4, because Ubuntu's image needs 30 GiB of its own. Any change to the VM's compose file replaces the VM and that disk with it, so its traces go. The deploy's plan guard stops for `allow_destroy` first. Traces are a 60-day working record, and what must last lives in git.
- **A static public address** with the name `langfuse-wab-dev-<suffix>.<region>.cloudapp.azure.com`. It stays when the VM is replaced, so the Entra redirect URI does too. `terraform output -raw langfuse_url` prints it.
- **A network security group.** Port 443 takes only the apps' outbound addresses, which Terraform reads from the Container Apps, and the team's addresses in `langfuse_allowed_ips`. Other Azure customers can share the apps' addresses, so Langfuse's keys and sign-in still guard it. Port 80 is open to everyone, because Let's Encrypt checks the certificate request there, and Caddy redirects the rest to 443. Nothing else comes in.
- **The compose stack**, written by cloud-init to `/etc/langfuse/compose.yaml`: Langfuse web and worker 4.80.0, ClickHouse 26.3.62.3 capped at 1.5 GiB with `clickhouse.xml`, as the laptop profile was measured (3.3 GiB at peak for the whole stack), Valkey 8.1.11 with a password and `noeviction`, and Caddy 2.11.9 in front of web, each pinned by digest. Only Caddy publishes a port. Every service restarts by itself after a reboot. Telemetry and the signup newsletter are off. Unattended security updates stay on, and a kernel update reboots the VM at 03:00 Singapore time. `scripts/check-langfuse-images.sh` fails when an image or the ClickHouse config differs from `deploy/compose.yaml`'s `langfuse` profile.
- **Secrets in Key Vault only.** The VM's own managed identity may read Langfuse's secrets and nothing else. At every start, `langfuse.service` reads them into `/etc/langfuse/secrets.env`, which only root can read. Terraform generates the project keys, `SALT`, `ENCRYPTION_KEY`, `NEXTAUTH_SECRET`, the passwords for PostgreSQL, ClickHouse, Valkey and the first user, and `trace-pseudonym-key`, which only platform-api reads. Two secrets come from other systems, so Terraform makes each with a placeholder and a person sets it: `langfuse-entra-client-secret` and `langfuse-judge-anthropic-key`. The VM never reads the judge's key.
- **A storage account** `stlfwabdev<suffix>` with a private `langfuse` container for events and media, TLS 1.2, HTTPS only and no public blob access. Langfuse signs in with its account key, which goes to Key Vault.
- **A `langfuse` database** on the existing PostgreSQL server, and a `langfuse` role that the db-init job creates from `sql/db-init-langfuse.sql`. With Langfuse off, the job runs exactly what it ran before.
- **Two alerts.** One fires when the VM has fewer than 50 CPU credits left, about 40 minutes at full load before Azure throttles it. One fires when its disk is 80% full: Azure Monitor Agent sends the disk's use to the Log Analytics workspace, and a log alert reads it, because a VM has no platform metric for that. Both email `langfuse_alert_email` when it is set.
- **Settings for the apps.** agent-runtime gets `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`, `LANGFUSE_TRACING_ENVIRONMENT` (`azure-dev`) and `LANGFUSE_RELEASE` (the image tag). platform-api gets the keys, `LANGFUSE_BASE_URL` and `TRACE_PSEUDONYM_KEY`.
- **Run-command for the deploy identity on this VM,** through the role `Langfuse VM run command (rg-wab-dev)`, for the nightly housekeeping job. The identity is `deploy_principal_object_id`, never whoever runs apply. It is limited to this VM only once Contributor is narrowed, below.

`tests/langfuse.tftest.hcl` checks both states against mocked providers: off adds nothing and gives no app a Langfuse setting, and on gives each app exactly the settings above.

### Cost

From ADR 0050, at pay-as-you-go list prices for Southeast Asia on 16 Nov 2026: about **USD 75 a month while the VM runs** (about USD 69 for the VM, USD 2.40 for the disk and USD 3.65 for the address), and **about USD 6 a month while it is stopped** (deallocated). The storage account, the two alerts and the disk samples add well under USD 2 a month. That last figure is a guess, not checked against the price list. Against the USD 100 credit, run the VM only in test weeks and demos.

### Run-command and Contributor

- **"This VM only" is not true yet.** The deploy identity has Contributor on `rg-wab-dev`, and Contributor already includes run-command on every VM in it. The custom role limits the deploy only once Contributor is narrowed.
- **The bootstrap must widen first.** The deploy identity may not create role definitions, and its RBAC Administrator role may only assign the four roles its condition lists. So `bootstrap/setup-azure.sh` now creates the custom role on `rg-wab-dev` and adds its ID to that condition. It also registers `Microsoft.Compute` and `Microsoft.Network`. An Owner of the subscription runs it again by hand. No agent or workflow runs it. Until then, a plan with Langfuse on stops with "role not found".

### How a person turns it on

Every step changes cloud resources or settings, so a person does it, and only after the team lead approves the cost.

1. **Run the bootstrap again** as an Owner: `STATE_ACCOUNT=<name> infra/bootstrap/setup-azure.sh <owner>/<repo>`. It registers the two providers, creates the run-command role and replaces the deploy identity's RBAC Administrator assignment with the wider condition.
2. **Register Langfuse's Entra app** in the tenant of `OIDC_ISSUER`. Make it a web app with assignment required, assign only the team's group, and add the `email` claim. Langfuse identifies people by email.
3. **Pass the variables to the deploy.** `.github/workflows/deploy.yml` does not pass them yet. A follow-up adds these lines to its `env`:

   ```yaml
   TF_VAR_langfuse_enabled: ${{ vars.LANGFUSE_ENABLED || 'false' }}
   TF_VAR_deploy_principal_object_id: ${{ vars.DEPLOY_PRINCIPAL_OBJECT_ID }}
   TF_VAR_langfuse_entra_client_id: ${{ vars.LANGFUSE_ENTRA_CLIENT_ID }}
   TF_VAR_langfuse_owner_email: ${{ secrets.LANGFUSE_OWNER_EMAIL }}
   TF_VAR_langfuse_allowed_ips: ${{ secrets.LANGFUSE_ALLOWED_IPS }}
   TF_VAR_langfuse_alert_email: ${{ secrets.LANGFUSE_ALERT_EMAIL }}
   ```

   The owner email, the team's addresses and the alert email name people, so they are secrets on `azure-dev`, as for n8n.
4. **Deploy with `allow_destroy` ticked.** Turning Langfuse on gives platform-api, agent-runtime and the db-init job a new Key Vault secret each, which replaces their 90-second role waits, and the plan guard stops on any replace. Read the listed addresses first: they should be `time_sleep` waits only. Turning it off destroys the VM, its disk and its storage, so it needs the tick too.
5. **Finish the Entra app.** Add `<langfuse_url>/api/auth/callback/azure-ad` as its redirect URI. Create a client secret, and put its value, not its ID, in Key Vault: `az keyvault secret set --vault-name kv-wab-dev-<suffix> --name langfuse-entra-client-secret --value <value>`. Then restart Langfuse so it reads the secret: `az vm run-command invoke --resource-group rg-wab-dev --name vm-langfuse-wab-dev --command-id RunShellScript --scripts "systemctl restart langfuse"`.
6. **Sign in** at `langfuse_url` with the Entra account whose email is `langfuse_owner_email`. Langfuse made that account the Owner of the `CODESparks` organization and its `AI Workflow Builder` project at first start. Invite each teammate by email as a Member.

### What the first apply must confirm

The offline checks cannot show these:

- The VM boots, `systemctl status langfuse` is active, and `docker compose --file /etc/langfuse/compose.yaml ps` shows five healthy services. If not, the VM's serial log in boot diagnostics shows cloud-init's output.
- Caddy gets a certificate, and `<langfuse_url>` opens Langfuse's sign-in page from a listed address and times out from any other.
- A Planner turn in the Portal shows up as a trace, which proves the apps' outbound addresses are the ones the security group lets in.
- `az vm run-command invoke` works for the deploy identity, and `Perf` in the Log Analytics workspace gets the root disk's `% Used Space` every 5 minutes.
- The VM's peak memory under `docker stats` stays under 6 GiB. ADR 0050 moves it to `Standard_B4as_v2` if not.

## The simulation n8n

[ADR 0054](../docs/adr/0054-simulation-mode-tries-each-workflow-on-mock-systems-in-a-separate-n8n-before-the-real-test-run.md) tries each workflow version against mock systems in a second n8n, before its test run. **On Azure it is off.** `enable_simulation` defaults to `false`, and then Terraform makes none of it. **Nothing here is applied until the team lead turns it on.** `deploy/compose.simulation.yaml` is the same stack on a laptop and in CI.

### What it creates

With `enable_simulation = true`, `envs/dev/simulation.tf` adds:

- **A virtual network** `vnet-wab-dev-sim`, `10.81.0.0/24`, with one subnet `snet-wab-dev-sim`, `10.81.0.0/27`, for Container Apps alone.
- **A network security group** on that subnet. Out, it lets through the subnet itself, and port 443 to `MicrosoftContainerRegistry` and `AzureFrontDoor.FirstParty` for Azure's system images, `AzureContainerRegistry` and `Storage.<region>` for our registry, which is Basic and has no private endpoint, `AzureActiveDirectory` for the identities, and `AzureMonitor` for logs, plus port 53 to Azure's DNS. In, it lets through the subnet and Azure's load balancer. It refuses everything else both ways.
- **A Container Apps environment** `cae-wab-dev-sim` on that subnet, with no public address, and logs to the same workspace. Apps in one environment share its subnet, so nothing of the platform's runs there.
- **Four apps.** `sim-postgres` runs the PostgreSQL pin, reached on TCP 5432 inside the environment only. Its data lives in the container, so a restart starts it empty. `sim-n8n` runs our n8n image with the platform n8n's guards. Its blocks call `sim-gateway`, the simulation gateway, which runs platform-api's image with its own command and holds only the simulation's node key, start secret and n8n owner (ADR 0054, section 3). It is in this environment, so the platform's n8n can't reach it. `sim-mock-github` runs mock GitHub.
- **The task runner** `sim-n8n-runners`, as the platform's: none of n8n's secrets, and no container gets its identity. It takes its token as a value, through azapi's `sensitive_body`, which is never stored or shown.
- **Two jobs.** `sim-db-init` makes the two databases from `sql/db-init-simulation.sql`, then runs `sql/db-init.sql`. `sim-bootstrap` runs platform-api's bootstrap against the simulation n8n.
- **Its own keys.** Terraform makes 12 for the simulation alone and keeps them as the apps' and jobs' own secrets. None is in Key Vault, no app or job here reads Key Vault, and each identity here may only pull images.

The service tags cover every Azure customer's registries and storage, not only ours, so the network cannot narrow the simulation to the mocks alone. Isolation rests on holding no real key, and the network rules are a second layer (ADR 0054, spike item S6). `tests/simulation.tftest.hcl` checks both states against mocked providers: off makes nothing, and on holds only the settings it lists, only its own keys, only addresses in its own environment, and only the network rules above, even with the platform's real keys set.

### How a person turns it on

Every step changes cloud resources or the deploy, so a person does it, and only after the team lead's OK.

1. **Push mock GitHub's image.** The deploy pushes our four images only. A follow-up adds `mock-github` with the same tag.
2. **Pass the variable to the deploy.** `.github/workflows/deploy.yml` does not pass it yet. A follow-up adds `TF_VAR_enable_simulation: ${{ vars.ENABLE_SIMULATION || 'false' }}`.
3. **Run the two jobs after the apply,** `sim-db-init` then `sim-bootstrap`, as the deploy runs the platform's. They must run again whenever `sim-postgres` restarts.
4. **Reach the gateway from the platform.** The platform's apps run in another environment and can't reach `sim-gateway` yet. ADR 0054's PR 5 starts simulated runs and reads their records, and chooses how.

Mock Slack is not on Azure. Container Apps cannot answer to `slack.com` without a private DNS zone and a certificate for that name. Slack's block is notice-only, so a run by hand pins it, as the spike found for Teams, Outlook and Gmail.

### What the first apply must confirm

- The environment starts on its subnet behind these rules, and Azure pulls its system images and ours. If either fails, the security group is the first suspect: Azure's list of what a workload profiles environment needs may have changed.
- Azure takes `Storage.<region>` written with the region's name as Terraform has it, such as `Storage.southeastasia`.
- From `sim-n8n`, `api.github.com` and the platform's apps are out of reach, and `sim-mock-github`, `sim-gateway` and `sim-postgres` are in reach.
- What it costs. Four apps stay on all the time, `sim-postgres`, `sim-n8n`, `sim-gateway` and `sim-n8n-runners`, with 1.25 vCPU and 2.5 GiB together. Nobody has priced it yet.

## Cost estimate

This is an **estimate** from Azure's published US-dollar list prices for pay-as-you-go. We did not check prices for Southeast Asia, which can be 10 to 20 percent higher.

| Item | Per month |
|---|---|
| PostgreSQL B1ms compute and 32 GB storage | USD 16 to 20 |
| Container Apps: platform-api and n8n always on (0.75 vCPU, 1.5 GiB) after the monthly free grant. Low end if Azure bills them at the idle rate, high end at the active rate | USD 16 to 54 |
| Container Apps: agent-runtime and the Portal, scaled to zero between demos | about USD 0 |
| Container registry, Basic | about USD 5 |
| Cosmos DB on the free tier, capped at the free 1000 RU/s and well under its 25 GB | USD 0. Serverless, if the free tier is refused, costs cents at our volume |
| Log Analytics, under the first 5 GB free | USD 0 to 3 |
| Key Vault operations, Terraform state storage | under USD 1 |
| **Total** | **about USD 35 to 85** |

Azure for Students gives USD 100 of credit for 12 months. At this rate, an environment that runs all the time uses the credit in two or three months. So bring it up for demos and test weeks, and take it down afterwards with `terraform destroy` from a signed-in laptop. Keep these points in mind:

- The state storage, the deploy identity and the empty resource group `rg-wab-dev` stay. Terraform did not create the group, so it does not delete it. Leave it in place: the deploy identity's roles live on it, and an empty group costs nothing. The next deploy starts from there in about 20 minutes (a guess).
- Run only `destroy` from a laptop. `apply` belongs to the deploy workflow, because the Terraform code gives its caller two roles as a service principal, and a person is not one.
- A new environment gets a new domain, so the Portal's address changes. After the first deploy that follows a destroy, add the Portal's new redirect URIs to its app registration (step 9 below).
- Key Vault names stay reserved for 7 days after a destroy, which is why the names carry a random suffix.

## One-time human steps before the first deploy

Do these in order. Each one changes cloud resources or repository settings, so a person does them. The order matters: the GitHub environment `azure-dev` must exist, limited to `main`, before any Azure credential trusts it.

### The gate, as it is

The repository is private. On a private repository with GitHub Pro, an environment can be limited to certain branches, but it cannot have required reviewers, "Prevent self-review" or a wait timer. Those need a public repository or GitHub Enterprise. So the gate is:

- Only code on `main` can deploy, because the `azure-dev` environment only accepts `main`. Since 29 Oct 2026 (PR #44) a pull request into `main` no longer needs a second person's approval, so what reaches `main` is checked by CI and by the team's review practice, not by a branch rule.
- A person starts each deploy by hand. Anyone with write access to the repository can start one.
- No second person approves each run. To make up for that, the deploy stops before any apply that would destroy or replace a resource, unless the person who starts it ticks `allow_destroy`.

If the repository is made public later, add required reviewers and "Prevent self-review" to `azure-dev`.

### Steps

1. **Wait until the owner account is on GitHub Pro.** On GitHub Free, a private repository has no environments, no environment secrets and no branch protection, so none of the gate above exists.
2. **Add the teammates as collaborators.** They review the pull requests into `main` (step 3).
3. **Protect `main`.** In the repository's Settings, open Branches and add a rule for `main`:
   - Tick "Require a pull request before merging", with 1 required approval. GitHub never counts the author's own approval.
   - Tick "Require approval of the most recent reviewable push", so a change pushed after the approval needs a new one.
   - Tick "Do not allow bypassing the above settings", so the owner cannot push to `main` directly either.
4. **Create the GitHub environment.** In Settings, open Environments and create `azure-dev`. Under Deployment branches and tags, choose "Selected branches and tags" and add `main` only. Keep it that way. The deploy's secrets go into this environment, not into the repository's secrets (step 7).

   Do this before step 5. The deploy identity's federated credential trusts any workflow job that names `environment: azure-dev`. A workflow that names an environment that does not exist creates it, with no rules at all. So if the credential came first, a workflow on any branch could act as the deploy identity.
5. **Create the state storage, the resource group and the deploy identity.** Follow [bootstrap/README.md](bootstrap/README.md). It prints five values for step 7.
6. **Register the Entra ID apps.** Follow [docs/auth/entra-setup.md](../docs/auth/entra-setup.md). It creates the two app registrations, with the app roles `Operator` and `Approver` on platform-api's, and gives the values for the `OIDC_` variables in step 7. The Portal's address does not exist until the first deploy, so register the Portal app without its redirect URIs for now. If the university tenant does not let students register apps, this step needs a tenant that does, because app roles live on an app registration. The deploy identity from step 5 does not have this problem, because it is a managed identity.
7. **Set the environment's secrets and variables.** On the `azure-dev` environment, add these. The repository is public, so anyone can read the deploy's logs, and GitHub masks only secret values. So every value that names a person, an ID or the state storage goes under Secrets, and so do the addresses allowed to reach n8n. Only settings that name nobody go under Variables: the region, the Cosmos DB switches, and n8n's switch and inside ranges.

   | Secret | Value |
   |---|---|
   | `AZURE_CLIENT_ID` | printed by the bootstrap script |
   | `AZURE_TENANT_ID` | printed by the bootstrap script |
   | `AZURE_SUBSCRIPTION_ID` | printed by the bootstrap script |
   | `GH_RELEASE_TOKEN` | optional. A GitHub token for the release checker, as [Secrets](#secrets) describes |
   | `TEAMS_WEBHOOK_URL` | optional. A Teams Workflows webhook's address, so approval cards go to a real channel (ADR 0036). Run the one-time check in [Secrets](#secrets) first. Leave it unset for the practice Teams copy |
   | `TFSTATE_RESOURCE_GROUP` | printed by the bootstrap script |
   | `TFSTATE_STORAGE_ACCOUNT` | printed by the bootstrap script |
   | `OIDC_ISSUER` | `https://login.microsoftonline.com/<tenant-id>/v2.0`. The Portal uses it as its sign-in authority too |
   | `OIDC_AUDIENCE` | the Application (client) ID of platform-api's app registration, not its `api://` URI |
   | `OIDC_CLIENT_ID` | the Application (client) ID of the Portal's app registration |
   | `OIDC_SCOPE` | `openid profile offline_access api://<api-client-id>/access_as_user` |
   | `OIDC_JWKS_URL` | optional. Leave it unset, and platform-api finds the keys through the issuer |
   | `N8N_OWNER_EMAIL` | the email for the n8n owner account |
   | `FIRST_OPERATOR` | the work email of the first Operator. Needed on the first deploy |
   | `FIRST_APPROVERS` | the work emails of the first two Approvers, separated by a comma. Two different people. The first Operator may be one of them |
   | `N8N_EDITOR_ALLOWED_IPS` | optional. Public IPv4 addresses or ranges that may reach n8n, separated by commas, such as `203.0.113.7,198.51.100.0/24`. Used only while `N8N_EDITOR_EXTERNAL` is `true`. Unset lets every address reach n8n's sign-in page ([n8n's editor](#n8ns-editor)) |

   | Variable | Value |
   |---|---|
   | `TEAMS_CHANNEL` | optional. The Teams channel's name, as the approval card and the activity log name it. Unset means `CODESparks Ops` |
   | `PLANNER_MODE` | optional. `ai_led` lets the Planner's model lead through checked tools on top of the rules (ADR 0049). Unset means `rules`, today's Planner. Set it only after the team lead reads the eval runs ADR 0049 asks for. Going back is setting it to `rules` |
   | `TEAM_TIME_ZONE` | optional. The zone the team works in, such as `Europe/London`. Unset means `Asia/Singapore`. Set it before the first workflow is made. Changing it later grades each workflow laid out on the old zone Needs a fix (ADR 0046). n8n still fires its Schedule Trigger on the old zone, and our API refuses each run at its first block, before it reads anything, until its schedule is saved again or its zone is changed in n8n. Terraform checks only that the value looks like a zone name, so a name that is not a real zone passes the plan, and platform-api then refuses to start |
   | `AZURE_LOCATION` | optional. The region for every resource. Unset means `southeastasia`. Set it before the first deploy only: changing it later replaces everything, PostgreSQL included |
   | `COSMOS_LOCATION` | optional. A region for Cosmos DB alone, when it is refused in `AZURE_LOCATION` |
   | `COSMOS_SERVERLESS` | optional. `true` makes a serverless Cosmos DB account, for when the free tier is refused. Unset means `false` |
   | `N8N_EDITOR_EXTERNAL` | optional. `true` opens n8n's editor at `https://n8n.<domain>`, once a bootstrap has succeeded. Unset means `false`: n8n stays internal ([n8n's editor](#n8ns-editor)) |
   | `N8N_INTERNAL_ALLOWED_CIDRS` | optional. Ranges, separated by commas, that `N8N_EDITOR_ALLOWED_IPS` adds for the platform's own calls to n8n. Unset means `100.100.0.0/17,100.100.128.0/19,100.100.160.0/19,100.100.192.0/19`. Change it only if the deploy shows those calls come from elsewhere |

   With the GitHub CLI, each is one command, for example `gh secret set AZURE_TENANT_ID --env azure-dev` (it asks for the value) or `gh variable set AZURE_LOCATION --env azure-dev --body eastasia`.
8. **Run the deploy.** In the Actions tab, run the `deploy` workflow on `main`. Leave `allow_destroy` off. The workflow then:
   1. creates the registry if it is missing,
   2. copies PostgreSQL into the registry by digest, then builds and pushes our four images, tagged with the commit SHA. Our n8n image is the pinned n8n with our node pack inside (`deploy/n8n/Dockerfile`),
   3. creates the `db-init` job if it is missing and runs it, so the database roles exist before any app starts. This step also creates the Cosmos DB account, because the job reads its secrets from Key Vault and Key Vault holds the account's key. A new account takes about 5 to 10 minutes,
   4. creates or updates the `migrate` job with the new platform-api image and runs it, so the database is at the new schema before the new platform-api starts ([Migrations on a deploy](#migrations-on-a-deploy)). Step 3 already brought everything the job depends on up to date, so this apply changes only the job and its identity,
   5. plans everything, puts the count of changes in the run summary, and applies that exact plan,
   6. runs the `bootstrap` job, and prints the Portal's and platform-api's addresses and the Cosmos DB account's name.

   Each apply in steps 1, 3, 4 and 5 first saves its plan and checks it. If the plan would destroy or replace any resource, the deploy stops before that apply and prints only the counts. Run it again with `allow_destroy` ticked only when you mean it, for example after renaming a resource on purpose.

   The workflow never runs on a push. Only `workflow_dispatch` starts it. It prints summaries only: Terraform's summary lines, the plan's counts, the job names, the two public addresses and the Cosmos DB account's name. The full plan and Terraform's full output stay in files on the runner and are never uploaded. On a failure it prints Terraform's errors, which can name a resource.
9. **Add the Portal's redirect URIs.** In the Portal's app registration, add `https://<portal-host>/auth/callback` and `https://<portal-host>/signed-out` as single-page application redirect URIs, with the address the deploy printed. Sign-in works from then on. Repeat this after any deploy that creates a new environment, because its address changes.

### What to watch on the first deploy

These were not testable offline, so they are guesses until a real deploy confirms them:

- **Found on the first deploy, 31 Oct 2026:** Azure now creates a Container Apps environment as an *express* environment when the create request names no environment mode, even when it names a Consumption workload profile. Express runs no jobs and reads no Key Vault references, so `db-init` failed with `ExpressEnvironmentResourceNotSupported`. The setting is `properties.environmentMode`. Only preview API versions have it, and azurerm 5.7.0 cannot set it.
  - **What the fix does.** `modules/container_env` creates the environment with azurerm as before, then sends one PATCH through the `azapi` provider that sets `environmentMode` to `WorkloadProfiles`, with API version `2025-10-02-preview`. A PATCH by hand converted the live environment this way. It went through `Archived` on the way to `WorkloadProfiles`. So an express environment left from an earlier run no longer needs deleting.
  - **Why it comes first.** The module's two outputs wait for the PATCH, so every app and job is created only after it. That includes the deploy's targeted `db-init` apply, because `-target` also takes everything its target depends on.
  - **What a plan shows.** On an environment that is already converted, the first plan adds one resource, the action, and its PATCH changes nothing. Later plans show no change. The plan guard only stops on a destroy or a replace, so the deploy goes ahead.
  - **Why an action.** It is an `azapi_resource_action`, not an `azapi_update_resource`. That resource sends a PUT that keeps only the fields in azapi's own copy of the API, and that copy has no `environmentMode`, so it would drop the setting without an error. An action has nothing to read back, though. If the mode ever changes in Azure, Terraform does not see it. To send the PATCH again, replace the action by hand (`terraform apply -replace='module.container_env.azapi_resource_action.workload_profiles_mode'`). Removing the action from the code changes nothing in Azure.
- Azure RBAC can take a few minutes to reach Key Vault and the registry. Microsoft says up to 10 minutes. Each app's identity waits 90 seconds after its role assignments before its app is created. The deploy identity waits 90 seconds after giving itself AcrPush and Key Vault Secrets Officer, before it pushes images or writes secrets. The workflow also tries `az acr login` and each `docker push` up to five times, 30 seconds apart. If an app still fails to read a secret, or Terraform cannot write one, rerun the workflow.
- The workflow waits for each job twice as long as the job's own timeout: 600 seconds for `db-init` and `migrate`, and 1200 for `bootstrap`. Pulling the image on a cold start counts against the wait, not the timeout. If a wait still runs out, check the job's execution in the Azure portal before you rerun.
- `az acr import` should keep each image's digest, since the Terraform code pulls PostgreSQL by digest. If a pull fails with "manifest unknown", compare the digest in the registry with `public-images.json`.
- The Azure admin role is not a superuser. `db-init` grants itself membership in `n8n` and `wab_owner` before it hands them their databases. A local PostgreSQL 17 run showed that the handover fails without that grant and works with it. On Azure it is still untested.
- Container Apps ingress ends any request after 240 seconds. The live view's event stream reconnects on its own. Check that the live view keeps up after 4 minutes.
- A subscription may have only one free-tier Cosmos DB account. If one exists, from a test by hand for example, the create fails. Delete the other account first, or set `COSMOS_SERVERLESS=true`. Azure may also refuse the region, as some Azure for Students subscriptions only allow a few. Then set `COSMOS_LOCATION` to an allowed region.
- `free_tier_enabled` cannot change on an existing account. Changing `COSMOS_SERVERLESS` later replaces the account, so the deploy stops for `allow_destroy`. The copier fills a new account from PostgreSQL.

## Run the checks locally

You need Docker. Nothing else is installed, and nothing talks to Azure.

```sh
infra/scripts/check.sh            # print the results
infra/scripts/check.sh out/infra  # also save each tool's output in out/infra/
```

The script runs, each in a Docker image pinned by digest:

1. `terraform fmt -check -recursive`
2. `terraform init -backend=false`, then `terraform validate`, for each environment
3. `scripts/check-variables.sh`, which plans each environment's `variables.tf` alone with good sign-in values and with each kind of value that platform-api or the Portal would refuse at startup, or that would open n8n wider than meant
4. `terraform test`, which applies each environment's `tests/*.tftest.hcl` against mocked providers, with Langfuse off and on
5. `tofu init -backend=false`, then `tofu validate`, on a copy without the lock file
6. `scripts/check-n8n-editor-gate.sh`, which runs the deploy's gate for n8n's editor against a fake `az`
7. `scripts/check-langfuse-images.sh`, which fails when the Langfuse VM's images differ from `deploy/compose.yaml`'s `langfuse` profile
8. `tflint` with the `terraform` and `azurerm` rulesets (`.tflint.hcl`)
9. Checkov's Terraform checks

CI runs the same script in the `infra` workflow, only when a pull request changes `infra/` or one of the two infrastructure workflows. It also runs `actionlint` on every workflow. Semgrep's `p/terraform` rules run in the main CI's SAST step.

Accepted findings are written next to the code they are about, with a one-line reason, in each tool's own syntax: `#checkov:skip=`, `# tflint-ignore:` and `# nosemgrep:`. Most come from the Basic registry tier and from having no virtual network. A virtual network and private endpoints would cost more than the credits allow, and they arrive with the move to DevNet (ADR 0005). [docs/evidence/iac/](../docs/evidence/iac/README.md) lists the first ones, and [docs/evidence/deploy/](../docs/evidence/deploy/README.md) the ones the Cosmos DB account added.

## How AWS stays possible

ADR 0004 keeps a move to AWS open. This code does that in two ways:

- **Modules per concern.** Each module wraps one kind of cloud service: logs, secrets, registry, database, container runtime, identity. A move to AWS replaces each module with its AWS twin (CloudWatch, Secrets Manager, ECR, RDS for PostgreSQL, ECS on Fargate, IAM roles) and keeps the same `envs/` table of apps and settings. The tooling stays the same: Terraform, the S3 state backend, the same checks and the same plan-and-apply workflow.
- **No Azure-only logic in the apps, except one adapter.** The apps read plain environment variables and talk to PostgreSQL, HTTP and each other. They never call Key Vault or Managed Identity directly. The managed identities and Key Vault references live in this folder only. The one Azure SDK is `azure-cosmos`, in platform-api's Cosmos DB adapter behind the `ActivityLog` port. A move to AWS adds a DynamoDB adapter behind the same port, or sets `ACTIVITY_READER=postgres` (ADR 0031).
