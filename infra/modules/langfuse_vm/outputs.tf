output "url" {
  description = "Langfuse's HTTPS address, for the SDKs (LANGFUSE_BASE_URL) and the Entra redirect URI."
  value       = "https://${azurerm_public_ip.this.fqdn}"
}

output "vm_name" {
  description = "The VM's name, which run-command takes."
  value       = azurerm_linux_virtual_machine.this.name
}

output "storage_account_key" {
  description = "The storage account's key, which Langfuse signs in to blob storage with. The caller puts it in Key Vault."
  value       = azurerm_storage_account.this.primary_access_key
  sensitive   = true
}
