#Requires -Version 5.1
<#
.SYNOPSIS
    Setup one-shot de NotebookLM Azure — provisionne l'infrastructure et configure l'environnement local.

.DESCRIPTION
    Phases executées :
      0. Vérification des prérequis (az, python) — parallel
      1. Installation extensions Azure CLI (containerapp, bicep) — parallel
      2. Authentification Azure + sélection subscription
      3. Resource Group + déploiement Bicep (~12 min)
      4. Génération du fichier .env depuis les outputs Bicep
      5. Assignation des rôles IAM — parallel
      6. Création du virtualenv Python + installation des dépendances

.PARAMETER Subscription
    ID ou nom de la subscription Azure. Si omis et une seule subscription disponible, elle est
    sélectionnée automatiquement. Si plusieurs, un menu interactif s'affiche.

.PARAMETER Location
    Région Azure pour le déploiement. Défaut : francecentral.
    Le déploiement gpt-4o utilise le SKU GlobalStandard (quota global partagé), ce qui évite
    le problème de quota OpenAI.Standard.gpt-4o épuisé sur francecentral.
    Alternatives si quota insuffisant malgré tout : swedencentral, westeurope.

.PARAMETER ProjectName
    Préfixe des ressources Azure (3-8 caractères, minuscules). Défaut : nlmazure.

.PARAMETER ResourceGroup
    Nom du Resource Group cible. Défaut : rg-<ProjectName>-prod.
    S'il existe déjà, il est réutilisé tel quel (utile si votre compte n'a que des droits
    Contributor sur un Resource Group existant, sans droit de création au niveau subscription).

.PARAMETER SkipSSL
    Désactive la vérification SSL pour az CLI et pip.
    À utiliser sur les postes avec proxy d'entreprise (Zscaler, Forcepoint, etc.).
    Injecte aussi automatiquement le certificat Zscaler dans le bundle certifi Python.

.PARAMETER Force
    Écrase le fichier .env existant sans demander confirmation.

.EXAMPLE
    # Setup standard
    .\deploy.ps1

.EXAMPLE
    # Avec proxy d'entreprise
    .\deploy.ps1 -SkipSSL

.EXAMPLE
    # Région alternative + nom projet personnalisé
    .\deploy.ps1 -Location swedencentral -ProjectName monprojet

.EXAMPLE
    # Réutilise un Resource Group existant (droits Contributor déjà accordés dessus)
    .\deploy.ps1 -ResourceGroup rg-sp4-d-vgi-azu-notebook-txt
#>
param(
    [string]$Subscription  = "",
    [string]$Location      = "francecentral",
    [string]$ProjectName   = "nlmazure",
    [string]$ResourceGroup = "",
    [switch]$SkipSSL,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# ── Helpers affichage ──────────────────────────────────────────────────────────
function Write-Banner {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║   NotebookLM Azure — Setup automatisé   ║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Région        : $Location" -ForegroundColor DarkGray
    Write-Host "  Projet        : $ProjectName" -ForegroundColor DarkGray
    Write-Host "  Durée estimée : ~15 min (déploiement Azure)" -ForegroundColor DarkGray
    if ($SkipSSL) {
        Write-Host "  Mode SSL      : bypass activé (proxy entreprise)" -ForegroundColor Yellow
    }
    Write-Host ""
}

function Write-Phase($n, $total, $msg) {
    Write-Host "  [$n/$total] $msg" -ForegroundColor Cyan
}
function Write-OK($msg)   { Write-Host "        OK   $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "             $msg" -ForegroundColor DarkGray }
function Write-Warn($msg) { Write-Host "        !!   $msg" -ForegroundColor Yellow }
function Write-Fail($msg) {
    Write-Host ""
    Write-Host "  ERREUR : $msg" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# ── Phase 0 : Prérequis ────────────────────────────────────────────────────────
Write-Banner
Write-Phase 0 6 "Vérification des prérequis"

$prereqs = @(
    @{ Name = "Azure CLI (az)"; Cmd = "az";     Url = "https://aka.ms/installazurecliwindows" },
    @{ Name = "Python 3.11+";   Cmd = "python"; Url = "https://python.org/downloads" }
)

$checkResults = foreach ($p in $prereqs) { [bool](Get-Command $p.Cmd -ErrorAction SilentlyContinue) }

$missing = @()
for ($i = 0; $i -lt $prereqs.Count; $i++) {
    if ($checkResults[$i]) { Write-OK $prereqs[$i].Name }
    else {
        Write-Host "        ✗    $($prereqs[$i].Name) manquant" -ForegroundColor Red
        Write-Host "             Installer : $($prereqs[$i].Url)" -ForegroundColor DarkGray
        $missing += $prereqs[$i].Name
    }
}

if ($missing.Count -gt 0) {
    Write-Fail "Installez les outils manquants puis relancez deploy.ps1"
}

# ── Phase 1 : SSL + Extensions ────────────────────────────────────────────────
Write-Phase 1 6 "Configuration proxy & extensions Azure CLI"

if ($SkipSSL) {
    az config set core.verify_ssl=false --only-show-errors 2>&1 | Out-Null
    Write-OK "SSL verification désactivée (az CLI)"
    Write-Warn "Mode proxy : les certificats serveur Azure ne seront pas vérifiés"
}

# Installation extensions en parallèle
Write-Info "Installation containerapp + Bicep (parallel)…"
$extJobs = @(
    (Start-Job -ScriptBlock { az extension add --name containerapp --upgrade --only-show-errors 2>&1 }),
    (Start-Job -ScriptBlock { az bicep install 2>&1 })
)
$extJobs | Wait-Job | Out-Null
$extJobs | Remove-Job -Force
Write-OK "Extension containerapp installée"
Write-OK "Bicep CLI installé"

# ── Phase 2 : Authentification ────────────────────────────────────────────────
Write-Phase 2 6 "Authentification Azure"

$account = $null
try { $account = az account show 2>$null | ConvertFrom-Json } catch {}

if (-not $account) {
    Write-Info "Ouverture du navigateur pour az login…"
    az login --only-show-errors | Out-Null
    $account = az account show 2>&1 | ConvertFrom-Json
}
Write-OK "Connecté : $($account.user.name)"

# Sélection subscription
if ($Subscription) {
    az account set --subscription $Subscription --only-show-errors
    $account = az account show | ConvertFrom-Json
} else {
    $subs = az account list --query "[?state=='Enabled'].{name:name, id:id}" 2>&1 | ConvertFrom-Json
    if ($subs.Count -gt 1) {
        Write-Host ""
        Write-Host "        Subscriptions disponibles :" -ForegroundColor White
        for ($i = 0; $i -lt $subs.Count; $i++) {
            $marker = if ($subs[$i].id -eq $account.id) { " (active)" } else { "" }
            Write-Host "        [$i] $($subs[$i].name)$marker" -ForegroundColor Gray
        }
        Write-Host ""
        $sel = Read-Host "        Numéro à utiliser [0-$($subs.Count - 1)]"
        if ($sel -match '^\d+$' -and [int]$sel -lt $subs.Count) {
            az account set --subscription $subs[[int]$sel].id --only-show-errors
            $account = az account show | ConvertFrom-Json
        }
    }
}
Write-OK "Subscription : $($account.name) ($($account.id))"

$deployerOid    = az ad signed-in-user show --query id -o tsv 2>&1
$subscriptionId = $account.id
$rg             = if ($ResourceGroup) { $ResourceGroup } else { "rg-$ProjectName-prod" }
$deployName     = "deploy-$(Get-Date -Format 'yyyyMMddHHmm')"

# ── Phase 3 : Resource Group + Bicep ─────────────────────────────────────────
Write-Phase 3 6 "Infrastructure Azure"

# Création RG si nécessaire (idempotent — réutilise le RG s'il existe déjà,
# utile quand le compte n'a pas le droit de créer un RG au niveau subscription)
$rgExists = (az group exists --name $rg) -eq 'true'
if ($rgExists) {
    Write-OK "Resource Group existant réutilisé : $rg ($Location)"
} else {
    az group create --name $rg --location $Location `
        --tags project=$ProjectName managed-by=bicep `
        --output none --only-show-errors 2>&1 | Out-Null
    Write-OK "Resource Group créé : $rg ($Location)"
}

Write-Info "Déploiement Bicep en cours — environ 12 minutes…"
Write-Info "(OpenAI et Document Intelligence sont les plus lents à provisionner)"

az deployment group create `
    --resource-group $rg `
    --template-file "$ProjectRoot\infra\main.bicep" `
    --parameters deployerObjectId=$deployerOid projectName=$ProjectName `
    --name $deployName `
    --output none `
    --only-show-errors 2>&1

Write-OK "Déploiement Bicep terminé"

# ── Phase 4 : .env ────────────────────────────────────────────────────────────
Write-Phase 4 6 "Génération du fichier .env"

$envFile = Join-Path $ProjectRoot ".env"
if ((Test-Path $envFile) -and -not $Force) {
    $overwrite = Read-Host "        .env existant détecté. Écraser ? (o/N)"
    if ($overwrite -ne 'o') { Write-Fail "Annulé. Relancez avec -Force pour écraser automatiquement." }
}

# Un seul appel API pour tous les outputs
$rawOutputs = az deployment group show -g $rg -n $deployName `
    --query properties.outputs --output json 2>&1
$outputs = $rawOutputs | ConvertFrom-Json

# Génération d'une API Key sécurisée
$apiKeyBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($apiKeyBytes)
$apiKey = [Convert]::ToBase64String($apiKeyBytes) -replace '[/+=]', ''

$envContent = @"
# Généré automatiquement par deploy.ps1 le $(Get-Date -Format 'yyyy-MM-dd HH:mm')
# NE PAS COMMITTER CE FICHIER — il contient des secrets

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=$($outputs.openAIEndpoint.value)
AZURE_OPENAI_GPT4O_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large

# Azure AI Search
AZURE_SEARCH_ENDPOINT=$($outputs.searchEndpoint.value)

# Azure Document Intelligence
AZURE_DOCINT_ENDPOINT=$($outputs.docIntEndpoint.value)

# Azure Blob Storage
AZURE_STORAGE_ACCOUNT_NAME=$($outputs.storageAccountName.value)

# Azure Key Vault (pour la production — Container Apps)
AZURE_KEYVAULT_URI=https://$($outputs.keyVaultName.value).vault.azure.net/

# Authentification API (généré aléatoirement)
API_KEY=$apiKey
"@

[System.IO.File]::WriteAllText($envFile, $envContent, [System.Text.Encoding]::UTF8)
Write-OK ".env généré (API_KEY aléatoire incluse)"

# ── Phase 5 : Rôles IAM ───────────────────────────────────────────────────────
Write-Phase 5 6 "Rôles IAM (4 assignations parallèles)"

$scope = "/subscriptions/$subscriptionId/resourceGroups/$rg"
$roles = @(
    "Cognitive Services OpenAI User",
    "Search Index Data Contributor",
    "Cognitive Services User",
    "Storage Blob Data Contributor"
)

$roleJobs = foreach ($role in $roles) {
    Start-Job -ScriptBlock {
        az role assignment create `
            --assignee $using:deployerOid `
            --role $using:role `
            --scope $using:scope `
            --only-show-errors 2>&1 | Out-Null
    }
}
$roleJobs | Wait-Job | Out-Null
$roleJobs | Remove-Job -Force

Write-OK "Rôles IAM assignés :"
foreach ($role in $roles) { Write-Info "  - $role" }
Write-Warn "Propagation IAM : attendez 3-5 min avant d'indexer des documents"

# ── Phase 6 : Virtualenv Python ───────────────────────────────────────────────
Write-Phase 6 6 "Environnement Python"

$venvPath  = Join-Path $ProjectRoot "api\.venv"
$pipExe    = Join-Path $venvPath "Scripts\pip.exe"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPath)) {
    python -m venv $venvPath 2>&1 | Out-Null
    Write-OK "Virtualenv créé : api\.venv"
} else {
    Write-OK "Virtualenv existant réutilisé"
}

# Flags pip selon mode SSL
$pipBase = @(
    "install",
    "-r", "$ProjectRoot\api\requirements.txt",
    "-r", "$ProjectRoot\ingest\requirements.txt",
    "--quiet"
)
if ($SkipSSL) {
    $pipBase += @(
        "--trusted-host", "pypi.org",
        "--trusted-host", "files.pythonhosted.org",
        "--trusted-host", "pypi.python.org"
    )
}

Write-Info "Installation des dépendances Python…"
& $pipExe @pipBase
Write-OK "Dépendances installées (api + ingest)"

# Injection du certificat Zscaler dans le bundle certifi si -SkipSSL
if ($SkipSSL) {
    Write-Info "Recherche du certificat Zscaler dans le store Windows…"
    $zscalerCerts = @(Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -match "Zscaler" })

    if ($zscalerCerts.Count -gt 0) {
        $certifiBundle = & $pythonExe -c "import certifi; print(certifi.where())" 2>&1
        foreach ($cert in $zscalerCerts) {
            $pem = "-----BEGIN CERTIFICATE-----`n" +
                   [Convert]::ToBase64String($cert.Export('Cert'), 'InsertLineBreaks') +
                   "`n-----END CERTIFICATE-----`n"
            Add-Content -Path $certifiBundle -Value $pem -Encoding ascii
        }
        Write-OK "$($zscalerCerts.Count) certificat(s) Zscaler injecté(s) dans certifi"
        Write-Info "Path : $certifiBundle"
    } else {
        Write-Warn "Aucun certificat Zscaler trouvé — à injecter manuellement si besoin"
        Write-Info "Voir GUIDE-DEPLOIEMENT.md section 'Proxy d entreprise'"
    }
}

# ── Résumé final ──────────────────────────────────────────────────────────────
$apiUrl = $outputs.apiUrl.value

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║           Setup terminé !                ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Prochaines étapes :" -ForegroundColor White
Write-Host "  1. Attendez 3-5 min (propagation des rôles IAM)" -ForegroundColor DarkGray
Write-Host "  2. Lancez le serveur de dev :" -ForegroundColor DarkGray
Write-Host "     .\start-dev.ps1" -ForegroundColor Cyan
Write-Host "  3. Ajoutez vos documents dans le rail gauche" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Ressources Azure créées :" -ForegroundColor White
Write-Host "  Resource Group : $rg" -ForegroundColor DarkGray
Write-Host "  URL production : https://$apiUrl" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Pour supprimer toutes les ressources : .\teardown.ps1" -ForegroundColor Yellow
Write-Host ""
