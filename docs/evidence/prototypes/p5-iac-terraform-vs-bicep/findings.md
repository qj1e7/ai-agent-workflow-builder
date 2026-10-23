# IaC prototype: Terraform / OpenTofu vs Bicep

Throwaway prototype, run on 20 Oct 2026. Nothing touched a cloud account. All tools ran in Docker and the containers are removed.
Labels: **observed** (I ran it, raw file named), **from docs** (URL), **assumed**.

Folders: `terraform/` (same `.tf` files were also run under OpenTofu), `bicep/`, raw output in `raw/`.

## Versions table (all observed, pulled 20 Oct 2026)

| Tool | Version | Image digest | Released |
|---|---|---|---|
| Terraform | 1.16.5 | hashicorp/terraform@sha256:c7926feace05d0f7e73542842bf3945924e955a1f782cf000ccbb8d18fa42d77 | 2 Oct 2026 |
| OpenTofu | 1.12.7 | ghcr.io/opentofu/opentofu@sha256:3f068ee39a7233d39d9179fb2116a052a6fecdc350dfe2fccebb45b17ef1aa86 | 1 Oct 2026 |
| azurerm provider | = 5.7.0 (pinned) | n/a | 24 Sep 2026 |
| Azure CLI | 2.90.0 | mcr.microsoft.com/azure-cli@sha256:e3768dde8142efa45d8f356a317aaac77abd7da15ba3719b0a150e9453f251db | 1 Sep 2026 |
| Bicep CLI (via `az bicep install`) | 0.48.1 | downloaded inside the container | 5 Oct 2026 |
| Checkov | 3.3.20 | bridgecrew/checkov@sha256:6d20ebbcde58b2dce6e3151a6771fefa4d468281fe442475455623f5799b9f53 | before 6 Oct 2026 |
| Semgrep | 1.179.0 | semgrep/semgrep@sha256:93963d9295a366f59e4850127b1550400ee7b388f04fe144e4a1f6325d96e01b | 2 Oct 2026 |

Release dates come from the GitHub and Docker Hub APIs. Bicep 0.48.1 is 15 days old, azurerm 5.7.0 is 26 days old. Raw: `raw/01-tf-version.txt`, `01-tofu-version.txt`, `02-az-version.txt`, `05-checkov-version.txt`, `05-semgrep-version.txt`.

## 1. Terraform and OpenTofu on the same code (observed)
- Terraform: `init -backend=false` passed, `validate` passed, `fmt -check` passed. Provider azurerm 5.7.0 installed. First try, no edits after writing. Raw: `raw/01-tf-init.txt`, `01-tf-validate.txt`, `01-tf-fmt.txt`.
- OpenTofu: I copied the `.tf` files to a clean folder with no lock file. The SHA-256 of every file matched (`raw/01-code-hashes-*.txt`). `tofu init -backend=false`, `validate` and `fmt -check` all passed. It installed the same azurerm 5.7.0. Raw: `raw/01-tofu-init.txt`, `01-tofu-validate.txt`, `01-tofu-fmt.txt`.
- Answer: yes, the same unchanged code passes in both.
- Limit: validate only checks syntax and the provider schema. It does not prove Azure accepts the values (for example names, SKUs, regions). Nothing here was applied.

## 2. Bicep build and lint (observed)
- `az bicep build` of `main.bicep` and `resources.bicep` to ARM JSON: exit 0, zero errors, zero warnings.
- `az bicep lint` on both files: exit 0, zero warnings. `az bicep format` produced one change on my first draft (a for-loop layout). I applied it. After that both files are format-clean.
- Raw: `raw/02-bicep-build-lint.txt`, `02-main.json`, `02-resources.json`.
- Same limit as above: a clean build does not prove ARM will accept the API versions and properties.

## 3. Coverage (observed in the code, not applied)
Every resource in the list is expressed in both tools, with no workaround:
Log Analytics, App Insights, Container Apps environment, three Container Apps, the Container Apps Job with a manual trigger, PostgreSQL Flexible Server 17 with `B_Standard_B1ms` and two databases, Static Web App Free, Key Vault, user-assigned identity, the Key Vault Secrets User role, and the Key Vault reference secret on platform-api (only the secret URL goes into the app).

Gaps and notes, none blocking:
- Bicep needs a two-file layout (subscription-scope `main.bicep` that creates the resource group, plus a module). Terraform creates the resource group in the same folder.
- Bicep and Terraform both need the deployer to hold a Key Vault write role before the secret can be created. I added a deployer role assignment in both. In real use the deploy identity needs permission to create role assignments (Owner or User Access Administrator). This is **assumed** from how Azure RBAC works.
- Static Web Apps only exist in some regions. `southeastasia` is probably not one of them. This is **assumed** and I did not check the region list. The Static Web App `location` should be its own parameter in both versions.
- The Postgres admin password and `database_url` are inputs (`sensitive = true` in Terraform, `@secure()` in Bicep). No secret is in any file. Terraform will keep both values in its state file (**assumed** from how Terraform works). Bicep deployments do not store `@secure()` values in deployment history (**assumed**, not checked in docs).
- The "bootstrap" job is defined, not run.

## 4. Size (observed, `raw/04-loc.txt`)
Non-blank, non-comment lines. Neither variant has comments.

| Variant | Files | Lines |
|---|---|---|
| Terraform | main.tf 186, variables.tf 27, versions.tf 13, outputs.tf 7 | 233 |
| Bicep | resources.bicep 233, main.bicep 26 | 259 |

About equal. Bicep is longer here mostly because of the extra subscription-scope wrapper and the nested JSON-like properties. For one language read by non-experts, this is a wash.

## 5. Security scan (observed)
**Checkov 3.3.20** supports both. Terraform framework and Bicep framework both ran with 0 parsing errors. Raw: `raw/05-checkov-terraform.json`, `05-checkov-bicep.json`, `05-checkov-both-cli.txt`.

| Folder | Resources scanned | Passed | Failed | Severity |
|---|---|---|---|---|
| terraform | 17 | 3 | 7 | all 7 have severity `None` |
| bicep | 14 | 6 | 5 | all 5 have severity `None` |

Checkov gives no severity in the free CLI (everything is `None`). So the count by severity is: 12 findings, 0 High, 0 Medium, 0 Low, 12 unrated.

Terraform failures: CKV2_AZURE_32 (Key Vault private endpoint), CKV2_AZURE_57 (Postgres private endpoint), CKV_AZURE_109 (Key Vault firewall), CKV_AZURE_114 (secret content type), CKV_AZURE_136 (Postgres geo-redundant backup), CKV_AZURE_189 (Key Vault public access), CKV_AZURE_41 (secret expiry).
Bicep failures: CKV_AZURE_109, CKV_AZURE_114, CKV_AZURE_189, CKV_AZURE_41, and CKV_AZURE_42 (Key Vault recoverable).

Differences worth knowing: Checkov has two Terraform-only checks here (the private endpoint and geo-backup ones) and one Bicep-only failure (CKV_AZURE_42, which wants `enableSoftDelete` set explicitly; I did not set it). So the two rule sets are not equal in depth. Terraform gets more checks. I did not investigate whether the Bicep rule set misses those same checks or just does not model them.

**Semgrep 1.179.0** (`raw/05-semgrep-terraform.txt`, `05-semgrep-bicep.txt`, `05-semgrep-terraform-findings.txt`):
- `--config p/terraform` on `terraform/`: 63 rules, 4 files scanned, 1 finding (INFO, secret expiry, `main.tf` line 56).
- The same config on `bicep/`: "Nothing to scan", 0 files. Semgrep has no Bicep rules or parser in this setup. I did not check whether any other Semgrep rule pack handles Bicep.
- So Semgrep in CI covers Terraform and not Bicep. Checkov would be needed for Bicep. Checkov also works for Terraform.

## 6. Plan / what-if with no credentials (observed, one run each)
- `terraform plan` (`raw/06-tf-plan-nocreds.txt`): `Error: unable to build authorizer for Resource Manager API: could not configure AzureCli Authorizer: could not parse Azure CLI version: launching Azure CLI: exec: "az": executable file not found in $PATH`. The Terraform container has no `az`. On a laptop with `az` and no login, the message would be different; I did not test that.
- `az deployment sub what-if` (`raw/06-bicep-whatif-nocreds.txt`): `ERROR: Please run 'az login' to setup account.`
- Both need a login. Neither can preview offline. Terraform `validate` and Bicep `build` are the offline checks.

## 7. State
- **Terraform azurerm backend (from docs).** You need a storage account and a private blob container made before the first `init`. The backend settings are `storage_account_name`, `container_name`, `key`, plus auth. State is stored as plain text and can contain secrets, so lock the account down. Blobs are locked automatically during writes. https://learn.microsoft.com/en-us/azure/developer/terraform/store-state-in-azure-storage
- **CI auth for the backend (from docs).** Entra ID is recommended, with OIDC for GitHub Actions: set `use_oidc = true`, `use_azuread_auth = true`, `tenant_id`, `client_id`. The client ID can belong to an app registration or a user-assigned managed identity. The identity needs Storage Blob Data Contributor on the container. Access key and SAS token also work but are not recommended. https://developer.hashicorp.com/terraform/language/backend/azurerm
- **Chicken and egg.** The state storage account has to be created outside the main code, by hand or by a small bootstrap script. This is **assumed** from the doc steps above, which create it first.
- **Bicep (from docs).** No state file. "Azure stores all states." `what-if` reads the live environment. https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/overview
- Cost of that: Bicep never deletes things you removed from the file unless you use a complete-mode deployment or deployment stacks. This is **assumed** from my knowledge of ARM and not checked in docs this run.

## 8. Licences
| Tool | Licence | Source |
|---|---|---|
| Terraform | BSL 1.1 (Licensed Work: Terraform 1.6.0 or later, copyright IBM Corp.; change date four years after each release; then MPL 2.0) | **from docs**: https://github.com/hashicorp/terraform/blob/main/LICENSE and https://www.hashicorp.com/en/bsl |
| OpenTofu | MPL 2.0 | **from docs**: https://github.com/opentofu/opentofu/blob/main/LICENSE |
| Bicep | MIT, copyright Microsoft | **from docs**: https://github.com/Azure/bicep/blob/main/LICENSE |

What BSL means here (from the HashiCorp BSL page above):
- Production use is allowed. The one limit is offering Terraform to third parties as a paid hosted or embedded product that competes with HashiCorp's paid versions.
- Using it for internal purposes within an organization is not a competitive offering, per that page. So our FYP use and NCS running it for CODESparks is fine.
- A handover to NCS is fine for internal use. NCS would only have a problem if it resold a Terraform-based product. Source use is separate from this: the code we write in HCL is ours. The BSL covers the Terraform tool, not our `.tf` files.
- Plain-language risk: BSL is not "open source" by the OSI definition, so some company policies ban it. Whether NCS has such a policy is **unknown**. Ask NCS. This is not legal advice.
- OpenTofu runs the same HCL (observed in item 1), so it is the fallback if the BSL is a blocker.
- The azurerm provider is licensed separately. I believe it is MPL 2.0 but did not check this run (**assumed**).

## 9. AWS portability (honest view)
The resource code does not port in either tool. Container Apps, Flexible Server, Static Web Apps and Key Vault have no one-to-one AWS names, and the resource types differ (`azurerm_*` vs `aws_*`). In Bicep, nothing at all ports, because Bicep only targets Azure/ARM.

What carries over:
- Terraform / OpenTofu (**assumed**, from how they work): the language (HCL), variables and modules patterns, the `init / validate / plan / apply` flow, the state model (remote state file plus locking, with an S3 backend instead of azurerm), the CI steps, and the same tool for a second cloud. A team that knows HCL needs to learn a new provider, not a new tool. Our ports-and-adapters code split would map to separate modules per cloud.
- Bicep (**assumed**): only habits and concepts. The workflow of build, lint, what-if, deploy does not exist for AWS (CloudFormation or CDK would be a new tool). The Docker images, n8n and the app code are unaffected in both cases.

## 10. CI deploy auth on Azure for Students
The question is whether a GitHub Actions deploy can authenticate. This affects both tools equally.

- **From docs.** By default every Entra user can register applications. A tenant admin can switch "Users can register applications" to No, and then you get "Access denied: You don't have permission to register applications in the directory". https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/delegate-app-roles
- **From credible community sources, not official docs.** Microsoft Q&A threads say students on Azure for Students often hit this app-registration error and often lack full Entra access, and the moderator answer points to the tenant admin setting above. Examples: https://learn.microsoft.com/en-us/answers/questions/1858836/unable-to-create-application-in-azure-student-acco and https://learn.microsoft.com/en-us/answers/a/1641494. I did not find an official statement that Azure for Students itself blocks service principals. So: whether it works depends on the university tenant, and I could not verify NUS's tenant setting. **Unverified.**
- **A way around it, from docs.** GitHub Actions can authenticate to Azure with a federated credential on a **user-assigned managed identity**. That is an Azure resource, not an app registration. To create it you need Contributor or Owner on the subscription, not an Entra directory role. The Terraform azurerm backend also accepts a managed identity client ID. https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-create-trust-user-assigned-managed-identity and https://developer.hashicorp.com/terraform/language/backend/azurerm
- **Still assumed.** That the student account has Owner or Contributor on the student subscription (likely, not checked), and that `azure/login` with a managed identity client ID works end to end from a private repo on a student subscription. I did not test either.
- **Cheap test the team can run on day one:** `az ad app create --display-name test` and `az identity create`. If the first fails and the second works, use the managed identity path. If both fail, the fallback is a personal Azure account or a manual deploy.
- Neither IaC tool changes this risk. Terraform has one extra piece, the state storage account, which also needs the same identity.

## Platform-api Container App with Key Vault secret reference

Terraform (`terraform/main.tf`):
```hcl
resource "azurerm_container_app" "platform_api" {
  name                         = "platform-api"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.apps.id
  }

  template {
    min_replicas = 1
    container {
      name   = "platform-api"
      image  = local.placeholder_image
      cpu    = 0.5
      memory = "1Gi"
      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  depends_on = [azurerm_role_assignment.apps_secrets_user]
}
```

Bicep (`bicep/resources.bicep`):
```bicep
resource platformApi 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'platform-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
      }
      secrets: [
        {
          name: 'database-url'
          keyVaultUrl: databaseUrlSecret.properties.secretUri
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'platform-api'
          image: placeholderImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'DATABASE_URL', secretRef: 'database-url' }
          ]
        }
      ]
      scale: { minReplicas: 1 }
    }
  }
  dependsOn: [appsSecretsUser]
}
```
Both hold only the Key Vault reference (a versionless secret URL plus the identity). The value is never in the app definition. The secret value still passes through the pipeline once, as a sensitive or secure input, when the vault secret is created.

## Facts table

| Point | Terraform | OpenTofu | Bicep |
|---|---|---|---|
| Covers our full resource list | Yes (observed) | Yes, same code (observed) | Yes (observed) |
| Offline checks pass | validate + fmt (observed) | validate + fmt (observed) | build + lint + format (observed) |
| Lines of code | 233 | 233 (same files) | 259 |
| Checkov | 7 failed / 3 passed | same files, not rerun | 5 failed / 6 passed |
| Semgrep rules | Yes, 1 INFO finding | Yes (same HCL) | None (0 files scanned) |
| Preview needs login | Yes (observed) | not run | Yes (observed) |
| State | Remote file in storage, set up first (docs) | same (assumed) | None, Azure holds it (docs) |
| Licence | BSL 1.1 (docs) | MPL 2.0 (docs) | MIT (docs) |
| Runs on AWS later | Same tool, new provider code (assumed) | same (assumed) | No (assumed) |
| New Azure features | Wait for provider release (assumed) | same | Available as soon as ARM has them (docs) |
| CI auth risk on student sub | Same, plus state account | same | Same |
| Maintainability for non-technical staff | Both are code; neither is zero-coding | | |

## My recommendation (mine, not a fact)
Use Terraform syntax, run it with OpenTofu if NCS rejects the BSL, and treat the pick as low risk because both tools passed the same checks. The deciding reasons are AWS portability of the workflow, Semgrep covering HCL in the CI we already have, and that the team already wrote ADRs assuming portability. Bicep is a good choice if the team decides Azure-only is enough, since it has no state file to set up and secure, and that removes one moving part from the student subscription. Whichever is picked, run the day-one auth test in item 10 before anything else, because it can block both.

## Not verified
- Nothing was applied or planned against Azure, so real-world errors (names, regions, quotas, Static Web App region, Postgres SKU in the region, Student offer limits) are unknown.
- NUS tenant settings for app registration.
- Whether NCS accepts BSL software.
- azurerm provider licence, Bicep deletion behaviour, and the AWS portability points were not checked against sources.
- Checkov's Bicep rule depth versus Terraform beyond these counts; Semgrep Bicep support beyond the `p/terraform` pack.
