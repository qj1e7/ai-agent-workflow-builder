variable "name" {
  description = "Name stem, such as wab-dev."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the environment."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Workspace that receives container logs."
  type        = string
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}

variable "infrastructure_subnet_id" {
  description = "Subnet the environment runs in. Null puts it on Azure's default network, which can never change afterwards."
  type        = string
  default     = null
}

variable "internal_load_balancer_enabled" {
  description = "True gives the environment no public address, only one in its subnet. Needs infrastructure_subnet_id. Null keeps Azure's default, a public address."
  type        = bool
  default     = null
}
