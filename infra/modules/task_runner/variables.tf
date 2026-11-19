variable "name" {
  description = "Container App name, such as n8n-runners."
  type        = string
}

variable "name_stem" {
  description = "Environment stem, such as wab-dev, added to the identity name."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the app."
  type        = string
}

variable "resource_group_id" {
  description = "Resource ID of that group, the app's parent."
  type        = string
}

variable "environment_id" {
  description = "Container Apps environment ID. n8n's broker port must be reachable in it."
  type        = string
}

variable "registry_id" {
  description = "Registry resource ID, the AcrPull scope."
  type        = string
}

variable "registry_server" {
  description = "Registry login server."
  type        = string
}

variable "image" {
  description = "Full image reference of n8n's task runner, at n8n's own version."
  type        = string
}

variable "broker_uri" {
  description = "Where n8n's task broker listens, as the runner calls it, such as http://n8n:5679."
  type        = string
}

variable "auth_token" {
  description = "The Key Vault secret both n8n and the runner read as N8N_RUNNERS_AUTH_TOKEN: its versionless URL and its resource ID."
  type = object({
    url   = string
    scope = string
  })
}

variable "time_zone" {
  description = "The team time zone, which code in the runner reads as its own."
  type        = string
}

variable "cpu" {
  description = "vCPU per replica."
  type        = number
  default     = 0.25
}

variable "memory" {
  description = "Memory per replica. Container Apps fixes the ratio at 2 GiB per vCPU."
  type        = string
  default     = "0.5Gi"
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}
