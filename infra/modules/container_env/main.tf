resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${var.name}"
  location                   = var.location
  resource_group_name        = var.resource_group_name
  log_analytics_workspace_id = var.log_analytics_workspace_id
  logs_destination           = "log-analytics"
  tags                       = var.tags

  # Naming a workload profile makes Azure create a standard environment. Without one, Azure now
  # creates an express environment, which runs no jobs and reads no Key Vault references.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}
