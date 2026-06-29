targetScope = 'resourceGroup'

@description('Préfixe unique pour nommer les ressources (3-8 chars lowercase)')
@minLength(3)
@maxLength(8)
param projectName string = 'nlmazure'

@description('Environnement de déploiement')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'prod'

@description('Région Azure')
param location string = resourceGroup().location

@description('Object ID AAD de l\'identité qui déploie (pour Key Vault access policy)')
param deployerObjectId string

@description('Image Docker initiale du Container App (placeholder pour premier déploiement)')
param apiImageTag string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Déployer le conteneur neo4j-legacykb (golden source GraphRAG)')
param deployLegacyKb bool = true

@description('Mot de passe du compte neo4j du conteneur neo4j-legacykb')
@secure()
param neo4jLegacyKbPassword string = ''

@description('URI bolt:// du conteneur neo4j-legacykb (golden source GraphRAG) consommé par l\'API')
param neo4jLegacyKbUri string = ''

@description('Clé API partagée protégeant les endpoints /api/* — stockée dans Key Vault')
@secure()
param apiKey string = ''

@description('Email pour les alertes Azure Monitor (redémarrages ACI neo4j-legacykb). Laisser vide pour désactiver les alertes.')
param alertEmail string = ''

@description('Origines CORS autorisées sur ca-api, séparées par des virgules. Défaut : origine de start-dev.ps1 (AUDIT-2026-06, frontend local appelant /api/legacykb/* directement puisque neo4j-legacykb n\'a plus d\'IP publique). Vide = CORS désactivé.')
param corsAllowedOrigins string = 'http://127.0.0.1:8000'

var suffix = '${projectName}-${environment}'
// Les noms de Key Vault sont uniques globalement (tous tenants Azure confondus, comme les
// comptes de stockage) — un nom prévisible 'kv-<suffix>' peut donc collisionner avec un vault
// détenu par un tenant tiers (vu en prod : 'kv-nlmavgi-prod' déjà pris alors qu'absent de cet
// abonnement, actif ou soft-deleted). On ajoute un hash court et déterministe.
var kvSuffix = '${take(suffix, 14)}-${substring(uniqueString(resourceGroup().id), 0, 6)}'
// Tags obligatoires (policy abonnement "Agentic Studio — Baseline Security", découverte
// lors de la migration réseau AUDIT-2026-06 -- absente lors des déploiements précédents,
// donc jamais déclenchée avant la création de nouvelles ressources réseau type VNet/NSG).
// Squad/CostCenter : valeurs génériques en attendant les vraies valeurs organisationnelles.
var tags = {
  Squad: 'notebooklm-azure'
  Environment: environment
  CostCenter: 'unknown'
  ManagedBy: 'bicep'
  Project: projectName
}

// ── Réseau privé pour neo4j-legacykb (AUDIT-2026-06, finding haut CVSS 8.3) ─────
module network 'modules/network.bicep' = {
  name: 'network'
  params: {
    suffix: suffix
    location: location
    tags: tags
  }
}

// ── Monitoring (déployé en premier pour avoir l'instrumentation key) ──────────
module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    suffix: suffix
    location: location
    tags: tags
  }
}

// ── Key Vault ──────────────────────────────────────────────────────────────────
module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    suffix: kvSuffix
    location: location
    tags: tags
    deployerObjectId: deployerObjectId
  }
}

// ── Azure OpenAI ──────────────────────────────────────────────────────────────
module openai 'modules/openai.bicep' = {
  name: 'openai'
  params: {
    suffix: suffix
    location: location
    tags: tags
  }
}

// ── Azure AI Search ───────────────────────────────────────────────────────────
module search 'modules/search.bicep' = {
  name: 'search'
  params: {
    suffix: suffix
    location: location
    tags: tags
  }
}

// ── Storage ───────────────────────────────────────────────────────────────────
module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    suffix: suffix
    location: location
    tags: tags
  }
}

// ── Document Intelligence ─────────────────────────────────────────────────────
module docint 'modules/docint.bicep' = {
  name: 'docint'
  params: {
    suffix: suffix
    location: location
    tags: tags
  }
}

// ── Container Registry ────────────────────────────────────────────────────────
module registry 'modules/registry.bicep' = {
  name: 'registry'
  params: {
    suffix: suffix
    location: location
    tags: tags
  }
}

// ── Neo4j Legacy KB (golden source GraphRAG, conteneur ACI dédié) ────────────────
module neo4jLegacyKb 'modules/neo4j-legacykb.bicep' = if (deployLegacyKb) {
  name: 'neo4jLegacyKb'
  params: {
    suffix: suffix
    location: location
    tags: tags
    neo4jPassword: neo4jLegacyKbPassword
    alertEmail: alertEmail
    aciSubnetId: network.outputs.aciSubnetId
  }
}

// ── Container Apps (API) ──────────────────────────────────────────────────────
module containerapp 'modules/containerapp.bicep' = {
  name: 'containerapp'
  params: {
    suffix: suffix
    location: location
    tags: tags
    apiImageTag: apiImageTag
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    keyVaultUri: keyvault.outputs.uri
    neo4jLegacyKbUri: deployLegacyKb ? neo4jLegacyKb.?outputs.?uri ?? '' : neo4jLegacyKbUri
    registryLoginServer: registry.outputs.loginServer
    gpt4oDeploymentName: openai.outputs.gpt4oDeploymentName
    embeddingDeploymentName: openai.outputs.embeddingDeploymentName
    caeSubnetId: network.outputs.caeSubnetId
    legacyKbImportStorageAccount: deployLegacyKb ? neo4jLegacyKb.?outputs.?storageAccountName ?? '' : ''
    legacyKbImportShareName: deployLegacyKb ? neo4jLegacyKb.?outputs.?shareName ?? '' : ''
    corsAllowedOrigins: corsAllowedOrigins
  }
}

// ── Références existantes pour les noms déterministes ───────────────────────
// L'UAMI est créée par le module containerapp avec ce nom prévisible.
// On la référence en "existing" pour pouvoir calculer le GUID des role assignments
// à partir de son ID (connu dès que le nom est connu).
resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-api-${suffix}'
  dependsOn: [containerapp]
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: 'kv-${kvSuffix}'
  dependsOn: [keyvault]
}

// ── Role Assignments : Managed Identity → Services ───────────────────────────
// API Container App → Azure OpenAI (Cognitive Services OpenAI User)
resource roleApiOpenAI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, apiIdentity.id, 'CognitiveServicesOpenAIUser')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// API Container App → Azure AI Search (Search Index Data Reader)
resource roleApiSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, apiIdentity.id, 'SearchIndexDataContributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// API Container App → Key Vault (Key Vault Secrets User)
resource roleApiKV 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, apiIdentity.id, 'KeyVaultSecretsUser')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Secrets dans Key Vault ───────────────────────────────────────────────────
// Utilise "parent" pour que le nom soit juste le nom du secret (pas vault/secret),
// ce qui permet à Bicep de le calculer dès le début du déploiement.
resource kvOpenAIEndpoint 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'openai-endpoint'
  properties: {
    value: openai.outputs.endpoint
  }
}

resource kvSearchEndpoint 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'search-endpoint'
  properties: {
    value: search.outputs.endpoint
  }
}

resource kvDocIntEndpoint 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'docint-endpoint'
  properties: {
    value: docint.outputs.endpoint
  }
}

resource kvStorageAccount 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'storage-account-name'
  properties: {
    value: storage.outputs.accountName
  }
}

// Clé API — uniquement si fournie au déploiement.
resource kvApiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(apiKey)) {
  parent: kv
  name: 'api-key'
  properties: {
    value: apiKey
  }
}

// Mot de passe neo4j-legacykb — uniquement si fourni (instance golden source externe au déploiement).
resource kvNeo4jLegacyKbPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(neo4jLegacyKbPassword)) {
  parent: kv
  name: 'neo4j-legacykb-password'
  properties: {
    value: neo4jLegacyKbPassword
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────
output apiUrl string = containerapp.outputs.apiUrl
output registryLoginServer string = registry.outputs.loginServer
output keyVaultName string = keyvault.outputs.name
output openAIEndpoint string = openai.outputs.endpoint
output searchEndpoint string = search.outputs.endpoint
output storageAccountName string = storage.outputs.accountName
output docIntEndpoint string = docint.outputs.endpoint
output neo4jLegacyKbUri string = neo4jLegacyKb.?outputs.?uri ?? ''
// Remplace neo4jLegacyKbFqdn (AUDIT-2026-06) : plus de FQDN public, seulement une IP
// privée dans snet-aci-legacykb — consommée par deploy.ps1 pour générer le certificat
// TLS (SAN IP plutôt que SAN DNS) et par import-neo4j-legacykb.ps1 (cf. ce script).
output neo4jLegacyKbPrivateIp string = neo4jLegacyKb.?outputs.?privateIp ?? ''
output neo4jLegacyKbStorageAccount string = neo4jLegacyKb.?outputs.?storageAccountName ?? ''
output neo4jLegacyKbShareName string = neo4jLegacyKb.?outputs.?shareName ?? ''
output neo4jLegacyKbSslShareName string = neo4jLegacyKb.?outputs.?sslShareName ?? ''
