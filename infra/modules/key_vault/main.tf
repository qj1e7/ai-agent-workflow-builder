data "azurerm_client_config" "current" {}

# tflint-ignore: azurerm_resources_missing_prevent_destroy # Purge protection already keeps a deleted vault and its secrets for 7 days.
resource "azurerm_key_vault" "this" {
  #checkov:skip=CKV_AZURE_109:No firewall. The deploy runs on GitHub-hosted runners with changing IPs, and Container Apps without a VNet reach the vault over its public endpoint. RBAC on each secret is the control.
  #checkov:skip=CKV_AZURE_189:Public network access stays on for the same reason. A private endpoint comes with the DevNet move (ADR 0005).
  #checkov:skip=CKV2_AZURE_32:A private endpoint needs a VNet and costs about USD 7 a month. Deferred to the DevNet move (ADR 0005).
  name                       = var.name
  location                   = var.location
  resource_group_name        = var.resource_group_name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 7
  tags                       = var.tags
}

# The deployer is the deploy workflow's managed identity. Its role-assignment rights only cover
# service principals, so Azure refuses the assignment unless the request names the principal type.
resource "azurerm_role_assignment" "deployer_secrets_officer" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
  principal_type       = "ServicePrincipal"
}

# Azure RBAC can take minutes to reach Key Vault. Without the wait, the first secret write can be
# refused. The secrets read the vault ID through this resource, so they are written after it.
resource "time_sleep" "deployer_rbac_propagation" {
  create_duration = "90s"

  triggers = {
    role_assignment_id = azurerm_role_assignment.deployer_secrets_officer.id
    key_vault_id       = azurerm_key_vault.this.id
  }
}

# nosemgrep: terraform.azure.security.keyvault.keyvault-ensure-secret-expires.keyvault-ensure-secret-expires
resource "azurerm_key_vault_secret" "this" {
  #checkov:skip=CKV_AZURE_41:Generated secrets do not expire. An expired secret would stop every Container App that reads it, and nothing rotates them yet.
  for_each = toset(nonsensitive(keys(var.secrets)))

  name         = each.key
  value        = var.secrets[each.key]
  content_type = "text/plain"
  key_vault_id = time_sleep.deployer_rbac_propagation.triggers["key_vault_id"]
  tags         = var.tags
}
