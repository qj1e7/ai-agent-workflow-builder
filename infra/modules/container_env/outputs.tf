output "id" {
  description = "Environment resource ID."
  value       = azurerm_container_app_environment.this.id
}

output "default_domain" {
  description = "DNS suffix that app host names end with."
  value       = azurerm_container_app_environment.this.default_domain
}
