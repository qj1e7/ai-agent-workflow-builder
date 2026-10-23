# Partial configuration. The deploy workflow passes the storage account, container and key with
# -backend-config, from the repository variables that infra/bootstrap/README.md sets up.
terraform {
  backend "azurerm" {
    use_azuread_auth = true
  }
}
