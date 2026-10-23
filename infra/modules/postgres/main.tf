# tflint-ignore: azurerm_resources_missing_prevent_destroy # Dev data is disposable, and terraform destroy is how the team stops spending credits.
resource "azurerm_postgresql_flexible_server" "this" {
  #checkov:skip=CKV_AZURE_136:Geo-redundant backup doubles backup storage cost. Seven days of local backups are enough for a dev environment.
  #checkov:skip=CKV2_AZURE_57:A private endpoint needs a VNet. The server takes TLS only and strong generated passwords. Deferred to the DevNet move (ADR 0005).
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  version                       = "17"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  administrator_login           = var.administrator_login
  administrator_password        = var.administrator_password
  public_network_access_enabled = true
  tags                          = var.tags

  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = false
  }

  lifecycle {
    ignore_changes = [zone]
  }
}

# Container Apps on the consumption plan without a VNet have no fixed outbound IP, so the
# server admits Azure-internal traffic. 0.0.0.0 to 0.0.0.0 is Azure's marker for that rule.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  #checkov:skip=CKV2_AZURE_26:Needed while the apps have no VNet (ADR 0005). TLS is required and every role has a 48-character generated password.
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "this" {
  for_each = toset(var.databases)

  name      = each.key
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
