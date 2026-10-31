output "fqdn" {
  description = "Host name of the app's ingress."
  value       = azurerm_container_app.this.ingress[0].fqdn
}

output "identity_principal_id" {
  description = "Object ID of the app's managed identity, for data roles such as Cosmos DB's."
  value       = module.identity.principal_id
}
