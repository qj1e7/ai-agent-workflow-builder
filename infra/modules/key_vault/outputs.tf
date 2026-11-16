output "secrets" {
  description = "Each secret's versionless URL, for a Container Apps Key Vault reference, and its resource ID, for an RBAC scope."
  value = {
    for name, secret in merge(azurerm_key_vault_secret.this, azurerm_key_vault_secret.set_by_a_person) : name => {
      url   = secret.versionless_id
      scope = secret.resource_versionless_id
    }
  }
}
