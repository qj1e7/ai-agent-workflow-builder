---
status: accepted
---

# Write infrastructure as code in Terraform, and keep it working under OpenTofu

The walking skeleton deploys to Azure through CI, so the team must pick an infrastructure-as-code tool. CLAUDE.md left Terraform or Bicep open. [Prototype P5](../evidence/prototypes/p5-iac-terraform-vs-bicep/findings.md) wrote the same Azure setup in both, using the resource list from the [walking skeleton design](../design/walking-skeleton.md). Both expressed every resource with no workaround, including the Container Apps Job and a Key Vault secret reference. Both passed their offline checks. Terraform took 233 lines and Bicep 259. So the choice turns on what comes after the first deploy. We chose Terraform. The team lead accepted this on 22 Oct 2026. [ADR 0004](0004-host-on-azure-behind-ports-and-adapters.md) keeps a move to AWS open, and Terraform's language, plan and apply steps, state model and CI jobs carry over to AWS. Bicep only targets Azure. Semgrep, which our CI already runs, has Terraform rules, and P5 found no Semgrep rules for Bicep. The same Terraform code also passed unchanged under OpenTofu, its open-source fork, which gives us a way out if the licence becomes a problem.

## Considered options

- **Bicep.** It is Microsoft's own language for Azure, under the MIT licence. It keeps no state file, because Azure holds the state, so there is no storage account to set up and protect. It passed build and lint with no warnings. It lost because it only targets Azure and P5 found no Semgrep rules for it. Checkov, a separate IaC scanner, covers both. It is the better pick if the team decides the platform will only ever run on Azure.
- **OpenTofu as the main tool.** The same code ran unchanged, and its MPL 2.0 licence raises no questions at handover. We keep it as the fallback rather than the default, because the azurerm provider's own documentation and Microsoft's Azure guides are written for Terraform.

## Consequences

- Terraform keeps its state in an Azure storage account, which must exist before the first `terraform init`. A person creates it once, because changing cloud resources needs a human. State can hold secrets in plain text, so only the deploy identity can read it.
- Terraform is under the Business Source License 1.1. Using it to run our own platform, and NCS using it after handover, is allowed. If NCS does not accept BSL software, we switch to the OpenTofu binary. P5 only ran `validate` under OpenTofu, so a switch still needs a real plan to confirm it.
- Terraform and the azurerm provider are pinned. CI runs `terraform fmt -check` and `terraform validate`, and Semgrep's Terraform rules join the SAST job.
- Whichever tool we use, GitHub Actions needs an Azure identity to deploy. Some university tenants stop students from creating app registrations. On day one, try `az ad app create`. If it is refused, use a user-assigned managed identity with a federated credential, which needs rights on the Azure subscription rather than on the university's directory.
- If the team accepts this, "Terraform or Bicep" leaves the open decisions in `AGENTS.md` and `CLAUDE.md`.
