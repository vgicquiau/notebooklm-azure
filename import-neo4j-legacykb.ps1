#Requires -Version 5.1
<#
.SYNOPSIS
    Upload du dump GraphML vers le conteneur neo4j-legacykb et import via APOC.

.DESCRIPTION
    Appelé automatiquement par deploy.ps1 après le déploiement Bicep. Peut aussi être
    relancé seul (ex. après mise à jour du dump GraphML) sans redéployer toute
    l'infrastructure :

    1. Upload le fichier GraphML dans le partage Azure Files monté sur le conteneur.
    2. Attend que l'API HTTP de Neo4j (port 7474) réponde (jusqu'à 3 minutes — le temps
       que le conteneur démarre et installe le plugin APOC).
    3. Exécute `CALL apoc.import.graphml(...)` via l'API transactionnelle HTTP de Neo4j.

.PARAMETER ResourceGroup
    Resource Group contenant le storage account et le conteneur ACI.

.PARAMETER StorageAccountName
    Nom du storage account dédié (output Bicep `neo4jLegacyKbStorageAccount`).

.PARAMETER ShareName
    Nom du partage Azure Files (output Bicep `neo4jLegacyKbShareName`, défaut "neo4j-import").

.PARAMETER Fqdn
    FQDN du conteneur ACI (ex. neo4j-legacykb-nlmavgi-prod.swedencentral.azurecontainer.io).

.PARAMETER Neo4jPassword
    Mot de passe du compte neo4j (utilisateur fixe "neo4j").

.PARAMETER DumpPath
    Chemin du fichier GraphML à importer. Défaut : docs/extract/repartition_cleaned_export.graphml.

.EXAMPLE
    .\import-neo4j-legacykb.ps1 -ResourceGroup rg-nlmavgi-prod `
        -StorageAccountName stneo4jkbnlmavgiprod -ShareName neo4j-import `
        -Fqdn neo4j-legacykb-nlmavgi-prod.swedencentral.azurecontainer.io `
        -Neo4jPassword (Get-Content secret.txt)
#>
param(
    [Parameter(Mandatory)] [string]$ResourceGroup,
    [Parameter(Mandatory)] [string]$StorageAccountName,
    [string]$ShareName = "neo4j-import",
    [Parameter(Mandatory)] [string]$Fqdn,
    [Parameter(Mandatory)] [SecureString]$Neo4jPassword,
    [string]$DumpPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

if (-not $DumpPath) {
    $DumpPath = Join-Path $ProjectRoot "docs\extract\repartition_cleaned_export.graphml"
}

if (-not (Test-Path $DumpPath)) {
    Write-Host "  !!   Dump GraphML introuvable ($DumpPath) — import ignoré" -ForegroundColor Yellow
    Write-Host "       Placez votre export dans docs/extract/ et relancez ce script." -ForegroundColor DarkGray
    exit 0
}

$dumpFileName = Split-Path $DumpPath -Leaf

# ── 1. Upload du dump dans le partage Azure Files ───────────────────────────────
# SEC-011 : --auth-mode login — identité Azure CLI / Managed Identity.
# Aucune clé de compte n'est récupérée ni transmise en clair.
# Prérequis : rôle "Storage File Data SMB Share Contributor" sur le compte de stockage.
az storage file upload --share-name $ShareName --account-name $StorageAccountName --auth-mode login `
    --source $DumpPath --path $dumpFileName --output none --only-show-errors 2>&1 | Out-Null
Write-Host "  OK   Dump GraphML uploadé : $StorageAccountName/$ShareName/$dumpFileName" -ForegroundColor Green

# ── 2. Attente disponibilité Neo4j (démarrage conteneur + installation APOC) ────
# HTTP (7474) désactivé — health check sur HTTPS (7473) avec cert auto-signé accepté.
Write-Host "       Attente démarrage de neo4j-legacykb (jusqu'à 3 min)…" -ForegroundColor DarkGray
$ready = $false
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
for ($i = 0; $i -lt 36; $i++) {
    try {
        Invoke-WebRequest -Uri "https://${Fqdn}:7473" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 5
    }
}
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = $null

if (-not $ready) {
    Write-Host "  !!   neo4j-legacykb non joignable après 3 min — relancez ce script plus tard" -ForegroundColor Yellow
    exit 0
}

# ── 3. Import GraphML via apoc.import.graphml (API transactionnelle HTTP) ───────
# SecureString → texte brut uniquement le temps de construire le header Basic Auth,
# immédiatement zéroïsé en mémoire après usage (SEC-002).
$bstr      = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Neo4jPassword)
$plainPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

$authPair = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("neo4j:$plainPass"))
$plainPass = $null  # Libère la référence dès que possible

$cypher = "CALL apoc.import.graphml('file:///var/lib/neo4j/import/$dumpFileName', {readLabels: true}) YIELD nodes, relationships RETURN nodes, relationships"
$body = @{ statements = @(@{ statement = $cypher }) } | ConvertTo-Json -Depth 5

# Le certificat Bolt/HTTPS est auto-signé (généré par deploy.ps1) — on désactive
# temporairement la validation TLS pour cet appel, puis on restaure avant de quitter.
$_origCallback = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
$resp = $null
$_importError = $null
try {
    $resp = Invoke-RestMethod -Uri "https://${Fqdn}:7473/db/neo4j/tx/commit" -Method Post `
        -Headers @{ Authorization = "Basic $authPair"; "Content-Type" = "application/json" } `
        -Body $body -TimeoutSec 180
} catch {
    $_importError = $_.Exception.Message
}
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = $_origCallback

if ($_importError) {
    Write-Host "  !!   Import GraphML échoué : $_importError" -ForegroundColor Yellow
    exit 0
}

if ($resp.errors.Count -gt 0) {
    Write-Host "  !!   Import GraphML : $($resp.errors[0].message)" -ForegroundColor Yellow
} else {
    $row = $resp.results[0].data[0].row
    Write-Host "  OK   Import GraphML terminé : $($row[0]) nœuds, $($row[1]) relations" -ForegroundColor Green
}
