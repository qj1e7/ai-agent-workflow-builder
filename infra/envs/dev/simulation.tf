# The simulation n8n (ADR 0054): a second n8n where a workflow version is tried against mock
# systems before its test run. None of it exists while enable_simulation is false.
#
# It runs in a Container Apps environment of its own, on a subnet of its own. Apps in one
# environment share its subnet, so nothing of the platform's runs there. A network security group
# keeps the subnet off the internet and away from the platform: it reaches its own subnet, and only
# the Azure services Container Apps needs to pull images, sign in and send logs. Those service tags
# cover every Azure customer's registries and storage, not only ours, so isolation rests on holding
# no real key, and the network is a second layer (ADR 0054, spike item S6).
#
# It holds no real key. Every key here is made by Terraform for the simulation alone and kept as
# the apps' own secrets. No app or job here reads Key Vault, and no identity here has a Key Vault
# role. deploy/compose.simulation.yaml is the same stack on a laptop and in CI.

locals {
  simulation_subnet = "10.81.0.0/27"

  # What the subnet may reach besides itself, from "Securing a virtual network" in Azure's
  # Container Apps docs for a workload profiles environment. Our registry is Basic, with no private
  # endpoint, so pulling from it needs the registry and storage tags.
  simulation_outbound = {
    container-apps-system  = { priority = 110, protocol = "Tcp", port = "443", to = "MicrosoftContainerRegistry" }
    front-door-first-party = { priority = 120, protocol = "Tcp", port = "443", to = "AzureFrontDoor.FirstParty" }
    our-registry           = { priority = 130, protocol = "Tcp", port = "443", to = "AzureContainerRegistry" }
    registry-storage       = { priority = 140, protocol = "Tcp", port = "443", to = "Storage.${var.location}" }
    managed-identity       = { priority = 150, protocol = "Tcp", port = "443", to = "AzureActiveDirectory" }
    logs                   = { priority = 160, protocol = "Tcp", port = "443", to = "AzureMonitor" }
    azure-dns              = { priority = 170, protocol = "*", port = "53", to = "168.63.129.16/32" }
  }

  # The apps reach each other by name inside the environment, over HTTPS as the platform's do.
  simulation_domain = try(module.simulation_env[0].default_domain, "")
  simulation_url = {
    for name in ["sim-n8n", "sim-gateway", "sim-mock-github"] :
    name => "https://${name}.internal.${local.simulation_domain}"
  }

  # Each app's secrets name the simulation's own keys in random_password.simulation.
  simulation_apps = {
    for name, app in {
      sim-postgres = {
        image        = local.images["postgres"]
        cpu          = 0.25
        memory       = "0.5Gi"
        min_replicas = 1
        max_replicas = 1
        # Its data lives in the container only, so a restart starts it empty, and the
        # simulation's jobs must run again.
        ingress        = { external = false, target_port = 5432, transport = "tcp", exposed_port = 5432 }
        internal_ports = []
        env            = {}
        secrets        = { POSTGRES_PASSWORD = "postgres-password" }
      }

      # Our n8n with the platform n8n's guards and image. Our blocks call the simulation gateway,
      # which ADR 0054's PR 3 adds as sim-gateway. Until then nothing answers there.
      sim-n8n = {
        image        = local.images["n8n"]
        cpu          = 0.5
        memory       = "1Gi"
        min_replicas = 1
        max_replicas = 1
        ingress      = { external = false, target_port = 5678 }
        # The broker its task runner calls, which only apps in this environment reach.
        internal_ports = [5679]
        env = merge(local.n8n_guards, {
          DB_TYPE                           = "postgresdb"
          DB_POSTGRESDB_HOST                = "sim-postgres"
          DB_POSTGRESDB_PORT                = "5432"
          DB_POSTGRESDB_DATABASE            = "n8n"
          DB_POSTGRESDB_USER                = "n8n"
          WEBHOOK_URL                       = "${local.simulation_url["sim-n8n"]}/"
          GENERIC_TIMEZONE                  = var.team_time_zone
          N8N_DIAGNOSTICS_ENABLED           = "false"
          N8N_VERSION_NOTIFICATIONS_ENABLED = "false"
          N8N_PERSONALIZATION_ENABLED       = "false"
          N8N_HIRING_BANNER_ENABLED         = "false"
          N8N_DISABLED_MODULES              = "mcp-registry"
          N8N_RUNNERS_BROKER_LISTEN_ADDRESS = "0.0.0.0"
          EXECUTIONS_DATA_SAVE_ON_SUCCESS   = "all"
          WAB_REQUEST_TIMEOUT_SECONDS       = local.n8n_request_timeout_seconds
          WAB_API_URL                       = local.simulation_url["sim-gateway"]
        })
        secrets = {
          DB_POSTGRESDB_PASSWORD = "n8n-db-password"
          N8N_ENCRYPTION_KEY     = "n8n-encryption-key"
          WAB_NODE_KEY           = "node-key"
          WAB_START_SECRET       = "start-secret"
          N8N_RUNNERS_AUTH_TOKEN = "runners-token"
        }
      }

      # The deploy does not push this image yet. infra/README.md says what turning it on needs.
      sim-mock-github = {
        image          = "${module.registry.login_server}/mock-github:${var.image_tag}"
        cpu            = 0.25
        memory         = "0.5Gi"
        min_replicas   = 0
        max_replicas   = 1
        ingress        = { external = false, target_port = 8200 }
        internal_ports = []
        env            = {}
        secrets        = {}
      }
    } : name => app if var.enable_simulation
  }

  simulation_jobs = {
    for name, job in {
      # Makes the two databases, then the roles, as db-init does for the platform.
      sim-db-init = {
        image           = local.images["postgres"]
        timeout_seconds = 300
        command = [
          "/bin/sh", "-c",
          "printf '%s\\n' \"$DB_INIT_SQL\" | psql -v ON_ERROR_STOP=1 -v n8n_pw=\"$N8N_DB_PASSWORD\" -v owner_pw=\"$WAB_OWNER_PASSWORD\" -v builder_pw=\"$WAB_BUILDER_PASSWORD\" -v orchestration_pw=\"$WAB_ORCHESTRATION_PASSWORD\" -v monitoring_pw=\"$WAB_MONITORING_PASSWORD\"",
        ]
        env = {
          PGHOST     = "sim-postgres"
          PGPORT     = "5432"
          PGDATABASE = "postgres"
          PGUSER     = "postgres"
          PGSSLMODE  = "disable"
          DB_INIT_SQL = join("\n", [
            file("${path.module}/../../sql/db-init-simulation.sql"),
            file("${path.module}/../../sql/db-init.sql"),
          ])
        }
        secrets = {
          PGPASSWORD                 = "postgres-password"
          N8N_DB_PASSWORD            = "n8n-db-password"
          WAB_OWNER_PASSWORD         = "owner-password"
          WAB_BUILDER_PASSWORD       = "builder-password"
          WAB_ORCHESTRATION_PASSWORD = "orchestration-password"
          WAB_MONITORING_PASSWORD    = "monitoring-password"
        }
      }

      # platform-api's own bootstrap, against the simulation n8n and its database.
      sim-bootstrap = {
        image           = local.images["platform-api"]
        timeout_seconds = 600
        command         = ["python", "-m", "platform_api.bootstrap"]
        env = merge(local.n8n_guards, {
          N8N_BASE_URL          = local.simulation_url["sim-n8n"]
          N8N_OWNER_EMAIL       = "owner@simulation.example"
          PLATFORM_INTERNAL_URL = local.simulation_url["sim-gateway"]
          TEAM_TIME_ZONE        = var.team_time_zone
        })
        secrets = {
          DATABASE_URL_OWNER = "database-url-owner"
          N8N_OWNER_PASSWORD = "n8n-owner-password"
          STEP_KEY           = "step-key"
        }
      }
    } : name => job if var.enable_simulation
  }

  # The simulation's keys by name, and the database address its bootstrap signs in with.
  simulation_keys = merge(
    { for name, password in random_password.simulation : name => password.result },
    {
      for name in var.enable_simulation ? ["database-url-owner"] : [] :
      name => "postgresql://wab_owner:${random_password.simulation["owner-password"].result}@sim-postgres:5432/platform"
    },
  )
}

resource "random_password" "simulation" {
  for_each = var.enable_simulation ? toset([
    "postgres-password",
    "n8n-db-password",
    "owner-password",
    "builder-password",
    "orchestration-password",
    "monitoring-password",
    "n8n-encryption-key",
    "n8n-owner-password",
    "runners-token",
    "step-key",
    "node-key",
    "start-secret",
  ]) : toset([])

  length      = 48
  special     = false
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
}

resource "azurerm_virtual_network" "simulation" {
  count = var.enable_simulation ? 1 : 0

  name                = "vnet-${local.stem}-sim"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  address_space       = ["10.81.0.0/24"]
  tags                = local.tags
}

resource "azurerm_subnet" "simulation" {
  count = var.enable_simulation ? 1 : 0

  name                 = "snet-${local.stem}-sim"
  resource_group_name  = data.azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.simulation[0].name
  address_prefixes     = [local.simulation_subnet]

  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_network_security_group" "simulation" {
  count = var.enable_simulation ? 1 : 0

  name                = "nsg-${local.stem}-sim"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  tags                = local.tags

  security_rule {
    name                       = "in-from-own-subnet"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = local.simulation_subnet
    destination_address_prefix = local.simulation_subnet
  }

  # Azure's load balancer checks the environment's health.
  security_rule {
    name                       = "in-from-load-balancer"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = local.simulation_subnet
  }

  security_rule {
    name                       = "in-nothing-else"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "out-to-own-subnet"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = local.simulation_subnet
    destination_address_prefix = local.simulation_subnet
  }

  dynamic "security_rule" {
    for_each = local.simulation_outbound
    content {
      name                       = "out-to-${security_rule.key}"
      priority                   = security_rule.value.priority
      direction                  = "Outbound"
      access                     = "Allow"
      protocol                   = security_rule.value.protocol
      source_port_range          = "*"
      destination_port_range     = security_rule.value.port
      source_address_prefix      = local.simulation_subnet
      destination_address_prefix = security_rule.value.to
    }
  }

  # Azure's own default rules would let it reach the internet and the rest of the network.
  security_rule {
    name                       = "out-nothing-else"
    priority                   = 4096
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "simulation" {
  count = var.enable_simulation ? 1 : 0

  subnet_id                 = azurerm_subnet.simulation[0].id
  network_security_group_id = azurerm_network_security_group.simulation[0].id
}

# Its own environment, with no public address, made only once the subnet has its rules.
module "simulation_env" {
  source = "../../modules/container_env"
  count  = var.enable_simulation ? 1 : 0

  name                           = "${local.stem}-sim"
  location                       = var.location
  resource_group_name            = data.azurerm_resource_group.this.name
  log_analytics_workspace_id     = module.observability.log_analytics_workspace_id
  infrastructure_subnet_id       = azurerm_subnet.simulation[0].id
  internal_load_balancer_enabled = true
  tags                           = local.tags

  depends_on = [azurerm_subnet_network_security_group_association.simulation]
}

module "simulation_app" {
  source   = "../../modules/container_app"
  for_each = local.simulation_apps

  name                = each.key
  name_stem           = local.stem
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  environment_id      = module.simulation_env[0].id
  registry_id         = module.registry.id
  registry_server     = module.registry.login_server
  image               = each.value.image
  command             = null
  cpu                 = each.value.cpu
  memory              = each.value.memory
  min_replicas        = each.value.min_replicas
  max_replicas        = each.value.max_replicas
  ingress             = each.value.ingress
  internal_ports      = each.value.internal_ports
  env                 = each.value.env
  secrets             = {}
  inline_secrets      = { for name, key in each.value.secrets : name => local.simulation_keys[key] }
  tags                = local.tags
}

module "simulation_job" {
  source   = "../../modules/container_app_job"
  for_each = local.simulation_jobs

  name                = each.key
  name_stem           = local.stem
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  environment_id      = module.simulation_env[0].id
  registry_id         = module.registry.id
  registry_server     = module.registry.login_server
  image               = each.value.image
  command             = each.value.command
  cpu                 = 0.25
  memory              = "0.5Gi"
  timeout_seconds     = each.value.timeout_seconds
  env                 = each.value.env
  secrets             = {}
  inline_secrets      = { for name, key in each.value.secrets : name => local.simulation_keys[key] }
  tags                = local.tags
}

# The simulation n8n's task runner, as the platform's is (ADR 0051), with its token as a value.
module "simulation_n8n_runners" {
  source = "../../modules/task_runner"
  count  = var.enable_simulation ? 1 : 0

  name                = "sim-n8n-runners"
  name_stem           = local.stem
  location            = var.location
  resource_group_name = data.azurerm_resource_group.this.name
  resource_group_id   = data.azurerm_resource_group.this.id
  environment_id      = module.simulation_env[0].id
  registry_id         = module.registry.id
  registry_server     = module.registry.login_server
  image               = local.images["n8n-runners"]
  broker_uri          = "http://sim-n8n:5679"
  auth_token_value    = random_password.simulation["runners-token"].result
  time_zone           = var.team_time_zone
  tags                = local.tags
}
