resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${var.name}"
  location                   = var.location
  resource_group_name        = var.resource_group_name
  log_analytics_workspace_id = var.log_analytics_workspace_id
  logs_destination           = "log-analytics"
  tags                       = var.tags

  # Every app and job runs on this profile.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

# Azure now creates an *express* environment when the create request names no environment mode,
# even with the workload profile above. Express runs no Container Apps jobs and reads no Key Vault
# references. azurerm 5.7.0 cannot set the mode, and only preview API versions have it, so this
# sends the same PATCH that converted the live environment on 31 Oct 2026.
#
# It is an action, not an azapi_update_resource. That resource sends a PUT that keeps only the
# fields in azapi's built-in copy of the API, and that copy has no environmentMode, so it would
# drop the setting without an error. The action runs when it is created, and again when the
# environment is replaced or this body changes. Removing it changes nothing in Azure.
resource "azapi_resource_action" "workload_profiles_mode" {
  type        = "Microsoft.App/managedEnvironments@2025-10-02-preview"
  resource_id = azurerm_container_app_environment.this.id
  method      = "PATCH"

  body = {
    properties = {
      environmentMode = "WorkloadProfiles"
    }
  }
}
