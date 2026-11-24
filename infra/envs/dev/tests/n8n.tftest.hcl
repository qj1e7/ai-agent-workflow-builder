# n8n with every built-in block (ADR 0051, spike P9, build step 12): n8n and the bootstrap job get
# the same guards, n8n has no allow list, the task runner runs in an app of its own that holds none
# of n8n's secrets and gives no container its identity, and n8n's editor opens as ADR 0034 chose,
# to the addresses listed or, with none, to every address. Every provider is mocked, so this runs offline. deploy/compose.yaml holds the same, and
# scripts/n8n-guards.sh checks it there.

mock_provider "azapi" {}
mock_provider "time" {}

# The same mocks as langfuse.tftest.hcl's. OpenTofu can't read them from a shared file.
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

run "n8n_and_bootstrap_get_the_same_guards_and_n8n_has_no_allow_list" {
  command = apply

  assert {
    condition = alltrue([
      for name, value in local.n8n_guards :
      local.apps.n8n.env[name] == value && local.jobs.bootstrap.env[name] == value
    ])
    error_message = "n8n and the bootstrap job must get every guard, with the same value."
  }

  assert {
    condition = (
      local.n8n_guards.N8N_BLOCK_ENV_ACCESS_IN_NODE == "true" &&
      local.n8n_guards.N8N_RUNNERS_MODE == "external" &&
      local.n8n_guards.N8N_DEPRECATED_NODES_BLOCK != "false" &&
      local.n8n_guards.N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES != "false" &&
      trimspace(local.n8n_guards.N8N_RESTRICT_FILE_ACCESS_TO) != ""
    )
    error_message = "The guards must keep $env closed, run code in the external runner, refuse the deprecated blocks and keep the file blocks in their own folder."
  }

  assert {
    condition = length(setsubtract(
      [
        "n8n-nodes-base.executeCommand",
        "n8n-nodes-base.localFileTrigger",
        "n8n-nodes-base.function",
        "n8n-nodes-base.functionItem",
        "@n8n/n8n-nodes-langchain.code",
        "n8n-nodes-base.git",
        "n8n-nodes-base.gitTool",
      ],
      jsondecode(local.apps.n8n.env.NODES_EXCLUDE),
    )) == 0
    error_message = "NODES_EXCLUDE must leave out every block that reaches n8n's own secrets, disk or host (n8n_blocks.LEFT_OUT)."
  }

  assert {
    condition = alltrue([
      for name in ["NODES_INCLUDE", "NODE_FUNCTION_ALLOW_BUILTIN", "NODE_FUNCTION_ALLOW_EXTERNAL", "N8N_RUNNERS_INSECURE_MODE"] :
      !contains(keys(local.apps.n8n.env), name) && !contains(keys(local.apps.n8n.secrets), name)
    ])
    error_message = "n8n must have no allow list and none of the settings that let code reach further."
  }

  assert {
    condition     = contains(keys(local.apps.n8n.secrets), "N8N_RUNNERS_AUTH_TOKEN") && contains(keys(module.key_vault.secrets), "n8n-runners-auth-token")
    error_message = "n8n must read the runner's token from Key Vault."
  }

  assert {
    condition     = local.internal_ports.n8n == [5679] && local.apps.n8n.env.N8N_RUNNERS_BROKER_LISTEN_ADDRESS == "0.0.0.0"
    error_message = "n8n's broker must listen on 5679, open only inside the environment."
  }

  assert {
    condition     = local.apps.n8n.env.WAB_REQUEST_TIMEOUT_SECONDS == "30"
    error_message = "n8n's own blocks must give up on a read after 30 seconds a try, as platform-api's stop words say (ADR 0056)."
  }
}

run "the_task_runner_holds_none_of_n8n_s_secrets_and_no_identity" {
  command = apply

  assert {
    condition     = toset(module.n8n_runners.container_settings) == toset(["N8N_RUNNERS_TASK_BROKER_URI", "N8N_RUNNERS_AUTH_TOKEN", "N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT", "GENERIC_TIMEZONE"])
    error_message = "The runner may get only its broker's address, its token and its runners' own settings."
  }

  assert {
    condition     = !module.n8n_runners.identity_in_containers
    error_message = "No container in the runner app may ask for its identity's token."
  }

  assert {
    condition     = output.n8n_runners_app_name == "n8n-runners"
    error_message = "The runner is its own app."
  }
}

# The team lead kept ADR 0034's choice of 1 Nov: with the switch on and no addresses listed, the
# editor's sign-in page answers every address.
run "n8n_s_editor_opens_to_every_address_without_a_list" {
  command = apply

  variables {
    n8n_editor_external = true
  }

  assert {
    condition     = local.ingress.n8n.external && output.n8n_editor_url != "" && length(local.n8n_allowed_cidrs) == 0
    error_message = "With the switch on and no addresses listed, n8n's editor opens to every address, as ADR 0034 chose."
  }

  assert {
    condition     = local.apps["platform-api"].env["N8N_STAFF_ACCESS"] == "on"
    error_message = "Staff get n8n accounts while its editor is open."
  }
}

run "n8n_s_editor_stays_internal_while_the_switch_is_off" {
  command = apply

  assert {
    condition     = !local.ingress.n8n.external && output.n8n_editor_url == "" && !contains(keys(local.apps["platform-api"].env), "N8N_STAFF_ACCESS")
    error_message = "With the switch off, n8n stays internal and staff get no n8n accounts."
  }
}

run "n8n_s_editor_opens_to_the_addresses_listed" {
  command = apply

  variables {
    n8n_editor_external    = true
    n8n_editor_allowed_ips = "203.0.113.7"
  }

  assert {
    condition     = local.ingress.n8n.external && output.n8n_editor_url != "" && contains([for rule in local.n8n_allowed_cidrs : rule.cidr], "203.0.113.7/32")
    error_message = "With addresses listed, n8n's editor must open to them alone."
  }
}
