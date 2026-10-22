output "log_analytics_workspace_id" {
  description = "Workspace that the Container Apps environment sends logs to."
  value       = azurerm_log_analytics_workspace.this.id
}

output "application_insights_connection_string" {
  description = "Connection string for apps that send telemetry to Application Insights."
  value       = azurerm_application_insights.this.connection_string
  sensitive   = true
}
