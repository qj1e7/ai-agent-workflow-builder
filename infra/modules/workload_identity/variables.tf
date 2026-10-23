variable "name" {
  description = "Workload name with the environment stem, such as platform-api-wab-dev."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the identity."
  type        = string
}

variable "registry_id" {
  description = "Registry resource ID, the AcrPull scope."
  type        = string
}

variable "secret_scopes" {
  description = "Key Vault secret resource IDs the workload reads, by environment variable name. Each gets its own Key Vault Secrets User assignment."
  type        = map(string)
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}
