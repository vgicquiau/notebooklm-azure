// Réseau privé pour neo4j-legacykb (AUDIT-2026-06, finding haut CVSS 8.3 : la base de
// connaissances legacy était joignable directement depuis Internet, IP publique sans
// restriction réseau). Ce module crée le VNet et les deux sous-réseaux nécessaires :
//   - snet-aci-legacykb : déploiement VNet de l'ACI neo4j-legacykb (plus d'IP publique)
//   - snet-cae          : intégration VNet de l'environnement Container Apps (ca-api),
//                         seul point d'entrée autorisé vers neo4j-legacykb (NSG)
//
// ca-api garde son ingress externe (FQDN public) — seule la communication ca-api ->
// neo4j-legacykb bascule sur le réseau privé. mcp-legacykb n'est pas concerné : il
// n'appelle jamais neo4j-legacykb directement, uniquement l'API publique de ca-api
// (cf. mcp-legacykb/server.py).

param suffix string
param location string
param tags object

var vnetAddressPrefix = '10.20.0.0/16'
var aciSubnetPrefix = '10.20.1.0/27'
var caeSubnetPrefix = '10.20.2.0/23'

resource nsgAci 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: 'nsg-aci-legacykb-${suffix}'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowFromContainerAppsSubnet'
        properties: {
          description: 'Seul ca-api (snet-cae) peut atteindre neo4j-legacykb (HTTPS 7473 / Bolt 7687).'
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: caeSubnetPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRanges: ['7473', '7687']
        }
      }
      {
        name: 'DenyAllOtherInbound'
        properties: {
          description: 'Aucun autre accès entrant — remplace l\'exposition publique précédente.'
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: 'vnet-${suffix}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [vnetAddressPrefix]
    }
    subnets: [
      {
        name: 'snet-aci-legacykb'
        properties: {
          addressPrefix: aciSubnetPrefix
          networkSecurityGroup: {
            id: nsgAci.id
          }
          delegations: [
            {
              name: 'aci-delegation'
              properties: {
                serviceName: 'Microsoft.ContainerInstance/containerGroups'
              }
            }
          ]
        }
      }
      {
        name: 'snet-cae'
        properties: {
          // Délégation requise (ManagedEnvironmentSubnetDelegationError) à la CRÉATION
          // d'un nouvel environnement avec vnetConfiguration -- contrairement au message
          // ManagedEnvironmentV1SubnetDelegationNotAllowed rencontré plus tôt en tentant
          // d'AJOUTER un VNet à l'environnement V1 existant (sans délégation, à l'époque).
          // Azure exige l'inverse selon qu'on crée du neuf ou qu'on migre un environnement
          // déjà existant -- ce repo recrée l'environnement (suppression+création), donc
          // la délégation est nécessaire ici.
          addressPrefix: caeSubnetPrefix
          delegations: [
            {
              name: 'cae-delegation'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output aciSubnetId string = vnet.properties.subnets[0].id
output caeSubnetId string = vnet.properties.subnets[1].id
