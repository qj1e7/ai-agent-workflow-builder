output "fqdn" {
  description = "Host name of the app's ingress."
  value       = azurerm_container_app.this.ingress[0].fqdn
}
