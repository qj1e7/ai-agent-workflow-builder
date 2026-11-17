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

output "n8n_editor_url" {
  description = "Where n8n's editor opens when n8n_editor_external is true and n8n_editor_allowed_ips names who may reach it. Empty while n8n is internal."
  value       = local.n8n_editor_open ? local.url["n8n"] : ""
}

output "n8n_runners_app_name" {
  description = "n8n's task runner app, for the checks before a deploy: its environment holds no identity endpoint, and it reaches n8n's broker."
  value       = module.n8n_runners.name
}

output "job_names" {
  description = "Container Apps Jobs, in the order the deploy workflow runs them."
  value       = [module.job["db-init"].name, module.job["bootstrap"].name]
}

output "cosmos_account_name" {
  description = "Cosmos DB account that holds the activity log's copy."
  value       = module.cosmos.account_name
}

output "langfuse_url" {
  description = "Langfuse's address while langfuse_enabled is true. Its Entra app's redirect URI is this address plus /api/auth/callback/azure-ad. Empty while it is off."
  value       = var.langfuse_enabled ? module.langfuse_vm[0].url : ""
}

output "langfuse_vm_name" {
  description = "The Langfuse VM's name, for az vm run-command. Empty while langfuse_enabled is false."
  value       = var.langfuse_enabled ? module.langfuse_vm[0].vm_name : ""
}
