locals {
  # platform-api's Cosmos DB adapter names these in code (monitoring/cosmos_log.py, ADR 0031).
  database      = "activity"
  container     = "run_events"
  partition_key = "/runId"

  # Cosmos DB's built-in Data Contributor reads and writes items. It cannot change databases,
  # containers or the account.
  data_contributor_role = "00000000-0000-0000-0000-000000000002"
}

resource "azurerm_cosmosdb_account" "this" {
  #checkov:skip=CKV_AZURE_140:platform-api signs in with the account key today (COSMOS_KEY, read from Key Vault). Local auth goes off once it signs in with its managed identity.
  #checkov:skip=CKV_AZURE_99:No IP or network filter. Container Apps without a VNet have no fixed outbound address, and the checker reads items from a laptop. The key and the data role are the control, as for Key Vault.
  #checkov:skip=CKV_AZURE_101:Public network access stays on for the same reason. A private endpoint comes with the DevNet move (ADR 0005).
  #checkov:skip=CKV_AZURE_100:Microsoft-managed keys encrypt the data. A customer-managed key needs a Key Vault key and an identity for the account, and the account holds only a copy of the activity log.
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  free_tier_enabled   = !var.serverless
  minimal_tls_version = "Tls12"
  # The account key may read and write items but never make, change or delete a database or a
  # container. Terraform makes both, and platform-api only reads them.
  access_key_metadata_writes_enabled = false
  local_authentication_enabled       = true
  public_network_access_enabled      = true
  automatic_failover_enabled         = false
  multiple_write_locations_enabled   = false
  tags                               = var.tags

  # A reader sees an event as soon as the copier has written it (ADR 0031).
  consistency_policy {
    consistency_level = "Strong"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
    zone_redundant    = false
  }

  dynamic "capabilities" {
    for_each = var.serverless ? ["EnableServerless"] : []
    content {
      name = capabilities.value
    }
  }

  # The free tier covers 1000 RU/s. The cap makes Azure refuse more throughput instead of billing it.
  dynamic "capacity" {
    for_each = var.serverless ? [] : [1000]
    content {
      total_throughput_limit = capacity.value
    }
  }
}

resource "azurerm_cosmosdb_sql_database" "activity" {
  name                = local.database
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.this.name
}

resource "azurerm_cosmosdb_sql_container" "run_events" {
  name                  = local.container
  resource_group_name   = var.resource_group_name
  account_name          = azurerm_cosmosdb_account.this.name
  database_name         = azurerm_cosmosdb_sql_database.activity.name
  partition_key_paths   = [local.partition_key]
  partition_key_kind    = "Hash"
  partition_key_version = 2
  throughput            = var.serverless ? null : 1000
}

resource "azurerm_cosmosdb_sql_role_assignment" "data_contributor" {
  for_each = var.data_contributors

  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.this.name
  role_definition_id  = "${azurerm_cosmosdb_account.this.id}/sqlRoleDefinitions/${local.data_contributor_role}"
  principal_id        = each.value
  scope               = "${azurerm_cosmosdb_account.this.id}/dbs/${azurerm_cosmosdb_sql_database.activity.name}"
}
