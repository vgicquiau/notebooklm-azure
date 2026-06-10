# ============================================================================
# Azure Setup -- FIXUP pass for Sprint 0 (targets gaps from the first run)
#
# The first run (SPRINT0_setup-azure.ps1) created: Storage Account, SQL
# Server+DB, App Insights, 4 Function Apps (+ Managed Identity), Static Web
# App, and 2 of 4 OpenAI RBAC role assignments. It hit 4 distinct bugs:
#
#   1. az keyvault create : flags --enable-soft-delete/--soft-delete-retention
#      no longer exist in current az CLI -> replaced by --retention-days.
#      RESULT: Key Vault was never created (cascading "vault not found"
#      errors on every secret-set / set-policy call afterwards).
#   2. az container create : --os-type is now required explicitly (was
#      defaulting to null -> InvalidOsType). RESULT: Neo4j ACI not created.
#   3. az role assignment create : 2 of the 4 Function App identities were
#      too fresh for AAD/MS Graph propagation ("Cannot find user or service
#      principal..."). RESULT: only 2/4 RBAC OpenAI assignments succeeded.
#   4. az functionapp config appsettings set : az on Windows is az.cmd, a
#      batch shim launched through cmd.exe, which re-tokenizes the command
#      line. Values like "@Microsoft.KeyVault(SecretUri=...)" contain ( )
#      which cmd.exe treats as command-grouping metacharacters -> parse
#      error "NEO4J_PASSWORD etait inattendu". RESULT: app settings not
#      written. FIX: bypass az.cmd's argument line entirely by sending the
#      JSON payload through "az rest --body @file.json" (validated working).
#
# Everything already created by the first run is left untouched -- this
# script only fills the gaps. Idempotent: safe to re-run.
# ============================================================================

$subscriptionId = "07875763-82ff-4808-a7da-e3d0dccc86fc"
$resourceGroup  = "rg-sp4-d-vgi-azu-vgi-sandbox-txt"
$location       = "francecentral"
$envName        = "dev"

$sqlPassword    = "ChangeMe@SQL2026!"
$neo4jPassword  = "ChangeMe@Neo4j2026"

$prefix             = "modernagent"
$storageAccountName = "${prefix}stg${envName}"
$sqlServerName      = "$prefix-sql-$envName"
$sqlDbName          = "modernagent_db"
$keyVaultName       = "$prefix-kv-$envName"
$neo4jAciName       = "neo4j-$envName"
$neo4jDnsLabel      = "neo4j-modernagent-$envName"

$existingArchiMindUrl   = "https://app-api-nlmazure-prod.azurewebsites.net"
$existingOpenAIName     = "oai-nlmazure-prod"
$existingOpenAIEndpoint = "https://oai-nlmazure-prod.openai.azure.com/"
$existingSearchName     = "srch-nlmazure-prod"
$existingSearchEndpoint = "https://srch-nlmazure-prod.search.windows.net"

# Principal IDs captured from the first run (functionapp identity show)
$allApps = [ordered]@{
    "modernagent-adgm-dev"     = "abc3c3b8-23f1-4154-b307-d26b59d38fac"
    "modernagent-sevenrqa-dev" = "02fbd213-f810-46a0-ac67-858a2eea6341"
    "modernagent-admm-dev"     = "89d8364d-504d-4f38-9d76-65e841ac1954"
    "modernagent-mwp-dev"      = "0be6e7e3-8dae-4f84-b37e-9c1e2c829572"
}
# These 2 did not get the OpenAI role on the first pass (identity too fresh for AAD propagation)
$retryRoleAssignment = @("modernagent-sevenrqa-dev", "modernagent-mwp-dev")

Write-Host ""
Write-Host "================================================"
Write-Host " Modernization Agent -- Sprint 0 FIXUP pass"
Write-Host "================================================"
Write-Host ""

az account set --subscription $subscriptionId

# =========================================================================
# FIX 1 : Key Vault (corrected flag) + secrets
# =========================================================================
Write-Host "[FIX 1/5] Creating Key Vault (--retention-days replaces removed flags)..."
az keyvault create `
  --resource-group $resourceGroup `
  --name $keyVaultName `
  --location $location `
  --retention-days 7 `
  --output none

Write-Host "  -> Fetching storage + search keys for secret storage..."
$storageKey = (az storage account keys list --resource-group $resourceGroup --account-name $storageAccountName --query "[0].value" --output tsv)
$searchKey  = (az search admin-key show --service-name $existingSearchName --resource-group $resourceGroup --query "primaryKey" --output tsv)

$sqlConnStr   = "Server=tcp:$sqlServerName.database.windows.net,1433;Initial Catalog=$sqlDbName;Persist Security Info=False;User ID=sqladmin;Password=$sqlPassword;MultipleActiveResultSets=False;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;"
$blobConnStr  = "DefaultEndpointsProtocol=https;AccountName=$storageAccountName;AccountKey=$storageKey;EndpointSuffix=core.windows.net"
$neo4jBoltUri = "bolt://${neo4jDnsLabel}.${location}.azurecontainer.io:7687"

az keyvault secret set --vault-name $keyVaultName --name "sql-connection-string"  --value $sqlConnStr              --output none
az keyvault secret set --vault-name $keyVaultName --name "blob-connection-string" --value $blobConnStr             --output none
az keyvault secret set --vault-name $keyVaultName --name "neo4j-bolt-uri"         --value $neo4jBoltUri            --output none
az keyvault secret set --vault-name $keyVaultName --name "neo4j-password"         --value $neo4jPassword           --output none
az keyvault secret set --vault-name $keyVaultName --name "azure-search-key"       --value $searchKey               --output none
az keyvault secret set --vault-name $keyVaultName --name "azure-search-endpoint"  --value $existingSearchEndpoint  --output none
az keyvault secret set --vault-name $keyVaultName --name "azure-openai-endpoint"  --value $existingOpenAIEndpoint  --output none
Write-Host "  -> 7 secrets written to $keyVaultName"

# =========================================================================
# FIX 2 : Neo4j ACI -- defined via YAML file, NOT inline --environment-variables
#
# A first attempt with --os-type Linux + inline --environment-variables
# DID create a Running container, but silently WITHOUT GDS: the value
# NEO4J_PLUGINS='["graph-data-science"]' survives PowerShell fine, but
# az.cmd/cmd.exe strips the inner double quotes in transit, delivering the
# INVALID-JSON string [graph-data-science] to the container. The entrypoint's
# jq parse then fails ("parse error: Invalid numeric literal..."), the plugin
# install step is skipped, and Neo4j starts up clean with zero indication
# anything is missing -- only `SHOW PROCEDURES ... 'gds.louvain'` reveals it.
# FIX: define the whole container group in a YAML file (same "route complex
# values through a file" pattern as FIX 5's appsettings) -- a YAML single-
# quoted scalar preserves the inner " literally, bypassing cmd.exe entirely.
# =========================================================================
Write-Host "[FIX 2/5] Creating Neo4j on Azure Container Instances (via YAML file)..."
Write-Host "  -> GDS plugin download at startup (~2-3 minutes)"
$neo4jTmpDir = "$env:TEMP\modernagent-neo4j"
New-Item -ItemType Directory -Force -Path $neo4jTmpDir | Out-Null
$neo4jYaml = @"
location: $location
name: $neo4jAciName
properties:
  osType: Linux
  restartPolicy: OnFailure
  ipAddress:
    type: Public
    dnsNameLabel: $neo4jDnsLabel
    ports:
    - protocol: TCP
      port: 7474
    - protocol: TCP
      port: 7687
  containers:
  - name: $neo4jAciName
    properties:
      image: neo4j:5.22-community
      ports:
      - protocol: TCP
        port: 7474
      - protocol: TCP
        port: 7687
      environmentVariables:
      - name: NEO4J_AUTH
        value: 'neo4j/$neo4jPassword'
      - name: NEO4J_PLUGINS
        value: '["graph-data-science"]'
      - name: NEO4J_server_default__listen__address
        value: '0.0.0.0'
      - name: NEO4J_dbms_security_procedures_unrestricted
        value: 'gds.*,apoc.*'
      resources:
        requests:
          cpu: 1
          memoryInGB: 2
type: Microsoft.ContainerInstance/containerGroups
"@
$neo4jYamlPath = Join-Path $neo4jTmpDir "neo4j-container.yaml"
[System.IO.File]::WriteAllText($neo4jYamlPath, $neo4jYaml, (New-Object System.Text.UTF8Encoding($false)))
az container create --resource-group $resourceGroup --file $neo4jYamlPath --output none

Write-Host "  -> Neo4j Browser : http://${neo4jDnsLabel}.${location}.azurecontainer.io:7474"
Write-Host "  -> Neo4j Bolt    : bolt://${neo4jDnsLabel}.${location}.azurecontainer.io:7687"

# =========================================================================
# FIX 3 : OpenAI RBAC -- retry the 2 identities that were too fresh for AAD
# =========================================================================
Write-Host "[FIX 3/5] Retrying OpenAI RBAC role assignment (AAD propagation should be done by now)..."
$openaiResourceId = (az cognitiveservices account show --name $existingOpenAIName --resource-group $resourceGroup --query "id" --output tsv)

foreach ($appName in $retryRoleAssignment) {
    $principalId = $allApps[$appName]
    Write-Host "  -> $appName ($principalId)"
    az role assignment create `
      --assignee $principalId `
      --role "Cognitive Services OpenAI User" `
      --scope $openaiResourceId `
      --output none
}

# =========================================================================
# FIX 4 : Key Vault read access for all 4 identities (vault now exists)
#
# NOTE: az keyvault create now defaults to --enable-rbac-authorization true,
# so the legacy "az keyvault set-policy" is REJECTED with "Cannot set
# policies to a vault with '--enable-rbac-authorization' specified".
# Grant access via RBAC role assignment instead ("Key Vault Secrets User"
# = read-only get/list, exactly what Function App setting references need).
# =========================================================================
Write-Host "[FIX 4/5] Granting Key Vault read access to all 4 Function App identities (RBAC)..."
$keyVaultId = (az keyvault show --name $keyVaultName --resource-group $resourceGroup --query "id" --output tsv)
foreach ($appName in $allApps.Keys) {
    az role assignment create --assignee $allApps[$appName] --role "Key Vault Secrets User" --scope $keyVaultId --output none
}
Write-Host "  -> Done"

# =========================================================================
# FIX 5 : App settings via az rest + JSON file (bypasses az.cmd/cmd.exe parsing)
# =========================================================================
Write-Host "[FIX 5/5] Writing Function App settings via az rest (file-based body)..."
$kvBase = "https://$keyVaultName.vault.azure.net/secrets"
$tmpDir = "$env:TEMP\modernagent-appsettings"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

foreach ($appName in $allApps.Keys) {
    $settings = [ordered]@{
        NEO4J_BOLT_URI                    = "@Microsoft.KeyVault(SecretUri=$kvBase/neo4j-bolt-uri/)"
        NEO4J_PASSWORD                    = "@Microsoft.KeyVault(SecretUri=$kvBase/neo4j-password/)"
        SQL_CONNECTION_STRING             = "@Microsoft.KeyVault(SecretUri=$kvBase/sql-connection-string/)"
        BLOB_CONNECTION_STRING            = "@Microsoft.KeyVault(SecretUri=$kvBase/blob-connection-string/)"
        AZURE_SEARCH_KEY                  = "@Microsoft.KeyVault(SecretUri=$kvBase/azure-search-key/)"
        BLOB_CONTAINER_RETRODOCS          = "retrodocs"
        AZURE_OPENAI_ENDPOINT             = $existingOpenAIEndpoint
        AZURE_OPENAI_GPT4O_DEPLOYMENT     = "gpt-4o"
        AZURE_OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-large"
        AZURE_SEARCH_ENDPOINT             = $existingSearchEndpoint
        ARCHIMIND_API_URL                 = $existingArchiMindUrl
    }
    $body = (@{ properties = $settings } | ConvertTo-Json -Depth 5)
    $bodyFile = Join-Path $tmpDir "$appName.json"
    [System.IO.File]::WriteAllText($bodyFile, $body, (New-Object System.Text.UTF8Encoding($false)))

    $uri = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.Web/sites/$appName/config/appsettings?api-version=2022-09-01"
    Write-Host "  -> $appName"
    az rest --method PUT --uri $uri --body "@$bodyFile" --output none
}

# =========================================================================
# VERIFICATION
# =========================================================================
Write-Host ""
Write-Host "[VERIFY] Checking results..."
Start-Sleep -Seconds 8

$kvCheck = az keyvault show --name $keyVaultName --resource-group $resourceGroup --query "name" --output tsv 2>$null
Write-Host "  -> Key Vault            : $kvCheck"

$neo4jState = az container show --resource-group $resourceGroup --name $neo4jAciName --query "instanceView.state" --output tsv 2>$null
Write-Host "  -> Neo4j ACI state      : $neo4jState (will reach 'Running' after plugin download)"

$assignedCount = (az role assignment list --scope $openaiResourceId --query "[?roleDefinitionName=='Cognitive Services OpenAI User'] | length(@)" --output tsv)
Write-Host "  -> OpenAI RBAC assigned : $assignedCount / 4 Function App identities"

$sampleSettings = az functionapp config appsettings list --resource-group $resourceGroup --name "modernagent-adgm-dev" --query "[?name=='AZURE_OPENAI_ENDPOINT' || name=='NEO4J_BOLT_URI'].{name:name, value:value}" --output tsv 2>$null
Write-Host "  -> Sample app settings on modernagent-adgm-dev:"
Write-Host "$sampleSettings"

Write-Host ""
Write-Host "================================================"
Write-Host " Fixup pass complete"
Write-Host "================================================"
Write-Host ""
Write-Host "STILL TO DO MANUALLY :"
Write-Host "  1. Create blob containers 'retrodocs' and 'exports'"
Write-Host "     (local az CLI cannot reach *.blob.core.windows.net : Zscaler corporate"
Write-Host "      proxy presents a self-signed cert that Python's certifi bundle rejects --"
Write-Host "      this only affects data-plane CLI calls from this PC, not the deployed app)"
Write-Host "     -> Portal: Storage Account $storageAccountName > Containers > + Container"
Write-Host "  2. Run SPRINT0_setup-sql.sql in the Azure Portal Query Editor"
Write-Host "  3. Open Neo4j Browser (after ~2-3 min startup) and run SPRINT0_setup-neo4j.cypher"
Write-Host "     http://${neo4jDnsLabel}.${location}.azurecontainer.io:7474"
Write-Host "  4. Deploy the functions: func azure functionapp publish modernagent-adgm-dev"
Write-Host ""
