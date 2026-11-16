# Langfuse's blob storage for raw events and media (LANGFUSE_USE_AZURE_BLOB). Langfuse signs in with
# the account key only, so the key is on.
# tflint-ignore: azurerm_resources_missing_prevent_destroy # Traces are a 60-day working record. What must last lives in git (ADR 0050).
resource "azurerm_storage_account" "this" {
  #checkov:skip=CKV2_AZURE_40:Langfuse's Azure blob client signs in with the account key only. The key is in Key Vault.
  #checkov:skip=CKV_AZURE_33:The account has no queues. It holds Langfuse's blobs only.
  #checkov:skip=CKV_AZURE_35:No network filter, like Key Vault and Cosmos DB. The deploy's GitHub runners need the endpoint, and requests from the VM's own region skip IP rules. The key is the control.
  #checkov:skip=CKV_AZURE_59:Public network access stays on for the same reason. A private endpoint comes with the DevNet move (ADR 0005).
  #checkov:skip=CKV2_AZURE_33:A private endpoint needs the apps in a virtual network. Deferred to the DevNet move (ADR 0005).
  #checkov:skip=CKV_AZURE_206:Locally redundant. Traces are a 60-day working record, and what must last lives in git (ADR 0050).
  #checkov:skip=CKV2_AZURE_1:Microsoft-managed keys encrypt the data. A customer-managed key needs a Key Vault key and an identity for the account.
  #checkov:skip=CKV2_AZURE_38:No soft delete. A trace the housekeeping job deletes should be gone, not kept 7 more days (ADR 0050).
  name                             = var.storage_account_name
  location                         = var.location
  resource_group_name              = var.resource_group_name
  account_kind                     = "StorageV2"
  account_tier                     = "Standard"
  account_replication_type         = "LRS"
  min_tls_version                  = "TLS1_2"
  https_traffic_only_enabled       = true
  allow_nested_items_to_be_public  = false
  shared_access_key_enabled        = true
  local_user_enabled               = false
  cross_tenant_replication_enabled = false
  tags                             = var.tags

  # Langfuse's download links last an hour. Longer ones are logged.
  sas_policy {
    expiration_period = "00.02:00:00"
    expiration_action = "Log"
  }
}

# tflint-ignore: azurerm_resources_missing_prevent_destroy # Traces are a 60-day working record. What must last lives in git (ADR 0050).
resource "azurerm_storage_container" "langfuse" {
  #checkov:skip=CKV2_AZURE_21:Blob read logging would send every Langfuse read to Log Analytics, against its 1 GB a day cap.
  name                  = "langfuse"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}
