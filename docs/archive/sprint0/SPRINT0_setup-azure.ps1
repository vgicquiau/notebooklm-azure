# ============================================================================
# Azure Setup -- Provisioning Modernization Agent Sprint 0
# ADAPTE A L'EXECUTION : utilise le resource group existant et reutilise
# les ressources ArchiMind / OpenAI / Search deja en place.
#
# Decouvert au premier lancement :
#   - Le compte n'a PAS de droits au niveau subscription
#     (impossible de creer un nouveau resource group)
#   - Mais il a Contributor + RBAC Admin sur :
#       rg-sp4-d-vgi-azu-vgi-sandbox-txt   (region francecentral)
#   - Ce resource group contient DEJA :
#       app-api-nlmazure-prod   -> backend ArchiMind (Web App, Running)
#       oai-nlmazure-prod       -> Azure OpenAI (deployments: gpt-4o, text-embedding-3-large)
#       srch-nlmazure-prod      -> Azure AI Search (standard)
#       kv-nlmazure-prod        -> Key Vault ArchiMind
#   - Azure OpenAI a l'auth locale desactivee (disableLocalAuth=true)
#       => pas de cle API : auth obligatoire via Managed Identity + role RBAC
#          "Cognitive Services OpenAI User"
#
# Architecture resultante :
#   PC Windows   : IDE + browser + az CLI uniquement
#   Reutilise    : ArchiMind, Azure OpenAI (gpt-4o), Azure AI Search
#                  -> zero redeploiement, zero cout supplementaire
#   Azure ACI    : Neo4j Community + GDS (bolt public, dev uniquement)
#   Azure Fn     : 4 Function Apps (ADG-M, 7RQA, ADM-M, MWP) + Managed Identity
#   Azure SWA    : Frontend React Modernization Agent
#   Azure SQL    : base modernagent_db
#   Azure Blob   : retro-docs + exports
#   Azure KV     : secrets dedies (modernagent-kv-dev)
#
# Prerequis : az login + az account set --subscription <id>
# ============================================================================

# =========================================================================
# VARIABLES
# =========================================================================
$subscriptionId = "07875763-82ff-4808-a7da-e3d0dccc86fc"
$resourceGroup  = "rg-sp4-d-vgi-azu-vgi-sandbox-txt"   # RG existant -- Contributor + RBAC Admin
$location       = "francecentral"                      # Region du RG existant
$envName        = "dev"

# Mots de passe (deja definis avec l'utilisateur)
$sqlPassword    = "ChangeMe@SQL2026!"
$neo4jPassword  = "ChangeMe@Neo4j2026"

# Nommage Azure -- nouvelles ressources Modernization Agent
$prefix             = "modernagent"
$storageAccountName = "${prefix}stg${envName}"
$sqlServerName      = "$prefix-sql-$envName"
$sqlDbName          = "modernagent_db"
$keyVaultName       = "$prefix-kv-$envName"
$appInsightsName    = "$prefix-ai-$envName"
$neo4jAciName       = "neo4j-$envName"
$neo4jDnsLabel      = "neo4j-modernagent-$envName"
$fnAdgm             = "$prefix-adgm-$envName"
$fnSevenRqa         = "$prefix-sevenrqa-$envName"
$fnAdmm             = "$prefix-admm-$envName"
$fnMwp              = "$prefix-mwp-$envName"
$webApp             = "$prefix-web-$envName"

# Ressources EXISTANTES reutilisees (ne pas creer -- deja en prod)
$existingArchiMindUrl   = "https://app-api-nlmazure-prod.azurewebsites.net"
$existingOpenAIName     = "oai-nlmazure-prod"
$existingOpenAIEndpoint = "https://oai-nlmazure-prod.openai.azure.com/"
$existingSearchName     = "srch-nlmazure-prod"
$existingSearchEndpoint = "https://srch-nlmazure-prod.search.windows.net"

Write-Host ""
Write-Host "================================================"
Write-Host " Modernization Agent -- Sprint 0 Azure Setup"
Write-Host " RG existant : $resourceGroup ($location)"
Write-Host " Reutilise   : ArchiMind, Azure OpenAI (gpt-4o), Azure AI Search"
Write-Host "================================================"
Write-Host ""

# =========================================================================
# 1. Subscription (le resource group existe deja -- pas de creation)
# =========================================================================
Write-Host "[1/9] Setting subscription..."
az account set --subscription $subscriptionId

# =========================================================================
# 2. Storage Account (Blob : retro-docs + exports)
# =========================================================================
Write-Host "[2/9] Creating Blob Storage..."
az storage account create `
  --resource-group $resourceGroup `
  --name $storageAccountName `
  --location $location `
  --sku Standard_LRS `
  --kind StorageV2

$storageKey = (az storage account keys list `
  --resource-group $resourceGroup `
  --account-name $storageAccountName `
  --query "[0].value" --output tsv)

az storage container create --name "retrodocs" --account-name $storageAccountName --account-key $storageKey | Out-Null
az storage container create --name "exports"   --account-name $storageAccountName --account-key $storageKey | Out-Null

# =========================================================================
# 3. Azure SQL Database
# =========================================================================
Write-Host "[3/9] Creating Azure SQL Server + Database..."
az sql server create `
  --resource-group $resourceGroup `
  --name $sqlServerName `
  --admin-user "sqladmin" `
  --admin-password $sqlPassword `
  --location $location

az sql server firewall-rule create `
  --resource-group $resourceGroup `
  --server $sqlServerName `
  --name "AllowAzureServices" `
  --start-ip-address "0.0.0.0" `
  --end-ip-address "0.0.0.0"

az sql db create `
  --resource-group $resourceGroup `
  --server $sqlServerName `
  --name $sqlDbName `
  --service-objective "Basic" `
  --backup-storage-redundancy "Local"

Write-Host "  -> Executer SPRINT0_setup-sql.sql via Azure Portal Query Editor apres cette etape"

# =========================================================================
# 4. Key Vault -- secrets dedies Modernization Agent
#    IMPORTANT : pas de azure-openai-key stockee. Le compte oai-nlmazure-prod
#    a disableLocalAuth=true (pas de cle API possible). L'authentification
#    se fait exclusivement via Managed Identity + role RBAC (etape 7).
# =========================================================================
Write-Host "[4/9] Creating Key Vault..."
az keyvault create `
  --resource-group $resourceGroup `
  --name $keyVaultName `
  --location $location `
  --enable-soft-delete true `
  --soft-delete-retention 7

Write-Host "  -> Recuperation de la cle Search existante pour stockage securise..."
$searchKey = (az search admin-key show --service-name $existingSearchName --resource-group $resourceGroup --query "primaryKey" --output tsv)

$sqlConnStr   = "Server=tcp:$sqlServerName.database.windows.net,1433;Initial Catalog=$sqlDbName;Persist Security Info=False;User ID=sqladmin;Password=$sqlPassword;MultipleActiveResultSets=False;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;"
$blobConnStr  = "DefaultEndpointsProtocol=https;AccountName=$storageAccountName;AccountKey=$storageKey;EndpointSuffix=core.windows.net"
$neo4jBoltUri = "bolt://${neo4jDnsLabel}.${location}.azurecontainer.io:7687"

az keyvault secret set --vault-name $keyVaultName --name "sql-connection-string"  --value $sqlConnStr              | Out-Null
az keyvault secret set --vault-name $keyVaultName --name "blob-connection-string" --value $blobConnStr             | Out-Null
az keyvault secret set --vault-name $keyVaultName --name "neo4j-bolt-uri"         --value $neo4jBoltUri            | Out-Null
az keyvault secret set --vault-name $keyVaultName --name "neo4j-password"         --value $neo4jPassword           | Out-Null
az keyvault secret set --vault-name $keyVaultName --name "azure-search-key"       --value $searchKey               | Out-Null
az keyvault secret set --vault-name $keyVaultName --name "azure-search-endpoint"  --value $existingSearchEndpoint  | Out-Null
az keyvault secret set --vault-name $keyVaultName --name "azure-openai-endpoint"  --value $existingOpenAIEndpoint  | Out-Null

Write-Host "  -> azure-openai-key NON stockee (auth Managed Identity -- role RBAC applique en etape 7)"

# =========================================================================
# 5. Application Insights
# =========================================================================
Write-Host "[5/9] Creating Application Insights..."
az monitor app-insights component create `
  --app $appInsightsName `
  --location $location `
  --resource-group $resourceGroup `
  --application-type web

# =========================================================================
# 6. Neo4j sur Azure Container Instances (ACI)
#    Image : neo4j:5.22-community (Docker Hub, pas de Marketplace)
#    GDS   : installe automatiquement via NEO4J_PLUGINS au demarrage
# =========================================================================
Write-Host "[6/9] Creating Neo4j on Azure Container Instances..."
Write-Host "  -> Telechargement du plugin GDS au demarrage (~2-3 minutes)"

az container create `
  --resource-group $resourceGroup `
  --name $neo4jAciName `
  --image "neo4j:5.22-community" `
  --location $location `
  --dns-name-label $neo4jDnsLabel `
  --ports 7474 7687 `
  --cpu 1 `
  --memory 2 `
  --environment-variables `
    NEO4J_AUTH="neo4j/$neo4jPassword" `
    NEO4J_PLUGINS='["graph-data-science"]' `
    NEO4J_server_default__listen__address="0.0.0.0" `
    NEO4J_dbms_security_procedures_unrestricted="gds.*,apoc.*" `
  --restart-policy OnFailure

Write-Host "  -> Neo4j Browser : http://${neo4jDnsLabel}.${location}.azurecontainer.io:7474"
Write-Host "  -> Neo4j Bolt    : bolt://${neo4jDnsLabel}.${location}.azurecontainer.io:7687"

# =========================================================================
# 7. Azure Function Apps (4 modules) -- Managed Identity + RBAC OpenAI + Key Vault
# =========================================================================
Write-Host "[7/9] Creating Function Apps ADG-M, 7RQA, ADM-M, MWP..."

# ID de la ressource OpenAI existante, necessaire pour le role assignment RBAC
$openaiResourceId = (az cognitiveservices account show --name $existingOpenAIName --resource-group $resourceGroup --query "id" --output tsv)

# References Key Vault construites comme variables (evite le parsing PS5.1 sur @ et parentheses)
$kvBase        = "https://$keyVaultName.vault.azure.net/secrets"
$kvs_neo4jBolt = 'NEO4J_BOLT_URI=@Microsoft.KeyVault(SecretUri=' + $kvBase + '/neo4j-bolt-uri/)'
$kvs_neo4jPwd  = 'NEO4J_PASSWORD=@Microsoft.KeyVault(SecretUri=' + $kvBase + '/neo4j-password/)'
$kvs_sqlConn   = 'SQL_CONNECTION_STRING=@Microsoft.KeyVault(SecretUri=' + $kvBase + '/sql-connection-string/)'
$kvs_blobConn  = 'BLOB_CONNECTION_STRING=@Microsoft.KeyVault(SecretUri=' + $kvBase + '/blob-connection-string/)'
$kvs_searchKey = 'AZURE_SEARCH_KEY=@Microsoft.KeyVault(SecretUri=' + $kvBase + '/azure-search-key/)'

foreach ($app in @($fnAdgm, $fnSevenRqa, $fnAdmm, $fnMwp)) {
    Write-Host "  -> $app"
    az functionapp create `
      --resource-group $resourceGroup `
      --consumption-plan-location $location `
      --runtime "python" `
      --runtime-version "3.11" `
      --name $app `
      --os-type "Linux" `
      --functions-version 4 `
      --storage-account $storageAccountName | Out-Null

    # Managed Identity -- necessaire pour Key Vault ET Azure OpenAI (disableLocalAuth=true)
    az functionapp identity assign --resource-group $resourceGroup --name $app | Out-Null
    $principalId = (az functionapp identity show --resource-group $resourceGroup --name $app --query "principalId" --output tsv)

    # RBAC : autoriser cette identite a appeler Azure OpenAI
    az role assignment create `
      --assignee $principalId `
      --role "Cognitive Services OpenAI User" `
      --scope $openaiResourceId | Out-Null

    # Acces en lecture aux secrets du Key Vault
    az keyvault set-policy `
      --name $keyVaultName `
      --object-id $principalId `
      --secret-permissions get list | Out-Null

    # Variables d'environnement
    az functionapp config appsettings set `
      --resource-group $resourceGroup `
      --name $app `
      --settings $kvs_neo4jBolt $kvs_neo4jPwd $kvs_sqlConn $kvs_blobConn $kvs_searchKey `
        "BLOB_CONTAINER_RETRODOCS=retrodocs" `
        "AZURE_OPENAI_ENDPOINT=$existingOpenAIEndpoint" `
        "AZURE_OPENAI_GPT4O_DEPLOYMENT=gpt-4o" `
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large" `
        "AZURE_SEARCH_ENDPOINT=$existingSearchEndpoint" `
        "ARCHIMIND_API_URL=$existingArchiMindUrl" | Out-Null
}

# =========================================================================
# 8. Azure Static Web App (Frontend React Modernization Agent)
# =========================================================================
Write-Host "[8/9] Creating Static Web App..."
az staticwebapp create `
  --resource-group $resourceGroup `
  --name $webApp `
  --location "westeurope"

# =========================================================================
# 9. Verification RBAC (la propagation peut prendre 1-2 minutes)
# =========================================================================
Write-Host "[9/9] Verification des role assignments OpenAI..."
Start-Sleep -Seconds 5
$assignedCount = (az role assignment list --scope $openaiResourceId --query "[?roleDefinitionName=='Cognitive Services OpenAI User'] | length(@)" --output tsv)
Write-Host "  -> $assignedCount identite(s) Function App autorisee(s) sur Azure OpenAI"

# =========================================================================
# RESUME
# =========================================================================
Write-Host ""
Write-Host "================================================"
Write-Host " Setup termine !"
Write-Host "================================================"
Write-Host ""
Write-Host "RESSOURCES CREEES :"
Write-Host "  Neo4j ACI    : http://${neo4jDnsLabel}.${location}.azurecontainer.io:7474"
Write-Host "  Bolt URI     : bolt://${neo4jDnsLabel}.${location}.azurecontainer.io:7687"
Write-Host "  SQL Server   : $sqlServerName.database.windows.net"
Write-Host "  Blob Storage : $storageAccountName"
Write-Host "  Key Vault    : $keyVaultName"
Write-Host "  Fn ADG-M     : https://$fnAdgm.azurewebsites.net/api"
Write-Host "  Fn 7RQA      : https://$fnSevenRqa.azurewebsites.net/api"
Write-Host "  Fn ADM-M     : https://$fnAdmm.azurewebsites.net/api"
Write-Host "  Fn MWP       : https://$fnMwp.azurewebsites.net/api"
Write-Host "  Frontend SWA : $webApp"
Write-Host ""
Write-Host "RESSOURCES REUTILISEES (zero cout supplementaire) :"
Write-Host "  ArchiMind    : $existingArchiMindUrl"
Write-Host "  Azure OpenAI : $existingOpenAIEndpoint (gpt-4o, auth Managed Identity)"
Write-Host "  Azure Search : $existingSearchEndpoint"
Write-Host ""
Write-Host "ETAPES MANUELLES RESTANTES :"
Write-Host "  1. Executer SPRINT0_setup-sql.sql dans Azure Portal Query Editor"
Write-Host "  2. Ouvrir Neo4j Browser puis executer SPRINT0_setup-neo4j.cypher"
Write-Host "  3. Deployer les fonctions : func azure functionapp publish $fnAdgm"
Write-Host ""
Write-Host "PC WINDOWS : IDE + browser + az CLI uniquement. Aucun serveur local requis."
Write-Host ""
Write-Host "RAPPEL SECURITE : la cle Search a transite en clair dans la session CLI."
Write-Host "Envisager 'az search admin-key renew' apres verification du bon fonctionnement."
