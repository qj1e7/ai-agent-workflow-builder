terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = ">= 2.13.0, < 3.0.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 5.7.0, < 6.0.0"
    }
  }
}
