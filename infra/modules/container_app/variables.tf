variable "name" {
  description = "Container App name. Other apps in the environment reach it by this name."
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
  description = "vCPU per replica."
  type        = number
}

variable "memory" {
  description = "Memory per replica, such as 1Gi. Container Apps fixes the ratio at 2 GiB per vCPU."
  type        = string
}

variable "min_replicas" {
  description = "Minimum replicas. 0 lets the app scale to zero."
  type        = number
}

variable "max_replicas" {
  description = "Maximum replicas."
  type        = number
}

variable "ingress" {
  description = "Whether the app is reachable from the internet, and the port it listens on."
  type = object({
    external    = bool
    target_port = number
  })
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
