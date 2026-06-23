param suffix string
param location string
param tags object
param apiImageTag string
param appInsightsConnectionString string
param keyVaultUri string = ''
param neo4jLegacyKbUri string = ''
param registryLoginServer string
param gpt4oDeploymentName string
param embeddingDeploymentName string

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-api-${suffix}'
  location: location
  tags: tags
}

resource roleAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, apiIdentity.id, 'AcrPull')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: 'cae-${suffix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
  }
}

resource api 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'ca-api-${suffix}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${apiIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: registryLoginServer
          identity: apiIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImageTag
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(
            [
              {
                name: 'AZURE_CLIENT_ID'
                value: apiIdentity.properties.clientId
              }
              {
                name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
                value: appInsightsConnectionString
              }
              {
                name: 'AZURE_OPENAI_GPT4O_DEPLOYMENT'
                value: gpt4oDeploymentName
              }
              {
                name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT'
                value: embeddingDeploymentName
              }
            ],
            empty(keyVaultUri) ? [] : [
              {
                name: 'AZURE_KEYVAULT_URI'
                value: keyVaultUri
              }
            ],
            empty(neo4jLegacyKbUri) ? [] : [
              {
                name: 'NEO4J_LEGACYKB_URI'
                value: neo4jLegacyKbUri
              }
            ]
          )
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [roleAcrPull]
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output principalId string = apiIdentity.properties.principalId
output name string = api.name
