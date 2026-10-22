#!/bin/sh
# One-time Azure setup that Terraform cannot do for itself. A person runs it once, signed in
# with `az login` as an Owner of the subscription. Every command is safe to run again.
# Read infra/bootstrap/README.md first.
# Usage: infra/bootstrap/setup-azure.sh <github-owner/repo>
set -eu

repo=${1:?usage: setup-azure.sh <github-owner/repo>}
location=${LOCATION:-southeastasia}
state_group=${STATE_GROUP:-rg-wab-tfstate}
state_account=${STATE_ACCOUNT:?set STATE_ACCOUNT to a new storage account name, 3 to 24 lowercase letters and digits}
deploy_identity=${DEPLOY_IDENTITY:-id-wab-deploy}
# Must match rg-${local.stem} in infra/envs/dev/main.tf. Terraform reads this group, it does not create it.
app_group=rg-wab-dev

subscription=$(az account show --query id --output tsv)
tenant=$(az account show --query tenantId --output tsv)
me=$(az ad signed-in-user show --query id --output tsv)

echo "1. Register the resource providers the environment uses"
# The deploy identity has no rights on the subscription, so Terraform cannot register these
# itself. The list covers every resource type in infra/, plus Storage for the state account.
for namespace in Microsoft.App Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL Microsoft.Insights \
  Microsoft.KeyVault Microsoft.ManagedIdentity Microsoft.OperationalInsights Microsoft.Storage; do
  az provider register --namespace "$namespace" --wait
done

echo "2. Create the Terraform state storage, with access keys turned off"
az group create --name "$state_group" --location "$location" --output none
az storage account create --name "$state_account" --resource-group "$state_group" --location "$location" \
  --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
  --allow-blob-public-access false --allow-shared-key-access false --output none
az storage account blob-service-properties update --account-name "$state_account" --resource-group "$state_group" \
  --enable-versioning true --enable-delete-retention true --delete-retention-days 30 --output none
account_id=$(az storage account show --name "$state_account" --resource-group "$state_group" --query id --output tsv)
az role assignment create --assignee-object-id "$me" --assignee-principal-type User \
  --role "Storage Blob Data Contributor" --scope "$account_id" --output none
echo "   Waiting a minute for the new role to take effect"
sleep 60
az storage container create --name tfstate --account-name "$state_account" --auth-mode login --output none

echo "3. Create the resource group that Terraform deploys into"
az group create --name "$app_group" --location "$location" \
  --tags project=ai-workflow-builder environment=dev --output none
app_group_id=$(az group show --name "$app_group" --query id --output tsv)

echo "4. Create the deploy identity and trust GitHub's azure-dev environment"
az identity create --name "$deploy_identity" --resource-group "$state_group" --location "$location" --output none
client_id=$(az identity show --name "$deploy_identity" --resource-group "$state_group" --query clientId --output tsv)
principal_id=$(az identity show --name "$deploy_identity" --resource-group "$state_group" --query principalId --output tsv)
if ! az identity federated-credential show --name github-azure-dev --identity-name "$deploy_identity" \
  --resource-group "$state_group" --output none 2>/dev/null; then
  az identity federated-credential create --name github-azure-dev --identity-name "$deploy_identity" \
    --resource-group "$state_group" --issuer https://token.actions.githubusercontent.com \
    --subject "repo:$repo:environment:azure-dev" --audiences api://AzureADTokenExchange --output none
fi

echo "5. Give the deploy identity its roles, on the state container and on $app_group only"
az role assignment create --assignee-object-id "$principal_id" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope "$account_id/blobServices/default/containers/tfstate" --output none
az role assignment create --assignee-object-id "$principal_id" --assignee-principal-type ServicePrincipal \
  --role Contributor --scope "$app_group_id" --output none
# In $app_group the deploy may only hand out or remove the four roles the Terraform code assigns
# (AcrPull, AcrPush, Key Vault Secrets User and Key Vault Secrets Officer), and only to service
# principals, which include our managed identities. It can never give a person a role.
roles="7f951dda-4ed3-4680-a7ca-43fe172d538d, 8311e382-0749-4cb8-b61a-304f252e45ec, 4633458b-17de-408a-b874-0445c86b69e6, b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
condition="((!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {$roles} AND @Request[Microsoft.Authorization/roleAssignments:PrincipalType] ForAnyOfAnyValues:StringEqualsIgnoreCase {'ServicePrincipal'})) AND ((!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {$roles} AND @Resource[Microsoft.Authorization/roleAssignments:PrincipalType] ForAnyOfAnyValues:StringEqualsIgnoreCase {'ServicePrincipal'}))"
az role assignment create --assignee-object-id "$principal_id" --assignee-principal-type ServicePrincipal \
  --role "Role Based Access Control Administrator" --scope "$app_group_id" \
  --condition "$condition" --condition-version 2.0 --output none

echo
echo "Done. Set these variables on the azure-dev GitHub environment:"
echo "  AZURE_CLIENT_ID=$client_id"
echo "  AZURE_TENANT_ID=$tenant"
echo "  AZURE_SUBSCRIPTION_ID=$subscription"
echo "  TFSTATE_RESOURCE_GROUP=$state_group"
echo "  TFSTATE_STORAGE_ACCOUNT=$state_account"
