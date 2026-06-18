#Requires -Version 5.1
<#
.SYNOPSIS
    Upload du dump GraphML vers Azure Files pour le conteneur neo4j-legacykb.

.DESCRIPTION
    1. Construit un bundle CA custom (copie du certifi d'az CLI + certs racine Zscaler
       du magasin Windows) pour contourner l'erreur CERTIFICATE_VERIFY_FAILED des
       commandes "az storage" derriere le proxy d'entreprise.
    2. Cree le partage de fichiers "neo4j-import" sur le compte stneo4jimportvgi.
    3. Upload docs/extract/repartition_cleaned_export.graphml dans ce partage.
    4. Liste le contenu du partage pour verification.
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

# ── 1. Bundle CA custom avec certs Zscaler ─────────────────────────────────
$origBundle   = "C:\Program Files\Microsoft SDKs\Azure\CLI2\Lib\site-packages\certifi\cacert.pem"
$customBundle = "$env:USERPROFILE\.azure\custom-ca-bundle.pem"

New-Item -ItemType Directory -Force -Path (Split-Path $customBundle) | Out-Null
Copy-Item $origBundle $customBundle -Force

$certs = Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -match "Zscaler" }

$seen = @{}
foreach ($cert in $certs) {
    if ($seen.ContainsKey($cert.Thumbprint)) { continue }
    $seen[$cert.Thumbprint] = $true
    $pem = "-----BEGIN CERTIFICATE-----`n" +
           [Convert]::ToBase64String($cert.Export('Cert'), 'InsertLineBreaks') +
           "`n-----END CERTIFICATE-----`n"
    Add-Content -Path $customBundle -Value $pem -Encoding ascii
}
Write-Host "OK   $($seen.Count) certificat(s) Zscaler ajoute(s) au bundle CA custom" -ForegroundColor Green

$env:REQUESTS_CA_BUNDLE = $customBundle

# ── 2-4. Creation du partage + upload + verification ───────────────────────
# SEC-011 : utilise --auth-mode login (identité Azure CLI / Managed Identity)
# au lieu de --account-key pour ne jamais exposer de clé de compte en clair.
# Prérequis : rôle "Storage File Data SMB Share Contributor" sur le compte.
$rg      = "rg-sp4-d-vgi-azu-notebook-txt"
$storage = "stneo4jimportvgi"
$dump    = Join-Path $ProjectRoot "docs\extract\repartition_cleaned_export.graphml"

if (-not (Test-Path $dump)) {
    Write-Error "Dump introuvable : $dump"
    exit 1
}

az storage share create --name neo4j-import --account-name $storage --auth-mode login --output none
Write-Host "OK   Partage 'neo4j-import' cree (ou deja existant)" -ForegroundColor Green

az storage file upload --share-name neo4j-import --account-name $storage --auth-mode login `
    --source $dump --path repartition_cleaned_export.graphml --output none
Write-Host "OK   Dump uploade : repartition_cleaned_export.graphml" -ForegroundColor Green

Write-Host ""
Write-Host "Contenu du partage neo4j-import :" -ForegroundColor White
az storage file list --share-name neo4j-import --account-name $storage --auth-mode login -o table
