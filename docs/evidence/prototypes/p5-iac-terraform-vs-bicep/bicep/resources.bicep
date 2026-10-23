param location string
param namePrefix string
param deployerObjectId string
param postgresAdminLogin string

@secure()
param postgresAdminPassword string

@secure()
param databaseUrl string

var placeholderImage = 'mcr.microsoft.com/k8se/quickstart:latest'
var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var secretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var databaseNames = [
  'platform'
  'n8n'
]

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-law'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-appi'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id'
  location: location
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${namePrefix}-kv'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enablePurgeProtection: true
  }
}

resource appsSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, identity.id, secretsUserRoleId)
  scope: kv
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
  }
}

resource deployerSecretsOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, deployerObjectId, secretsOfficerRoleId)
  scope: kv
  properties: {
    principalId: deployerObjectId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsOfficerRoleId)
  }
}

resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'database-url'
  properties: {
    value: databaseUrl
  }
  dependsOn: [deployerSecretsOfficer]
}

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${namePrefix}-pg'
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '17'
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 }
    availabilityZone: '1'
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource databases 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = [
  for name in databaseNames: {
    parent: pg
    name: name
    properties: {
      charset: 'UTF8'
      collation: 'en_US.utf8'
    }
  }
]

resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: '${namePrefix}-swa'
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource n8n 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'n8n'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 5678
      }
    }
    template: {
      containers: [
        {
          name: 'n8n'
          image: 'n8nio/n8n:2.42.6'
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

resource agentRuntime 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'agent-runtime'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8100
      }
    }
    template: {
      containers: [
        {
          name: 'agent-runtime'
          image: placeholderImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
  }
}

resource platformApi 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'platform-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
      }
      secrets: [
        {
          name: 'database-url'
          keyVaultUrl: databaseUrlSecret.properties.secretUri
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'platform-api'
          image: placeholderImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'DATABASE_URL', secretRef: 'database-url' }
          ]
        }
      ]
      scale: { minReplicas: 1 }
    }
  }
  dependsOn: [appsSecretsUser]
}

resource bootstrap 'Microsoft.App/jobs@2024-03-01' = {
  name: 'bootstrap'
  location: location
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
    }
    template: {
      containers: [
        {
          name: 'bootstrap'
          image: placeholderImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
    }
  }
}

output platformApiFqdn string = platformApi.properties.configuration.ingress.fqdn
