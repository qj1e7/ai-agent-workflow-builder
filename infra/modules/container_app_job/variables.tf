variable "name" {
  description = "Job name, used with az containerapp job start."
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
  description = "Resource group that holds the job."
  type        = string
}

variable "environment_id" {
  description = "Container Apps environment ID."
  type        = string
}

variable "image" {
  description = "Full image reference."
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

variable "command" {
  description = "Overrides the image's command. Null keeps the image's own."
  type        = list(string)
  default     = null
}

variable "cpu" {
  description = "vCPU for the job's one replica."
  type        = number
}

variable "memory" {
  description = "Memory for the job's one replica, such as 0.5Gi."
  type        = string
}

variable "timeout_seconds" {
  description = "How long one run may take before Azure stops it."
  type        = number
}

variable "env" {
  description = "Plain environment variables."
  type        = map(string)
}

variable "secrets" {
  description = "Environment variables read from Key Vault, by variable name. Each holds the secret's versionless URL and its resource ID."
  type = map(object({
    url   = string
    scope = string
  }))
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}
