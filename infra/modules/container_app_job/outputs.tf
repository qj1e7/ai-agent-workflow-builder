output "name" {
  description = "Job name, for az containerapp job start."
  value       = azurerm_container_app_job.this.name
}
