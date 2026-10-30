# One-time Azure setup

Terraform keeps its state in an Azure storage account, and GitHub Actions needs an Azure identity to deploy. Neither can be created by the Terraform code that depends on them, so a person creates both once with [`setup-azure.sh`](setup-azure.sh). Changing cloud resources needs a human (`AGENTS.md`), so no agent or workflow runs this script.

## Before you start

- Steps 1 to 4 of [the main README's one-time steps](../README.md#one-time-human-steps-before-the-first-deploy) are done: the owner account is on GitHub Pro, the teammates are collaborators, `main` is protected, and the `azure-dev` environment exists, limited to `main`. This script makes Azure trust that environment, so it must exist first.
- You have the Azure CLI and are signed in with `az login`.
- Your account is an Owner of the Azure for Students subscription. The script creates role assignments, which Contributor cannot do.
- You picked a storage account name. It must be 3 to 24 lowercase letters and digits, and unique across Azure, for example `stwabtfstate` plus your initials.

## Run it

```sh
STATE_ACCOUNT=<storage-account-name> infra/bootstrap/setup-azure.sh <github-owner>/<repo>
```

The script does five things, and each is safe to run again:

1. It registers the Azure resource providers that the environment uses. The deploy identity has no rights on the subscription, so the Terraform code cannot register them itself (`resource_provider_registrations = "none"`). Cosmos DB's provider, `Microsoft.DocumentDB`, joined the list for the rebuild's deploy. If you ran the script before that, run it again, or run `az provider register --namespace Microsoft.DocumentDB --wait` once.
2. It creates the resource group `rg-wab-tfstate` and the state storage account. Access keys are off (`--allow-shared-key-access false`), so the only way in is an Entra ID identity with a data role. Blob versioning and 30 days of soft delete let you recover an overwritten or deleted state file. It also creates the private `tfstate` container.
3. It creates the resource group `rg-wab-dev`, where Terraform puts the whole environment. Terraform reads this group but never creates or deletes it, so `terraform destroy` leaves it behind, empty.
4. It creates the user-assigned managed identity `id-wab-deploy` and a federated credential that trusts GitHub's OIDC tokens for the `azure-dev` environment of your repository. This needs no app registration, so it works even when the university tenant blocks app registrations (ADR 0013).
5. It gives the deploy identity three roles, none of them on the whole subscription:
   - Storage Blob Data Contributor on the `tfstate` container only.
   - Contributor on `rg-wab-dev`, to create the environment's resources. That includes Cosmos DB's own data roles, which are not Azure roles, so the condition below does not cover them. The Terraform code gives one, to platform-api's identity. Contributor can already read the Cosmos DB account's keys, so the data role gives the deploy no reach it did not have.
   - Role Based Access Control Administrator on `rg-wab-dev`, with a condition. It may only assign or remove AcrPull, AcrPush, Key Vault Secrets User and Key Vault Secrets Officer, which are the only roles the Terraform code assigns. And it may only give them to service principals, such as our managed identities, never to a person or a group. The condition follows Microsoft's ["Constrain ACR management" example](https://learn.microsoft.com/en-us/azure/role-based-access-control/delegate-role-assignments-examples#example-constrain-acr-management).

At the end the script prints five values. Put the three Azure IDs on the `azure-dev` GitHub environment as secrets, and the two state values as variables, as step 7 of [the main README](../README.md#one-time-human-steps-before-the-first-deploy) describes.

## Who can act as the deploy identity

The federated credential trusts any workflow job that names the `azure-dev` environment, whatever branch it runs on. The environment's rules decide which jobs those are. While the repository is private on GitHub Pro, the gate is:

- Only `main` can deploy, because `azure-dev` only accepts `main`. And `main` only takes pull requests that someone other than the author approved, so only reviewed code can deploy.
- A person starts each deploy by hand. Anyone with write access can start one.
- No second person approves each run. Required reviewers on an environment need a public repository or GitHub Enterprise. Instead, the deploy stops before any apply that would destroy or replace a resource, unless the person who starts it ticks `allow_destroy`.

Two things break the gate, so avoid both:

- A missing environment. A workflow that names one that does not exist creates it, with no rules. That is why `azure-dev` must exist before this script runs.
- Looser rules. Do not add other branches to `azure-dev`, and do not let anyone bypass the protection on `main`.

If the repository is made public later, add required reviewers and "Prevent self-review" to `azure-dev`.

## Why the state needs this care

Terraform state holds every generated secret in plain text: the database passwords, `STEP_KEY`, `AGENT_API_KEY`, `CALLBACK_SIGNING_KEY`, `SETTINGS_ENCRYPTION_KEY`, the n8n encryption key and the Cosmos DB account key, plus the GitHub token when one is set. Anyone who can read the state file can read those secrets. With access keys off, only identities with a blob data role can read it: the deploy identity and the person who ran this script. Do not give anyone else a data role on this storage account.

The script was written without access to Azure and has not been run. If a step fails, the error from `az` names the problem, and you can rerun the script after you fix it.
