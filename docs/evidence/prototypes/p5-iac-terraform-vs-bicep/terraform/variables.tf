variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "southeastasia"
}

variable "name_prefix" {
  type    = string
  default = "fyp"
}

variable "deployer_object_id" {
  type        = string
  description = "Object ID of the identity that runs the deploy. It needs to write the secret."
}

variable "postgres_admin_login" {
  type    = string
  default = "pgadmin"
}

variable "postgres_admin_password" {
  type      = string
  sensitive = true
}

variable "database_url" {
  type      = string
  sensitive = true
}
