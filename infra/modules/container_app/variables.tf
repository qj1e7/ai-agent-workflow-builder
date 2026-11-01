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
  description = "Whether the app is reachable from the internet, the port it listens on, and which addresses may reach it. Empty allowed_cidrs lets every address in. Otherwise each entry is an Allow rule, and Container Apps refuses every other address."
  type = object({
    external    = bool
    target_port = number
    allowed_cidrs = optional(list(object({
      name = string
      cidr = string
    })), [])
  })

  validation {
    condition     = length(distinct([for rule in var.ingress.allowed_cidrs : rule.name])) == length(var.ingress.allowed_cidrs)
    error_message = "Each entry in allowed_cidrs needs its own name."
  }

  validation {
    condition     = alltrue([for rule in var.ingress.allowed_cidrs : can(cidrhost(rule.cidr, 0)) && strcontains(rule.cidr, "/")])
    error_message = "Each entry in allowed_cidrs must be an IPv4 range in CIDR form, such as 203.0.113.7/32."
  }
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

variable "inline_secrets" {
  description = "Environment variables kept as the app's own secrets, by variable name, for values Terraform makes that are not in Key Vault. A new Key Vault secret would give the app's identity a new role, which replaces its role wait, and the deploy's plan guard stops on any replace."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}
