output "fqdn" {
  description = "Host name of the app's ingress."
  value       = azurerm_container_app.this.ingress[0].fqdn
}

output "identity_principal_id" {
  description = "Object ID of the app's managed identity, for data roles such as Cosmos DB's."
  value       = module.identity.principal_id
}

output "outbound_ip_addresses" {
  description = "Public addresses the app's calls leave from. Container Apps can share them with other Azure customers."
  value       = azurerm_container_app.this.outbound_ip_addresses
}
