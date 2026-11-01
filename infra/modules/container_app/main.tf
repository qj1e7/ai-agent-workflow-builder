module "identity" {
  source = "../workload_identity"

  name                = "${var.name}-${var.name_stem}"
  location            = var.location
  resource_group_name = var.resource_group_name
  registry_id         = var.registry_id
  secret_scopes       = { for env_name, secret in var.secrets : env_name => secret.scope }
  tags                = var.tags
}

resource "azurerm_container_app" "this" {
  name                         = var.name
  container_app_environment_id = var.environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = var.tags

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

  ingress {
    external_enabled = var.ingress.external
    target_port      = var.ingress.target_port

    # Container Apps cannot mix Allow and Deny rules. With Allow rules, it refuses every address
    # outside them with "RBAC: access denied". No ingress field forces a replace in azurerm 5.7.0,
    # so adding or removing rules updates the app in place.
    dynamic "ip_security_restriction" {
      for_each = var.ingress.allowed_cidrs
      content {
        name             = ip_security_restriction.value.name
        action           = "Allow"
        ip_address_range = ip_security_restriction.value.cidr
      }
    }

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

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
