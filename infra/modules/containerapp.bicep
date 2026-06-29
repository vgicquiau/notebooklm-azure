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

@description('ID du sous-réseau délégué à Microsoft.App/environments (AUDIT-2026-06 : intégration VNet pour atteindre neo4j-legacykb en privé — cf. infra/modules/network.bicep). Ingress externe inchangé, ca-api garde son FQDN public.')
param caeSubnetId string

@description('Storage account + partage Azure Files "neo4j-import" de neo4j-legacykb (AUDIT-2026-06) — le Job y dépose le résultat de chaque import, lu ensuite par import-neo4j-legacykb.ps1 via az storage file download (control-plane, pas d\'accès réseau direct requis).')
param legacyKbImportStorageAccount string = ''
param legacyKbImportShareName string = ''

@description('Origines autorisées en CORS, séparées par des virgules (ex. http://127.0.0.1:8000 pour le frontend local — AUDIT-2026-06 : neo4j-legacykb n\'a plus d\'IP publique, le frontend local doit appeler ca-api directement pour les routes /api/legacykb/*). Vide = CORS désactivé (comportement par défaut, inchangé).')
param corsAllowedOrigins string = ''

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

resource legacyKbImportStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = if (!empty(legacyKbImportStorageAccount)) {
  name: legacyKbImportStorageAccount
}

resource environment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: 'cae-${suffix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    // Intégration VNet (AUDIT-2026-06) : internal=false conserve l'ingress public de
    // ca-api (FQDN inchangé) ; seule la communication sortante vers neo4j-legacykb
    // passe désormais par snet-cae plutôt que par Internet.
    vnetConfiguration: {
      infrastructureSubnetId: caeSubnetId
      internal: false
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
            empty(corsAllowedOrigins) ? [] : [
              {
                name: 'CORS_ALLOWED_ORIGINS'
                value: corsAllowedOrigins
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

// ── Storage de l'environnement (AUDIT-2026-06) : partage neo4j-import monté sur le
// Job d'import — uniquement pour y déposer le fichier de résultat (cf. import_legacykb.py),
// pas pour le dump GraphML lui-même (lu par Neo4j directement depuis son propre montage).
resource envImportStorage 'Microsoft.App/managedEnvironments/storages@2023-05-01' = if (!empty(legacyKbImportStorageAccount)) {
  parent: environment
  name: 'neo4j-import'
  properties: {
    azureFile: {
      accountName: legacyKbImportStorageAccount
      accountKey: legacyKbImportStorage.listKeys().keys[0].value
      shareName: legacyKbImportShareName
      accessMode: 'ReadWrite'
    }
  }
}

// ── Job d'import legacykb (AUDIT-2026-06) : exécute api/scripts/import_legacykb.py
// depuis snet-cae (seul sous-réseau autorisé par le NSG de neo4j-legacykb) — remplace
// les appels HTTPS directs que faisait auparavant import-neo4j-legacykb.ps1 depuis le
// poste de l'opérateur. Déclenché via `az containerapp job start` ; les paramètres par
// exécution (nom du dump, purge) sont poussés via `az containerapp job update
// --set-env-vars` juste avant chaque déclenchement (cf. import-neo4j-legacykb.ps1).
resource importJob 'Microsoft.App/jobs@2023-05-02-preview' = if (!empty(legacyKbImportStorageAccount)) {
  name: 'caj-import-legacykb-${suffix}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${apiIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
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
          name: 'import'
          image: apiImageTag
          command: ['python', '-m', 'api.scripts.import_legacykb']
          // --dump-filename / --purge poussés via DUMP_FILENAME / PURGE_BEFORE_IMPORT
          // (set-env-vars juste avant le déclenchement) -- args fixes ici, le script lit
          // ces variables s'ils ne sont pas passés en CLI (cf. import_legacykb.py).
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(
            [
              { name: 'AZURE_CLIENT_ID', value: apiIdentity.properties.clientId }
              // Valeurs par défaut -- écrasées avant chaque déclenchement par
              // `az containerapp job update --set-env-vars` (cf. import-neo4j-legacykb.ps1).
              { name: 'DUMP_FILENAME', value: '' }
              { name: 'PURGE_BEFORE_IMPORT', value: 'false' }
            ],
            empty(keyVaultUri) ? [] : [{ name: 'AZURE_KEYVAULT_URI', value: keyVaultUri }],
            empty(neo4jLegacyKbUri) ? [] : [{ name: 'NEO4J_LEGACYKB_URI', value: neo4jLegacyKbUri }]
          )
          volumeMounts: [
            { volumeName: 'neo4j-import', mountPath: '/import' }
          ]
        }
      ]
      volumes: [
        {
          name: 'neo4j-import'
          storageType: 'AzureFile'
          storageName: 'neo4j-import'
        }
      ]
    }
  }
  dependsOn: [roleAcrPull, envImportStorage]
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output principalId string = apiIdentity.properties.principalId
output name string = api.name
output importJobName string = !empty(legacyKbImportStorageAccount) ? importJob.name : ''
