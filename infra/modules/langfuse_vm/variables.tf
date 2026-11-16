variable "name" {
  description = "Name stem, such as langfuse-wab-dev. Resources add their own type prefix."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds every resource here."
  type        = string
}

variable "dns_label" {
  description = "DNS label of the public address. Langfuse's address is https://<dns_label>.<location>.cloudapp.azure.com, which Caddy gets a certificate for."
  type        = string
}

variable "storage_account_name" {
  description = "Globally unique name of the storage account for Langfuse's events and media, 3 to 24 lowercase letters and digits."
  type        = string
}

variable "secrets" {
  description = "Key Vault secrets the VM reads into its env file at each start, by variable name. Each holds the secret's versionless URL and its resource ID. The VM's identity may read these and nothing else."
  type = map(object({
    url   = string
    scope = string
  }))
}

variable "allowed_https_cidrs" {
  description = "IPv4 ranges that may reach Langfuse on port 443: the apps' outbound addresses and the team's own."
  type        = list(string)
}

variable "postgres_host" {
  description = "Host name of the PostgreSQL server that holds the langfuse database."
  type        = string
}

variable "owner_email" {
  description = "Email of the team lead, whom Langfuse makes the organization's Owner at first start (LANGFUSE_INIT_USER_EMAIL)."
  type        = string
  sensitive   = true
}

variable "entra_tenant_id" {
  description = "Tenant of Langfuse's Entra app registration (AUTH_AZURE_AD_TENANT_ID)."
  type        = string
}

variable "entra_client_id" {
  description = "Application (client) ID of Langfuse's Entra app registration (AUTH_AZURE_AD_CLIENT_ID)."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Workspace that receives the VM's disk use, for the disk alert."
  type        = string
}

variable "alert_email" {
  description = "Email that the CPU credit and disk alerts go to. Empty sends them nowhere, and they show only in Azure Monitor."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}

variable "deployer_principal_id" {
  description = "Object ID of the deploy workflow's identity, which gets run-command on this VM only."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.deployer_principal_id))
    error_message = "deployer_principal_id must be an object ID, a GUID."
  }
}
