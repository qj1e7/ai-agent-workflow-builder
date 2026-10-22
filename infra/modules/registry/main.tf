data "azurerm_client_config" "current" {}

resource "azurerm_container_registry" "this" {
  #checkov:skip=CKV_AZURE_139:Basic SKU cannot turn off public network access. Premium costs about USD 50 a month.
  #checkov:skip=CKV_AZURE_165:Geo-replication needs Premium.
  #checkov:skip=CKV_AZURE_166:Quarantine needs Premium.
  #checkov:skip=CKV_AZURE_167:Untagged-manifest retention needs Premium.
  #checkov:skip=CKV_AZURE_233:Zone redundancy needs Premium.
  #checkov:skip=CKV_AZURE_237:Dedicated data endpoints need Premium.
  #checkov:skip=CKV_AZURE_163:Image vulnerability scanning needs Microsoft Defender for Containers, a paid plan.
  #checkov:skip=CKV_AZURE_164:Content trust (signed images) needs Premium. Our images are pushed only by the reviewed deploy workflow.
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}

# The deployer is the deploy workflow's managed identity. Its role-assignment rights only cover
# service principals, so Azure refuses the assignment unless the request names the principal type.
resource "azurerm_role_assignment" "deployer_push" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPush"
  principal_id         = data.azurerm_client_config.current.object_id
  principal_type       = "ServicePrincipal"
}
