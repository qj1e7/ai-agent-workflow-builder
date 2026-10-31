# IaC evidence: offline checks of the Azure Terraform code

**Date.** 23 Oct 2026 (Singapore time).
**Code.** Branch `infra/terraform-azure`, the code in `infra/`, `.github/workflows/infra.yml` and `.github/workflows/deploy.yml`.
**Main command.** `infra/scripts/check.sh docs/evidence/iac`. The other commands are listed below.
**Azure.** No check here contacted Azure. No check had Azure credentials, and `terraform init` skipped the state backend. Every tool ran in a Docker image pinned by digest. This was true when the checks ran. Since then, on 31 Oct 2026, the one-time setup and the deploy workflow have run against Azure. "What these checks do not cover" says what that changes.

## What ran

| # | Check | Tool and version | Result | Output |
|---|---|---|---|---|
| 1 | `terraform fmt -check -recursive` | Terraform 1.16.5 | Clean. No file needs formatting | `terraform-fmt.txt` (empty on purpose) |
| 2 | `terraform init -backend=false`, then `terraform validate` | Terraform 1.16.5 | "Success! The configuration is valid." | `terraform-validate-dev.txt` |
| 3 | `infra/scripts/check-variables.sh`: `terraform plan` on a module that holds only `envs/dev/variables.tf`, with good sign-in values and with each kind of value platform-api or the Portal refuses at startup | Terraform 1.16.5 | All 24 cases as expected: 3 accepted, 21 refused, each by the right variable's rule | `terraform-variables-dev.txt` |
| 4 | `tofu init -backend=false`, then `tofu validate`, on a copy without the lock file | OpenTofu 1.12.7 | "Success! The configuration is valid." | `tofu-validate-dev.txt` |
| 5 | `tflint --recursive`, with the `terraform` ruleset (all rules) and the `azurerm` ruleset 0.32.0 | TFLint 0.64.0 | 0 issues, after 3 accepted findings | `tflint.txt` |
| 6 | Checkov, Terraform checks | Checkov 3.3.20 | Passed 6, Failed 0, Skipped 15 | `checkov.txt` |
| 7 | Semgrep `p/terraform`, `p/nginx` and `p/github-actions` on `infra/`, `.github/` and `portal/nginx/` | Semgrep 1.179.0 | 81 rules on 45 files, 0 findings, after 1 accepted finding | `semgrep.txt` |
| 8 | actionlint on every workflow | actionlint 1.7.12 | 0 errors in 4 files | `actionlint.txt` |
| 9 | ShellCheck on `setup-azure.sh` and the six scripts in `infra/scripts/` | ShellCheck 0.11.0 | No findings, exit 0 | `shellcheck.txt` |
| 10 | `infra/sql/db-init.sql`, run twice with the `db-init` job's own command, as a non-superuser admin with CREATEROLE and CREATEDB | PostgreSQL 17, the digest in `infra/public-images.json` | Both runs exit 0. `n8n` owns `n8n`, `wab_owner` owns `platform`, all five roles sign in, none is a superuser | `db-init.txt` |
| 11 | `portal/nginx/render.test.sh`, the Portal's nginx render test from the sign-in work | nginx 1.27-alpine | 24 of 24 pass. Each render runs `nginx -t`, so the `proxy_ssl_server_name on` line passes | `portal-render-test.txt` |
| 12 | The Portal's nginx with the settings Terraform gives it on Azure | nginx 1.27-alpine | An earlier draft of this pull request left out `OIDC_SCOPE`, and with those settings the Portal refuses to start ("OIDC_SCOPE is not set"). With the settings Terraform gives it now, it passes `nginx -t` and serves the sign-in settings. The sign-in pull request has no Terraform, so the gap was only ever in this pull request | `portal-azure-render.txt` |
| 13 | `terraform test` with mocked providers, on a copy of `infra/` with two test-only outputs: agent-runtime's secret names and the vault's secret names | Terraform 1.16.5 | Without `github_token`, agent-runtime gets only `AGENT_API_KEY` and the vault has no `github-token`. With it, agent-runtime also gets `GITHUB_TOKEN` and the vault stores it. 2 of 2 pass | `terraform-github-token-test.txt` |
| 14 | Gitleaks, CI's `detect --no-git` over the working tree, and `detect` over the git history of the review-fix commits | Gitleaks 8.21.2 | No leaks found in either scan | `gitleaks.txt` |
| 15 | The destroy guard: `plan-guard.sh` on real saved plans, then `guarded-apply.sh` end to end, on a scratch module of `terraform_data` resources | Terraform 1.16.5, jq | A destroy or a replace, in either order, is refused unless `allow_destroy` is true, and the refusal leaves the state untouched. Adds, in-place changes, no change and a targeted update pass. Empty input and JSON that is not a plan are refused. Only counts are printed | `plan-guard-test.txt` |

Rows 1 to 6 are `check.sh`. CI runs the same script in the `infra` workflow. CI's own SAST step also runs Semgrep with all eight of its rule sets, now with `p/terraform`, over the whole repository. We ran that exact rule list too: 313 rules on 315 files, 0 findings. Its output is not saved, because it starts with a Git warning from the worktree setup.

Two more things were checked by hand and not saved:

- The azurerm provider 5.7.0 still has `resource_provider_registrations`, and `terraform validate` accepts `"none"`. A made-up value is refused with the list `core`, `extended`, `all`, `none`, `legacy`.
- The provider's source at v5.7.0 shows that creating the Key Vault, the registry and the PostgreSQL server needs no rights outside the resource group. The Key Vault's check for a soft-deleted vault of the same name reads the subscription, and the provider carries on when that read is refused.

### Images

| Tool | Image |
|---|---|
| Terraform | `hashicorp/terraform:1.16.5@sha256:c7926feace05d0f7e73542842bf3945924e955a1f782cf000ccbb8d18fa42d77` |
| OpenTofu | `ghcr.io/opentofu/opentofu:1.12.7@sha256:3f068ee39a7233d39d9179fb2116a052a6fecdc350dfe2fccebb45b17ef1aa86` |
| TFLint | `ghcr.io/terraform-linters/tflint:v0.64.0@sha256:1c595f42d794c32c45a6ea8b58655fd66433d4ca3b1bc631c574a48d120bd19f` |
| Checkov | `bridgecrew/checkov:3.3.20@sha256:6d20ebbcde58b2dce6e3151a6771fefa4d468281fe442475455623f5799b9f53` |
| Semgrep | `semgrep/semgrep:1.179.0@sha256:93963d9295a366f59e4850127b1550400ee7b388f04fe144e4a1f6325d96e01b` |
| actionlint and ShellCheck | `rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667` |
| PostgreSQL | `postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3` |
| nginx | `nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10` |
| Gitleaks | `zricethezav/gitleaks:v8.21.2@sha256:0e99e8821643ea5b235718642b93bb32486af9c8162c8b8731f7cbdc951a7f46` |

The Terraform providers are pinned to azurerm 5.7.0, random 3.9.1 and time 0.14.2. The lock file has hashes for five platforms for each of them.

## Accepted findings

Each one is written next to its code, with its reason, in the tool's own syntax: `#checkov:skip=`, `# tflint-ignore:` or `# nosemgrep:`. Most come from two choices. The registry is on the Basic tier, because Premium costs about USD 50 a month. And there is no virtual network, because a network and private endpoints cost more than the credits allow. Both come back with the move to DevNet (ADR 0005).

### Checkov (15)

| Rule | Where | Why we accept it |
|---|---|---|
| CKV_AZURE_109 | Key Vault | No firewall. The deploy runs on GitHub-hosted runners with changing IP addresses, and Container Apps without a virtual network reach the vault over its public endpoint. Role-based access on each secret is the control. |
| CKV_AZURE_189 | Key Vault | Public network access stays on, for the same reason. |
| CKV2_AZURE_32 | Key Vault | A private endpoint needs a virtual network and costs about USD 7 a month. It comes with DevNet. |
| CKV_AZURE_41 | Key Vault secrets | The generated secrets do not expire. An expired secret would stop every app that reads it, and nothing rotates them yet. |
| CKV_AZURE_136 | PostgreSQL | Geo-redundant backup doubles the backup cost. Seven days of local backups are enough for a dev environment. |
| CKV2_AZURE_57 | PostgreSQL | A private endpoint needs a virtual network. The server takes TLS only, and every role has a long generated password. It comes with DevNet. |
| CKV2_AZURE_26 | PostgreSQL firewall rule | The rule that lets Azure services in is needed while the apps have no virtual network. It admits any Azure customer's services, not only ours. TLS is required, and every role has a 48-character generated password. The team lead accepted this risk for the demo environment on 23 Oct 2026. See "Known risk" in [infra/README.md](../../../infra/README.md). |
| CKV_AZURE_139 | Registry | The Basic tier cannot turn off public network access. |
| CKV_AZURE_165 | Registry | Geo-replication needs Premium. |
| CKV_AZURE_166 | Registry | Quarantine needs Premium. |
| CKV_AZURE_167 | Registry | Retention of untagged images needs Premium. |
| CKV_AZURE_233 | Registry | Zone redundancy needs Premium. |
| CKV_AZURE_237 | Registry | Dedicated data endpoints need Premium. |
| CKV_AZURE_163 | Registry | Image scanning needs Microsoft Defender for Containers, a paid plan. |
| CKV_AZURE_164 | Registry | Signed images need Premium. Only the reviewed deploy workflow pushes images. |

### TFLint (3)

| Rule | Where | Why we accept it |
|---|---|---|
| `azurerm_resources_missing_prevent_destroy` | Key Vault | Purge protection already keeps a deleted vault and its secrets for 7 days. |
| `azurerm_resources_missing_prevent_destroy` | PostgreSQL | The dev data can be thrown away, and `terraform destroy` is how the team stops spending credits. |
| `terraform_unused_required_providers` | `time` provider in `envs/dev` | Only a child module uses it. The root pins its exact version. |

### Semgrep (1)

| Rule | Where | Why we accept it |
|---|---|---|
| `keyvault-ensure-secret-expires` | Key Vault secrets | The same reason as CKV_AZURE_41. |

### Added with the Cosmos DB account (P14, 31 Oct 2026)

These are offline checks too, like the rest of this page. The deploy of the rebuilt app (P14) added `infra/modules/cosmos/` and accepted five more findings, written next to its code in the same way. With them, Checkov skips 19 checks in all and TFLint ignores 6 findings. The run that shows them is `docs/evidence/deploy/infra-checks/`: Checkov passed 7, failed 0 and skipped 19, and TFLint found 0 issues. [The deploy evidence](../deploy/README.md) lists them too.

| Tool | Rule | Where | Why we accept it |
|---|---|---|---|
| Checkov | CKV_AZURE_140 | Cosmos DB account | Local auth stays on, because platform-api signs in with the account key today. The key is in Key Vault, and platform-api's identity already has the data role, so turning it off is a code change in platform-api plus one line in `modules/cosmos/main.tf`. |
| Checkov | CKV_AZURE_99 | Cosmos DB account | No IP or network filter. Container Apps without a virtual network have no fixed outbound address. The key and the data roles are the control, as for Key Vault. |
| Checkov | CKV_AZURE_101 | Cosmos DB account | Public network access stays on, for the same reason. A private endpoint comes with DevNet (ADR 0005). |
| Checkov | CKV_AZURE_100 | Cosmos DB account | Microsoft-managed keys encrypt the data. A customer-managed key needs a Key Vault key and an identity for the account, for an account that holds only a copy of the activity log. |
| TFLint | `azurerm_resources_missing_prevent_destroy` | Cosmos DB account, its `activity` database and its `run_events` container, one finding each | They hold only a copy. PostgreSQL keeps every event, and the copier fills a new account, so `terraform destroy` stays the way to stop spending credits. |

One Checkov check passes that the account could have failed: CKV_AZURE_132, because the account key may not create or change databases and containers (`access_key_metadata_writes_enabled = false`, `infra/modules/cosmos/main.tf:27`).

## What these checks do not cover

- **Azure itself.** These checks planned nothing against Azure and applied nothing. The deploy workflow did, after they ran, on 31 Oct 2026. Run 41158792708 stopped at the Azure sign-in. Run 41158886844 applied Terraform until Azure refused to create the Cosmos DB account in East Asia, because of high demand there. The next deploy is set to put that account in koreacentral (`COSMOS_LOCATION`). The infra README lists what to watch on a deploy. What the deploys show about regions, quotas, role assignments, Key Vault references and `az acr import` belongs with the deploy, not with these checks.
- **The one-time setup.** These checks did not run `infra/bootstrap/setup-azure.sh`. It ran on 31 Oct 2026, and every step finished, including the role assignment with the condition that follows Microsoft's "Constrain ACR management" example.
- **The deploy workflow.** These checks did not run it. Its first runs, on 31 Oct 2026, are described under "Azure itself" above.
- **Sign-in on Azure.** Row 12 shows the Portal starts with Terraform's settings. Signing in through Entra ID on Azure is not tested.

## Run the checks again

```sh
# Rows 1 to 6
infra/scripts/check.sh docs/evidence/iac

# Row 7
docker run --rm --volume "$PWD:/src:ro" --workdir /src \
  semgrep/semgrep:1.179.0@sha256:93963d9295a366f59e4850127b1550400ee7b388f04fe144e4a1f6325d96e01b \
  semgrep scan --config p/terraform --config p/nginx --config p/github-actions \
  --metrics=off --error infra .github portal/nginx

# Row 8
docker run --rm --volume "$PWD:/repo:ro" --workdir /repo \
  rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667

# Row 9
docker run --rm --volume "$PWD:/repo:ro" --workdir /repo --entrypoint shellcheck \
  rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667 \
  infra/bootstrap/setup-azure.sh infra/scripts/*.sh

# Row 11
portal/nginx/render.test.sh

# Row 14, the scan CI runs
docker run --rm --volume "$PWD:/repo:ro" \
  zricethezav/gitleaks:v8.21.2@sha256:0e99e8821643ea5b235718642b93bb32486af9c8162c8b8731f7cbdc951a7f46 \
  detect --no-git --source /repo --redact --verbose
```

Rows 10, 12, 13 and 15 were one-off runs. Each output file starts with what was run.
