output "platform_api_fqdn" {
  value = azurerm_container_app.platform_api.ingress[0].fqdn
}

output "appinsights_connection_string" {
  value     = azurerm_application_insights.ai.connection_string
  sensitive = true
}
