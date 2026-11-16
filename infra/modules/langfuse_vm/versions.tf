terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 5.7.0, < 6.0.0"
    }
    time = {
      source  = "hashicorp/time"
      version = ">= 0.14.2, < 1.0.0"
    }
  }
}
