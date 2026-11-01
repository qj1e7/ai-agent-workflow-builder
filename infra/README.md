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
| Container App | `n8n` | Internal ingress on 5678, 0.5 vCPU, exactly 1 replica |
| Container App | `portal` | External ingress on 8080, 0.25 vCPU, scales to zero |
| Container Apps Job | `db-init` | Creates the per-context database roles. Runs on every deploy |
| Container Apps Job | `bootstrap` | Migrations, n8n owner, workflow load and lint. Runs on every deploy |
| Managed identities | `id-<app>-wab-dev`, one per app and job | AcrPull on the registry, and Key Vault Secrets User on each secret it reads. platform-api's also has Cosmos DB's built-in Data Contributor role on the `activity` database |

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
  sql/db-init.sql      the role setup that the db-init job runs
  public-images.json   n8n and PostgreSQL, pinned by digest, copied into our registry
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
| `CALLBACK_ALLOWED_ORIGINS` | `http://platform-api:8000` | platform-api's HTTPS origin |
| `PRACTICE_JIRA_URL` (agent-runtime) | `http://platform-api:8000` | platform-api's HTTPS URL, or `practice_jira_url` when it is set |
| `COSMOS_ENDPOINT` | `http://cosmos:8081`, the emulator | the account's endpoint |
| `COSMOS_KEY` | the emulator's published key | a Key Vault secret, copied from the account |
| `ACTIVITY_READER` | `cosmos` by default | always `cosmos` |
| `TEAMS_CHANNEL` | `CODESparks Ops` unless `.env` sets it | the `TEAMS_CHANNEL` variable when it is set, else platform-api's default, `CODESparks Ops` |
| `TEAMS_WEBHOOK_URL` | `.env`, empty by default, so the practice Teams copy | a Key Vault secret from `TEAMS_WEBHOOK_URL`, only when that secret is set (ADR 0036) |
| `MAX_BODY_BYTES` | not set, so 2 MiB (2097152). platform-api refuses a larger request body with 413 | not set, so the same 2 MiB |
| `SETTINGS_ENCRYPTION_KEY` | `.env` | a generated Key Vault secret. If it is lost, an Operator pastes the model key again |
| `FIRST_OPERATOR`, `FIRST_APPROVERS` | `.env`, empty by default | from `first_operator` and `first_approvers`, only when they are set |
| n8n database settings | `postgres` host, password from `.env` | the server's host name, TLS on, password from Key Vault |
| `N8N_ENCRYPTION_KEY` | `.env` | Key Vault secret. It must never change |
| `N8N_SECURE_COOKIE` | `false`, for plain HTTP | not set, so n8n's default `true` applies over HTTPS |
| Portal `API_UPSTREAM` | `http://platform-api:8000` | platform-api's HTTPS URL |
| Portal `OIDC_AUTHORITY`, `OIDC_CLIENT_ID`, `OIDC_SCOPE` | not set | from secrets, for `/config.json`. `OIDC_AUTHORITY` is the same value as `OIDC_ISSUER` |

Apps call each other over HTTPS, because Container Apps redirects plain HTTP and our HTTP clients do not follow redirects. Traffic between apps in one environment stays inside it.

Every app's address comes from the Container Apps environment's default domain: `https://<app>.<domain>`, or `https://<app>.internal.<domain>` for an internal app. So the Portal and platform-api can each know the other's address without waiting for the other app to exist. Azure picks the domain when it creates the environment, so a new environment gets a new one.

## Known risk: the database is reachable from Azure

The PostgreSQL server has public access, with the firewall rule that lets Azure services in. That rule lets in any Azure customer's services, not only our apps. TLS and a 48-character generated password per role are what keep others out.

The Cosmos DB account has public access with no IP filter at all, like Key Vault, because the apps have no fixed outbound address and the checker reads items from a laptop. Its account key and Entra ID data roles keep others out. The key cannot change databases or containers, and the account holds only a copy of the activity log: PostgreSQL keeps every event.

The team lead accepted this for the dev and demo environment on 23 Oct 2026. Private networking comes with DevNet.

Changing it later is not a small edit. Private access needs the Container Apps environment inside a virtual network, and an environment cannot join one after it is created. So the move means recreating the environment, which also gives it a new domain and new app addresses.

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
7. **Set the environment's secrets and variables.** On the `azure-dev` environment, add these. The repository is public, so anyone can read the deploy's logs, and GitHub masks only secret values. So every value that names a person, an ID or the state storage goes under Secrets. Only the region and the Cosmos DB switches go under Variables.

   | Secret | Value |
   |---|---|
   | `AZURE_CLIENT_ID` | printed by the bootstrap script |
   | `AZURE_TENANT_ID` | printed by the bootstrap script |
   | `AZURE_SUBSCRIPTION_ID` | printed by the bootstrap script |
   | `GH_RELEASE_TOKEN` | optional. A GitHub token for the release checker, as [Secrets](#secrets) describes |
   | `TEAMS_WEBHOOK_URL` | optional. A Teams Workflows webhook's address, so approval cards go to a real channel (ADR 0036). Leave it unset for the practice Teams copy |
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

   | Variable | Value |
   |---|---|
   | `PRACTICE_JIRA_URL` | optional. Leave it unset, and agent-runtime reads platform-api's own practice Jira |
   | `TEAMS_CHANNEL` | optional. The Teams channel's name, as the approval card and the activity log name it. Unset means `CODESparks Ops` |
   | `AZURE_LOCATION` | optional. The region for every resource. Unset means `southeastasia`. Set it before the first deploy only: changing it later replaces everything, PostgreSQL included |
   | `COSMOS_LOCATION` | optional. A region for Cosmos DB alone, when it is refused in `AZURE_LOCATION` |
   | `COSMOS_SERVERLESS` | optional. `true` makes a serverless Cosmos DB account, for when the free tier is refused. Unset means `false` |

   With the GitHub CLI, each is one command, for example `gh secret set AZURE_TENANT_ID --env azure-dev` (it asks for the value) or `gh variable set AZURE_LOCATION --env azure-dev --body eastasia`.
8. **Run the deploy.** In the Actions tab, run the `deploy` workflow on `main`. Leave `allow_destroy` off. The workflow then:
   1. creates the registry if it is missing,
   2. copies n8n and PostgreSQL into the registry by digest, then builds and pushes our three images, tagged with the commit SHA,
   3. creates the `db-init` job if it is missing and runs it, so the database roles exist before any app starts. This step also creates the Cosmos DB account, because the job reads its secrets from Key Vault and Key Vault holds the account's key. A new account takes about 5 to 10 minutes,
   4. plans everything, puts the count of changes in the run summary, and applies that exact plan,
   5. runs the `bootstrap` job, and prints the Portal's and platform-api's addresses and the Cosmos DB account's name.

   Each apply in steps 1, 3 and 4 first saves its plan and checks it. If the plan would destroy or replace any resource, the deploy stops before that apply and prints only the counts. Run it again with `allow_destroy` ticked only when you mean it, for example after renaming a resource on purpose.

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
- The workflow waits for each job twice as long as the job's own timeout: 600 seconds for `db-init` and 1200 for `bootstrap`. Pulling the image on a cold start counts against the wait, not the timeout. If a wait still runs out, check the job's execution in the Azure portal before you rerun.
- `az acr import` should keep each image's digest, since the Terraform code pulls n8n and PostgreSQL by digest. If a pull fails with "manifest unknown", compare the digest in the registry with `public-images.json`.
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
3. `scripts/check-variables.sh`, which plans each environment's `variables.tf` alone with good sign-in values and with each kind of value that platform-api or the Portal would refuse at startup
4. `tofu init -backend=false`, then `tofu validate`, on a copy without the lock file
5. `tflint` with the `terraform` and `azurerm` rulesets (`.tflint.hcl`)
6. Checkov's Terraform checks

CI runs the same script in the `infra` workflow, only when a pull request changes `infra/` or one of the two infrastructure workflows. It also runs `actionlint` on every workflow. Semgrep's `p/terraform` rules run in the main CI's SAST step.

Accepted findings are written next to the code they are about, with a one-line reason, in each tool's own syntax: `#checkov:skip=`, `# tflint-ignore:` and `# nosemgrep:`. Most come from the Basic registry tier and from having no virtual network. A virtual network and private endpoints would cost more than the credits allow, and they arrive with the move to DevNet (ADR 0005). [docs/evidence/iac/](../docs/evidence/iac/README.md) lists the first ones, and [docs/evidence/deploy/](../docs/evidence/deploy/README.md) the ones the Cosmos DB account added.

## How AWS stays possible

ADR 0004 keeps a move to AWS open. This code does that in two ways:

- **Modules per concern.** Each module wraps one kind of cloud service: logs, secrets, registry, database, container runtime, identity. A move to AWS replaces each module with its AWS twin (CloudWatch, Secrets Manager, ECR, RDS for PostgreSQL, ECS on Fargate, IAM roles) and keeps the same `envs/` table of apps and settings. The tooling stays the same: Terraform, the S3 state backend, the same checks and the same plan-and-apply workflow.
- **No Azure-only logic in the apps, except one adapter.** The apps read plain environment variables and talk to PostgreSQL, HTTP and each other. They never call Key Vault or Managed Identity directly. The managed identities and Key Vault references live in this folder only. The one Azure SDK is `azure-cosmos`, in platform-api's Cosmos DB adapter behind the `ActivityLog` port. A move to AWS adds a DynamoDB adapter behind the same port, or sets `ACTIVITY_READER=postgres` (ADR 0031).
