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
  jira_token_set   = nonsensitive(var.jira_api_token != "")

  # A real Jira (ADR 0035). Each setting is passed only when it is set, so an unset JIRA_BASE_URL
  # keeps platform-api's own practice Jira. The account's email is not secret.
  jira_settings = {
    for name, value in {
      JIRA_BASE_URL   = var.jira_base_url
      JIRA_EMAIL      = trimspace(nonsensitive(var.jira_email))
      JIRA_BROWSE_URL = var.jira_browse_url
    } : name => value if value != ""
  }

  # Confluence (ENGINE-PLAN E12, D2), set the same way. Unset keeps it not connected, and only the
  # pages in CONFLUENCE_PAGES are ever read. With no token of its own, platform-api signs in with
  # Jira's when both are on one Atlassian site.
  confluence_token_set = nonsensitive(var.confluence_api_token != "")
  confluence_settings = {
    for name, value in {
      CONFLUENCE_BASE_URL = var.confluence_base_url
      CONFLUENCE_EMAIL    = trimspace(var.confluence_email)
      CONFLUENCE_PAGES    = var.confluence_pages
    } : name => value if value != ""
  }

  # The keys the platform makes in n8n for n8n's own Jira, GitHub and Slack blocks (ADR 0045,
  # ENGINE-PLAN E16). Each secret sits in Key Vault, and platform-api makes the key in n8n only
  # once the system shows it can only read or post. Unset makes no key: a Jira key then reads the
  # practice Jira while it serves, and the other blocks never pass the check.
  n8n_key_secrets = {
    for name, value in {
      "n8n-key-jira-token"   = var.n8n_key_jira_token
      "n8n-key-github-token" = var.n8n_key_github_token
      "n8n-key-slack-token"  = var.n8n_key_slack_token
    } : name => value if nonsensitive(value != "")
  }
  n8n_key_env = {
    "n8n-key-jira-token"   = "N8N_KEY_JIRA_TOKEN"
    "n8n-key-github-token" = "N8N_KEY_GITHUB_TOKEN"
    "n8n-key-slack-token"  = "N8N_KEY_SLACK_TOKEN"
  }
  n8n_key_settings = {
    for name, value in {
      N8N_KEY_JIRA_URL   = var.n8n_key_jira_url
      N8N_KEY_JIRA_EMAIL = trimspace(var.n8n_key_jira_email)
      N8N_KEY_GITHUB_URL = var.n8n_key_github_url
    } : name => value if value != ""
  }

  # The same for the Teams Workflows webhook (ADR 0036). Unset keeps the practice Teams copy.
  teams_webhook_set = nonsensitive(var.teams_webhook_url != "")
  # And for the Tell flow, which posts a run's notice and emails it (ENGINE-PLAN D1). Unset keeps
  # the practice copy. The team's email list must be set with it.
  teams_tell_webhook_set = nonsensitive(var.teams_tell_webhook_url != "")
  tell_email_to          = trimspace(var.tell_email_to)

  # The first people's addresses are not secret, and the app table's for_each needs plain values.
  first_people = trimspace(nonsensitive(var.first_operator)) == "" ? {} : {
    FIRST_OPERATOR  = trimspace(nonsensitive(var.first_operator))
    FIRST_APPROVERS = trimspace(nonsensitive(var.first_approvers))
  }

  # n8n runs our own image, built on the n8n pin in public-images.json with our node pack inside.
  public_images = jsondecode(file("${path.module}/../../public-images.json"))
  images = merge(
    { for name, image in local.public_images : name => "${module.registry.login_server}/${image.repository}@${image.digest}" if name != "n8n" },
    { for name in ["platform-api", "agent-runtime", "portal", "n8n"] : name => "${module.registry.login_server}/${name}:${var.image_tag}" },
  )

  # n8n's editor (ADR 0034). The addresses only point at people, and the app table's for_each
  # needs plain values, so they are made plain here, as the first people are. One address is /32.
  n8n_editor_cidrs = [
    for entry in split(",", nonsensitive(var.n8n_editor_allowed_ips)) :
    strcontains(entry, "/") ? trimspace(entry) : "${trimspace(entry)}/32"
    if trimspace(entry) != ""
  ]
  # platform-api and the bootstrap job call n8n from inside the Container Apps environment. A
  # workload profiles environment reserves these ranges for itself, as "Restrictions for subnet
  # address ranges" in https://learn.microsoft.com/en-us/azure/container-apps/custom-virtual-networks
  # lists. ADR 0034 says what the deploy must confirm about them.
  n8n_internal_cidrs = [
    for entry in split(",", trimspace(var.n8n_internal_allowed_cidrs) == "" ? "100.100.0.0/17,100.100.128.0/19,100.100.160.0/19,100.100.192.0/19" : var.n8n_internal_allowed_cidrs) :
    strcontains(entry, "/") ? trimspace(entry) : "${trimspace(entry)}/32"
    if trimspace(entry) != ""
  ]
  # n8n loads every built-in block (ADR 0051), so anyone who reaches n8n can call a Webhook or a
  # Form a member published. Its editor opens only with addresses listed, and then Container Apps
  # lets in only those and the inside ranges.
  n8n_editor_open = var.n8n_editor_external && length(local.n8n_editor_cidrs) > 0
  n8n_allowed_cidrs = local.n8n_editor_open ? concat(
    [for i, cidr in local.n8n_editor_cidrs : { name = "editor-${i + 1}", cidr = cidr }],
    [for i, cidr in local.n8n_internal_cidrs : { name = "inside-environment-${i + 1}", cidr = cidr }],
  ) : []

  # Container Apps redirect plain HTTP to HTTPS, and our services do not follow redirects, so
  # every call between apps uses the HTTPS host name. Internal apps have "internal." in theirs.
  ingress = {
    platform-api  = { external = true, target_port = 8000 }
    agent-runtime = { external = false, target_port = 8100 }
    n8n           = { external = local.n8n_editor_open, target_port = 5678, allowed_cidrs = local.n8n_allowed_cidrs }
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

  # Langfuse (ADR 0050). Its secrets by Key Vault name, with the name the VM's env file gives each.
  # The VM's identity may read these and no other secret.
  langfuse_vm_secrets = {
    "langfuse-public-key"          = "LANGFUSE_INIT_PROJECT_PUBLIC_KEY"
    "langfuse-secret-key"          = "LANGFUSE_INIT_PROJECT_SECRET_KEY"
    "langfuse-salt"                = "SALT"
    "langfuse-encryption-key"      = "ENCRYPTION_KEY"
    "langfuse-nextauth-secret"     = "NEXTAUTH_SECRET"
    "langfuse-db-password"         = "LANGFUSE_DB_PASSWORD"
    "langfuse-clickhouse-password" = "CLICKHOUSE_PASSWORD"
    "langfuse-valkey-password"     = "VALKEY_PASSWORD"
    "langfuse-init-user-password"  = "LANGFUSE_INIT_USER_PASSWORD"
    "langfuse-storage-key"         = "STORAGE_ACCOUNT_KEY"
    "langfuse-entra-client-secret" = "AUTH_AZURE_AD_CLIENT_SECRET"
  }
  # Langfuse's own key formats.
  langfuse_key_prefix = {
    "langfuse-public-key" = "pk-lf-"
    "langfuse-secret-key" = "sk-lf-"
  }
  # Another system issues these, so a person sets them in Key Vault. The judge's key is for
  # Langfuse's LLM connection, which the setup script makes (ADR 0050, PR B). The VM never reads it.
  langfuse_secrets_set_by_a_person = ["langfuse-entra-client-secret", "langfuse-judge-anthropic-key"]
  # Langfuse's Entra app lives in the tenant the Portal signs people in with.
  langfuse_entra_tenant_id = try(regex("^https://login\\.microsoftonline\\.com/([0-9a-fA-F-]{36})/", var.oidc_issuer)[0], "")
  # The team's addresses for Langfuse, written as n8n's are. One address is /32.
  langfuse_team_cidrs = [
    for entry in split(",", nonsensitive(var.langfuse_allowed_ips)) :
    strcontains(entry, "/") ? trimspace(entry) : "${trimspace(entry)}/32"
    if trimspace(entry) != ""
  ]
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
    "n8n-runners-auth-token",
    "step-key",
    "wab-node-key",
    "wab-start-secret",
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

# Langfuse's secrets (ADR 0050), and the pseudonym key that platform-api names people in traces
# with. None exists while langfuse_enabled is false.
resource "random_password" "langfuse" {
  for_each = var.langfuse_enabled ? toset([
    "langfuse-public-key",
    "langfuse-secret-key",
    "langfuse-salt",
    "langfuse-nextauth-secret",
    "langfuse-db-password",
    "langfuse-clickhouse-password",
    "langfuse-valkey-password",
    "langfuse-init-user-password",
    "trace-pseudonym-key",
  ]) : toset([])

  length      = 48
  special     = false
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
}

# Langfuse's ENCRYPTION_KEY is 256 bits written as 64 hex characters. The digits plus "abcdef" as
# the only special characters make exactly that alphabet, and the value stays sensitive.
resource "random_password" "langfuse_encryption_key" {
  count = var.langfuse_enabled ? 1 : 0

  length           = 64
  upper            = false
  lower            = false
  numeric          = true
  special          = true
  override_special = "abcdef"
}

module "postgres" {
  source = "../../modules/postgres"

  name                   = "psql-${local.stem}-${local.suffix}"
  location               = var.location
  resource_group_name    = data.azurerm_resource_group.this.name
  administrator_login    = local.postgres_admin_login
  administrator_password = random_password.generated["pg-admin-password"].result
  databases              = concat(["platform", "n8n"], var.langfuse_enabled ? ["langfuse"] : [])
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
    local.jira_token_set ? { "jira-api-token" = var.jira_api_token } : {},
    local.confluence_token_set ? { "confluence-api-token" = var.confluence_api_token } : {},
    local.teams_webhook_set ? { "teams-webhook-url" = var.teams_webhook_url } : {},
    local.teams_tell_webhook_set ? { "teams-tell-webhook-url" = var.teams_tell_webhook_url } : {},
    local.n8n_key_secrets,
    var.langfuse_enabled ? merge(
      {
        for name, password in random_password.langfuse :
        name => "${lookup(local.langfuse_key_prefix, name, "")}${password.result}"
      },
      {
        "langfuse-encryption-key" = random_password.langfuse_encryption_key[0].result
        "langfuse-storage-key"    = module.langfuse_vm[0].storage_account_key
      },
    ) : {},
  )
  secrets_set_by_a_person = var.langfuse_enabled ? local.langfuse_secrets_set_by_a_person : []
}

# Langfuse on one small VM, not on Container Apps (ADR 0050). Off by default, so plan makes nothing.
module "langfuse_vm" {
  source = "../../modules/langfuse_vm"
  count  = var.langfuse_enabled ? 1 : 0

  name                 = "langfuse-${local.stem}"
  location             = var.location
  resource_group_name  = data.azurerm_resource_group.this.name
  dns_label            = "langfuse-${local.stem}-${local.suffix}"
  storage_account_name = "stlf${replace(local.stem, "-", "")}${local.suffix}"
  secrets              = { for name, env_name in local.langfuse_vm_secrets : env_name => local.secret[name] }
  # The apps share the environment's outbound addresses, which other Azure customers can share
  # too, so Langfuse's keys and sign-in still guard it.
  allowed_https_cidrs = distinct(concat(
    module.app["platform-api"].outbound_ip_addresses,
    module.app["agent-runtime"].outbound_ip_addresses,
    local.langfuse_team_cidrs,
  ))
  postgres_host              = module.postgres.fqdn
  owner_email                = trimspace(var.langfuse_owner_email)
  entra_tenant_id            = local.langfuse_entra_tenant_id
  entra_client_id            = var.langfuse_entra_client_id
  log_analytics_workspace_id = module.observability.log_analytics_workspace_id
  alert_email                = trimspace(var.langfuse_alert_email)
  deployer_principal_id      = var.deploy_principal_object_id
  tags                       = local.tags
}

locals {
  # n8n's settings that keep what a workflow runs away from n8n's secrets (ADR 0051, spike P9). n8n
  # loads every built-in block but those in NODES_EXCLUDE, so these settings are the guard. n8n
  # and the bootstrap job get the same map, and bootstrap refuses to start the platform unless each
  # holds (platform-api's n8n_guard.py). NODE_FUNCTION_ALLOW_BUILTIN, NODE_FUNCTION_ALLOW_EXTERNAL
  # and N8N_RUNNERS_INSECURE_MODE stay unset. deploy/compose.yaml's x-n8n-guards holds the same.
  n8n_guards = {
    # n8n never loads a block that reaches its own secrets, disk or host: Execute Command, Local File
    # Trigger, Function, Function Item, LangChain Code, and Git with its tool (n8n_blocks.LEFT_OUT).
    NODES_EXCLUDE = jsonencode([
      "n8n-nodes-base.executeCommand",
      "n8n-nodes-base.localFileTrigger",
      "n8n-nodes-base.function",
      "n8n-nodes-base.functionItem",
      "@n8n/n8n-nodes-langchain.code",
      "n8n-nodes-base.git",
      "n8n-nodes-base.gitTool",
    ])
    N8N_COMMUNITY_PACKAGES_ENABLED = "false"
    # No $env in expressions, and n8n hands none of its environment to the task runner.
    N8N_BLOCK_ENV_ACCESS_IN_NODE = "true"
    # Code, AI Transform, the Code Tool, Sort and Item Lists run their code in the task runner
    # app, module.n8n_runners, which holds none of n8n's secrets.
    N8N_RUNNERS_MODE = "external"
    # n8n also refuses Function, Function Item and LangChain Code as deprecated.
    N8N_DEPRECATED_NODES_BLOCK = "true"
    # The file blocks reach only this folder, never n8n's own folders, and never /proc.
    N8N_RESTRICT_FILE_ACCESS_TO        = "/home/node/.n8n-files"
    N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES = "true"
  }

  # More ports each app listens on, reachable only from inside the environment.
  internal_ports = {
    n8n = [5679]
  }
}

locals {
  secret = module.key_vault.secrets

  # Tracing (ADR 0050). Off, neither app gets any Langfuse setting, and tracing stays off.
  langfuse_env = var.langfuse_enabled ? {
    LANGFUSE_BASE_URL = module.langfuse_vm[0].url
  } : {}
  langfuse_keys = var.langfuse_enabled ? {
    LANGFUSE_PUBLIC_KEY = local.secret["langfuse-public-key"]
    LANGFUSE_SECRET_KEY = local.secret["langfuse-secret-key"]
  } : {}

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
          AUTH_MODE              = "oidc"
          PUBLIC_BASE_URL        = local.url["portal"]
          OIDC_ISSUER            = var.oidc_issuer
          OIDC_AUDIENCE          = var.oidc_audience
          AGENT_RUNTIME_URL      = local.url["agent-runtime"]
          N8N_BASE_URL           = local.url["n8n"]
          N8N_OWNER_EMAIL        = var.n8n_owner_email
          PLATFORM_INTERNAL_URL  = local.url["platform-api"]
          COSMOS_ENDPOINT        = module.cosmos.endpoint
          ACTIVITY_READER        = "cosmos"
          JIRA_API_FLAVOR        = var.jira_api_flavor
          JIRA_ISSUE_TYPE        = var.jira_issue_type
          WATCHLIST_JIRA_PROJECT = var.watchlist_jira_project
          TEAM_TIME_ZONE         = var.team_time_zone
        },
        var.oidc_jwks_url == "" ? {} : { OIDC_JWKS_URL = var.oidc_jwks_url },
        var.teams_channel == "" ? {} : { TEAMS_CHANNEL = var.teams_channel },
        # Staff reach n8n's editor only while it is open, so only then do they get n8n accounts
        # (ENGINE-PLAN 2.9). platform-api still waits for a bootstrap that proved n8n's guards.
        local.n8n_editor_open ? {
          N8N_STAFF_ACCESS = "on"
          N8N_EDITOR_URL   = local.url["n8n"]
        } : {},
        local.tell_email_to == "" ? {} : { TELL_EMAIL_TO = local.tell_email_to },
        local.first_people,
        local.jira_settings,
        local.confluence_settings,
        local.n8n_key_settings,
        local.langfuse_env,
      )
      secrets = merge(
        {
          DATABASE_URL_BUILDER       = local.secret["database-url-builder"]
          DATABASE_URL_ORCHESTRATION = local.secret["database-url-orchestration"]
          DATABASE_URL_MONITORING    = local.secret["database-url-monitoring"]
          AGENT_API_KEY              = local.secret["agent-api-key"]
          STEP_KEY                   = local.secret["step-key"]
          WAB_NODE_KEY               = local.secret["wab-node-key"]
          WAB_START_SECRET           = local.secret["wab-start-secret"]
          N8N_OWNER_PASSWORD         = local.secret["n8n-owner-password"]
          CALLBACK_SIGNING_KEY       = local.secret["callback-signing-key"]
          SETTINGS_ENCRYPTION_KEY    = local.secret["settings-encryption-key"]
          COSMOS_KEY                 = local.secret["cosmos-key"]
        },
        local.jira_token_set ? { JIRA_API_TOKEN = local.secret["jira-api-token"] } : {},
        local.confluence_token_set ? {
          CONFLUENCE_API_TOKEN = local.secret["confluence-api-token"]
        } : {},
        local.teams_webhook_set ? { TEAMS_WEBHOOK_URL = local.secret["teams-webhook-url"] } : {},
        local.teams_tell_webhook_set ? {
          TEAMS_TELL_WEBHOOK_URL = local.secret["teams-tell-webhook-url"]
        } : {},
        { for name in keys(local.n8n_key_secrets) : local.n8n_key_env[name] => local.secret[name] },
        local.langfuse_keys,
        var.langfuse_enabled ? { TRACE_PSEUDONYM_KEY = local.secret["trace-pseudonym-key"] } : {},
      )
    }

    agent-runtime = {
      image        = local.images["agent-runtime"]
      command      = null
      cpu          = 0.25
      memory       = "0.5Gi"
      min_replicas = 0
      max_replicas = 1
      env = merge(
        {
          GITHUB_API_BASE          = var.github_api_base
          CALLBACK_ALLOWED_ORIGINS = local.url["platform-api"]
          PLATFORM_JIRA_URL        = local.url["platform-api"]
          PLANNER_MODE             = var.planner_mode
        },
        local.langfuse_env,
        var.langfuse_enabled ? {
          LANGFUSE_TRACING_ENVIRONMENT = "azure-${var.environment}"
          LANGFUSE_RELEASE             = var.image_tag
        } : {},
      )
      secrets = merge(
        { AGENT_API_KEY = local.secret["agent-api-key"] },
        local.github_token_set ? { GITHUB_TOKEN = local.secret["github-token"] } : {},
        local.langfuse_keys,
      )
    }

    n8n = {
      image        = local.images["n8n"]
      command      = null
      cpu          = 0.5
      memory       = "1Gi"
      min_replicas = 1
      max_replicas = 1
      # With its editor open, n8n builds its links from its public address. n8n listens on 5678,
      # so without N8N_EDITOR_BASE_URL it would add :5678 to them.
      #
      # N8N_PROXY_HOPS trusts the one X-Forwarded-For hop that Container Apps' ingress adds. Without
      # it n8n sees the proxy's address for everyone, so one visitor could use up the sign-in
      # limit for all, the bootstrap included.
      #
      # It also creates its owner from these settings, so its setup page never offers the owner to
      # a visitor. n8n 2.42.6 runs this in start.js's init(), before server.start() registers any
      # REST route, and rewrites the owner on every start (OwnerInstanceSettingsLoader,
      # overwriteExisting). The bootstrap's own setup call then gets "Instance owner already setup"
      # and signs in, as on any later run. The names match the ones the bootstrap uses. The hash is
      # in local.inline_secrets.
      #
      # GENERIC_TIMEZONE is the team time zone, so a workflow set to n8n's default zone runs on the
      # team's, as platform-api reads it.
      env = merge(
        local.n8n_guards,
        {
          DB_TYPE                           = "postgresdb"
          DB_POSTGRESDB_HOST                = module.postgres.fqdn
          DB_POSTGRESDB_PORT                = "5432"
          DB_POSTGRESDB_DATABASE            = "n8n"
          DB_POSTGRESDB_USER                = "n8n"
          DB_POSTGRESDB_SSL_ENABLED         = "true"
          WEBHOOK_URL                       = "${local.url["n8n"]}/"
          GENERIC_TIMEZONE                  = var.team_time_zone
          N8N_DIAGNOSTICS_ENABLED           = "false"
          N8N_VERSION_NOTIFICATIONS_ENABLED = "false"
          N8N_PERSONALIZATION_ENABLED       = "false"
          N8N_HIRING_BANNER_ENABLED         = "false"
          # Stops n8n asking api.n8n.io for its list of MCP servers every 8 hours (issue #86). We use no
          # MCP servers in n8n, and the block catalogue leaves those blocks out (ADR 0051), as local does.
          N8N_DISABLED_MODULES = "mcp-registry"
          # The broker the task runner app connects to, on port 5679, which only apps inside the
          # environment reach (internal_ports). Container Apps' ingress reaches the container on
          # its own address, which n8n can't know before it starts, so the broker listens on every
          # address of the container. The token guards it, and infra/README.md lists who else
          # in the environment reaches it as a check for the deploy.
          N8N_RUNNERS_BROKER_LISTEN_ADDRESS = "0.0.0.0"
          # 30 days of executions (ENGINE-PLAN D10). A waiting execution is never pruned (P7 Q16).
          EXECUTIONS_DATA_PRUNE           = "true"
          EXECUTIONS_DATA_MAX_AGE         = "720"
          EXECUTIONS_DATA_SAVE_ON_SUCCESS = "all"
          WAB_API_URL                     = local.url["platform-api"]
        },
        local.n8n_editor_open ? {
          N8N_PROTOCOL                      = "https"
          N8N_HOST                          = trimprefix(local.url["n8n"], "https://")
          N8N_EDITOR_BASE_URL               = "${local.url["n8n"]}/"
          N8N_PROXY_HOPS                    = "1"
          N8N_INSTANCE_OWNER_MANAGED_BY_ENV = "true"
          N8N_INSTANCE_OWNER_EMAIL          = var.n8n_owner_email
          N8N_INSTANCE_OWNER_FIRST_NAME     = "Platform"
          N8N_INSTANCE_OWNER_LAST_NAME      = "Bootstrap"
        } : {},
      )
      secrets = {
        DB_POSTGRESDB_PASSWORD = local.secret["n8n-db-password"]
        N8N_ENCRYPTION_KEY     = local.secret["n8n-encryption-key"]
        WAB_NODE_KEY           = local.secret["wab-node-key"]
        WAB_START_SECRET       = local.secret["wab-start-secret"]
        N8N_RUNNERS_AUTH_TOKEN = local.secret["n8n-runners-auth-token"]
      }
    }

    portal = {
      image        = local.images["portal"]
      command      = null
      cpu          = 0.25
      memory       = "0.5Gi"
      min_replicas = 0
      max_replicas = 1
      # With a real Jira, ticket keys link there and the Portal hides its Practice Jira page.
      env = merge(
        {
          PORTAL_MODE    = "live"
          API_UPSTREAM   = local.url["platform-api"]
          OIDC_AUTHORITY = var.oidc_issuer
          OIDC_CLIENT_ID = var.oidc_client_id
          OIDC_SCOPE     = var.oidc_scope
        },
        var.jira_base_url == "" ? {} : {
          JIRA_BROWSE_URL = var.jira_browse_url != "" ? var.jira_browse_url : "${trimsuffix(var.jira_base_url, "/")}/browse/{key}"
        },
      )
      secrets = {}
    }
  }

  # Secrets that are not in Key Vault, by app. They stay out of the app table, because its
  # for_each needs plain values. n8n's owner password hash is the stored bcrypt hash of the
  # password the bootstrap signs in with, so it is the same on every plan.
  inline_secrets = {
    n8n = local.n8n_editor_open ? {
      N8N_INSTANCE_OWNER_PASSWORD_HASH = random_password.generated["n8n-owner-password"].bcrypt_hash
    } : {}
  }

  jobs = {
    db-init = {
      image           = local.images["postgres"]
      timeout_seconds = 300
      command = [
        "/bin/sh", "-c",
        "printf '%s\\n' \"$DB_INIT_SQL\" | psql -v ON_ERROR_STOP=1 -v n8n_pw=\"$N8N_DB_PASSWORD\" -v owner_pw=\"$WAB_OWNER_PASSWORD\" -v builder_pw=\"$WAB_BUILDER_PASSWORD\" -v orchestration_pw=\"$WAB_ORCHESTRATION_PASSWORD\" -v monitoring_pw=\"$WAB_MONITORING_PASSWORD\"${var.langfuse_enabled ? " -v langfuse_pw=\"$LANGFUSE_DB_PASSWORD\"" : ""}",
      ]
      env = {
        PGHOST     = module.postgres.fqdn
        PGPORT     = "5432"
        PGDATABASE = "postgres"
        PGUSER     = local.postgres_admin_login
        PGSSLMODE  = "require"
        DB_INIT_SQL = join("\n", concat(
          [file("${path.module}/../../sql/db-init.sql")],
          var.langfuse_enabled ? [file("${path.module}/../../sql/db-init-langfuse.sql")] : [],
        ))
      }
      secrets = merge(
        {
          PGPASSWORD                 = local.secret["pg-admin-password"]
          N8N_DB_PASSWORD            = local.secret["n8n-db-password"]
          WAB_OWNER_PASSWORD         = local.secret["wab-owner-password"]
          WAB_BUILDER_PASSWORD       = local.secret["wab-builder-password"]
          WAB_ORCHESTRATION_PASSWORD = local.secret["wab-orchestration-password"]
          WAB_MONITORING_PASSWORD    = local.secret["wab-monitoring-password"]
        },
        var.langfuse_enabled ? { LANGFUSE_DB_PASSWORD = local.secret["langfuse-db-password"] } : {},
      )
    }

    migrate = {
      image           = local.images["platform-api"]
      timeout_seconds = 300
      command         = ["python", "-m", "platform_api.migrate"]
      env             = {}
      secrets = {
        DATABASE_URL_OWNER = local.secret["database-url-owner"]
      }
    }

    bootstrap = {
      image           = local.images["platform-api"]
      timeout_seconds = 600
      command         = ["python", "-m", "platform_api.bootstrap"]
      # The same guards n8n gets, which bootstrap checks before the platform starts (ADR 0051).
      env = merge(local.n8n_guards, {
        N8N_BASE_URL          = local.url["n8n"]
        N8N_OWNER_EMAIL       = var.n8n_owner_email
        PLATFORM_INTERNAL_URL = local.url["platform-api"]
        TEAM_TIME_ZONE        = var.team_time_zone
      })
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
  internal_ports      = lookup(local.internal_ports, each.key, [])
  env                 = each.value.env
  secrets             = each.value.secrets
  inline_secrets      = lookup(local.inline_secrets, each.key, {})
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

# n8n's external task runner, in an app of its own with none of n8n's secrets (ADR 0051, spike
# P9). It calls n8n's broker on the port n8n's app opens inside the environment.
module "n8n_runners" {
  source = "../../modules/task_runner"

  name                = "n8n-runners"
  name_stem           = local.stem
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  resource_group_id   = data.azurerm_resource_group.this.id
  environment_id      = module.container_env.id
  registry_id         = module.registry.id
  registry_server     = module.registry.login_server
  image               = local.images["n8n-runners"]
  broker_uri          = "http://n8n:${local.internal_ports.n8n[0]}"
  auth_token          = local.secret["n8n-runners-auth-token"]
  time_zone           = var.team_time_zone
  tags                = local.tags
}
