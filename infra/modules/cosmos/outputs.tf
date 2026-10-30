output "account_name" {
  description = "Account name, for the deploy summary and the checker's Cosmos DB lane."
  value       = azurerm_cosmosdb_account.this.name
}

output "endpoint" {
  description = "Account endpoint that platform-api reads as COSMOS_ENDPOINT. It resolves only once the container exists, because the account key may not create one."
  value       = azurerm_cosmosdb_account.this.endpoint
  depends_on  = [azurerm_cosmosdb_sql_container.run_events]
}

output "primary_key" {
  description = "Account key that platform-api reads as COSMOS_KEY, through Key Vault."
  value       = azurerm_cosmosdb_account.this.primary_key
  sensitive   = true
}
