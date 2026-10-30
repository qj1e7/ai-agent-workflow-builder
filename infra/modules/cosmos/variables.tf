variable "name" {
  description = "Globally unique account name, 3 to 44 lowercase letters, digits and hyphens."
  type        = string
}

variable "location" {
  description = "Azure region. The account lives in this one region only, which Strong consistency needs."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the account."
  type        = string
}

variable "serverless" {
  description = "False uses the free tier, which covers 1000 RU/s and 25 GB and is allowed once per subscription. True makes a serverless account, which has no free tier and bills each request."
  type        = bool
}

variable "data_contributors" {
  description = "Principal IDs, by a name of our choosing, that get Cosmos DB's built-in Data Contributor role on the activity database."
  type        = map(string)
}

variable "tags" {
  description = "Tags for every resource."
  type        = map(string)
}
