# Both outputs wait for the mode change, so no app or job that reads them is created on an express
# environment. That includes the deploy's targeted db-init apply, because -target also takes
# everything its target depends on.
output "id" {
  description = "Environment resource ID, once the environment is in workload profiles mode."
  value       = azurerm_container_app_environment.this.id
  depends_on  = [azapi_resource_action.workload_profiles_mode]
}

output "default_domain" {
  description = "DNS suffix that app host names end with."
  value       = azurerm_container_app_environment.this.default_domain
  depends_on  = [azapi_resource_action.workload_profiles_mode]
}
