variable "name" {
  description = "Globally unique registry name, letters and digits only."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the registry."
  type        = string
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}
