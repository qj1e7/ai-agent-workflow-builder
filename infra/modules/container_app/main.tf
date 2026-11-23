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

  # The names are plain and the values stay sensitive, as in modules/key_vault.
  dynamic "secret" {
    for_each = toset(nonsensitive(keys(var.inline_secrets)))
    content {
      name  = lower(replace(secret.value, "_", "-"))
      value = var.inline_secrets[secret.value]
    }
  }

  ingress {
    external_enabled = var.ingress.external
    target_port      = var.ingress.target_port
    # Unset for HTTP apps, so Azure keeps its own default.
    transport    = var.ingress.transport
    exposed_port = var.ingress.exposed_port

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

      dynamic "env" {
        for_each = toset(nonsensitive(keys(var.inline_secrets)))
        content {
          name        = env.value
          secret_name = lower(replace(env.value, "_", "-"))
        }
      }
    }
  }
}

# More ports on the app's internal address, only from inside the Container Apps environment, such
# as the broker n8n's task runner connects to (ADR 0051). azurerm 5.7.0 can't set
# additionalPortMappings, so this sends the PATCH that adds them. azurerm keeps the fields it
# doesn't manage when it updates the app, except when the ingress changes: it then writes the
# ingress whole, without them. So the action runs again whenever the ingress or the app's revision
# changes, which the header carries. The header means nothing to Azure.
resource "azapi_resource_action" "internal_ports" {
  count = length(var.internal_ports) > 0 ? 1 : 0

  type        = "Microsoft.App/containerApps@2025-07-01"
  resource_id = azurerm_container_app.this.id
  method      = "PATCH"

  headers = {
    x-wab-after = sha256(jsonencode([var.ingress, var.internal_ports, azurerm_container_app.this.latest_revision_name]))
  }

  body = {
    properties = {
      configuration = {
        ingress = {
          additionalPortMappings = [
            for port in var.internal_ports : { external = false, targetPort = port, exposedPort = port }
          ]
        }
      }
    }
  }
}
