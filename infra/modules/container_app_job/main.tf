module "identity" {
  source = "../workload_identity"

  name                = "${var.name}-${var.name_stem}"
  location            = var.location
  resource_group_name = var.resource_group_name
  registry_id         = var.registry_id
  secret_scopes       = { for env_name, secret in var.secrets : env_name => secret.scope }
  tags                = var.tags
}

resource "azurerm_container_app_job" "this" {
  name                         = var.name
  location                     = var.location
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.environment_id
  replica_timeout_in_seconds   = var.timeout_seconds
  replica_retry_limit          = 0
  workload_profile_name        = "Consumption"
  tags                         = var.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [module.identity.id]
  }

  registry {
    server   = var.registry_server
    identity = module.identity.id
  }

  dynamic "secret" {
    for_each = var.secrets
    content {
      name                = lower(replace(secret.key, "_", "-"))
      key_vault_secret_id = secret.value.url
      identity            = module.identity.id
    }
  }

  template {
    container {
      name    = var.name
      image   = var.image
      cpu     = var.cpu
      memory  = var.memory
      command = var.command

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secrets
        content {
          name        = env.key
          secret_name = lower(replace(env.key, "_", "-"))
        }
      }
    }
  }
}
