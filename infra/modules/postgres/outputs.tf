output "fqdn" {
  description = "Server host name for connection strings."
  value       = azurerm_postgresql_flexible_server.this.fqdn
}
