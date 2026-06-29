@minLength(3)
param suffix string
param location string
param tags object

@secure()
param neo4jPassword string

@description('Email destinataire des alertes Azure Monitor (redémarrages ACI). Vide = alertes désactivées.')
param alertEmail string = ''

@description('ID du sous-réseau délégué à Microsoft.ContainerInstance/containerGroups (AUDIT-2026-06 : déploiement VNet, plus d\'IP publique — cf. infra/modules/network.bicep).')
param aciSubnetId string

var storageName = take(replace('stneo4jkb${suffix}', '-', ''), 24)
var shareName = 'neo4j-import'
var sslShareName = 'neo4j-ssl'

// Storage account dédié (allowSharedKeyAccess: true, requis pour le montage Azure File
// par clé sur ACI — le storage account principal a allowSharedKeyAccess: false).
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
  }
}

resource fileServices 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' existing = {
  parent: storage
  name: 'default'
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileServices
  name: shareName
}

// Partage Azure Files dédié aux certificats TLS (SEC-002 : chiffrement Bolt + HTTPS).
// deploy.ps1 génère un cert auto-signé et l'upload ici après le déploiement Bicep,
// puis redémarre l'ACI — Neo4j monte /ssl en lecture et démarre avec TLS activé.
resource sslShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileServices
  name: sslShareName
}

// Conteneur neo4j-legacykb (golden source GraphRAG, lecture seule côté API).
// NEO4J_PLUGINS est un tableau JSON passé tel quel via ARM — contrairement à
// `az container create --environment-variables`, pas de problème de guillemets PowerShell.
resource containerGroup 'Microsoft.ContainerInstance/containerGroups@2023-05-01' = {
  name: 'aci-neo4j-legacykb-${suffix}'
  location: location
  tags: tags
  properties: {
    osType: 'Linux'
    restartPolicy: 'OnFailure'
    // Déploiement dans snet-aci-legacykb (network.bicep) : IP privée uniquement, plus
    // d'IP publique/DNS label. Le NSG du sous-réseau n'autorise en entrée que snet-cae
    // (ca-api) sur 7473/7687 (AUDIT-2026-06, finding haut CVSS 8.3).
    subnetIds: [
      {
        id: aciSubnetId
        name: 'aci-legacykb-nic'
      }
    ]
    ipAddress: {
      type: 'Private'
      ports: [
        { protocol: 'TCP', port: 7473 }
        { protocol: 'TCP', port: 7687 }
      ]
    }
    containers: [
      {
        name: 'neo4j'
        properties: {
          image: 'neo4j:5.22-community'
          resources: {
            requests: {
              cpu: 1
              memoryInGB: 2
            }
          }
          ports: [
            { protocol: 'TCP', port: 7473 }
            { protocol: 'TCP', port: 7687 }
          ]
          environmentVariables: [
            #disable-next-line use-secure-value-for-secure-inputs
            { name: 'NEO4J_AUTH', secureValue: 'neo4j/${neo4jPassword}' }
            { name: 'NEO4J_PLUGINS', value: '["apoc","graph-data-science"]' }
            // Ré-activé après la migration réseau (AUDIT-2026-06) : nécessaire à
            // apoc.import.graphml, utilisé par le Job de (ré)import (cf. containerapp.bicep,
            // api/scripts/import_legacykb.py) -- seul usage légitime de file.enabled ici.
            // Le risque initial (finding critique) tenait à la combinaison avec l'IP
            // publique du conteneur, supprimée par ce même audit (cf. network.bicep) :
            // l'instance n'est plus joignable que depuis snet-cae, donc plus depuis Internet.
            { name: 'NEO4J_apoc_import_file_enabled', value: 'true' }
            { name: 'NEO4J_apoc_import_file_use__neo4j__config', value: 'false' }
            { name: 'NEO4J_server_default__listen__address', value: '0.0.0.0' }
            // Restreint au strict nécessaire : seule apoc.path.subgraphAll est appelée par
            // l'application (cf. legacykb_client.py:get_impact_paths) — gds.*/apoc.* complets
            // retirés (AUDIT-2026-06). Les procédures GDS restent disponibles pour exploration
            // manuelle via Neo4j Browser, simplement sans le mode "unrestricted".
            { name: 'NEO4J_dbms_security_procedures_unrestricted', value: 'apoc.path.subgraphAll' }
            // HTTP désactivé — seul HTTPS (7473) est exposé (SEC-002)
            { name: 'NEO4J_server_http_enabled', value: 'false' }
            // TLS Bolt (port 7687) — bolt+s:// requis (SEC-002)
            { name: 'NEO4J_dbms_ssl_policy_bolt_enabled', value: 'true' }
            { name: 'NEO4J_dbms_ssl_policy_bolt_base__directory', value: '/ssl' }
            { name: 'NEO4J_dbms_ssl_policy_bolt_private__key', value: 'neo4j.key' }
            { name: 'NEO4J_dbms_ssl_policy_bolt_public__certificate', value: 'neo4j.crt' }
            { name: 'NEO4J_dbms_ssl_policy_bolt_client__auth', value: 'NONE' }
            { name: 'NEO4J_server_bolt_tls__level', value: 'REQUIRED' }
            // TLS HTTPS (port 7473) — mêmes certificats que Bolt
            { name: 'NEO4J_server_https_enabled', value: 'true' }
            { name: 'NEO4J_dbms_ssl_policy_https_enabled', value: 'true' }
            { name: 'NEO4J_dbms_ssl_policy_https_base__directory', value: '/ssl' }
            { name: 'NEO4J_dbms_ssl_policy_https_private__key', value: 'neo4j.key' }
            { name: 'NEO4J_dbms_ssl_policy_https_public__certificate', value: 'neo4j.crt' }
            { name: 'NEO4J_dbms_ssl_policy_https_client__auth', value: 'NONE' }
          ]
          volumeMounts: [
            { name: 'neo4j-import', mountPath: '/var/lib/neo4j/import' }
            { name: 'neo4j-ssl', mountPath: '/ssl' }
          ]
        }
      }
    ]
    volumes: [
      {
        name: 'neo4j-import'
        azureFile: {
          shareName: shareName
          storageAccountName: storage.name
          storageAccountKey: storage.listKeys().keys[0].value
        }
      }
      {
        name: 'neo4j-ssl'
        azureFile: {
          shareName: sslShareName
          storageAccountName: storage.name
          storageAccountKey: storage.listKeys().keys[0].value
        }
      }
    ]
  }
}

// ── Alertes Azure Monitor (optionnel — activé si alertEmail est fourni) ──────────
// Détecte les crash-loops de Neo4j (ex. cert TLS expiré) et envoie un email.
// Seuil : > 5 redémarrages cumulés sur 15 min — dépasse largement le redémarrage
// normal post-déploiement (1 restart lors de l'upload du cert).
resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = if (!empty(alertEmail)) {
  name: 'ag-neo4j-legacykb-${suffix}'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'neo4j-alert'
    enabled: true
    emailReceivers: [
      {
        name: 'admin'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

resource restartAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (!empty(alertEmail)) {
  name: 'alert-neo4j-restarts-${suffix}'
  location: 'global'
  tags: tags
  properties: {
    description: 'neo4j-legacykb redémarre anormalement — vérifier si le certificat TLS a expiré.'
    severity: 2
    enabled: true
    scopes: [containerGroup.id]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'RestartCountHigh'
          metricName: 'RestartCount'
          metricNamespace: 'Microsoft.ContainerInstance/containerGroups'
          operator: 'GreaterThan'
          threshold: 5
          timeAggregation: 'Maximum'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

// bolt+ssc:// = Bolt chiffré avec cert auto-signé (driver Python accepte sans CA publique).
// Plus de FQDN public (AUDIT-2026-06) : l'IP privée du sous-réseau snet-aci-legacykb
// sert d'hôte — stable tant que le container group n'est pas recréé (cf. plan de bascule).
output uri string = 'bolt+ssc://${containerGroup.properties.ipAddress.ip}:7687'
output privateIp string = containerGroup.properties.ipAddress.ip
output storageAccountName string = storage.name
output shareName string = share.name
output sslShareName string = sslShare.name
