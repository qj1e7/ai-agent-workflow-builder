terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.9.1"
    }
    # tflint-ignore: terraform_unused_required_providers # Only a child module uses it. The root pins the exact version.
    time = {
      source  = "hashicorp/time"
      version = "= 0.14.2"
    }
  }
}
