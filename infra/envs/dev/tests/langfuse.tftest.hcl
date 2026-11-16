# Langfuse off adds nothing and gives the apps no Langfuse setting. On, the VM exists and the apps
# trace (ADR 0050). Every provider is mocked, so this runs offline. The mocks give each resource
# type one fixed ID of the right shape, because azurerm checks the IDs it is given.

mock_provider "azapi" {}
mock_provider "time" {}

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "11111111-2222-3333-4444-555555555555"
      object_id       = "22222222-3333-4444-5555-666666666666"
      subscription_id = "00000000-0000-0000-0000-000000000000"
    }
  }
  mock_data "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev"
    }
  }
  mock_data "azurerm_role_definition" {
    defaults = {
      role_definition_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/33333333-4444-5555-6666-777777777777"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.OperationalInsights/workspaces/log-wab-dev" }
  }
  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.ContainerRegistry/registries/crwabdevabcde"
      login_server = "crwabdevabcde.azurecr.io"
    }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id             = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.App/managedEnvironments/cae-wab-dev"
      default_domain = "example.southeastasia.azurecontainerapps.io"
    }
  }
  mock_resource "azurerm_container_app" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.App/containerApps/app"
      outbound_ip_addresses = ["20.0.0.1", "20.0.0.2"]
    }
  }
  mock_resource "azurerm_container_app_job" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.App/jobs/job" }
  }
  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = {
      id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-wab-dev-abcde"
      fqdn = "psql-wab-dev-abcde.postgres.database.azure.com"
    }
  }
  mock_resource "azurerm_cosmosdb_account" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-wab-dev-abcde"
      endpoint = "https://cosmos-wab-dev-abcde.documents.azure.com:443/"
    }
  }
  mock_resource "azurerm_key_vault" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.KeyVault/vaults/kv-wab-dev-abcde" }
  }
  mock_resource "azurerm_key_vault_secret" {
    defaults = {
      versionless_id          = "https://kv-wab-dev-abcde.vault.azure.net/secrets/secret"
      resource_versionless_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.KeyVault/vaults/kv-wab-dev-abcde/secrets/secret"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id"
      principal_id = "44444444-5555-6666-7777-888888888888"
      client_id    = "55555555-6666-7777-8888-999999999999"
    }
  }
  mock_resource "azurerm_virtual_network" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Network/virtualNetworks/vnet" }
  }
  mock_resource "azurerm_subnet" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Network/virtualNetworks/vnet/subnets/snet" }
  }
  mock_resource "azurerm_network_security_group" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Network/networkSecurityGroups/nsg" }
  }
  mock_resource "azurerm_public_ip" {
    defaults = {
      id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Network/publicIPAddresses/pip"
      fqdn = "langfuse-wab-dev-abcde.southeastasia.cloudapp.azure.com"
    }
  }
  mock_resource "azurerm_network_interface" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Network/networkInterfaces/nic" }
  }
  mock_resource "azurerm_linux_virtual_machine" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Compute/virtualMachines/vm" }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Storage/storageAccounts/stlfwabdevabcde"
      primary_blob_endpoint = "https://stlfwabdevabcde.blob.core.windows.net/"
    }
  }
  mock_resource "azurerm_monitor_action_group" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Insights/actionGroups/ag" }
  }
  mock_resource "azurerm_monitor_data_collection_rule" {
    defaults = { id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.Insights/dataCollectionRules/dcr" }
  }
}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  image_tag       = "test"
  n8n_owner_email = "owner@example.test"
  oidc_issuer     = "https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0"
  oidc_audience   = "66666666-7777-8888-9999-000000000000"
  oidc_client_id  = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
  oidc_scope      = "openid profile"
}

run "langfuse_off_changes_nothing" {
  command = apply

  assert {
    condition     = length(module.langfuse_vm) == 0 && output.langfuse_url == "" && output.langfuse_vm_name == ""
    error_message = "With langfuse_enabled false, there must be no Langfuse VM."
  }

  assert {
    condition = alltrue([
      for app in values(local.apps) : alltrue([
        for name in concat(keys(app.env), keys(app.secrets)) : !startswith(name, "LANGFUSE_") && name != "TRACE_PSEUDONYM_KEY"
      ])
    ])
    error_message = "With langfuse_enabled false, no app may get a Langfuse setting, so tracing stays off."
  }

  assert {
    condition     = alltrue([for name in keys(module.key_vault.secrets) : !startswith(name, "langfuse-") && name != "trace-pseudonym-key"])
    error_message = "With langfuse_enabled false, Key Vault must hold no Langfuse secret."
  }

  assert {
    condition     = local.jobs["db-init"].env.DB_INIT_SQL == file("../../sql/db-init.sql") && !strcontains(local.jobs["db-init"].command[2], "langfuse")
    error_message = "With langfuse_enabled false, the db-init job must run exactly db-init.sql."
  }
}

run "langfuse_on_traces_both_apps" {
  command = apply

  variables {
    langfuse_enabled           = true
    langfuse_owner_email       = "lead@example.test"
    langfuse_entra_client_id   = "12345678-1234-1234-1234-123456789012"
    deploy_principal_object_id = "87654321-4321-4321-4321-210987654321"
  }

  assert {
    condition     = length(module.langfuse_vm) == 1 && output.langfuse_url == "https://langfuse-wab-dev-abcde.southeastasia.cloudapp.azure.com"
    error_message = "With langfuse_enabled true, there must be one Langfuse VM at its https address."
  }

  assert {
    condition = (
      local.apps["agent-runtime"].env.LANGFUSE_BASE_URL == output.langfuse_url &&
      local.apps["agent-runtime"].env.LANGFUSE_TRACING_ENVIRONMENT == "azure-dev" &&
      local.apps["agent-runtime"].env.LANGFUSE_RELEASE == "test" &&
      toset([for name in keys(local.apps["agent-runtime"].secrets) : name if startswith(name, "LANGFUSE_")]) == toset(["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"])
    )
    error_message = "agent-runtime must get Langfuse's address, keys, environment and release."
  }

  assert {
    condition = (
      local.apps["platform-api"].env.LANGFUSE_BASE_URL == output.langfuse_url &&
      toset([for name in keys(local.apps["platform-api"].secrets) : name if startswith(name, "LANGFUSE_") || name == "TRACE_PSEUDONYM_KEY"]) == toset(["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "TRACE_PSEUDONYM_KEY"])
    )
    error_message = "platform-api must get Langfuse's address and keys, and the pseudonym key."
  }

  assert {
    condition = alltrue([
      for app in ["n8n", "portal"] : alltrue([
        for name in concat(keys(local.apps[app].env), keys(local.apps[app].secrets)) : !startswith(name, "LANGFUSE_") && name != "TRACE_PSEUDONYM_KEY"
      ])
    ])
    error_message = "Only agent-runtime and platform-api may get Langfuse settings."
  }

  assert {
    condition     = length(setintersection(toset(keys(local.langfuse_vm_secrets)), toset(["trace-pseudonym-key", "langfuse-judge-anthropic-key"]))) == 0
    error_message = "The VM must not read the pseudonym key or the judge's key. Langfuse needs neither."
  }

  assert {
    condition     = strcontains(local.jobs["db-init"].env.DB_INIT_SQL, file("../../sql/db-init-langfuse.sql")) && strcontains(local.jobs["db-init"].command[2], "-v langfuse_pw=")
    error_message = "With langfuse_enabled true, the db-init job must also create Langfuse's role."
  }
}
