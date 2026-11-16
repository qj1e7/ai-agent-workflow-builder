variable "name" {
  description = "Globally unique vault name, 3 to 24 characters."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the vault."
  type        = string
}

variable "secrets" {
  description = "Secret values by Key Vault secret name. The values also land in Terraform state."
  type        = map(string)
  sensitive   = true
}

variable "secrets_set_by_a_person" {
  description = "Names of secrets whose value a person sets by hand. Terraform makes each with a placeholder and never changes its value."
  type        = set(string)
  default     = []
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}
