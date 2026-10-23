targetScope = 'subscription'

param location string = 'southeastasia'
param namePrefix string = 'fyp'
param deployerObjectId string
param postgresAdminLogin string = 'pgadmin'

@secure()
param postgresAdminPassword string

@secure()
param databaseUrl string

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: '${namePrefix}-rg'
  location: location
}

module platform 'resources.bicep' = {
  name: 'platform'
  scope: rg
  params: {
    location: location
    namePrefix: namePrefix
    deployerObjectId: deployerObjectId
    postgresAdminLogin: postgresAdminLogin
    postgresAdminPassword: postgresAdminPassword
    databaseUrl: databaseUrl
  }
}

output platformApiFqdn string = platform.outputs.platformApiFqdn
