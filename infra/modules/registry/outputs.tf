output "id" {
  description = "Registry resource ID, the scope for AcrPull."
  value       = azurerm_container_registry.this.id
}

output "name" {
  description = "Registry name, for az acr login. It resolves only after the deployer's AcrPush has had time to propagate."
  value       = time_sleep.deployer_rbac_propagation.triggers["name"]
}

output "login_server" {
  description = "Registry host that image names start with. It resolves only after the deployer's AcrPush has had time to propagate."
  value       = time_sleep.deployer_rbac_propagation.triggers["login_server"]
}
