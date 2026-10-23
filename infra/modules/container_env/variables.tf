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
