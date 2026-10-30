output "resource_group_name" {
  description = "Resource group that holds the environment."
  value       = data.azurerm_resource_group.this.name
}

output "registry_name" {
  description = "Registry the deploy workflow pushes images to."
  value       = module.registry.name
}

output "registry_login_server" {
  description = "Registry host that image names start with."
  value       = module.registry.login_server
}

output "portal_url" {
  description = "Where people open the Portal."
  value       = local.url["portal"]
}

output "platform_api_url" {
  description = "platform-api's public URL."
  value       = local.url["platform-api"]
}

output "job_names" {
  description = "Container Apps Jobs, in the order the deploy workflow runs them."
  value       = [module.job["db-init"].name, module.job["bootstrap"].name]
}

output "cosmos_account_name" {
  description = "Cosmos DB account that holds the activity log's copy."
  value       = module.cosmos.account_name
}
