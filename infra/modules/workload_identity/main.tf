resource "azurerm_user_assigned_identity" "this" {
  name                = "id-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "secret_reader" {
  for_each = var.secret_scopes

  scope                = each.value
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
  principal_type       = "ServicePrincipal"
}

# Azure RBAC takes a while to reach Key Vault and the registry. Without the wait, the first
# revision fails to read its secrets or pull its image, and the apply fails.
resource "time_sleep" "rbac_propagation" {
  create_duration = "90s"

  triggers = {
    identity_id = azurerm_user_assigned_identity.this.id
    roles = join(",", concat(
      [azurerm_role_assignment.acr_pull.id],
      [for assignment in azurerm_role_assignment.secret_reader : assignment.id],
    ))
  }
}
