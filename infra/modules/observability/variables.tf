variable "name" {
  description = "Name stem, such as wab-dev. Resources add their own type prefix."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the workspace and Application Insights."
  type        = string
}

variable "daily_quota_gb" {
  description = "Daily ingestion cap for Log Analytics, so a log storm cannot drain the student credits."
  type        = number
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}
