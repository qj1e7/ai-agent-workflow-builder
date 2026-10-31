provider "azurerm" {
  subscription_id = var.subscription_id
  # The deploy identity has rights on the resource group only, so it cannot register resource
  # providers on the subscription. infra/bootstrap/setup-azure.sh registers them once.
  resource_provider_registrations = "none"

  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
}

# Only modules/container_env uses azapi, to set a setting that azurerm cannot set yet. It signs in
# the same way as azurerm, from the ARM_ variables, and for the same reason registers no providers.
provider "azapi" {
  subscription_id            = var.subscription_id
  skip_provider_registration = true
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  stem   = "wab-${var.environment}"
  suffix = random_string.suffix.result

  tags = {
    project     = "ai-workflow-builder"
    environment = var.environment
    managed-by  = "terraform"
  }

  # Whether a token is set is not secret, and plain is needed to choose which secrets exist.
  github_token_set = nonsensitive(var.github_token != "")

  # The first people's addresses are not secret, and the app table's for_each needs plain values.
  first_people = trimspace(nonsensitive(var.first_operator)) == "" ? {} : {
    FIRST_OPERATOR  = trimspace(nonsensitive(var.first_operator))
    FIRST_APPROVERS = trimspace(nonsensitive(var.first_approvers))
  }

  public_images = jsondecode(file("${path.module}/../../public-images.json"))
  images = merge(
    { for name, image in local.public_images : name => "${module.registry.login_server}/${image.repository}@${image.digest}" },
    { for name in ["platform-api", "agent-runtime", "portal"] : name => "${module.registry.login_server}/${name}:${var.image_tag}" },
  )

  # Container Apps redirect plain HTTP to HTTPS, and our services do not follow redirects, so
  # every call between apps uses the HTTPS host name. Internal apps have "internal." in theirs.
  ingress = {
    platform-api  = { external = true, target_port = 8000 }
    agent-runtime = { external = false, target_port = 8100 }
    n8n           = { external = false, target_port = 5678 }
    portal        = { external = true, target_port = 8080 }
  }
  url = {
    for name, ingress in local.ingress :
    name => "https://${name}.${ingress.external ? "" : "internal."}${module.container_env.default_domain}"
  }

  postgres_admin_login = "wabadmin"
  platform_roles = {
    owner         = "wab_owner"
    builder       = "wab_builder"
    orchestration = "wab_orchestration"
    monitoring    = "wab_monitoring"
  }
}

# infra/bootstrap/setup-azure.sh creates the group and gives the deploy identity its roles on it,
# so Terraform reads the group and never creates or deletes it.
data "azurerm_resource_group" "this" {
  name = "rg-${local.stem}"
}

module "observability" {
  source = "../../modules/observability"

  name                = local.stem
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  daily_quota_gb      = var.log_daily_quota_gb
  tags                = local.tags
}

module "registry" {
  source = "../../modules/registry"

  name                = "cr${replace(local.stem, "-", "")}${local.suffix}"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  tags                = local.tags
}

module "container_env" {
  source = "../../modules/container_env"

  name                       = local.stem
  location                   = var.location
  resource_group_name        = data.azurerm_resource_group.this.name
  log_analytics_workspace_id = module.observability.log_analytics_workspace_id
  tags                       = local.tags
}

resource "random_password" "generated" {
  for_each = toset([
    "pg-admin-password",
    "n8n-db-password",
    "wab-owner-password",
    "wab-builder-password",
    "wab-orchestration-password",
    "wab-monitoring-password",
    "n8n-encryption-key",
    "n8n-owner-password",
    "step-key",
    "agent-api-key",
    "callback-signing-key",
    "settings-encryption-key",
  ])

  length      = 48
  special     = false
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
}

module "postgres" {
  source = "../../modules/postgres"

  name                   = "psql-${local.stem}-${local.suffix}"
  location               = var.location
  resource_group_name    = data.azurerm_resource_group.this.name
  administrator_login    = local.postgres_admin_login
  administrator_password = random_password.generated["pg-admin-password"].result
  databases              = ["platform", "n8n"]
  tags                   = local.tags
}

# The account key goes into Key Vault, because platform-api signs in with it today. Its managed
# identity also gets the data role, so it can sign in without the key once its code does.
module "cosmos" {
  source = "../../modules/cosmos"

  name                = "cosmos-${local.stem}-${local.suffix}"
  location            = var.cosmos_location == "" ? var.location : var.cosmos_location
  resource_group_name = data.azurerm_resource_group.this.name
  serverless          = var.cosmos_serverless
  data_contributors   = { platform-api = module.app["platform-api"].identity_principal_id }
  tags                = local.tags
}

module "key_vault" {
  source = "../../modules/key_vault"

  name                = "kv-${local.stem}-${local.suffix}"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  tags                = local.tags
  secrets = merge(
    { for name, password in random_password.generated : name => password.result },
    {
      for context, role in local.platform_roles :
      "database-url-${context}" => "postgresql://${role}:${random_password.generated["wab-${context}-password"].result}@${module.postgres.fqdn}:5432/platform?sslmode=require"
    },
    { "cosmos-key" = module.cosmos.primary_key },
    local.github_token_set ? { "github-token" = var.github_token } : {},
  )
}

locals {
  secret = module.key_vault.secrets

  apps = {
    platform-api = {
      image        = local.images["platform-api"]
      command      = null
      cpu          = 0.25
      memory       = "0.5Gi"
      min_replicas = 1
      max_replicas = 1
      # AUTH_MODE=dev refuses to start off localhost, so Azure always runs oidc. PUBLIC_BASE_URL
      # comes from the environment's domain, not from the Portal app, so the two apps do not
      # depend on each other.
      env = merge(
        {
          AUTH_MODE             = "oidc"
          PUBLIC_BASE_URL       = local.url["portal"]
          OIDC_ISSUER           = var.oidc_issuer
          OIDC_AUDIENCE         = var.oidc_audience
          AGENT_RUNTIME_URL     = local.url["agent-runtime"]
          N8N_BASE_URL          = local.url["n8n"]
          PLATFORM_INTERNAL_URL = local.url["platform-api"]
          COSMOS_ENDPOINT       = module.cosmos.endpoint
          ACTIVITY_READER       = "cosmos"
        },
        var.oidc_jwks_url == "" ? {} : { OIDC_JWKS_URL = var.oidc_jwks_url },
        local.first_people,
      )
      secrets = {
        DATABASE_URL_BUILDER       = local.secret["database-url-builder"]
        DATABASE_URL_ORCHESTRATION = local.secret["database-url-orchestration"]
        DATABASE_URL_MONITORING    = local.secret["database-url-monitoring"]
        AGENT_API_KEY              = local.secret["agent-api-key"]
        STEP_KEY                   = local.secret["step-key"]
        CALLBACK_SIGNING_KEY       = local.secret["callback-signing-key"]
        SETTINGS_ENCRYPTION_KEY    = local.secret["settings-encryption-key"]
        COSMOS_KEY                 = local.secret["cosmos-key"]
      }
    }

    agent-runtime = {
      image        = local.images["agent-runtime"]
      command      = null
      cpu          = 0.25
      memory       = "0.5Gi"
      min_replicas = 0
      max_replicas = 1
      env = {
        GITHUB_API_BASE          = var.github_api_base
        CALLBACK_ALLOWED_ORIGINS = local.url["platform-api"]
        PRACTICE_JIRA_URL        = var.practice_jira_url == "" ? local.url["platform-api"] : var.practice_jira_url
      }
      secrets = merge(
        { AGENT_API_KEY = local.secret["agent-api-key"] },
        local.github_token_set ? { GITHUB_TOKEN = local.secret["github-token"] } : {},
      )
    }

    n8n = {
      image        = local.images["n8n"]
      command      = null
      cpu          = 0.5
      memory       = "1Gi"
      min_replicas = 1
      max_replicas = 1
      env = {
        DB_TYPE                           = "postgresdb"
        DB_POSTGRESDB_HOST                = module.postgres.fqdn
        DB_POSTGRESDB_PORT                = "5432"
        DB_POSTGRESDB_DATABASE            = "n8n"
        DB_POSTGRESDB_USER                = "n8n"
        DB_POSTGRESDB_SSL_ENABLED         = "true"
        WEBHOOK_URL                       = "${local.url["n8n"]}/"
        N8N_DIAGNOSTICS_ENABLED           = "false"
        N8N_VERSION_NOTIFICATIONS_ENABLED = "false"
        N8N_PERSONALIZATION_ENABLED       = "false"
        N8N_HIRING_BANNER_ENABLED         = "false"
      }
      secrets = {
        DB_POSTGRESDB_PASSWORD = local.secret["n8n-db-password"]
        N8N_ENCRYPTION_KEY     = local.secret["n8n-encryption-key"]
      }
    }

    portal = {
      image        = local.images["portal"]
      command      = null
      cpu          = 0.25
      memory       = "0.5Gi"
      min_replicas = 0
      max_replicas = 1
      env = {
        PORTAL_MODE    = "live"
        API_UPSTREAM   = local.url["platform-api"]
        OIDC_AUTHORITY = var.oidc_issuer
        OIDC_CLIENT_ID = var.oidc_client_id
        OIDC_SCOPE     = var.oidc_scope
      }
      secrets = {}
    }
  }

  jobs = {
    db-init = {
      image           = local.images["postgres"]
      timeout_seconds = 300
      command = [
        "/bin/sh", "-c",
        "printf '%s\\n' \"$DB_INIT_SQL\" | psql -v ON_ERROR_STOP=1 -v n8n_pw=\"$N8N_DB_PASSWORD\" -v owner_pw=\"$WAB_OWNER_PASSWORD\" -v builder_pw=\"$WAB_BUILDER_PASSWORD\" -v orchestration_pw=\"$WAB_ORCHESTRATION_PASSWORD\" -v monitoring_pw=\"$WAB_MONITORING_PASSWORD\"",
      ]
      env = {
        PGHOST      = module.postgres.fqdn
        PGPORT      = "5432"
        PGDATABASE  = "postgres"
        PGUSER      = local.postgres_admin_login
        PGSSLMODE   = "require"
        DB_INIT_SQL = file("${path.module}/../../sql/db-init.sql")
      }
      secrets = {
        PGPASSWORD                 = local.secret["pg-admin-password"]
        N8N_DB_PASSWORD            = local.secret["n8n-db-password"]
        WAB_OWNER_PASSWORD         = local.secret["wab-owner-password"]
        WAB_BUILDER_PASSWORD       = local.secret["wab-builder-password"]
        WAB_ORCHESTRATION_PASSWORD = local.secret["wab-orchestration-password"]
        WAB_MONITORING_PASSWORD    = local.secret["wab-monitoring-password"]
      }
    }

    bootstrap = {
      image           = local.images["platform-api"]
      timeout_seconds = 600
      command         = ["python", "-m", "platform_api.bootstrap"]
      env = {
        N8N_BASE_URL          = local.url["n8n"]
        N8N_OWNER_EMAIL       = var.n8n_owner_email
        PLATFORM_INTERNAL_URL = local.url["platform-api"]
      }
      secrets = {
        DATABASE_URL_OWNER = local.secret["database-url-owner"]
        N8N_OWNER_PASSWORD = local.secret["n8n-owner-password"]
        STEP_KEY           = local.secret["step-key"]
      }
    }
  }
}

module "app" {
  source   = "../../modules/container_app"
  for_each = local.apps

  name                = each.key
  name_stem           = local.stem
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  environment_id      = module.container_env.id
  registry_id         = module.registry.id
  registry_server     = module.registry.login_server
  image               = each.value.image
  command             = each.value.command
  cpu                 = each.value.cpu
  memory              = each.value.memory
  min_replicas        = each.value.min_replicas
  max_replicas        = each.value.max_replicas
  ingress             = local.ingress[each.key]
  env                 = each.value.env
  secrets             = each.value.secrets
  tags                = local.tags
}

module "job" {
  source   = "../../modules/container_app_job"
  for_each = local.jobs

  name                = each.key
  name_stem           = local.stem
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  environment_id      = module.container_env.id
  registry_id         = module.registry.id
  registry_server     = module.registry.login_server
  image               = each.value.image
  command             = each.value.command
  cpu                 = 0.25
  memory              = "0.5Gi"
  timeout_seconds     = each.value.timeout_seconds
  env                 = each.value.env
  secrets             = each.value.secrets
  tags                = local.tags
}
