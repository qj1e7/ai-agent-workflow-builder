data "azurerm_client_config" "current" {}

locals {
  placeholder_image = "mcr.microsoft.com/k8se/quickstart:latest"
}

resource "azurerm_resource_group" "rg" {
  name     = "${var.name_prefix}-rg"
  location = var.location
}

resource "azurerm_log_analytics_workspace" "law" {
  name                = "${var.name_prefix}-law"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_application_insights" "ai" {
  name                = "${var.name_prefix}-appi"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"
}

resource "azurerm_user_assigned_identity" "apps" {
  name                = "${var.name_prefix}-id"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

resource "azurerm_key_vault" "kv" {
  name                       = "${var.name_prefix}-kv"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
}

resource "azurerm_role_assignment" "apps_secrets_user" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

resource "azurerm_role_assignment" "deployer_secrets_officer" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.deployer_object_id
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = var.database_url
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.deployer_secrets_officer]
}

resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = "${var.name_prefix}-pg"
  location                      = azurerm_resource_group.rg.location
  resource_group_name           = azurerm_resource_group.rg.name
  version                       = "17"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  administrator_login           = var.postgres_admin_login
  administrator_password        = var.postgres_admin_password
  public_network_access_enabled = true
  zone                          = "1"
}

resource "azurerm_postgresql_flexible_server_database" "db" {
  for_each  = toset(["platform", "n8n"])
  name      = each.key
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_static_web_app" "swa" {
  name                = "${var.name_prefix}-swa"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku_tier            = "Free"
  sku_size            = "Free"
}

resource "azurerm_container_app_environment" "env" {
  name                       = "${var.name_prefix}-env"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
}

resource "azurerm_container_app" "n8n" {
  name                         = "n8n"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  template {
    min_replicas = 1
    max_replicas = 1
    container {
      name   = "n8n"
      image  = "n8nio/n8n:2.42.6"
      cpu    = 0.5
      memory = "1Gi"
    }
  }

  ingress {
    external_enabled = false
    target_port      = 5678
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

resource "azurerm_container_app" "agent_runtime" {
  name                         = "agent-runtime"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  template {
    container {
      name   = "agent-runtime"
      image  = local.placeholder_image
      cpu    = 0.5
      memory = "1Gi"
    }
  }

  ingress {
    external_enabled = false
    target_port      = 8100
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

resource "azurerm_container_app" "platform_api" {
  name                         = "platform-api"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.apps.id
  }

  template {
    min_replicas = 1
    container {
      name   = "platform-api"
      image  = local.placeholder_image
      cpu    = 0.5
      memory = "1Gi"
      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  depends_on = [azurerm_role_assignment.apps_secrets_user]
}

resource "azurerm_container_app_job" "bootstrap" {
  name                         = "bootstrap"
  location                     = azurerm_resource_group.rg.location
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  replica_timeout_in_seconds   = 600

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "bootstrap"
      image  = local.placeholder_image
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }
}
