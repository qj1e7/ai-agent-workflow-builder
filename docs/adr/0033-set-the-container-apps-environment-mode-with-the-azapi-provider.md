---
status: proposed
---

# Set the Container Apps environment's mode with the azapi provider

On the first deploys to Azure on 31 Oct 2026, Azure created our Container Apps environment as an *express* environment. Express runs no Container Apps jobs and reads no Key Vault references, and our deploy needs both: the `db-init` and `bootstrap` jobs, and every app's secrets come from Key Vault ([ADR 0013](0013-write-infrastructure-in-terraform.md), [the infra README](../../infra/README.md)). Azure picks express when the create request names no environment mode, even when it names a Consumption workload profile. The setting is `properties.environmentMode`. It exists only in preview API versions such as `2025-10-02-preview`, and the azurerm provider we pin (5.7.0) cannot set it. A PATCH that sets `environmentMode` to `WorkloadProfiles` converted the live environment in place, so the mode can change after creation.

So infra/modules/container_env sends that PATCH through the **azapi provider** (`Azure/azapi`, pinned at 2.13.0), with an `azapi_resource_action` that runs once after the environment is created. Every app and job waits for it. azapi is Microsoft's own Terraform provider for calling the Azure resource API directly, and it covers settings azurerm has not caught up with yet.

## Considered options

- **Set the mode by hand after each new environment.** No new provider, but every fresh deploy, for example after `terraform destroy` to save credits, would fail at `db-init` until a person sent the PATCH.
- **`azapi_update_resource`.** It filters the body through azapi's built-in copy of the API, which has no `environmentMode` for this resource, so it would drop the setting and still report success.
- **Create the whole environment with `azapi_resource`.** Full control over the request, but it moves a resource out of azurerm and its state, and the apps would read its outputs through azapi's response export. More change for the same result.
- **Wait for azurerm to support the setting.** No date is known, and the deploy is needed now.

## Consequences

- A second Terraform provider enters `infra/`. It is pinned, locked for the same five platforms as the others, and validates under OpenTofu, so ADR 0013's fallback still holds.
- An action never reads back. If the mode is changed in Azure later, a plan does not show it. The infra README gives the command that sends the PATCH again.
- When azurerm can set `environmentMode` itself, the action and the azapi provider can go.
- This changes no app code and nothing in the approval gate or the safety checker.
