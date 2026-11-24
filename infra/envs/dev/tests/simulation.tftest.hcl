# The simulation n8n (ADR 0054). Off, Terraform makes none of it. On, it holds no real key: every
# secret is one of its own, every setting is on a list, every address is in its own environment,
# and its subnet reaches only itself and the Azure services Container Apps needs. The platform's
# real keys are set in the second run, so it shows none of them reaches the simulation. Every
# provider is mocked, so this runs offline. deploy/compose.simulation.yaml is the same stack in
# Compose, and scripts/simulation_isolation.py checks it there.

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

run "simulation_off_makes_nothing" {
  command = apply

  assert {
    condition = (
      length(random_password.simulation) == 0 &&
      length(azurerm_virtual_network.simulation) == 0 &&
      length(azurerm_subnet.simulation) == 0 &&
      length(azurerm_network_security_group.simulation) == 0 &&
      length(azurerm_subnet_network_security_group_association.simulation) == 0 &&
      length(module.simulation_env) == 0 &&
      length(module.simulation_app) == 0 &&
      length(module.simulation_job) == 0 &&
      length(module.simulation_n8n_runners) == 0
    )
    error_message = "With enable_simulation false, Terraform must make no part of the simulation n8n."
  }

  assert {
    condition     = local.apps.n8n.env.WAB_API_URL == local.url["platform-api"]
    error_message = "The platform's n8n must keep calling platform-api."
  }
}

# The platform's real keys are set here, so the run shows none of them reaches the simulation.
run "simulation_on_holds_no_real_key_and_reaches_only_its_own_subnet" {
  command = apply

  variables {
    enable_simulation    = true
    github_token         = "made-up-github-token"
    n8n_key_github_token = "made-up-n8n-github-token"
    n8n_key_github_url   = "https://github.example.test/api/v3"
    n8n_key_slack_token  = "made-up-slack-token"
    jira_base_url        = "https://jira.example.test"
    jira_api_token       = "made-up-jira-token"
  }

  # The mocks give every environment one domain, so the simulation's gets its own here.
  override_module {
    target = module.simulation_env
    outputs = {
      id             = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-wab-dev/providers/Microsoft.App/managedEnvironments/cae-wab-dev-sim"
      default_domain = "sim.southeastasia.azurecontainerapps.io"
    }
  }

  assert {
    condition = (
      length(azurerm_virtual_network.simulation) == 1 &&
      length(module.simulation_env) == 1 &&
      toset(keys(module.simulation_app)) == toset(["sim-postgres", "sim-n8n", "sim-mock-github"]) &&
      toset(keys(module.simulation_job)) == toset(["sim-db-init", "sim-bootstrap"]) &&
      length(module.simulation_n8n_runners) == 1
    )
    error_message = "With enable_simulation true, Terraform must make the network, the environment, its three apps, its two jobs and its task runner."
  }

  assert {
    condition = alltrue(flatten([
      for item in concat(values(local.simulation_apps), values(local.simulation_jobs)) : [
        for key in values(item.secrets) : contains(concat(keys(random_password.simulation), ["database-url-owner"]), key)
      ]
    ]))
    error_message = "Every secret of the simulation's apps and jobs must be one of the simulation's own keys, which Terraform makes for it alone."
  }

  assert {
    condition = (
      toset(concat(keys(local.simulation_apps["sim-n8n"].env), keys(local.simulation_apps["sim-n8n"].secrets))) ==
      toset(concat(keys(local.n8n_guards), [
        "DB_TYPE", "DB_POSTGRESDB_HOST", "DB_POSTGRESDB_PORT", "DB_POSTGRESDB_DATABASE", "DB_POSTGRESDB_USER",
        "DB_POSTGRESDB_PASSWORD", "WEBHOOK_URL", "GENERIC_TIMEZONE", "N8N_ENCRYPTION_KEY",
        "N8N_DIAGNOSTICS_ENABLED", "N8N_VERSION_NOTIFICATIONS_ENABLED", "N8N_PERSONALIZATION_ENABLED",
        "N8N_HIRING_BANNER_ENABLED", "N8N_DISABLED_MODULES", "N8N_RUNNERS_BROKER_LISTEN_ADDRESS",
        "N8N_RUNNERS_AUTH_TOKEN", "EXECUTIONS_DATA_SAVE_ON_SUCCESS", "WAB_API_URL", "WAB_NODE_KEY", "WAB_START_SECRET",
      ]))
    )
    error_message = "The simulation n8n may hold only the settings listed here, so a real key added later fails this test."
  }

  assert {
    condition = (
      toset(concat(keys(local.simulation_apps["sim-postgres"].env), keys(local.simulation_apps["sim-postgres"].secrets))) == toset(["POSTGRES_PASSWORD"]) &&
      length(local.simulation_apps["sim-mock-github"].env) == 0 &&
      length(local.simulation_apps["sim-mock-github"].secrets) == 0 &&
      toset(concat(keys(local.simulation_jobs["sim-db-init"].env), keys(local.simulation_jobs["sim-db-init"].secrets))) == toset([
        "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGSSLMODE", "DB_INIT_SQL", "PGPASSWORD", "N8N_DB_PASSWORD",
        "WAB_OWNER_PASSWORD", "WAB_BUILDER_PASSWORD", "WAB_ORCHESTRATION_PASSWORD", "WAB_MONITORING_PASSWORD",
      ]) &&
      toset(concat(keys(local.simulation_jobs["sim-bootstrap"].env), keys(local.simulation_jobs["sim-bootstrap"].secrets))) == toset(concat(keys(local.n8n_guards), [
        "N8N_BASE_URL", "N8N_OWNER_EMAIL", "PLATFORM_INTERNAL_URL", "TEAM_TIME_ZONE", "DATABASE_URL_OWNER",
        "N8N_OWNER_PASSWORD", "STEP_KEY",
      ]))
    )
    error_message = "The simulation's PostgreSQL, mock GitHub and jobs may hold only the settings listed here."
  }

  assert {
    condition = alltrue(flatten([
      for item in concat(values(local.simulation_apps), values(local.simulation_jobs)) : [
        for value in values(item.env) :
        !strcontains(value, "://") || strcontains(value, ".internal.sim.southeastasia.azurecontainerapps.io")
      ]
    ]))
    error_message = "Every address the simulation holds must be inside its own environment, never the platform's."
  }

  assert {
    condition = (
      local.simulation_apps["sim-n8n"].env.WAB_API_URL == "https://sim-gateway.internal.sim.southeastasia.azurecontainerapps.io" &&
      local.simulation_jobs["sim-bootstrap"].env.PLATFORM_INTERNAL_URL == local.simulation_apps["sim-n8n"].env.WAB_API_URL &&
      local.simulation_apps["sim-n8n"].env.DB_POSTGRESDB_HOST == "sim-postgres" &&
      local.simulation_jobs["sim-db-init"].env.PGHOST == "sim-postgres"
    )
    error_message = "The simulation n8n's blocks must call the simulation gateway, and it must use its own PostgreSQL."
  }

  assert {
    condition = (
      alltrue([
        for name, value in local.n8n_guards :
        local.simulation_apps["sim-n8n"].env[name] == value && local.simulation_jobs["sim-bootstrap"].env[name] == value
      ]) &&
      local.simulation_apps["sim-n8n"].image == local.apps.n8n.image &&
      local.simulation_jobs["sim-bootstrap"].image == local.jobs.bootstrap.image
    )
    error_message = "The simulation n8n must run the platform n8n's image and guards, and the platform's bootstrap."
  }

  assert {
    condition     = alltrue([for app in values(local.simulation_apps) : !app.ingress.external])
    error_message = "No app of the simulation may be reachable from outside its environment."
  }

  assert {
    condition = (
      length([
        for rule in azurerm_network_security_group.simulation[0].security_rule : rule
        if rule.direction == "Outbound" && rule.access == "Deny" && rule.priority == 4096 && rule.destination_address_prefix == "*"
      ]) == 1 &&
      length([
        for rule in azurerm_network_security_group.simulation[0].security_rule : rule
        if rule.direction == "Inbound" && rule.access == "Deny" && rule.priority == 4096 && rule.source_address_prefix == "*"
      ]) == 1
    )
    error_message = "The simulation's subnet must refuse everything its rules don't let through, both ways."
  }

  assert {
    condition = toset([
      for rule in azurerm_network_security_group.simulation[0].security_rule : rule.destination_address_prefix
      if rule.direction == "Outbound" && rule.access == "Allow"
      ]) == toset([
      "10.81.0.0/27", "MicrosoftContainerRegistry", "AzureFrontDoor.FirstParty", "AzureContainerRegistry",
      "Storage.southeastasia", "AzureActiveDirectory", "AzureMonitor", "168.63.129.16/32",
    ])
    error_message = "The simulation's subnet may reach only itself and the Azure services Container Apps needs, never the internet."
  }

  assert {
    condition     = length(azurerm_subnet_network_security_group_association.simulation) == 1
    error_message = "The simulation's subnet must carry its rules."
  }

  assert {
    condition = (
      toset(module.simulation_n8n_runners[0].container_settings) == toset(["N8N_RUNNERS_TASK_BROKER_URI", "N8N_RUNNERS_AUTH_TOKEN", "N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT", "GENERIC_TIMEZONE"]) &&
      !module.simulation_n8n_runners[0].identity_in_containers
    )
    error_message = "The simulation's task runner may get only its broker's address, its token and its runners' own settings, and no container in it may ask for its identity's token."
  }

  assert {
    condition     = alltrue([for name in keys(module.key_vault.secrets) : !startswith(name, "sim-") && !startswith(name, "simulation")])
    error_message = "Key Vault must hold none of the simulation's keys."
  }

  assert {
    condition     = local.apps.n8n.env.WAB_API_URL == local.url["platform-api"]
    error_message = "The platform's n8n must keep calling platform-api."
  }
}
