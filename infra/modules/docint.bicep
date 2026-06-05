param suffix string
param location string
param tags object

resource docint 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'di-${suffix}'
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: 'di-${suffix}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

output endpoint string = docint.properties.endpoint
output name string = docint.name
