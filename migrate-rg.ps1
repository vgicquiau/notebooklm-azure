#Requires -Version 5.1
<#
.SYNOPSIS
    Migre les ressources Azure de NotebookLM Azure vers un nouveau Resource Group / subscription.

.DESCRIPTION
    Conçu pour les politiques d'entreprise imposant une durée de vie limitée aux Resource Groups.
    Plutôt que de tout reconstruire (et de ré-indexer/ré-importer les données), ce script déplace
    nativement (ARM "resource move") les ressources qui le supportent — opération de métadonnées
    qui préserve les données (index Azure AI Search, images ACR, secrets Key Vault, blobs) et les
    endpoints (aucun changement de DNS) — et ne recrée que les ressources qui ne supportent pas le
    déplacement ARM : le Container App et son Managed Environment (avec une UAMI fraîche,
    recréés en redéployant le module containerapp.bicep) et le conteneur ACI neo4j-legacykb
    (dont le graphe vit en mémoire éphémère et doit de toute façon être ré-importé depuis le
    dump GraphML versionné).

    Phases :
      0. Prérequis + authentification (subscription source ET cible, même tenant Entra)
      1. Pré-vol — enregistrement des Resource Providers manquants + validation ARM à blanc
         (validateMoveResources) avant toute action destructive
      2. Déplacement groupé des ressources déplaçables (un seul appel ARM atomique)
      3. Reconstruction en parallèle du Container App + UAMI + rôles IAM (thread principal) et
         de la stack neo4j-legacykb (job d'arrière-plan : redéploiement Bicep + certificat TLS +
         import GraphML + correctif UTF-8)
      4. Réconciliation — mise à jour NEO4J_LEGACYKB_URI sur le Container App, régénération du
         .env local
      5. Validation post-migration (health checks /health et /api/legacykb/health)
      6. Résumé — affiche la commande de suppression de l'ancien RG, ne l'exécute JAMAIS

    Important : les attributions de rôle RBAC scopées sur une ressource ne survivent PAS à un
    "resource move" (documenté par Microsoft) — ce script les recrée systématiquement après coup,
    pour l'UAMI du Container App ET pour l'identité du développeur courant (az login), afin que
    l'ingestion locale continue de fonctionner sans intervention manuelle.

.PARAMETER SourceResourceGroup
    Resource Group actuel contenant les ressources NotebookLM Azure.

.PARAMETER SourceSubscription
    ID ou nom de la subscription source. Si omis, utilise la subscription actuellement active.

.PARAMETER DestResourceGroup
    Resource Group cible (créé automatiquement s'il n'existe pas).

.PARAMETER DestSubscription
    ID ou nom de la subscription cible (obligatoire — doit appartenir au même tenant Entra que
    la subscription source).

.PARAMETER ProjectName
    Préfixe des ressources Azure (3-8 caractères, minuscules). Doit correspondre à celui utilisé
    lors du déploiement initial (deploy.ps1). Défaut : nlmazure.

.PARAMETER Environment
    Suffixe d'environnement utilisé lors du déploiement initial. Défaut : prod.

.PARAMETER Neo4jPassword
    Nouveau mot de passe du compte neo4j pour le conteneur ACI recréé. Demandé interactivement
    si absent.

.PARAMETER AlertEmail
    Email pour les alertes Azure Monitor du conteneur neo4j-legacykb recréé. Vide = désactivées.

.PARAMETER SkipSSL
    Bypass SSL pour proxy d'entreprise (Zscaler, Forcepoint, etc.) — même mécanisme que deploy.ps1.

.PARAMETER Force
    Pas de prompt de confirmation avant le déplacement réel (Phase 2).

.PARAMETER ExcludeResourceNames
    Noms de ressources à exclure explicitement du déplacement (ex. résidus d'un déploiement
    antérieur avec un nommage incorrect — laissés dans l'ancien RG, supprimés avec lui en
    Phase 6). Comparaison exacte sur le nom de la ressource.

.EXAMPLE
    .\migrate-rg.ps1 -SourceResourceGroup rg-nlmazure-prod -DestResourceGroup rg-nlmazure-prod-v2 `
        -DestSubscription "Nouvelle Subscription"

.EXAMPLE
    # Avec proxy d'entreprise, sans prompt de confirmation
    .\migrate-rg.ps1 -SourceResourceGroup rg-sp4-d-vgi-azu-vgi-sandbox-txt `
        -DestResourceGroup rg-sp4-d-vgi-azu-vgi-sandbox2-txt -DestSubscription "Sandbox 2" `
        -ProjectName nlmavgi -SkipSSL -Force
#>
param(
    [Parameter(Mandatory)] [string]$SourceResourceGroup,
    [string]$SourceSubscription = "",
    [Parameter(Mandatory)] [string]$DestResourceGroup,
    [Parameter(Mandatory)] [string]$DestSubscription,
    [string]$ProjectName = "nlmazure",
    [string]$Environment = "prod",
    [SecureString]$Neo4jPassword,
    [string]$AlertEmail = "",
    [string[]]$ExcludeResourceNames = @(),
    [switch]$SkipSSL,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

$suffix = "$ProjectName-$Environment"

# ── Helpers affichage (mêmes conventions que deploy.ps1/teardown.ps1) ───────────
function Write-Banner {
    Write-Host ""
    Write-Host "  +==========================================+" -ForegroundColor Cyan
    Write-Host "  |   NotebookLM Azure  --  Migration RG    |" -ForegroundColor Cyan
    Write-Host "  +==========================================+" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Source : $SourceResourceGroup" -ForegroundColor DarkGray
    Write-Host "  Cible  : $DestResourceGroup ($DestSubscription)" -ForegroundColor DarkGray
    Write-Host "  Projet : $ProjectName ($Environment)" -ForegroundColor DarkGray
    if ($SkipSSL) {
        Write-Host "  Mode SSL : bypass active (proxy entreprise)" -ForegroundColor Yellow
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
function ConvertFrom-SecureStringPlain([SecureString]$sec) {
    if ($null -eq $sec) { return "" }
    $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($ptr) }
    finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
function Remove-FileSafe([string]$Path) {
    # Remove-Item echoue sur les comptes Windows dont le nom contient un point (ex.
    # "v.gicquiau" -> %TEMP% en 8.3 short-name "V5C98~1.GIC") avec une PSArgumentException
    # qui bypass -ErrorAction. [System.IO.File]::Delete() contourne le provider PowerShell.
    try { [System.IO.File]::Delete($Path) } catch {}
}

Write-Banner

# ── PHASE 0 : Prérequis + authentification ───────────────────────────────────
Write-Phase 0 6 "Prerequis et authentification (subscriptions source + cible)"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Fail "Azure CLI (az) introuvable. Installez-le : https://aka.ms/installazurecliwindows"
}

$tempBundle = $null
if ($SkipSSL) {
    az config set core.verify_ssl=false --only-show-errors 2>&1 | Out-Null
    Write-OK "SSL verification desactivee (az CLI)"

    # Meme mecanisme que deploy.ps1 Phase 1 : bundle certifi temporaire avec les
    # certificats Zscaler du store Windows, transmis a la Branche B (job) pour que
    # son appel pip install + ses appels az fonctionnent derriere le proxy.
    $certifiBundle = "C:\Program Files\Microsoft SDKs\Azure\CLI2\Lib\site-packages\certifi\cacert.pem"
    if (Test-Path $certifiBundle) {
        $tempBundle = "$env:TEMP\migrate_rg_cacert_zscaler.pem"
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
        } else {
            Write-Warn "Aucun certificat Zscaler trouve dans le store Windows"
        }
    } else {
        Write-Warn "Bundle certifi az CLI introuvable : $certifiBundle"
    }
}

$account = $null
try { $account = az account show 2>$null | ConvertFrom-Json } catch {}
if (-not $account) {
    Write-Info "Ouverture du navigateur pour az login..."
    az login --only-show-errors | Out-Null
}

if ($SourceSubscription) {
    az account set --subscription $SourceSubscription --only-show-errors
}
$srcAccount = az account show --only-show-errors 2>&1 | ConvertFrom-Json
$srcSubId   = $srcAccount.id
$tenantId   = $srcAccount.tenantId
Write-OK "Subscription source : $($srcAccount.name) ($srcSubId)"

$destAccountRaw = az account show --subscription $DestSubscription --only-show-errors 2>&1
$destAccount    = $destAccountRaw | ConvertFrom-Json
if (-not $destAccount) {
    Write-Fail "Subscription cible '$DestSubscription' inaccessible. Verifiez le nom/ID et vos droits."
}
if ($destAccount.tenantId -ne $tenantId) {
    Write-Fail "La subscription cible appartient a un tenant Entra different (move cross-tenant non supporte par ARM)."
}
$destSubId = $destAccount.id
Write-OK "Subscription cible  : $($destAccount.name) ($destSubId)"

$deployerObjectId = az ad signed-in-user show --query id -o tsv 2>&1
Write-Info "Deployer Object ID  : $deployerObjectId"

# ── PHASE 1 : Pré-vol ─────────────────────────────────────────────────────────
Write-Phase 1 6 "Pre-vol -- Resource Providers + inventaire + validation ARM"

az account set --subscription $srcSubId --only-show-errors

$rgInfo = az group show --name $SourceResourceGroup --only-show-errors 2>&1 | ConvertFrom-Json
if (-not $rgInfo) {
    Write-Fail "Resource Group source '$SourceResourceGroup' introuvable dans la subscription source."
}
$Location = $rgInfo.location
Write-OK "Resource Group source trouve -- region : $Location"

$destExists = (az group exists --name $DestResourceGroup --subscription $destSubId) -eq 'true'
if ($destExists) {
    $destRgInfo = az group show --name $DestResourceGroup --subscription $destSubId --only-show-errors 2>&1 | ConvertFrom-Json
    if ($destRgInfo.location -ne $Location) {
        Write-Fail "Le RG cible existe deja dans une region differente ($($destRgInfo.location) != $Location). Un move ARM exige la meme region -- ce script ne gere pas le changement de region (cf. etude de faisabilite)."
    }
    Write-OK "Resource Group cible existant reutilise : $DestResourceGroup"
} else {
    az group create --name $DestResourceGroup --location $Location --subscription $destSubId `
        --tags project=$ProjectName managed-by=bicep --output none --only-show-errors 2>&1 | Out-Null
    Write-OK "Resource Group cible cree : $DestResourceGroup ($Location)"
}

# Resource Providers requis -- enregistrement en parallele sur la subscription cible
$requiredProviders = @(
    'Microsoft.CognitiveServices', 'Microsoft.Search', 'Microsoft.KeyVault',
    'Microsoft.ContainerRegistry', 'Microsoft.Storage', 'Microsoft.Web',
    'Microsoft.Insights', 'Microsoft.ManagedIdentity', 'Microsoft.ContainerInstance'
)
Write-Info "Verification/enregistrement des Resource Providers sur la subscription cible (parallel)..."
$rpJobs = foreach ($rp in $requiredProviders) {
    Start-Job -ScriptBlock {
        param($provider, $sub)
        $state = az provider show --namespace $provider --subscription $sub --query registrationState -o tsv 2>$null
        if ($state -ne 'Registered') {
            az provider register --namespace $provider --subscription $sub --only-show-errors 2>&1 | Out-Null
        }
    } -ArgumentList $rp, $destSubId
}
$rpJobs | Wait-Job | Out-Null
$rpJobs | Remove-Job -Force
Write-OK "Resource Providers verifies/enregistres ($($requiredProviders.Count))"
Write-Info "(l'enregistrement peut prendre quelques minutes en arriere-plan cote Azure -- le move attendra si besoin)"

# Inventaire des ressources deplacables (exclut explicitement l'UAMI, le Container App /
# Managed Environment, et la stack ACI neo4j -- aucun de ces types ne supporte le move ARM ;
# voir tableau de l'etude de faisabilite). Le Container App et son Managed Environment sont
# recrees en Phase 3 (redeploiement du module containerapp.bicep), pas deplaces.
$movableTypes = @(
    'Microsoft.CognitiveServices/accounts',
    'Microsoft.Search/searchServices',
    'Microsoft.KeyVault/vaults',
    'Microsoft.ContainerRegistry/registries',
    'Microsoft.Storage/storageAccounts',
    'Microsoft.Insights/components'
)
$allResources = az resource list --resource-group $SourceResourceGroup --subscription $srcSubId `
    --output json --only-show-errors 2>&1 | ConvertFrom-Json

# Le(s) storage account(s) dedies a l'ACI neo4j-legacykb existant sont decouverts dynamiquement
# (via les volumes Azure Files reellement montes) plutot que devines par un motif de nommage --
# l'environnement reel peut suivre une convention plus ancienne que celle des templates Bicep
# actuels (ex. observe en pratique : "stneo4jimportvgi" au lieu de "stneo4jkb<suffix>").
# Filtrage cote PowerShell (Where-Object) plutot que --query JMESPath : une chaine --query
# avec des crochets pres du guillemet fermant casse le relais az.cmd -> python.exe sur
# certains postes (cf. import-neo4j-legacykb.ps1) ; "properties.volumes" suppose aussi un
# wrapper "properties" qui n'existe pas dans la sortie de toutes les versions d'az CLI
# (la forme aplatie expose "volumes" directement a la racine).
$existingNeo4jAci = $allResources | Where-Object { $_.type -eq 'Microsoft.ContainerInstance/containerGroups' } | Select-Object -First 1
$neo4jStorageNames = @()
if ($existingNeo4jAci) {
    # "az container show" ne supporte pas --ids de facon fiable -- on passe -g/-n explicitement.
    $aciDetail = az container show --resource-group $SourceResourceGroup --subscription $srcSubId `
        --name $existingNeo4jAci.name -o json --only-show-errors 2>&1 | ConvertFrom-Json
    $volumes = if ($aciDetail.volumes) { $aciDetail.volumes } else { $aciDetail.properties.volumes }
    $neo4jStorageNames = @($volumes | ForEach-Object { $_.azureFile.storageAccountName } | Where-Object { $_ } | Select-Object -Unique)
    if ($neo4jStorageNames.Count -eq 0) {
        Write-Warn "Aucun storage account detecte dynamiquement pour l'ACI '$($existingNeo4jAci.name)' -- verifiez manuellement la liste 'Ressources a deplacer' ci-dessous avant de confirmer."
    } else {
        Write-Info "ACI neo4j existant : $($existingNeo4jAci.name) -- storage(s) associe(s) exclu(s) du move : $($neo4jStorageNames -join ', ')"
    }
}

$toMove = $allResources | Where-Object {
    ($movableTypes -contains $_.type) -and ($neo4jStorageNames -notcontains $_.name) `
        -and ($ExcludeResourceNames -notcontains $_.name)
}

if ($toMove.Count -eq 0) {
    Write-Fail "Aucune ressource deplacable trouvee dans '$SourceResourceGroup'. Verifiez -ProjectName/-Environment."
}

# Garde-fou : si aucune ressource ne correspond au nom calcule depuis -ProjectName/-Environment,
# les phases suivantes (UAMI, roles, neo4j, .env) cibleraient des noms inexistants. On le detecte
# ici plutot que d'echouer profondement en Phase 3/4. Le Container App n'etant pas deplace
# (recree en Phase 3), on verifie plutot la presence de l'ACR -- toujours deplacable et
# toujours present puisque deploy.ps1 le cree systematiquement.
$expectedRegistry = "acr$(($suffix -replace '-', ''))"
if (-not ($toMove | Where-Object { $_.type -eq 'Microsoft.ContainerRegistry/registries' -and $_.name -eq $expectedRegistry })) {
    $foundRegistries = ($toMove | Where-Object { $_.type -eq 'Microsoft.ContainerRegistry/registries' } | ForEach-Object { $_.name }) -join ', '
    Write-Fail "Aucun Container Registry nomme '$expectedRegistry' (suffix calcule depuis -ProjectName='$ProjectName' -Environment='$Environment'). Registre(s) trouve(s) dans le RG : $foundRegistries. Corrigez -ProjectName/-Environment et relancez."
}

Write-Info "Ressources a deplacer ($($toMove.Count)) :"
foreach ($r in $toMove) { Write-Info "  - $($r.type) : $($r.name)" }

$skipped = $allResources | Where-Object {
    ($movableTypes -notcontains $_.type) -or ($neo4jStorageNames -contains $_.name) `
        -or ($ExcludeResourceNames -contains $_.name)
}
if ($skipped.Count -gt 0) {
    Write-Info "Ressources non deplacees (recreees en Phase 3 ou laissees dans l'ancien RG) :"
    foreach ($r in $skipped) { Write-Info "  - $($r.type) : $($r.name)" }
}

# Signalement (non bloquant) de ressources surnumeraires par rapport a ce qu'attend l'architecture
# de reference (1 compte OpenAI + 1 Document Intelligence) -- ex. observe en pratique : un compte
# "oai-...-prd" residuel a cote de "oai-...-prod". A vous de decider s'il doit etre deplace ou non.
$cogAccounts = $toMove | Where-Object { $_.type -eq 'Microsoft.CognitiveServices/accounts' }
if ($cogAccounts.Count -gt 2) {
    Write-Warn "Plus de 2 comptes Cognitive Services trouves -- verifiez qu'il ne s'agit pas d'un residu d'un deploiement anterieur :"
    foreach ($r in $cogAccounts) { Write-Warn "  - $($r.name)" }
}

$destRgId = "/subscriptions/$destSubId/resourceGroups/$DestResourceGroup"
$validateBody = @{
    resources         = @($toMove | ForEach-Object { $_.id })
    targetResourceGroup = $destRgId
} | ConvertTo-Json -Depth 5 -Compress

$tmpValidateBody = "$env:TEMP\migrate-rg-validate-$([guid]::NewGuid()).json"
[System.IO.File]::WriteAllText($tmpValidateBody, $validateBody, [System.Text.Encoding]::UTF8)

Write-Info "Validation ARM a blanc (validateMoveResources) -- aucun effet de bord..."
$validateResult = az rest --method post `
    --url "https://management.azure.com/subscriptions/$srcSubId/resourceGroups/$SourceResourceGroup/validateMoveResources?api-version=2021-04-01" `
    --body "@$tmpValidateBody" --headers "Content-Type=application/json" --only-show-errors 2>&1
$validateExitCode = $LASTEXITCODE
Remove-FileSafe $tmpValidateBody

if ($validateExitCode -ne 0) {
    Write-Fail "Validation ARM du move echouee -- corrigez avant de relancer :`n$validateResult"
}
Write-OK "Validation ARM reussie -- le move est autorise (locks, policy, quotas OK)"

if (-not $Force) {
    Write-Host ""
    Write-Host "  Pret a deplacer $($toMove.Count) ressource(s) de '$SourceResourceGroup' vers '$DestResourceGroup'." -ForegroundColor White
    $confirm = Read-Host "  Tapez 'MIGRER' pour confirmer (ou Entree pour annuler)"
    if ($confirm -ne 'MIGRER') {
        Write-Host "  Annule." -ForegroundColor Green
        exit 0
    }
}

# ── PHASE 2 : Déplacement groupé ──────────────────────────────────────────────
Write-Phase 2 6 "Deplacement groupe (az resource move -- operation ARM atomique)"

az account set --subscription $srcSubId --only-show-errors

$moveIds = @($toMove | ForEach-Object { $_.id })

# $ErrorActionPreference = "Stop" (global) transformerait la sortie stderr d'az, capturee via
# 2>&1, en exception terminante AVANT meme que l'affectation se termine -- on le neutralise
# temporairement pour pouvoir inspecter nous-memes le code de sortie et le detail de l'erreur.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$moveOutput = az resource move --ids $moveIds `
    --destination-group $DestResourceGroup --destination-subscription-id $destSubId `
    --only-show-errors 2>&1
$moveExitCode = $LASTEXITCODE
$ErrorActionPreference = $prevEAP

if ($moveExitCode -ne 0) {
    # validateMoveResources (Phase 1) ne couvre pas systematiquement toutes les policies
    # appliquees au moment du move reel (limitation documentee) -- on relance avec --debug
    # pour extraire le detail (souvent absent du message d'erreur compact par defaut).
    Write-Warn "Move ARM echoue -- $moveOutput"
    Write-Info "Nouvelle tentative avec --debug pour identifier la ressource/policy bloquante..."
    $ErrorActionPreference = 'Continue'
    $debugOutput = az resource move --ids $moveIds `
        --destination-group $DestResourceGroup --destination-subscription-id $destSubId `
        --debug 2>&1
    $ErrorActionPreference = $prevEAP
    $policyLines = $debugOutput | Select-String -Pattern 'policy|additionalInfo|Responsible AI|not allowed|disallowed' -SimpleMatch:$false
    if ($policyLines) {
        Write-Host ""
        Write-Host "  Detail extrait (--debug) :" -ForegroundColor Yellow
        $policyLines | Select-Object -Last 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkYellow }
    } else {
        Write-Warn "Aucune ligne policy/additionalInfo trouvee dans --debug -- sortie brute (dernieres 25 lignes) :"
        $debugOutput | Select-Object -Last 25 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    Write-Fail "Move ARM bloque par une policy -- aucune ressource n'a ete deplacee (operation atomique). Causes frequentes : compte Azure OpenAI/Cognitive Services soumis a une validation Responsible AI specifique a la subscription cible, ou policy de gouvernance sur la subscription sandbox. Pour isoler le coupable sans rien deplacer pour de vrai, relancez avec -ExcludeResourceNames incluant TOUS les comptes Cognitive Services (oai-$suffix,di-$suffix) -- si le reste passe, le blocage vient bien de ces comptes."
}

Write-OK "Move ARM termine -- $($toMove.Count) ressource(s) deplacee(s) (endpoints/DNS inchanges)"

# A partir d'ici, plus aucune action ne touche la subscription source -- on bascule
# le contexte CLI une seule fois pour eviter toute course entre le thread principal
# (Branche A) et le job d'arriere-plan (Branche B) qui partagent le meme profil az CLI.
az account set --subscription $destSubId --only-show-errors

# ── PHASE 3 : Reconstruction parallèle ────────────────────────────────────────
Write-Phase 3 6 "Reconstruction -- UAMI + roles IAM (thread principal) // stack neo4j (job)"

if ($null -eq $Neo4jPassword -or $Neo4jPassword.Length -eq 0) {
    Write-Host ""
    Write-Host "        Nouveau mot de passe neo4j-legacykb (conteneur recree) :" -ForegroundColor White
    $Neo4jPassword = Read-Host -AsSecureString "        Neo4j password"
}
$neo4jPlainPwd = ConvertFrom-SecureStringPlain $Neo4jPassword
if ([string]::IsNullOrWhiteSpace($neo4jPlainPwd)) {
    Write-Fail "Le mot de passe neo4j-legacykb est obligatoire."
}

# Branche B (lente : ~5 min) -- redeploiement Bicep autonome du module neo4j-legacykb,
# certificat TLS auto-signe, import GraphML, correctif UTF-8, mise a jour KV + appSetting.
$tagsJson = "{`"project`":`"$ProjectName`",`"environment`":`"$Environment`",`"managedBy`":`"bicep`"}"

$branchBJob = Start-Job -ScriptBlock {
    param($projectRoot, $destRg, $destSub, $suffix, $location, $tagsJson, $neo4jPwd, $alertEmail, $caBundle)

    if ($caBundle) { $env:REQUESTS_CA_BUNDLE = $caBundle }
    Set-Location $projectRoot
    $deployName = "migrate-neo4j-$(Get-Date -Format 'yyyyMMddHHmmss')"

    az deployment group create --resource-group $destRg --subscription $destSub `
        --template-file "$projectRoot\infra\modules\neo4j-legacykb.bicep" `
        --name $deployName --output none --only-show-errors `
        --parameters suffix=$suffix location=$location tags=$tagsJson `
            neo4jPassword=$neo4jPwd alertEmail=$alertEmail 2>&1

    $outputs = az deployment group show -g $destRg --subscription $destSub -n $deployName `
        --query properties.outputs --output json 2>&1 | ConvertFrom-Json

    $fqdn               = $outputs.fqdn.value
    $storageAccountName = $outputs.storageAccountName.value
    $shareName          = $outputs.shareName.value
    $aciGroup           = "aci-neo4j-legacykb-$suffix"

    # Certificat TLS auto-signe (Neo4j boucle en restart tant qu'il est absent -- meme
    # mecanisme que deploy.ps1 Phase 4b)
    $tmpKey    = "$env:TEMP\migrate_neo4j.key"
    $tmpCert   = "$env:TEMP\migrate_neo4j.crt"
    $tmpScript = "$env:TEMP\migrate_gen_neo4j_cert.py"
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
    python $tmpScript $fqdn $tmpKey $tmpCert

    $sslKey = az storage account keys list -g $destRg --subscription $destSub -n $storageAccountName --query '[0].value' -o tsv 2>&1
    az storage file upload --share-name neo4j-ssl --account-name $storageAccountName --account-key $sslKey `
        --source $tmpKey --path neo4j.key --output none --only-show-errors 2>&1 | Out-Null
    az storage file upload --share-name neo4j-ssl --account-name $storageAccountName --account-key $sslKey `
        --source $tmpCert --path neo4j.crt --output none --only-show-errors 2>&1 | Out-Null
    # Remove-Item echoue sur les comptes Windows dont le nom contient un point (8.3 short-name) --
    # [System.IO.File]::Delete() contourne le provider PowerShell. Pas d'acces a la fonction
    # Remove-FileSafe du scope parent depuis ce Start-Job -- on inline l'equivalent.
    foreach ($p in @($tmpKey, $tmpCert, $tmpScript)) { try { [System.IO.File]::Delete($p) } catch {} }

    az container restart --resource-group $destRg --subscription $destSub --name $aciGroup `
        --output none --only-show-errors 2>&1 | Out-Null

    # Import GraphML + correctif UTF-8 -- reutilise le script existant tel quel (gere son
    # propre delai d'attente de disponibilite de Neo4j jusqu'a 3 min, et applique
    # fix_utf8.cypher automatiquement apres l'import).
    $securePwd = ConvertTo-SecureString $neo4jPwd -AsPlainText -Force
    & "$projectRoot\import-neo4j-legacykb.ps1" -ResourceGroup $destRg -StorageAccountName $storageAccountName `
        -ShareName $shareName -Fqdn $fqdn -Neo4jPassword $securePwd 2>&1

    # Met a jour le secret Key Vault (deplace, meme nom). Le Container App n'existe pas
    # forcement encore a ce stade (cree en parallele par la Branche A) -- la mise a jour de
    # son env var NEO4J_LEGACYKB_URI se fait apres la jointure des deux branches (thread
    # principal), pas ici.
    $newUri = $outputs.uri.value
    az keyvault secret set --vault-name "kv-$suffix" --name "neo4j-legacykb-password" `
        --value $neo4jPwd --subscription $destSub --output none --only-show-errors 2>&1 | Out-Null

    return $newUri
} -ArgumentList $ProjectRoot, $DestResourceGroup, $destSubId, $suffix, $Location, $tagsJson, $neo4jPlainPwd, $AlertEmail, $tempBundle

Write-Info "Branche B (neo4j-legacykb) lancee en arriere-plan (~5 min)..."

# Branche A (rapide) -- execution sur le thread principal pendant que la Branche B tourne.
# Le Container App et son Managed Environment ne supportent pas le move ARM (contrairement
# a l'ancienne App Service) -- on les recree en redeployant le module containerapp.bicep,
# qui cree lui-meme une UAMI fraiche (id-api-<suffix>) et la configure (AcrPull, registries,
# AZURE_CLIENT_ID...). neo4jLegacyKbUri est laisse vide ici -- mis a jour une fois la
# Branche B terminee (le Container App doit exister avant qu'on puisse le cibler).
Write-Info "Branche A -- redeploiement du Container App (containerapp.bicep)..."

$registryLoginServer = az acr show -g $DestResourceGroup --subscription $destSubId `
    -n "acr$($suffix -replace '-', '')" --query loginServer -o tsv --only-show-errors 2>&1
$apiImageTag = "$registryLoginServer/notebooklm-api:latest"

$appInsightsId = az resource list -g $DestResourceGroup --subscription $destSubId `
    --resource-type Microsoft.Insights/components --query "[?name=='appi-$suffix'].id" -o tsv --only-show-errors 2>&1
$appInsightsConnStr = az resource show --ids $appInsightsId --subscription $destSubId `
    --query properties.ConnectionString -o tsv --only-show-errors 2>&1

$keyVaultUri = "https://kv-$suffix.vault.azure.net/"

$containerAppDeployName = "migrate-containerapp-$(Get-Date -Format 'yyyyMMddHHmmss')"
az deployment group create -g $DestResourceGroup --subscription $destSubId `
    --template-file "$ProjectRoot\infra\modules\containerapp.bicep" `
    --name $containerAppDeployName --output none --only-show-errors `
    --parameters suffix=$suffix location=$Location tags=$tagsJson `
        apiImageTag=$apiImageTag appInsightsConnectionString=$appInsightsConnStr `
        keyVaultUri=$keyVaultUri neo4jLegacyKbUri='' `
        registryLoginServer=$registryLoginServer `
        gpt4oDeploymentName=gpt-4o embeddingDeploymentName=text-embedding-3-large 2>&1

$containerAppOutputs = az deployment group show -g $DestResourceGroup --subscription $destSubId -n $containerAppDeployName `
    --query properties.outputs --output json 2>&1 | ConvertFrom-Json
$newIdentityPrincipalId = $containerAppOutputs.principalId.value
$apiUrl = $containerAppOutputs.apiUrl.value
Write-OK "Container App redeploye : $apiUrl (UAMI id-api-$suffix recreee, AcrPull configure par le module)"

# Roles RBAC -- non conserves par le move ARM (documente Microsoft) pour les ressources
# deplacees, et de toute facon recreees pour la nouvelle UAMI. AcrPull est deja assigne par
# containerapp.bicep lui-meme -- inutile de le dupliquer ici.
$rgScope = "/subscriptions/$destSubId/resourceGroups/$DestResourceGroup"

$uamiRoles = @('Cognitive Services OpenAI User', 'Search Index Data Contributor', 'Key Vault Secrets User')
$devRoles  = @('Cognitive Services OpenAI User', 'Search Index Data Contributor', 'Cognitive Services User',
               'Storage Blob Data Contributor', 'Key Vault Secrets Officer')

Write-Info "Reassignation des roles IAM (UAMI + developpeur, parallel)..."
$roleJobs = @()
$roleJobs += foreach ($role in $uamiRoles) {
    Start-Job -ScriptBlock {
        az role assignment create --assignee $using:newIdentityPrincipalId --role $using:role `
            --scope $using:rgScope --only-show-errors 2>&1 | Out-Null
    }
}
$roleJobs += foreach ($role in $devRoles) {
    Start-Job -ScriptBlock {
        az role assignment create --assignee $using:deployerObjectId --role $using:role `
            --scope $using:rgScope --only-show-errors 2>&1 | Out-Null
    }
}
$roleJobs | Wait-Job | Out-Null
$roleJobs | Remove-Job -Force
Write-OK "Roles IAM reassignes :"
foreach ($role in $uamiRoles) { Write-Info "  - $role (UAMI Container App)" }
foreach ($role in $devRoles)  { Write-Info "  - $role (developpeur)" }

Write-Info "Attente de la fin de la Branche B (stack neo4j-legacykb)..."
$null = Wait-Job $branchBJob
$neo4jUriEnv = Receive-Job $branchBJob | Select-Object -Last 1
Remove-Job $branchBJob -Force
Write-OK "Branche B terminee -- neo4j-legacykb pret : $neo4jUriEnv"

# ── PHASE 4 : Réconciliation ───────────────────────────────────────────────────
Write-Phase 4 6 "Reconciliation -- mise a jour NEO4J_LEGACYKB_URI + regeneration .env"

# AZURE_CLIENT_ID est deja correct depuis la creation du Container App (Branche A). Seul
# NEO4J_LEGACYKB_URI doit etre mis a jour maintenant que la Branche B a termine -- ce qui
# cree automatiquement une nouvelle revision (l'equivalent du redemarrage App Service,
# sans etape separee necessaire avec Container Apps).
az containerapp update -g $DestResourceGroup --subscription $destSubId -n "ca-api-$suffix" `
    --set-env-vars NEO4J_LEGACYKB_URI=$neo4jUriEnv --output none --only-show-errors 2>&1 | Out-Null
Write-OK "NEO4J_LEGACYKB_URI mis a jour sur le Container App (nouvelle revision activee automatiquement)"
Write-Warn "Propagation IAM : attendez 3-5 min avant de tester l'ingestion locale"

# Les endpoints des ressources deplacees sont inchanges (move = metadonnees) -- on les
# relit simplement depuis Azure pour regenerer un .env a jour (notamment NEO4J_LEGACYKB_URI
# qui, lui, a change puisque l'ACI a ete recree).
$openAIEndpoint  = az cognitiveservices account show -g $DestResourceGroup --subscription $destSubId -n "oai-$suffix" --query properties.endpoint -o tsv --only-show-errors 2>&1
$searchName      = "srch-$suffix"
$docIntEndpoint  = az cognitiveservices account show -g $DestResourceGroup --subscription $destSubId -n "di-$suffix" --query properties.endpoint -o tsv --only-show-errors 2>&1
$storageName     = az storage account list -g $DestResourceGroup --subscription $destSubId --query "[?starts_with(name,'st') && !starts_with(name,'stneo4jkb')].name | [0]" -o tsv --only-show-errors 2>&1
$apiKeyValue     = az keyvault secret show --vault-name "kv-$suffix" --subscription $destSubId --name "api-key" --query value -o tsv --only-show-errors 2>&1

$envFile = Join-Path $ProjectRoot ".env"
if ((Test-Path $envFile) -and -not $Force) {
    $overwrite = Read-Host "        .env existant detecte. Ecraser ? (o/N)"
    if ($overwrite -ne 'o') {
        Write-Warn "Conservation du .env existant -- mettez a jour NEO4J_LEGACYKB_URI manuellement : $neo4jUriEnv"
        $envFile = $null
    }
}
if ($envFile) {
    $envContent = @"
# Genere automatiquement par migrate-rg.ps1 le $(Get-Date -Format 'yyyy-MM-dd HH:mm')
# NE PAS COMMITTER CE FICHIER -- il contient des secrets

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=$openAIEndpoint
AZURE_OPENAI_GPT4O_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_INVENTAIRE_DEPLOYMENT=gpt-4o

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://$searchName.search.windows.net

# Azure Document Intelligence
AZURE_DOCINT_ENDPOINT=$docIntEndpoint

# Azure Blob Storage
AZURE_STORAGE_ACCOUNT_NAME=$storageName

# Neo4j Legacy KB (golden source GraphRAG) -- recree par la migration
NEO4J_LEGACYKB_URI=$neo4jUriEnv
NEO4J_LEGACYKB_PASSWORD=***

# Authentification API (secret Key Vault, inchange par le move)
API_KEY=$apiKeyValue

# URL de l'API deployee (utilisee par mcp-legacykb)
NOTEBOOKLM_API_URL=$apiUrl
"@
    [System.IO.File]::WriteAllText($envFile, $envContent, [System.Text.Encoding]::UTF8)
    Write-OK ".env regenere"
    Write-Info "NEO4J_LEGACYKB_PASSWORD est masque -- renseignez-le manuellement si besoin"
}

# ── PHASE 5 : Validation post-migration ───────────────────────────────────────
Write-Phase 5 6 "Validation post-migration"

# $apiUrl provient deja de la sortie du deploiement containerapp.bicep (Branche A) --
# pas besoin de le requeter a nouveau.
Write-Info "URL Container App : $apiUrl"
Write-Info "Attente de disponibilite (5 tentatives x 20s)..."

$ready = $false
$attempt = 0
do {
    $attempt++
    Start-Sleep -Seconds 20
    Write-Info "  Tentative $attempt/5 -- GET $apiUrl/health"
    try {
        $resp = Invoke-WebRequest -Uri "$apiUrl/health" -TimeoutSec 15 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) { $ready = $true; Write-OK "Health check OK" }
    } catch {
        Write-Info "  Pas de reponse -- redemarrage en cours"
    }
} while (-not $ready -and $attempt -lt 5)

if ($ready -and $apiKeyValue) {
    try {
        $headers = @{ "X-API-Key" = $apiKeyValue }
        $resp2 = Invoke-WebRequest -Uri "$apiUrl/api/legacykb/health" -Headers $headers `
                     -TimeoutSec 15 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($resp2.StatusCode -eq 200) { Write-OK "Legacy KB health check OK" }
        else { Write-Warn "Legacy KB health check : HTTP $($resp2.StatusCode)" }
    } catch {
        Write-Warn "Legacy KB health check inaccessible -- neo4j-legacykb est peut-etre encore en demarrage"
    }
} elseif (-not $ready) {
    Write-Warn "Le Container App n'a pas repondu apres 5 tentatives -- testez $apiUrl/health manuellement dans 2-3 min."
}

# ── PHASE 6 : Résumé + décommission (manuelle, jamais automatique) ───────────
Write-Host ""
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host "  |        Migration terminee !              |" -ForegroundColor Green
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host ""
Write-Host "  Resource Group cible : $DestResourceGroup ($($destAccount.name))" -ForegroundColor DarkGray
Write-Host "  URL production       : $apiUrl" -ForegroundColor DarkGray
Write-Host "  Neo4j Legacy KB      : $neo4jUriEnv" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Une fois la migration validee (tests manuels, ingestion locale OK), supprimez" -ForegroundColor White
Write-Host "  l'ancien Resource Group avec la commande suivante (jamais executee automatiquement) :" -ForegroundColor White
Write-Host ""
Write-Host "  az group delete --name $SourceResourceGroup --subscription $srcSubId --yes" -ForegroundColor Yellow
Write-Host ""
