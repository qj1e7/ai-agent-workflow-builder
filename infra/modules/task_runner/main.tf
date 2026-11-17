# n8n's external task runner, as a Container App of its own (ADR 0051, spike P9). The code of Code,
# AI Transform, the Code Tool, Sort and Item Lists runs here, so it holds none of n8n's secrets:
# only the token that lets it take n8n's tasks, from Key Vault.
#
# Its identity pulls the image and reads that token, and nothing else. Container Apps would give a
# container the identity's endpoint and header, and code that got out of the runner's sandbox could
# then ask for a token. identitySettings with lifecycle None keeps the identity to the platform's own
# use, out of every container. azurerm 5.7.0 can't set it, and the app must never start a revision
# without it, so the whole app is one azapi_resource.
#
# It has no ingress: the runner calls n8n's broker, and nothing calls the runner.

module "identity" {
  source = "../workload_identity"

  name                = "${var.name}-${var.name_stem}"
  location            = var.location
  resource_group_name = var.resource_group_name
  registry_id         = var.registry_id
  secret_scopes       = { N8N_RUNNERS_AUTH_TOKEN = var.auth_token.scope }
  tags                = var.tags
}

locals {
  token_secret = "n8n-runners-auth-token"
}

resource "azapi_resource" "this" {
  type      = "Microsoft.App/containerApps@2025-07-01"
  name      = var.name
  parent_id = var.resource_group_id
  location  = var.location
  tags      = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [module.identity.id]
  }

  body = {
    properties = {
      environmentId       = var.environment_id
      workloadProfileName = "Consumption"
      configuration = {
        activeRevisionsMode = "Single"
        identitySettings = [
          { identity = module.identity.id, lifecycle = "None" },
        ]
        registries = [
          { server = var.registry_server, identity = module.identity.id },
        ]
        secrets = [
          { name = local.token_secret, keyVaultUrl = var.auth_token.url, identity = module.identity.id },
        ]
      }
      template = {
        containers = [
          {
            name      = var.name
            image     = var.image
            resources = { cpu = var.cpu, memory = var.memory }
            env = [
              { name = "N8N_RUNNERS_TASK_BROKER_URI", value = var.broker_uri },
              { name = "N8N_RUNNERS_AUTH_TOKEN", secretRef = local.token_secret },
              # A runner the launcher started stops after 15 idle seconds, and the next task starts another.
              { name = "N8N_RUNNERS_AUTO_SHUTDOWN_TIMEOUT", value = "15" },
              { name = "GENERIC_TIMEZONE", value = var.time_zone },
            ]
          },
        ]
        # The launcher holds the broker connection, so it never scales to zero.
        scale = { minReplicas = 1, maxReplicas = 1 }
      }
    }
  }

  response_export_values = []
}
