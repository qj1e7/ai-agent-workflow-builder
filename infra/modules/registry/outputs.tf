output "id" {
  description = "Registry resource ID, the scope for AcrPull."
  value       = azurerm_container_registry.this.id
}

output "name" {
  description = "Registry name, for az acr login."
  value       = azurerm_container_registry.this.name
}

output "login_server" {
  description = "Registry host that image names start with."
  value       = azurerm_container_registry.this.login_server
}
