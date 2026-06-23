#Requires -Version 5.1
<#
.SYNOPSIS
    Déploiement complet de NotebookLM Azure — build image Docker + infrastructure + environnement local.

.DESCRIPTION
    Phases exécutées :
      0. Vérification des prérequis (az CLI, Python 3.11+)
      1. Configuration SSL proxy Zscaler + installation extensions Azure CLI (parallel)
      2. Authentification Azure + sélection subscription
      3. Build & push image Docker vers ACR
      4. Déploiement infrastructure Bicep (~12 min)
         4b. TLS Neo4j — certificat auto-signé (si deployLegacyKb=true)
         4c. Import du dump GraphML dans neo4j-legacykb (si deployLegacyKb=true)
      5. Génération du fichier .env depuis les outputs Bicep
      6. Assignation des rôles IAM — parallel
      7. Création du virtualenv Python + installation des dépendances
      8. Validation post-déploiement (health check)

.PARAMETER Subscription
    ID ou nom de la subscription Azure. Si omis et une seule subscription disponible, elle est
    sélectionnée automatiquement. Si plusieurs, un menu interactif s'affiche.

.PARAMETER Location
    Région Azure pour le déploiement. Défaut : swedencentral.

.PARAMETER ProjectName
    Préfixe des ressources Azure (3-8 caractères, minuscules). Défaut : nlmazure.

.PARAMETER ResourceGroup
    Nom du Resource Group cible. Défaut : rg-<ProjectName>-prod.

.PARAMETER Neo4jPassword
    Mot de passe du compte neo4j du conteneur neo4j-legacykb.
    Demandé interactivement si absent et deployLegacyKb=true.

.PARAMETER Neo4jUri
    URI bolt:// d'une instance neo4j-legacykb existante.
    Si fourni : deployLegacyKb=false (pas de création d'ACI), l'URI est passée directement à l'app.

.PARAMETER SkipSSL
    Bypass SSL pour proxy d'entreprise (Zscaler, Forcepoint, etc.).
    Désactive la vérification SSL az CLI et injecte les certificats Windows dans certifi.

.PARAMETER ImageOnly
    Seulement build + push de l'image Docker. Arrête avant le déploiement Bicep.

.PARAMETER Force
    Pas de prompt de confirmation (écrase .env existant, continue sans pause).

.EXAMPLE
    # Setup standard
    .\deploy.ps1

.EXAMPLE
    # Avec proxy d'entreprise Zscaler
    .\deploy.ps1 -SkipSSL

.EXAMPLE
    # Seulement rebuild l'image Docker
    .\deploy.ps1 -ImageOnly -SkipSSL

.EXAMPLE
    # Neo4j externe existant (pas de déploiement ACI)
    .\deploy.ps1 -Neo4jUri "bolt://my-neo4j.example.com:7687"

.EXAMPLE
    # Région + nom projet personnalisés
    .\deploy.ps1 -Location francecentral -ProjectName monprojet
#>
param(
    [string]$Subscription  = "",
    [string]$Location      = "swedencentral",
    [string]$ProjectName   = "nlmazure",
    [string]$ResourceGroup = "",
    [SecureString]$Neo4jPassword,
    [string]$Neo4jUri      = "",
    [string]$AlertEmail    = "",
    [switch]$SkipSSL,
    [switch]$ImageOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# Environnement cible (toujours prod pour le déploiement Bicep)
$environment = "prod"

# ── Helpers affichage ──────────────────────────────────────────────────────────
function Write-Banner {
    Write-Host ""
    Write-Host "  +==========================================+" -ForegroundColor Cyan
    Write-Host "  |   NotebookLM Azure  --  Deploiement     |" -ForegroundColor Cyan
    Write-Host "  +==========================================+" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Region        : $Location" -ForegroundColor DarkGray
    Write-Host "  Projet        : $ProjectName" -ForegroundColor DarkGray
    Write-Host "  Environnement : $environment" -ForegroundColor DarkGray
    Write-Host "  Duree estimee : ~15 min (build Docker + deploiement Azure)" -ForegroundColor DarkGray
    if ($SkipSSL) {
        Write-Host "  Mode SSL      : bypass active (proxy entreprise)" -ForegroundColor Yellow
    }
    if ($ImageOnly) {
        Write-Host "  Mode          : ImageOnly (build + push uniquement)" -ForegroundColor Yellow
    }
    if ($Neo4jUri) {
        Write-Host "  Neo4j         : URI externe fournie (pas de deploiement ACI)" -ForegroundColor DarkGray
    }
    Write-Host ""
}

function Write-Phase($n, $total, $msg) {
    Write-Host ""
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

# Helper : convertir SecureString en plain text (PowerShell 5.1 compatible)
function ConvertFrom-SecureStringPlain([SecureString]$sec) {
    if ($null -eq $sec) { return "" }
    $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($ptr) }
    finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

# Helper : écrire un fichier de paramètres ARM (JSON) pour az deployment group create.
# Évite de passer des secrets en key=value bruts sur la ligne de commande, où des
# caractères spéciaux (#, &, %...) peuvent casser le relais PowerShell -> cmd.exe -> az.cmd.
function New-BicepParametersFile([hashtable]$Values) {
    $paramsObj = [ordered]@{
        '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters     = [ordered]@{}
    }
    foreach ($key in $Values.Keys) {
        $paramsObj.parameters[$key] = @{ value = $Values[$key] }
    }
    $tempFile = Join-Path $env:TEMP "bicep-params-$([guid]::NewGuid()).json"
    ($paramsObj | ConvertTo-Json -Depth 5) | Set-Content -Path $tempFile -Encoding UTF8
    return $tempFile
}

# Helper : supprimer un fichier temporaire en évitant un bug du provider FileSystem de
# PowerShell — sur les comptes Windows dont le nom contient un point (ex: "v.gicquiau"),
# %TEMP% est résolu en 8.3 short-name (ex: "V5C98~1.GIC") et Remove-Item échoue avec
# "PSArgumentException : objet introuvable" même si le fichier existe (-ErrorAction et
# -LiteralPath n'y changent rien). [System.IO.File]::Delete() contourne le provider.
function Remove-FileSafe([string]$Path) {
    try { [System.IO.File]::Delete($Path) } catch {}
}

# ── PHASE 0 : Prérequis ────────────────────────────────────────────────────────
Write-Banner
Write-Phase 0 8 "Verification des prerequis"

$prereqs = @(
    @{ Name = "Azure CLI (az)"; Cmd = "az";     Url = "https://aka.ms/installazurecliwindows" },
    @{ Name = "Python 3.11+";   Cmd = "python"; Url = "https://python.org/downloads" }
)

$missing = @()
foreach ($p in $prereqs) {
    $cmd = Get-Command $p.Cmd -ErrorAction SilentlyContinue
    if ($cmd) {
        # Afficher la version détectée
        if ($p.Cmd -eq "az") {
            $ver = (az version --output json 2>$null | ConvertFrom-Json).'azure-cli'
            Write-OK "$($p.Name) — v$ver"
        } elseif ($p.Cmd -eq "python") {
            $ver = (python --version 2>&1) -replace '^Python\s+', ''
            # Vérifier 3.11+
            $parts = $ver -split '\.'
            if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
                Write-Host "        x    Python $ver detecte — Python 3.11+ requis" -ForegroundColor Red
                $missing += "$($p.Name) (version $ver insuffisante — 3.11+ requis)"
            } else {
                Write-OK "$($p.Name) — v$ver"
            }
        }
    } else {
        Write-Host "        x    $($p.Name) manquant" -ForegroundColor Red
        Write-Host "             Installer : $($p.Url)" -ForegroundColor DarkGray
        $missing += $p.Name
    }
}

if ($missing.Count -gt 0) {
    Write-Fail "Prerequis manquants : $($missing -join ', '). Installez-les puis relancez deploy.ps1."
}

# ── PHASE 1 : SSL + Extensions ────────────────────────────────────────────────
Write-Phase 1 8 "Configuration SSL + extensions Azure CLI"

# Variable globale pour le bundle certifi temporaire (utilisé en Phase 3)
$tempBundle = $null

if ($SkipSSL) {
    # Désactiver la vérification SSL pour les API calls az CLI
    az config set core.verify_ssl=false --only-show-errors 2>&1 | Out-Null
    Write-OK "SSL verification desactivee (az CLI)"

    # Créer un bundle certifi temporaire avec les certificats Zscaler du store Windows
    $certifiBundle = "C:\Program Files\Microsoft SDKs\Azure\CLI2\Lib\site-packages\certifi\cacert.pem"
    if (Test-Path $certifiBundle) {
        $tempBundle = "$env:TEMP\az_cacert_zscaler.pem"
        Copy-Item $certifiBundle $tempBundle -Force

        $zscalerCerts = @(Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
            Where-Object { $_.Subject -match "Zscaler" })

        if ($zscalerCerts.Count -gt 0) {
            foreach ($cert in $zscalerCerts) {
                $pem = "-----BEGIN CERTIFICATE-----`n" +
                       [Convert]::ToBase64String($cert.Export('Cert'), 'InsertLineBreaks') +
                       "`n-----END CERTIFICATE-----`n"
                Add-Content -Path $tempBundle -Value $pem -Encoding ascii
            }
            Write-OK "$($zscalerCerts.Count) certificat(s) Zscaler injecte(s) dans le bundle certifi temporaire"
            Write-Info "Bundle : $tempBundle"
        } else {
            Write-Warn "Aucun certificat Zscaler trouve dans le store Windows"
            Write-Info "az acr build utilisera le bundle certifi standard"
            # On utilise quand même le bundle copié (sans injection)
        }
    } else {
        Write-Warn "Bundle certifi az CLI introuvable : $certifiBundle"
        Write-Warn "az acr build risque d'echouer avec CERTIFICATE_VERIFY_FAILED"
    }

    Write-Warn "Mode proxy : les certificats serveur Azure ne seront pas verifies"
}

# Installation des extensions en parallèle
Write-Info "Installation extensions containerapp + Bicep (parallel)..."
$extJobs = @(
    (Start-Job -ScriptBlock { az extension add --name containerapp --upgrade --only-show-errors 2>&1 }),
    (Start-Job -ScriptBlock { az extension add --name bicep --upgrade --only-show-errors 2>&1 })
)
$extJobs | Wait-Job | Receive-Job | Out-Null
$extJobs | Remove-Job -Force
Write-OK "Extension containerapp installee"
Write-OK "Extension bicep installee"

# ── PHASE 2 : Authentification ────────────────────────────────────────────────
Write-Phase 2 8 "Authentification Azure"

$account = $null
try { $account = az account show 2>$null | ConvertFrom-Json } catch {}

if (-not $account) {
    Write-Info "Ouverture du navigateur pour az login..."
    az login --only-show-errors | Out-Null
    $account = az account show 2>&1 | ConvertFrom-Json
}
Write-OK "Connecte : $($account.user.name)"

# Sélection de la subscription
if ($Subscription) {
    az account set --subscription $Subscription --only-show-errors
    $account = az account show | ConvertFrom-Json
    Write-OK "Subscription definie : $($account.name)"
} else {
    $subs = az account list --query "[?state=='Enabled'].{name:name, id:id}" 2>&1 | ConvertFrom-Json
    if ($subs.Count -eq 1) {
        # Une seule subscription disponible — sélection automatique
        az account set --subscription $subs[0].id --only-show-errors
        $account = az account show | ConvertFrom-Json
        Write-OK "Subscription selectionnee automatiquement : $($account.name)"
    } elseif ($subs.Count -gt 1) {
        Write-Host ""
        Write-Host "        Subscriptions disponibles :" -ForegroundColor White
        for ($i = 0; $i -lt $subs.Count; $i++) {
            $marker = if ($subs[$i].id -eq $account.id) { " (active)" } else { "" }
            Write-Host "        [$i] $($subs[$i].name)$marker" -ForegroundColor Gray
        }
        Write-Host ""
        $sel = Read-Host "        Numero a utiliser [0-$($subs.Count - 1)]"
        if ($sel -match '^\d+$' -and [int]$sel -lt $subs.Count) {
            az account set --subscription $subs[[int]$sel].id --only-show-errors
            $account = az account show | ConvertFrom-Json
        }
    }
}
Write-OK "Subscription : $($account.name) ($($account.id))"

# Calculer l'Object ID de l'identité qui déploie (obligatoire pour Bicep)
$deployerObjectId = az ad signed-in-user show --query id -o tsv 2>&1
$subscriptionId   = $account.id
$rg               = if ($ResourceGroup) { $ResourceGroup } else { "rg-$ProjectName-$environment" }
$deployName       = "deploy-$(Get-Date -Format 'yyyyMMddHHmm')"

Write-Info "Deployer Object ID : $deployerObjectId"
Write-Info "Resource Group     : $rg"

# ── PHASE 3 : Build & push image Docker ──────────────────────────────────────
Write-Phase 3 8 "Build et push de l'image Docker vers ACR"

# Nom de l'ACR : acr<projectName><environment> (ex: acrnlmazureprod)
$acrName   = "acr$($ProjectName.ToLower())$($environment.ToLower())"
$imageTag  = "$acrName.azurecr.io/notebooklm-api:latest"

Write-Info "ACR         : $acrName"
Write-Info "Image tag   : $imageTag"

# Vérifier que l'ACR existe (créé par Bicep lors d'un déploiement précédent)
$acrExists = $null
try { $acrExists = az acr show -n $acrName --query name -o tsv 2>$null } catch {}

if (-not $acrExists) {
    Write-Warn "L'ACR '$acrName' n'existe pas encore."
    if ($ImageOnly) {
        Write-Fail "Mode -ImageOnly : l'ACR doit etre cree avant de builder l'image. Lancez d'abord deploy.ps1 sans -ImageOnly."
    }
    Write-Info "L'image sera buildee apres le deploiement Bicep (Phase 4)."
    $buildImageAfterBicep = $true
} else {
    $buildImageAfterBicep = $false
    Write-OK "ACR trouve : $acrName"

    Write-Info "Lancement du build ACR en arriere-plan..."
    Write-Info "(les logs Unicode pourraient corrompre la console — polling du statut a la place)"

    # Lancer le build dans un job PowerShell pour eviter le crash d'encodage cp1252
    # $env:PYTHONUTF8 = "1" force l'encodage UTF-8 dans le processus Python de l'az CLI
    $buildJob = Start-Job -ScriptBlock {
        param($acrN, $ca, $projectRoot)
        if ($ca) { $env:REQUESTS_CA_BUNDLE = $ca }
        $env:PYTHONUTF8 = "1"
        Set-Location $projectRoot
        az acr build -r $acrN -t notebooklm-api:latest -f api/Dockerfile . 2>&1
    } -ArgumentList $acrName, $tempBundle, $ProjectRoot

    # Attendre que le build ACR soit visible dans l'API (max 30s)
    $waited = 0
    do {
        Start-Sleep -Seconds 5
        $waited += 5
        $latestStatus = az acr task list-runs -r $acrName --top 1 --query '[0].status' -o tsv 2>$null
    } while ((-not $latestStatus -or $latestStatus -eq "") -and $waited -lt 30)

    # Poller le statut indépendamment du job (évite les problèmes d'encodage en console)
    Write-Info "Build en cours — polling du statut ACR toutes les 10s..."
    do {
        Start-Sleep -Seconds 10
        $latestStatus = az acr task list-runs -r $acrName --top 1 --query '[0].status' -o tsv 2>$null
        $runId        = az acr task list-runs -r $acrName --top 1 --query '[0].runId' -o tsv 2>$null
        Write-Info "  Build $runId : $latestStatus"
    } while ($latestStatus -eq "Running" -or $latestStatus -eq "Queued")

    # Récupérer la sortie du job (sans l'afficher pour éviter les chars Unicode)
    $null = Wait-Job $buildJob
    Remove-Job $buildJob -Force

    if ($latestStatus -ne "Succeeded") {
        Write-Fail "Build image echoue (statut ACR : $latestStatus). Consultez les logs : az acr task list-runs -r $acrName"
    }
    Write-OK "Image buildee et pushee : $imageTag"
}

# Arrêt si mode ImageOnly
if ($ImageOnly) {
    Write-Host ""
    Write-Host "  Mode -ImageOnly : arret apres le build image." -ForegroundColor Yellow
    Write-Host "  Image disponible : $imageTag" -ForegroundColor Green
    Write-Host ""
    exit 0
}

# ── PHASE 4 : Déploiement Bicep ───────────────────────────────────────────────
Write-Phase 4 8 "Infrastructure Azure (Bicep)"

# Création du Resource Group si nécessaire (idempotent)
$rgExists = (az group exists --name $rg) -eq 'true'
if ($rgExists) {
    Write-OK "Resource Group existant reutilise : $rg"
} else {
    az group create --name $rg --location $Location `
        --tags project=$ProjectName managed-by=bicep `
        --output none --only-show-errors 2>&1 | Out-Null
    Write-OK "Resource Group cree : $rg ($Location)"
}

# Déterminer si on déploie neo4j-legacykb en ACI
$deployLegacyKb  = $true
$neo4jPlainPwd   = ""
$neo4jUriParam   = ""

if ($Neo4jUri) {
    # URI fournie → on pointe sur l'instance existante, pas de déploiement ACI
    $deployLegacyKb = $false
    $neo4jUriParam  = $Neo4jUri
    Write-Info "Neo4j URI externe : $Neo4jUri"
    Write-Info "deployLegacyKb = false (pas de deploiement ACI)"

    # Le mot de passe est quand même stocké dans Key Vault pour que l'app puisse s'y connecter
    if ($null -eq $Neo4jPassword -or $Neo4jPassword.Length -eq 0) {
        Write-Host ""
        Write-Host "        Mot de passe du compte neo4j (pour stockage Key Vault) :" -ForegroundColor White
        $Neo4jPassword = Read-Host -AsSecureString "        Neo4j password"
    }
    $neo4jPlainPwd = ConvertFrom-SecureStringPlain $Neo4jPassword
} else {
    # Pas d'URI fournie → déploiement ACI neo4j-legacykb
    $deployLegacyKb = $true
    $neo4jUriParam  = ""

    if ($null -eq $Neo4jPassword -or $Neo4jPassword.Length -eq 0) {
        Write-Host ""
        Write-Host "        Mot de passe neo4j-legacykb (ACI) :" -ForegroundColor White
        $Neo4jPassword = Read-Host -AsSecureString "        Neo4j password"
    }
    $neo4jPlainPwd = ConvertFrom-SecureStringPlain $Neo4jPassword

    if ([string]::IsNullOrWhiteSpace($neo4jPlainPwd)) {
        Write-Fail "Le mot de passe neo4j-legacykb est obligatoire pour deployer l'ACI."
    }
    Write-Info "deployLegacyKb = true (deploiement ACI neo4j-legacykb)"
}

# Générer une API Key sécurisée (32 bytes → base64 URL-safe)
$apiKeyBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($apiKeyBytes)
$apiKey = [Convert]::ToBase64String($apiKeyBytes) -replace '[/+=]', ''

# Tag de l'image (si l'ACR n'existait pas encore, on utilise le placeholder)
$bicepImageTag = if ($buildImageAfterBicep) { "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" } else { $imageTag }

Write-Info "Deploiement Bicep en cours — environ 12 minutes..."
Write-Info "(OpenAI et Document Intelligence sont les plus lents a provisionner)"

$paramsFile = New-BicepParametersFile @{
    projectName           = $ProjectName
    environment           = $environment
    location              = $Location
    deployerObjectId      = $deployerObjectId
    apiImageTag           = $bicepImageTag
    deployLegacyKb        = $deployLegacyKb
    neo4jLegacyKbPassword = $neo4jPlainPwd
    neo4jLegacyKbUri      = $neo4jUriParam
    apiKey                = $apiKey
    alertEmail            = $AlertEmail
}
try {
    az deployment group create `
        --resource-group $rg `
        --template-file "$ProjectRoot\infra\main.bicep" `
        --name $deployName `
        --output none `
        --only-show-errors `
        --parameters "@$paramsFile" 2>&1
} finally {
    Remove-FileSafe $paramsFile
}

Write-OK "Deploiement Bicep termine"

# Récupérer tous les outputs en un seul appel
$rawOutputs = az deployment group show -g $rg -n $deployName `
    --query properties.outputs --output json 2>&1
$outputs = $rawOutputs | ConvertFrom-Json

# ── PHASE 4b : Certificat TLS Neo4j (auto-signé) ─────────────────────────────
# Neo4j démarre en boucle de redémarrage tant que /ssl/neo4j.key et /ssl/neo4j.crt
# sont absents. On génère le cert, on l'uploade dans le partage Azure Files,
# puis on redémarre l'ACI — Neo4j trouve le cert et démarre avec TLS activé.
if ($deployLegacyKb) {
    Write-Host ""
    Write-Host "  [4b/8] TLS Neo4j — génération et upload du certificat auto-signé" -ForegroundColor Cyan

    $neo4jFqdn    = $outputs.neo4jLegacyKbFqdn.value
    $sslStorage   = $outputs.neo4jLegacyKbStorageAccount.value
    $aciGroupName = "aci-neo4j-legacykb-$ProjectName-$environment"
    $tmpKey       = "$env:TEMP\neo4j.key"
    $tmpCert      = "$env:TEMP\neo4j.crt"
    $tmpScript    = "$env:TEMP\gen_neo4j_cert.py"

    # Script Python inline — génère RSA 2048 + cert auto-signé (validité 5 ans)
    @'
import sys, subprocess
try:
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'cryptography', '-q',
                           '--disable-pip-version-check'])
    from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
import datetime

fqdn, key_out, cert_out = sys.argv[1], sys.argv[2], sys.argv[3]
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, fqdn)])
cert = (x509.CertificateBuilder()
    .subject_name(subject).issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
    .add_extension(x509.SubjectAlternativeName([x509.DNSName(fqdn)]), critical=False)
    .sign(key, hashes.SHA256()))
open(key_out,  'wb').write(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption()))
open(cert_out, 'wb').write(cert.public_bytes(serialization.Encoding.PEM))
'@ | Set-Content -Path $tmpScript -Encoding UTF8

    python $tmpScript $neo4jFqdn $tmpKey $tmpCert
    Write-OK "Certificat auto-signé généré pour $neo4jFqdn"

    # Upload via clé de compte (première fois — le rôle RBAC File n'est pas encore propagé).
    $sslKey = az storage account keys list -g $rg -n $sslStorage --query '[0].value' -o tsv 2>&1

    # az storage file upload utilise le SDK data-plane (pas azure-cli-core) — il ignore
    # "core.verify_ssl=false" et a besoin de REQUESTS_CA_BUNDLE explicitement dans ce process
    # (même bundle Zscaler que celui injecté pour le job az acr build en Phase 3).
    $prevCaBundle = $env:REQUESTS_CA_BUNDLE
    if ($tempBundle) { $env:REQUESTS_CA_BUNDLE = $tempBundle }
    try {
        az storage file upload --share-name neo4j-ssl --account-name $sslStorage --account-key $sslKey `
            --source $tmpKey --path neo4j.key --no-progress --output none --only-show-errors 2>&1 | Out-Null
        az storage file upload --share-name neo4j-ssl --account-name $sslStorage --account-key $sslKey `
            --source $tmpCert --path neo4j.crt --no-progress --output none --only-show-errors 2>&1 | Out-Null
    } finally {
        $env:REQUESTS_CA_BUNDLE = $prevCaBundle
    }
    Write-OK "Certificats uploadés dans le partage Azure Files neo4j-ssl"

    # Nettoyer les fichiers temporaires
    Remove-FileSafe $tmpKey
    Remove-FileSafe $tmpCert
    Remove-FileSafe $tmpScript

    # Redémarrer l'ACI pour que Neo4j monte /ssl et démarre avec TLS
    Write-Info "Redémarrage de l'ACI neo4j-legacykb pour activer TLS..."
    az container restart --resource-group $rg --name $aciGroupName --output none --only-show-errors 2>&1 | Out-Null
    Write-OK "ACI $aciGroupName redémarré — Neo4j démarrera avec bolt+s:// et HTTPS"

    # ── PHASE 4c : Import du dump GraphML ────────────────────────────────────────
    Write-Host ""
    Write-Host "  [4c/8] Import GraphML — peuplement de neo4j-legacykb" -ForegroundColor Cyan
    $neo4jSecurePwd = ConvertTo-SecureString $neo4jPlainPwd -AsPlainText -Force
    & "$ProjectRoot\import-neo4j-legacykb.ps1" -ResourceGroup $rg -ProjectName $ProjectName -Environment $environment `
        -Neo4jPassword $neo4jSecurePwd -SkipSSL:$SkipSSL
}

# Si l'ACR vient d'être créé par Bicep, builder l'image maintenant
if ($buildImageAfterBicep) {
    Write-Info "ACR cree par Bicep — lancement du build image..."

    $buildJob = Start-Job -ScriptBlock {
        param($acrN, $ca, $projectRoot)
        if ($ca) { $env:REQUESTS_CA_BUNDLE = $ca }
        $env:PYTHONUTF8 = "1"
        Set-Location $projectRoot
        az acr build -r $acrN -t notebooklm-api:latest -f api/Dockerfile . 2>&1
    } -ArgumentList $acrName, $tempBundle, $ProjectRoot

    # Attendre que le build soit visible
    $waited = 0
    do {
        Start-Sleep -Seconds 5
        $waited += 5
        $latestStatus = az acr task list-runs -r $acrName --top 1 --query '[0].status' -o tsv 2>$null
    } while ((-not $latestStatus -or $latestStatus -eq "") -and $waited -lt 30)

    Write-Info "Build image en cours (post-Bicep) — polling toutes les 10s..."
    do {
        Start-Sleep -Seconds 10
        $latestStatus = az acr task list-runs -r $acrName --top 1 --query '[0].status' -o tsv 2>$null
        $runId        = az acr task list-runs -r $acrName --top 1 --query '[0].runId' -o tsv 2>$null
        Write-Info "  Build $runId : $latestStatus"
    } while ($latestStatus -eq "Running" -or $latestStatus -eq "Queued")

    $null = Wait-Job $buildJob
    Remove-Job $buildJob -Force

    if ($latestStatus -ne "Succeeded") {
        Write-Fail "Build image echoue (statut ACR : $latestStatus)."
    }
    Write-OK "Image buildee et pushee : $imageTag"

    # Mettre à jour le Container App avec la vraie image (second déploiement Bicep, rapide)
    Write-Info "Mise a jour du Container App avec la vraie image..."
    $paramsFileImg = New-BicepParametersFile @{
        projectName           = $ProjectName
        environment           = $environment
        location              = $Location
        deployerObjectId      = $deployerObjectId
        apiImageTag           = $imageTag
        deployLegacyKb        = $deployLegacyKb
        neo4jLegacyKbPassword = $neo4jPlainPwd
        neo4jLegacyKbUri      = $neo4jUriParam
        apiKey                = $apiKey
        alertEmail            = $AlertEmail
    }
    try {
        az deployment group create `
            --resource-group $rg `
            --template-file "$ProjectRoot\infra\main.bicep" `
            --name "deploy-$(Get-Date -Format 'yyyyMMddHHmm')-img" `
            --output none `
            --only-show-errors `
            --parameters "@$paramsFileImg" 2>&1
    } finally {
        Remove-FileSafe $paramsFileImg
    }
    Write-OK "Container App mis a jour avec l'image $imageTag"
}

# ── PHASE 5 : Génération .env ─────────────────────────────────────────────────
Write-Phase 5 8 "Generation du fichier .env"

$envFile = Join-Path $ProjectRoot ".env"
if ((Test-Path $envFile) -and -not $Force) {
    $overwrite = Read-Host "        .env existant detecte. Ecraser ? (o/N)"
    if ($overwrite -ne 'o') {
        Write-Fail "Annule. Relancez avec -Force pour ecraser automatiquement."
    }
}

# Récupérer l'URI neo4j depuis les outputs Bicep si on a déployé l'ACI
$neo4jUriEnv = ""
if ($deployLegacyKb) {
    $neo4jUriEnv = $outputs.neo4jLegacyKbUri.value
} else {
    $neo4jUriEnv = $Neo4jUri
}

$envContent = @"
# Genere automatiquement par deploy.ps1 le $(Get-Date -Format 'yyyy-MM-dd HH:mm')
# NE PAS COMMITTER CE FICHIER -- il contient des secrets

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=$($outputs.openAIEndpoint.value)
AZURE_OPENAI_GPT4O_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_INVENTAIRE_DEPLOYMENT=gpt-4o

# Azure AI Search
AZURE_SEARCH_ENDPOINT=$($outputs.searchEndpoint.value)

# Azure Document Intelligence
AZURE_DOCINT_ENDPOINT=$($outputs.docIntEndpoint.value)

# Azure Blob Storage
AZURE_STORAGE_ACCOUNT_NAME=$($outputs.storageAccountName.value)

# Azure Key Vault (pour la production -- le Container App lit la config via ses variables d'env)
# AZURE_KEYVAULT_URI=https://$($outputs.keyVaultName.value).vault.azure.net/

# Neo4j Legacy KB (golden source GraphRAG)
NEO4J_LEGACYKB_URI=$neo4jUriEnv
NEO4J_LEGACYKB_PASSWORD=***

# Authentification API (genere aleatoirement -- utilise aussi bien en local qu'en prod)
API_KEY=$apiKey

# URL de l'API deployee (utilisee par mcp-legacykb pour passer par l'API HTTPS
# plutot que par une connexion Bolt directe -- Zscaler casse l'inspection SSL
# sur le port Bolt 7687, non-HTTP, alors que les appels HTTPS standard passent)
NOTEBOOKLM_API_URL=$($outputs.apiUrl.value)
"@

[System.IO.File]::WriteAllText($envFile, $envContent, [System.Text.Encoding]::UTF8)
Write-OK ".env genere (API_KEY aleatoire incluse)"
Write-Info "NEO4J_LEGACYKB_PASSWORD est masque dans le .env — a renseigner manuellement si necessaire"
Write-Warn "Ne jamais committer le fichier .env"

# ── PHASE 6 : Rôles IAM ───────────────────────────────────────────────────────
Write-Phase 6 8 "Assignation des roles IAM (parallel)"

$scope = "/subscriptions/$subscriptionId/resourceGroups/$rg"

# Rôles pour l'identité du déployeur (accès local dev)
$devRoles = @(
    "Cognitive Services OpenAI User",
    "Search Index Data Contributor",
    "Cognitive Services User",
    "Storage Blob Data Contributor"
)

# Rôle pour l'UAMI du Container App (Key Vault Secrets User)
$uamiName = "id-api-$ProjectName-$environment"

Write-Info "Assignation des roles pour le deployer ($deployerObjectId)..."
$roleJobs = foreach ($role in $devRoles) {
    Start-Job -ScriptBlock {
        az role assignment create `
            --assignee $using:deployerObjectId `
            --role $using:role `
            --scope $using:scope `
            --only-show-errors 2>&1 | Out-Null
    }
}

# Récupérer l'ID de l'UAMI pour Key Vault Secrets User
Write-Info "Assignation Key Vault Secrets User pour l'UAMI du Container App..."
$uamiJob = Start-Job -ScriptBlock {
    $uamiId = az identity show -n $using:uamiName -g $using:rg --query principalId -o tsv 2>$null
    if ($uamiId) {
        az role assignment create `
            --assignee $uamiId `
            --role "Key Vault Secrets User" `
            --scope $using:scope `
            --only-show-errors 2>&1 | Out-Null
    }
}

($roleJobs + $uamiJob) | Wait-Job | Out-Null
($roleJobs + $uamiJob) | Remove-Job -Force

Write-OK "Roles IAM assignes :"
foreach ($role in $devRoles) { Write-Info "  - $role (deployer)" }
Write-Info "  - Key Vault Secrets User (UAMI Container App)"
Write-Warn "Propagation IAM : attendez 3-5 min avant d'indexer des documents"

# ── PHASE 7 : Virtualenv Python ───────────────────────────────────────────────
Write-Phase 7 8 "Environnement Python"

$venvPath  = Join-Path $ProjectRoot "api\.venv"
$pipExe    = Join-Path $venvPath "Scripts\pip.exe"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPath)) {
    python -m venv $venvPath 2>&1 | Out-Null
    Write-OK "Virtualenv cree : api\.venv"
} else {
    Write-OK "Virtualenv existant reutilise"
}

# Flags pip selon mode SSL
$pipArgs = @(
    "install",
    "-r", "$ProjectRoot\api\requirements.txt",
    "-r", "$ProjectRoot\ingest\requirements.txt",
    "--quiet"
)
if ($SkipSSL) {
    $pipArgs += @(
        "--trusted-host", "pypi.org",
        "--trusted-host", "files.pythonhosted.org",
        "--trusted-host", "pypi.python.org"
    )
}

Write-Info "Installation des dependances Python (api + ingest)..."
& $pipExe @pipArgs
Write-OK "Dependances installees"

# Injection du certificat Zscaler dans le bundle certifi du venv si -SkipSSL
if ($SkipSSL) {
    Write-Info "Injection des certificats Zscaler dans certifi du venv..."
    $zscalerCerts = @(Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -match "Zscaler" })

    if ($zscalerCerts.Count -gt 0) {
        $venvCertifi = & $pythonExe -c "import certifi; print(certifi.where())" 2>&1
        foreach ($cert in $zscalerCerts) {
            $pem = "-----BEGIN CERTIFICATE-----`n" +
                   [Convert]::ToBase64String($cert.Export('Cert'), 'InsertLineBreaks') +
                   "`n-----END CERTIFICATE-----`n"
            Add-Content -Path $venvCertifi -Value $pem -Encoding ascii
        }
        Write-OK "$($zscalerCerts.Count) certificat(s) Zscaler injecte(s) dans certifi venv"
        Write-Info "Path : $venvCertifi"
    } else {
        Write-Warn "Aucun certificat Zscaler trouve -- a injecter manuellement si besoin"
    }
}

# ── PHASE 8 : Validation post-déploiement ─────────────────────────────────────
Write-Phase 8 8 "Validation post-deploiement"

$apiUrl = $outputs.apiUrl.value
# Assurer que l'URL commence par https://
if (-not $apiUrl.StartsWith("http")) {
    $apiUrl = "https://$apiUrl"
}

Write-Info "URL Container App : $apiUrl"
Write-Info "Attente de disponibilite du Container App (5 tentatives x 20s)..."

$ready   = $false
$attempt = 0
do {
    $attempt++
    Start-Sleep -Seconds 20
    Write-Info "  Tentative $attempt/5 — GET $apiUrl/health"
    try {
        $resp = Invoke-WebRequest -Uri "$apiUrl/health" -TimeoutSec 15 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            Write-OK "Health check OK (HTTP $($resp.StatusCode))"
        } else {
            Write-Info "  HTTP $($resp.StatusCode) — pas encore pret"
        }
    } catch {
        Write-Info "  Pas de reponse — le Container App demarre peut-etre encore"
    }
} while (-not $ready -and $attempt -lt 5)

if ($ready) {
    # Tester /api/legacykb/health avec l'API Key
    Write-Info "Test du endpoint legacykb..."
    try {
        $headers = @{ "X-API-Key" = $apiKey }
        $resp2 = Invoke-WebRequest -Uri "$apiUrl/api/legacykb/health" -Headers $headers `
                     -TimeoutSec 15 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($resp2.StatusCode -eq 200) {
            Write-OK "Legacy KB health check OK"
        } else {
            Write-Warn "Legacy KB health check : HTTP $($resp2.StatusCode) (peut etre normal si neo4j demarre)"
        }
    } catch {
        Write-Warn "Legacy KB health check inaccessible -- neo4j-legacykb est peut-etre encore en demarrage"
    }
} else {
    Write-Warn "Le Container App n'a pas repondu apres 5 tentatives."
    Write-Info "Il peut encore demarrer -- attendez 2-3 min et testez $apiUrl/health manuellement."
}

# ── Résumé final ──────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host "  |        Deploiement termine !             |" -ForegroundColor Green
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host ""
Write-Host "  Ressources Azure crees :" -ForegroundColor White
Write-Host "  Resource Group   : $rg" -ForegroundColor DarkGray
Write-Host "  ACR              : $acrName" -ForegroundColor DarkGray
Write-Host "  Image            : $imageTag" -ForegroundColor DarkGray
Write-Host "  URL production   : $apiUrl" -ForegroundColor DarkGray
if ($neo4jUriEnv) {
    Write-Host "  Neo4j Legacy KB  : $neo4jUriEnv" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  API Key generee : *** (voir .env)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Prochaines etapes :" -ForegroundColor White
Write-Host "  1. Renseignez NEO4J_LEGACYKB_PASSWORD dans .env (si necessaire)" -ForegroundColor DarkGray
Write-Host "  2. Attendez 3-5 min (propagation des roles IAM)" -ForegroundColor DarkGray
Write-Host "  3. Lancez le serveur de dev local :" -ForegroundColor DarkGray
Write-Host "     .\start-dev.ps1" -ForegroundColor Cyan
Write-Host "  4. Ajoutez vos documents via le rail gauche" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Pour supprimer toutes les ressources : .\teardown.ps1" -ForegroundColor Yellow
Write-Host ""
