data "azurerm_client_config" "current" {}

locals {
  # The same name the apps get, so Caddy's certificate always matches LANGFUSE_BASE_URL.
  fqdn = azurerm_public_ip.this.fqdn

  # infra/bootstrap/setup-azure.sh creates this role with the same name, because the deploy
  # identity may not write role definitions.
  run_command_role = "Langfuse VM run command (${var.resource_group_name})"

  compose = templatefile("${path.module}/compose.yaml.tftpl", {
    fqdn            = local.fqdn
    postgres_host   = var.postgres_host
    storage_account = azurerm_storage_account.this.name
    blob_endpoint   = trimsuffix(azurerm_storage_account.this.primary_blob_endpoint, "/")
    container       = azurerm_storage_container.langfuse.name
    owner_email     = var.owner_email
    entra_tenant_id = var.entra_tenant_id
    entra_client_id = var.entra_client_id
  })

  cloud_init = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    compose    = local.compose
    caddyfile  = "${local.fqdn} {\n    reverse_proxy langfuse-web:3000\n}\n"
    clickhouse = file("${path.module}/clickhouse-logs.xml")
    secrets_script = templatefile("${path.module}/langfuse-secrets.sh.tftpl", {
      client_id = azurerm_user_assigned_identity.this.client_id
      secrets   = { for name, secret in var.secrets : name => secret.url }
    })
  })
}

resource "azurerm_virtual_network" "this" {
  name                = "vnet-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  address_space       = ["10.80.0.0/24"]
  tags                = var.tags
}

resource "azurerm_subnet" "this" {
  name                            = "snet-${var.name}"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = ["10.80.0.0/26"]
  default_outbound_access_enabled = false
}

# Only Caddy is reachable. 443 takes the apps and the team. 80 stays open to everyone, because
# Let's Encrypt checks the certificate request there, and Caddy redirects everything else to 443.
# Nothing else comes in: people use run-command, not SSH.
resource "azurerm_network_security_group" "this" {
  #checkov:skip=CKV_AZURE_160:Let's Encrypt checks the certificate request on port 80, from addresses it does not publish. Caddy answers nothing else there but a redirect to 443.
  name                = "nsg-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "https-from-apps-and-team"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefixes    = sort(distinct(var.allowed_https_cidrs))
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "http-for-certificates"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }

  # Azure's own default rules also let in the virtual network and its load balancer.
  security_rule {
    name                       = "deny-everything-else"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "this" {
  subnet_id                 = azurerm_subnet.this.id
  network_security_group_id = azurerm_network_security_group.this.id
}

# The name stays when the VM is replaced, so the Entra redirect URI and the apps' setting do not change.
resource "azurerm_public_ip" "this" {
  name                = "pip-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = var.dns_label
  tags                = var.tags
}

resource "azurerm_network_interface" "this" {
  #checkov:skip=CKV_AZURE_119:Caddy needs a public address for Let's Encrypt, and the Container Apps environment has no virtual network to reach a private one. The security group admits 443 and 80 only.
  name                = "nic-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.this.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.this.id
  }
}

resource "azurerm_user_assigned_identity" "this" {
  name                = "id-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "secret_reader" {
  for_each = var.secrets

  scope                = each.value.scope
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
  principal_type       = "ServicePrincipal"
}

# The VM reads its secrets on first boot. Azure RBAC can take minutes to reach Key Vault, so the
# VM waits for its roles. The boot script also retries.
resource "time_sleep" "rbac_propagation" {
  create_duration = "90s"

  triggers = {
    identity_id = azurerm_user_assigned_identity.this.id
    roles       = join(",", [for assignment in azurerm_role_assignment.secret_reader : assignment.id])
  }
}

# Any change to custom_data replaces the VM, and with it the traces on its disk. The deploy's plan
# guard stops for allow_destroy first.
# tflint-ignore: azurerm_resources_missing_prevent_destroy # Traces are a 60-day working record. What must last lives in git (ADR 0050).
resource "azurerm_linux_virtual_machine" "this" {
  #checkov:skip=CKV_AZURE_50:Two extensions are needed: Azure Monitor Agent for the disk alert, and the agent's run-command for the housekeeping job.
  name                            = "vm-${var.name}"
  computer_name                   = "langfuse"
  location                        = var.location
  resource_group_name             = var.resource_group_name
  size                            = "Standard_B2as_v2"
  admin_username                  = "langfuse"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.this.id]
  custom_data                     = base64encode(local.cloud_init)
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  provision_vm_agent              = true
  allow_extension_operations      = true
  tags                            = var.tags

  # Azure needs a key while password sign-in is off. Its private half was deleted when it was made,
  # and the security group has no SSH rule.
  admin_ssh_key {
    username   = "langfuse"
    public_key = file("${path.module}/no-private-key.pub")
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [time_sleep.rbac_propagation.triggers["identity_id"]]
  }

  # One 32 GiB Standard SSD (E4), the disk ADR 0050 prices. Ubuntu's image is 30 GiB, so a smaller
  # OS disk beside a data disk is not possible, and a data disk would be a second E4.
  os_disk {
    name                 = "osdisk-${var.name}"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 32
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  # Managed boot diagnostics keep the serial log, the one way to read a failed first boot without SSH.
  boot_diagnostics {}
}

data "azurerm_role_definition" "run_command" {
  name  = local.run_command_role
  scope = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}"
}

# The housekeeping job reaches the VM through run-command (ADR 0050). The deployer is the deploy
# workflow's managed identity, and its role-assignment rights only cover service principals.
resource "azurerm_role_assignment" "deployer_run_command" {
  scope              = azurerm_linux_virtual_machine.this.id
  role_definition_id = data.azurerm_role_definition.run_command.role_definition_resource_id
  principal_id       = data.azurerm_client_config.current.object_id
  principal_type     = "ServicePrincipal"
}
