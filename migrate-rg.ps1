#Requires -Version 5.1
<#
.SYNOPSIS
    Migre les ressources Azure de NotebookLM Azure vers un nouveau Resource Group / subscription.

.DESCRIPTION
    Conçu pour les politiques d'entreprise imposant une durée de vie limitée aux Resource Groups.
    Plutôt que de tout reconstruire (et de ré-indexer/ré-importer les données), ce script déplace
    nativement (ARM "resource move") les ressources qui le supportent — opération de métadonnées
    qui préserve les données (index Azure AI Search, images ACR, secrets Key Vault, blobs) et les
    endpoints (aucun changement de DNS) — et redéploie intégralement `infra/main.bicep` pour
    tout le reste (VNet/NSG, Container App + Managed Environment, ACI neo4j-legacykb, Job
    d'import) — exactement comme deploy.ps1, pas une orchestration manuelle séparée.

    AUDIT-2026-06 : ce choix (redéployer tout main.bicep plutôt que des modules isolés) n'est
    pas cosmétique — depuis la migration réseau, `containerapp.bicep` a besoin du sous-réseau
    `snet-cae` (network.bicep) ET du storage account de `neo4j-legacykb.bicep` (pour monter le
    partage du Job d'import), et `neo4j-legacykb.bicep` a besoin du sous-réseau
    `snet-aci-legacykb`. Orchestrer ces 3 modules à la main (comme le faisait l'ancienne version
    de ce script) reproduit une dépendance que Bicep résout déjà correctement tout seul à
    l'intérieur de `main.bicep` — et qui se rate facilement à la main (constaté en pratique lors
    de la migration réseau elle-même). Les ressources déjà déplacées par ARM move (OpenAI,
    Search, Storage, Key Vault, Registry, Monitoring) existent déjà sous le même nom dans le RG
    cible : Bicep les retrouve et ne fait qu'un no-op de confirmation dessus.

    Phases :
      0. Prérequis + authentification (subscription source ET cible, même tenant Entra)
      1. Pré-vol — enregistrement des Resource Providers manquants + validation ARM à blanc
         (validateMoveResources) avant toute action destructive
      2. Déplacement groupé des ressources déplaçables (un seul appel ARM atomique)
      3. Redéploiement de infra/main.bicep dans le RG cible (VNet/NSG, Container App + UAMI +
         rôles IAM, ACI neo4j-legacykb dans le VNet, Job d'import) // en parallèle : réassignation
         des rôles IAM du développeur courant (ne dépend pas du déploiement Bicep)
      4. Stack neo4j-legacykb — certificat TLS auto-signé (SAN = IP privée), upload, redémarrage
         ACI, déclenchement de l'import (réutilise import-neo4j-legacykb.ps1 tel quel)
      5. Régénération du .env local + validation post-migration (health checks)
      6. Résumé — affiche la commande de suppression de l'ancien RG, ne l'exécute JAMAIS

    Mot de passe neo4j-legacykb : réutilisé automatiquement depuis le secret Key Vault déjà
    déplacé (le Key Vault survit au move, son contenu est inchangé) — pas de nouveau mot de
    passe à fournir, sauf si ce secret est introuvable (instance jamais déployée ou Key Vault
    vide), auquel cas -Neo4jPassword est demandé.

    Clé API : préservée telle quelle (lue dans le Key Vault déplacé, jamais régénérée) — aucun
    client existant (mcp-legacykb, intégrations) n'a besoin d'être reconfiguré après la migration.

    Important : les attributions de rôle RBAC scopées sur une ressource ne survivent PAS à un
    "resource move" (documenté par Microsoft). Celles de l'UAMI du Container App sont recréées
    automatiquement par main.bicep (il les définit lui-même). Celles de l'identité du
    développeur courant (az login) sont recréées explicitement par ce script (Phase 3), pour que
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
    Mot de passe du compte neo4j pour le conteneur ACI recréé. Utilisé uniquement si le secret
    Key Vault déplacé est introuvable (cf. DESCRIPTION) — demandé interactivement dans ce cas
    si ce paramètre est absent.

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
function New-BicepParametersFile([hashtable]$Values) {
    # Meme helper que deploy.ps1 -- fichier de parametres temporaire, nom aleatoire,
    # toujours supprime par l'appelant (cf. finally) pour ne pas laisser de secret sur disque.
    $paramsObj = [ordered]@{
        '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters     = [ordered]@{}
    }
    foreach ($key in $Values.Keys) {
        $paramsObj.parameters[$key] = @{ value = $Values[$key] }
    }
    $tempFile = Join-Path $env:TEMP "migrate-rg-params-$([guid]::NewGuid()).json"
    ($paramsObj | ConvertTo-Json -Depth 5) | Set-Content -Path $tempFile -Encoding UTF8
    return $tempFile
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
    # certificats Zscaler du store Windows, necessaire pour les appels "az storage"
    # (SDK data-plane, ignore core.verify_ssl=false -- cf. deploy.ps1).
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
            $env:REQUESTS_CA_BUNDLE = $tempBundle
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
        --tags Project=$ProjectName Environment=$Environment ManagedBy=bicep --output none --only-show-errors 2>&1 | Out-Null
    Write-OK "Resource Group cible cree : $DestResourceGroup ($Location)"
}

# Resource Providers requis -- enregistrement en parallele sur la subscription cible.
# Microsoft.Network et Microsoft.App ajoutes (AUDIT-2026-06) : VNet/NSG (network.bicep)
# et Container Apps Jobs (containerapp.bicep) n'existaient pas avant la migration reseau.
$requiredProviders = @(
    'Microsoft.CognitiveServices', 'Microsoft.Search', 'Microsoft.KeyVault',
    'Microsoft.ContainerRegistry', 'Microsoft.Storage', 'Microsoft.Web',
    'Microsoft.Insights', 'Microsoft.ManagedIdentity', 'Microsoft.ContainerInstance',
    'Microsoft.Network', 'Microsoft.App'
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

Write-Warn "Si la subscription cible applique une policy de tags obligatoires (ex. rencontre en pratique : 'Squad'/'Environment'/'CostCenter'/'ManagedBy'/'Project'), le redeploiement Bicep (Phase 3) echouera sur les NOUVELLES ressources (VNet, NSG) avec 'RequestDisallowedByPolicy' tant que infra/main.bicep n'est pas mis a jour avec des valeurs de tags acceptees par cette policy -- voir la variable 'tags' en tete de infra/main.bicep."

# Inventaire des ressources deplacables (exclut explicitement l'UAMI, le Container App /
# Managed Environment / VNet / NSG / Job d'import, et la stack ACI neo4j -- aucun de ces
# types ne supporte le move ARM (ACI/UAMI/ContainerApp) ou n'a pas besoin d'etre deplace
# (VNet/NSG/Job, recrees sans cout par le redeploiement Bicep, cf. DESCRIPTION). Tous sont
# recrees en Phase 3 (redeploiement de infra/main.bicep), pas deplaces.
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
# les phases suivantes (Bicep, neo4j, .env) cibleraient des noms inexistants. On le detecte ici
# plutot que d'echouer profondement en Phase 3/4. Le Container App n'etant pas deplace (recree
# en Phase 3), on verifie plutot la presence de l'ACR -- toujours deplacable et toujours present
# puisque deploy.ps1 le cree systematiquement.
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

# A partir d'ici, plus aucune action ne touche la subscription source.
az account set --subscription $destSubId --only-show-errors

# ── PHASE 3 : Redéploiement de infra/main.bicep ──────────────────────────────
Write-Phase 3 6 "Redeploiement infra/main.bicep (VNet, Container App, neo4j-legacykb, Job) // roles IAM developpeur"

# Mot de passe neo4j -- reutilise depuis le secret Key Vault deja deplace (Key Vault =
# ressource deplacable, son contenu survit au move) plutot que d'en demander un nouveau.
$kvName = "kv-$suffix"
$existingNeo4jPwd = az keyvault secret show --vault-name $kvName --subscription $destSubId `
    --name "neo4j-legacykb-password" --query value -o tsv --only-show-errors 2>$null
if ($existingNeo4jPwd) {
    $neo4jPlainPwd = $existingNeo4jPwd
    Write-OK "Mot de passe neo4j-legacykb reutilise depuis le Key Vault deplace ($kvName)"
} else {
    if ($null -eq $Neo4jPassword -or $Neo4jPassword.Length -eq 0) {
        Write-Host ""
        Write-Host "        Secret 'neo4j-legacykb-password' introuvable dans $kvName -- nouveau mot de passe :" -ForegroundColor White
        $Neo4jPassword = Read-Host -AsSecureString "        Neo4j password"
    }
    $neo4jPlainPwd = ConvertFrom-SecureStringPlain $Neo4jPassword
    if ([string]::IsNullOrWhiteSpace($neo4jPlainPwd)) {
        Write-Fail "Le mot de passe neo4j-legacykb est obligatoire (secret Key Vault introuvable)."
    }
}
$existingNeo4jPwd = $null

# Cle API -- preservee telle quelle (vide ici => infra/main.bicep ne touche pas au secret
# Key Vault deja deplace, cf. condition "if (!empty(apiKey))" dans main.bicep). Aucun client
# existant (mcp-legacykb, integrations) n'a besoin d'etre reconfigure apres la migration.
$registryLoginServer = az acr show -g $DestResourceGroup --subscription $destSubId `
    -n "acr$($suffix -replace '-', '')" --query loginServer -o tsv --only-show-errors 2>&1
$apiImageTag = "$registryLoginServer/notebooklm-api:latest"
Write-Info "Image reutilisee telle quelle (deja a jour, deplacee avec le registre) : $apiImageTag"

# Reassignation des roles IAM du developpeur courant -- lancee en parallele du deploiement
# Bicep (Phase 3), ne depend pas de lui. Les roles de l'UAMI du Container App ne sont PAS
# reassignes ici : infra/main.bicep les definit lui-meme (roleApiOpenAI/roleApiSearch/roleApiKV),
# le redeploiement de ce template les recree automatiquement.
$rgScope = "/subscriptions/$destSubId/resourceGroups/$DestResourceGroup"
$devRoles = @('Cognitive Services OpenAI User', 'Search Index Data Contributor', 'Cognitive Services User',
              'Storage Blob Data Contributor', 'Key Vault Secrets Officer')
Write-Info "Reassignation des roles IAM developpeur (arriere-plan, parallel au deploiement Bicep)..."
$devRoleJobs = foreach ($role in $devRoles) {
    Start-Job -ScriptBlock {
        param($principal, $role, $scope, $sub)
        az role assignment create --assignee $principal --role $role --scope $scope --subscription $sub `
            --only-show-errors 2>&1 | Out-Null
    } -ArgumentList $deployerObjectId, $role, $rgScope, $destSubId
}

$paramsFile = New-BicepParametersFile @{
    projectName           = $ProjectName
    environment            = $Environment
    location               = $Location
    deployerObjectId       = $deployerObjectId
    apiImageTag            = $apiImageTag
    deployLegacyKb         = $true
    neo4jLegacyKbPassword  = $neo4jPlainPwd
    apiKey                 = ""
    alertEmail             = $AlertEmail
}
$bicepDeployName = "migrate-main-$(Get-Date -Format 'yyyyMMddHHmmss')"
Write-Info "Deploiement de infra/main.bicep en cours (~12 min, comme deploy.ps1)..."
try {
    az deployment group create --resource-group $DestResourceGroup --subscription $destSubId `
        --template-file "$ProjectRoot\infra\main.bicep" `
        --name $bicepDeployName --output none --only-show-errors `
        --parameters "@$paramsFile" 2>&1
} finally {
    Remove-FileSafe $paramsFile
}
$neo4jPlainPwd = $null

$bicepOutputs = az deployment group show -g $DestResourceGroup --subscription $destSubId -n $bicepDeployName `
    --query properties.outputs --output json --only-show-errors 2>&1 | ConvertFrom-Json

$apiUrl              = $bicepOutputs.apiUrl.value
$neo4jPrivateIp       = $bicepOutputs.neo4jLegacyKbPrivateIp.value
$neo4jStorageAccount  = $bicepOutputs.neo4jLegacyKbStorageAccount.value
$neo4jShareName       = $bicepOutputs.neo4jLegacyKbShareName.value
$keyVaultUriOut       = $bicepOutputs.keyVaultName.value
Write-OK "infra/main.bicep deploye -- API : $apiUrl  |  neo4j-legacykb (prive) : $neo4jPrivateIp"

$null = Wait-Job $devRoleJobs
$devRoleJobs | Remove-Job -Force
Write-OK "Roles IAM developpeur reassignes :"
foreach ($role in $devRoles) { Write-Info "  - $role" }

# ── PHASE 4 : Stack neo4j-legacykb -- certificat TLS + import ────────────────
Write-Phase 4 6 "neo4j-legacykb -- certificat TLS (SAN IP privee) + redemarrage + import"

$aciGroupName = "aci-neo4j-legacykb-$suffix"
$tmpKey    = "$env:TEMP\migrate_neo4j.key"
$tmpCert   = "$env:TEMP\migrate_neo4j.crt"
$tmpScript = "$env:TEMP\migrate_gen_neo4j_cert.py"

# Script Python inline -- identique a deploy.ps1 Phase 4b (SAN IPAddress, plus DNSName,
# depuis que neo4j-legacykb n'a plus de FQDN public -- AUDIT-2026-06).
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
import datetime, ipaddress

host, key_out, cert_out = sys.argv[1], sys.argv[2], sys.argv[3]
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
san = x509.IPAddress(ipaddress.ip_address(host))
cert = (x509.CertificateBuilder()
    .subject_name(subject).issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
    .add_extension(x509.SubjectAlternativeName([san]), critical=False)
    .sign(key, hashes.SHA256()))
open(key_out,  'wb').write(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption()))
open(cert_out, 'wb').write(cert.public_bytes(serialization.Encoding.PEM))
'@ | Set-Content -Path $tmpScript -Encoding UTF8
python $tmpScript $neo4jPrivateIp $tmpKey $tmpCert
Write-OK "Certificat auto-signe genere pour $neo4jPrivateIp"

$sslKey = az storage account keys list -g $DestResourceGroup --subscription $destSubId `
    -n $neo4jStorageAccount --query '[0].value' -o tsv --only-show-errors 2>&1
az storage file upload --share-name neo4j-ssl --account-name $neo4jStorageAccount --account-key $sslKey `
    --source $tmpKey --path neo4j.key --no-progress --output none --only-show-errors 2>&1 | Out-Null
az storage file upload --share-name neo4j-ssl --account-name $neo4jStorageAccount --account-key $sslKey `
    --source $tmpCert --path neo4j.crt --no-progress --output none --only-show-errors 2>&1 | Out-Null
foreach ($p in @($tmpKey, $tmpCert, $tmpScript)) { Remove-FileSafe $p }
Write-OK "Certificats uploades dans le partage Azure Files neo4j-ssl"

Write-Info "Redemarrage de l'ACI neo4j-legacykb pour activer TLS..."
az container restart --resource-group $DestResourceGroup --subscription $destSubId --name $aciGroupName `
    --output none --only-show-errors 2>&1 | Out-Null
Write-OK "ACI $aciGroupName redemarre -- Neo4j demarrera avec bolt+s:// et HTTPS"

Write-Info "Declenchement de l'import via le Job (import-neo4j-legacykb.ps1)..."
& "$ProjectRoot\import-neo4j-legacykb.ps1" -ResourceGroup $DestResourceGroup -ProjectName $ProjectName `
    -Environment $Environment -SkipSSL:$SkipSSL

# ── PHASE 5 : Régénération .env + validation ──────────────────────────────────
Write-Phase 5 6 "Regeneration .env + validation post-migration"

$openAIEndpoint  = az cognitiveservices account show -g $DestResourceGroup --subscription $destSubId -n "oai-$suffix" --query properties.endpoint -o tsv --only-show-errors 2>&1
$searchName      = "srch-$suffix"
$docIntEndpoint  = az cognitiveservices account show -g $DestResourceGroup --subscription $destSubId -n "di-$suffix" --query properties.endpoint -o tsv --only-show-errors 2>&1
$storageName     = az storage account list -g $DestResourceGroup --subscription $destSubId --query "[?starts_with(name,'st') && !starts_with(name,'stneo4jkb')].name | [0]" -o tsv --only-show-errors 2>&1
$apiKeyValue     = az keyvault secret show --vault-name $kvName --subscription $destSubId --name "api-key" --query value -o tsv --only-show-errors 2>&1

$envFile = Join-Path $ProjectRoot ".env"
if ((Test-Path $envFile) -and -not $Force) {
    $overwrite = Read-Host "        .env existant detecte. Ecraser ? (o/N)"
    if ($overwrite -ne 'o') {
        Write-Warn "Conservation du .env existant -- mettez a jour NEO4J_LEGACYKB_URI manuellement : bolt+ssc://${neo4jPrivateIp}:7687"
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

# Neo4j Legacy KB (golden source GraphRAG) -- IP privee, recreee par la migration
# (AUDIT-2026-06 : injoignable depuis ce poste hors VNet -- cf. CLAUDE.md/ARCHITECTURE.md)
NEO4J_LEGACYKB_URI=bolt+ssc://${neo4jPrivateIp}:7687
NEO4J_LEGACYKB_PASSWORD=***

# Authentification API (secret Key Vault, preserve par la migration)
API_KEY=$apiKeyValue

# URL de l'API deployee (utilisee par mcp-legacykb et par le frontend local pour
# /api/legacykb/* -- cf. CORS_ALLOWED_ORIGINS, AUDIT-2026-06)
NOTEBOOKLM_API_URL=$apiUrl
"@
    [System.IO.File]::WriteAllText($envFile, $envContent, [System.Text.Encoding]::UTF8)
    Write-OK ".env regenere"
    Write-Info "NEO4J_LEGACYKB_PASSWORD est masque -- renseignez-le manuellement si besoin"
}

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
Write-Host "  Neo4j Legacy KB      : bolt+ssc://${neo4jPrivateIp}:7687 (prive, snet-aci-legacykb)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Une fois la migration validee (tests manuels, ingestion locale OK), supprimez" -ForegroundColor White
Write-Host "  l'ancien Resource Group avec la commande suivante (jamais executee automatiquement) :" -ForegroundColor White
Write-Host ""
Write-Host "  az group delete --name $SourceResourceGroup --subscription $srcSubId --yes" -ForegroundColor Yellow
Write-Host ""
