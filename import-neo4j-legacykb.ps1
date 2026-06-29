#Requires -Version 5.1
<#
.SYNOPSIS
    Upload du dump (GraphML ou JSONL) vers le conteneur neo4j-legacykb et import via le Job dédié.

.DESCRIPTION
    Appelé automatiquement par deploy.ps1 après le déploiement Bicep (quand
    deployLegacyKb=true). Peut aussi être relancé seul à tout moment — après mise à
    jour du dump, ou pour repeupler une nouvelle instance neo4j-legacykb
    (nouveau -ProjectName, nouveau Resource Group...) — sans rien redéployer :

    1. Upload le fichier (GraphML ou JSONL, cf. -DumpPath) dans le partage Azure Files
       monté sur le conteneur (control-plane Azure Storage — clé de compte, pas
       d'accès réseau à neo4j-legacykb).
    2. Déclenche le Container Apps Job `caj-import-legacykb-*` (AUDIT-2026-06), qui
       détecte le format par l'extension du fichier et exécute le reste de la logique
       (attente démarrage, purge optionnelle, import -- `apoc.import.graphml` pour
       `.graphml`, création par lots via APOC pour `.jsonl`, cf. api/scripts/import_legacykb.py)
       depuis l'intérieur du VNet — seul point d'accès autorisé à neo4j-legacykb
       depuis que celui-ci a perdu son IP publique (cf. infra/modules/network.bicep).
    3. Attend la fin de l'exécution du Job et affiche son résultat (déposé par le Job
       lui-même dans le partage Azure Files, relu ici via control-plane).

    -StorageAccountName et -JobName sont optionnels : si omis, ils sont découverts
    automatiquement depuis -ResourceGroup. Seul -ResourceGroup est donc nécessaire
    dans le cas courant — le mot de passe neo4j n'est plus demandé ici : le Job le
    charge lui-même depuis Key Vault (AUDIT-2026-06).

.PARAMETER ResourceGroup
    Resource Group contenant le storage account, le conteneur ACI et le Job neo4j-legacykb.

.PARAMETER StorageAccountName
    Nom du storage account dédié. Découvert automatiquement depuis -ResourceGroup si omis.

.PARAMETER ShareName
    Nom du partage Azure Files (défaut "neo4j-import").

.PARAMETER JobName
    Nom du Container Apps Job d'import (ex. caj-import-legacykb-nlmrep-prod).
    Découvert automatiquement depuis -ResourceGroup si omis.

.PARAMETER DumpPath
    Chemin du fichier à importer -- .graphml ou .jsonl (format détecté par l'extension
    côté Job, cf. api/scripts/import_legacykb.py). Défaut :
    docs/extract/repartition_cleaned_export.graphml.

.PARAMETER ProjectName
    Préfixe du projet (suffixe des ressources "*-legacykb-<ProjectName>-<Environment>").
    Nécessaire seulement si -ResourceGroup contient plusieurs instances neo4j-legacykb
    (ex. plusieurs déploiements successifs sous des noms de projet différents) — sinon
    l'instance unique trouvée est utilisée automatiquement.

.PARAMETER Environment
    Suffixe d'environnement (défaut "prod"). Utilisé avec -ProjectName pour désambiguïser.

.PARAMETER SkipSSL
    Bypass SSL pour proxy d'entreprise (Zscaler, Forcepoint, etc.) — même mécanisme que deploy.ps1.

.PARAMETER PurgeBeforeImport
    Supprime tous les nœuds et relations existants (`MATCH (n) DETACH DELETE n`) avant
    l'import. Pour un dump GraphML, sans ce flag l'import est additif (upsert par
    propriété `id` — voir DESCRIPTION) : les nœuds absents du nouveau dump mais déjà
    présents en base restent en place. Pour un dump JSONL, l'import crée TOUJOURS de
    nouveaux nœuds (pas d'upsert) — réimporter sans -PurgeBeforeImport duplique tout.
    Destructif et irréversible — flag explicite opt-in, aucune confirmation
    interactive n'est redemandée.

.EXAMPLE
    # Cas courant : une seule instance neo4j-legacykb dans le RG — tout est découvert
    # automatiquement
    .\import-neo4j-legacykb.ps1 -ResourceGroup rg-sp5-d-vgi-azu-repart-nlm-txt -SkipSSL

.EXAMPLE
    # Repartir d'une base vide (nouveau dump ayant retiré des nœuds depuis le dernier
    # import) plutôt que de purger manuellement via le browser Neo4j
    .\import-neo4j-legacykb.ps1 -ResourceGroup rg-sp5-d-vgi-azu-repart-nlm-txt -PurgeBeforeImport -SkipSSL

.EXAMPLE
    # Plusieurs instances neo4j-legacykb dans le meme RG (deploiements successifs) —
    # -ProjectName desambiguise laquelle cibler
    .\import-neo4j-legacykb.ps1 -ResourceGroup rg-sp5-d-vgi-azu-repart-nlm-txt -ProjectName nlmrep -SkipSSL

.EXAMPLE
    # Import d'un export au format JSONL (ex. généré par un autre outil que le pipeline
    # GraphRAG habituel) -- format détecté automatiquement par l'extension du fichier
    .\import-neo4j-legacykb.ps1 -ResourceGroup rg-sp5-d-vgi-azu-repart-nlm-txt `
        -DumpPath docs\extract\mon_export.jsonl -PurgeBeforeImport -SkipSSL
#>
param(
    [Parameter(Mandatory)] [string]$ResourceGroup,
    [string]$StorageAccountName = "",
    [string]$ShareName = "neo4j-import",
    [string]$JobName = "",
    [string]$ProjectName = "",
    [string]$Environment = "prod",
    [string]$DumpPath = "",
    [switch]$SkipSSL,
    [switch]$PurgeBeforeImport
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

function Remove-FileSafe([string]$Path) {
    # Remove-Item échoue sur les comptes Windows dont le nom contient un point (ex.
    # "v.gicquiau" -> %TEMP% en 8.3 short-name "V5C98~1.GIC") avec une PSArgumentException
    # qui bypass -ErrorAction. [System.IO.File]::Delete() contourne le provider PowerShell.
    try { [System.IO.File]::Delete($Path) } catch {}
}

# Trouve, parmi une liste de ressources nommées "<prefix>-legacykb-*", celle qui
# correspond à -ProjectName/-Environment (ou l'unique candidate si pas d'ambiguïté).
# Factorisé : utilisé à la fois pour le conteneur ACI et pour le Container Apps Job.
function Select-LegacyKbResource([array]$Candidates, [string]$Prefix, [string]$Kind) {
    if ($Candidates.Count -eq 0) {
        Write-Host "  ERREUR : aucune ressource '$Prefix-legacykb-*' ($Kind) trouvee dans '$ResourceGroup'." -ForegroundColor Red
        exit 1
    } elseif ($Candidates.Count -eq 1) {
        return $Candidates[0]
    } elseif ($ProjectName) {
        $expectedName = "$Prefix-legacykb-$ProjectName-$Environment"
        $found = $Candidates | Where-Object { $_.name -eq $expectedName } | Select-Object -First 1
        if (-not $found) {
            Write-Host "  ERREUR : aucune ressource nommee '$expectedName' ($Kind) parmi les $($Candidates.Count) trouvees :" -ForegroundColor Red
            foreach ($c in $Candidates) { Write-Host "           - $($c.name)" -ForegroundColor DarkGray }
            exit 1
        }
        return $found
    } else {
        Write-Host "  ERREUR : $($Candidates.Count) ressources '$Prefix-legacykb-*' ($Kind) trouvees dans '$ResourceGroup' — ambigu :" -ForegroundColor Red
        foreach ($c in $Candidates) { Write-Host "           - $($c.name)" -ForegroundColor DarkGray }
        Write-Host "           Precisez -ProjectName (et -Environment si different de 'prod')." -ForegroundColor DarkGray
        exit 1
    }
}

# ── SSL proxy d'entreprise (même mécanisme que deploy.ps1 Phase 1) ─────────────
if ($SkipSSL) {
    az config set core.verify_ssl=false --only-show-errors 2>&1 | Out-Null
    $certifiBundle = "C:\Program Files\Microsoft SDKs\Azure\CLI2\Lib\site-packages\certifi\cacert.pem"
    if (Test-Path $certifiBundle) {
        $tempBundle = "$env:TEMP\import_neo4j_cacert_zscaler.pem"
        Copy-Item $certifiBundle $tempBundle -Force
        $zscalerCerts = @(Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
            Where-Object { $_.Subject -match "Zscaler" })
        foreach ($cert in $zscalerCerts) {
            $pem = "-----BEGIN CERTIFICATE-----`n" +
                   [Convert]::ToBase64String($cert.Export('Cert'), 'InsertLineBreaks') +
                   "`n-----END CERTIFICATE-----`n"
            Add-Content -Path $tempBundle -Value $pem -Encoding ascii
        }
        $env:REQUESTS_CA_BUNDLE = $tempBundle
        Write-Host "        OK   $($zscalerCerts.Count) certificat(s) Zscaler injecte(s)" -ForegroundColor Green
    }
}

# ── Découverte automatique du storage account et du Job d'import ───────────────
if (-not $StorageAccountName) {
    Write-Host "       Decouverte automatique de neo4j-legacykb dans '$ResourceGroup'..." -ForegroundColor DarkGray
    # Filtrage cote PowerShell (Where-Object) plutot que via --query JMESPath : une
    # chaine --query se terminant par "]" juste avant le guillemet fermant casse le
    # relais az.cmd -> python.exe sur ce poste (les guillemets entourant l'argument
    # disparaissent silencieusement, CMD.EXE choppe alors sur le "]" nu : "] etait inattendu").
    $allAci = az container list -g $ResourceGroup -o json 2>&1 | ConvertFrom-Json
    $aciCandidates = @($allAci | Where-Object { $_.name -like 'aci-neo4j-legacykb*' })
    $aci = Select-LegacyKbResource $aciCandidates 'aci' 'conteneur ACI'

    $aciDetail = az container show -g $ResourceGroup --name $aci.name -o json 2>&1 | ConvertFrom-Json
    $StorageAccountName = ($aciDetail.volumes |
        Where-Object { $_.azureFile.shareName -eq $ShareName } |
        Select-Object -First 1).azureFile.storageAccountName
    Write-Host "  OK   Conteneur : $($aci.name)  |  Storage : $StorageAccountName" -ForegroundColor Green
}

if (-not $JobName) {
    $allJobs = az containerapp job list -g $ResourceGroup -o json 2>&1 | ConvertFrom-Json
    $jobCandidates = @($allJobs | Where-Object { $_.name -like 'caj-import-legacykb*' })
    $job = Select-LegacyKbResource $jobCandidates 'caj-import' 'Container Apps Job'
    $JobName = $job.name
    Write-Host "  OK   Job d'import : $JobName" -ForegroundColor Green
}

if (-not $StorageAccountName -or -not $JobName) {
    Write-Host "  ERREUR : impossible de determiner StorageAccountName/JobName automatiquement." -ForegroundColor Red
    Write-Host "           Precisez-les explicitement via -StorageAccountName et -JobName." -ForegroundColor DarkGray
    exit 1
}

if (-not $DumpPath) {
    $DumpPath = Join-Path $ProjectRoot "docs\extract\repartition_cleaned_export.graphml"
}

if (-not (Test-Path $DumpPath)) {
    Write-Host "  !!   Dump GraphML introuvable ($DumpPath) — import ignoré" -ForegroundColor Yellow
    Write-Host "       Placez votre export dans docs/extract/ et relancez ce script." -ForegroundColor DarkGray
    exit 0
}

$dumpFileName = Split-Path $DumpPath -Leaf

# ── 1. Upload du dump dans le partage Azure Files (control-plane, clé de compte) ──
# --auth-mode login nécessite soit le rôle "Storage File Data SMB Share Contributor"
# (insuffisant pour les gros fichiers sans --enable-file-backup-request-intent), soit
# "Storage File Data Privileged Contributor" (bypass ACL, rôle plus large). La clé de
# compte évite cette dépendance RBAC supplémentaire pour cette opération ponctuelle —
# rôle Contributor (déjà nécessaire pour le reste du déploiement) suffit pour la lire.
$storageKey = az storage account keys list -g $ResourceGroup -n $StorageAccountName --query '[0].value' -o tsv 2>&1
az storage file upload --share-name $ShareName --account-name $StorageAccountName --account-key $storageKey `
    --no-progress `
    --source $DumpPath --path $dumpFileName --output none --only-show-errors 2>&1 | Out-Null
Write-Host "  OK   Dump GraphML uploadé : $StorageAccountName/$ShareName/$dumpFileName" -ForegroundColor Green

# ── 2. Déclenchement du Job d'import (AUDIT-2026-06) ────────────────────────────
# Le mot de passe neo4j n'est plus manipulé ici : le Job le charge lui-même depuis
# Key Vault via sa Managed Identity (cf. api/scripts/import_legacykb.py).
$purgeValue = if ($PurgeBeforeImport) { "true" } else { "false" }
Write-Host "       Mise a jour des parametres du Job ($JobName)..." -ForegroundColor DarkGray
# L'extension CLI "containerapp" écrit un spinner de progression sur stderr même en cas
# de succès. Sous Windows PowerShell, tout texte stderr d'un exécutable natif devient un
# ErrorRecord -- avec $ErrorActionPreference="Stop" (positionné en tête de script), ce
# spinner suffit à déclencher un NativeCommandError fatal malgré un exit code 0, que le
# flux soit redirigé (2>&1) ou non. On neutralise donc $ErrorActionPreference juste pour
# ces appels (commandes "containerapp", pas "container"/"storage" -- celles-ci n'ont pas
# ce spinner et ont fonctionné sans ce contournement plus haut dans le script).
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"

az containerapp job update -g $ResourceGroup -n $JobName --only-show-errors --output none `
    --set-env-vars "DUMP_FILENAME=$dumpFileName" "PURGE_BEFORE_IMPORT=$purgeValue" | Out-Null

Write-Host "       Declenchement du Job d'import..." -ForegroundColor DarkGray
$startResult = az containerapp job start -g $ResourceGroup -n $JobName -o json --only-show-errors | ConvertFrom-Json
$ErrorActionPreference = $prevEAP

$executionName = $startResult.name
if (-not $executionName) {
    Write-Host "  ERREUR : declenchement du Job echoue (pas de nom d'execution renvoye)." -ForegroundColor Red
    exit 1
}
Write-Host "  OK   Execution declenchee : $executionName" -ForegroundColor Green

# ── 3. Attente de la fin d'exécution (jusqu'à 10 min — replicaTimeout du Job) ────
Write-Host "       Attente de la fin de l'import (jusqu'à 10 min)…" -ForegroundColor DarkGray
$status = $null
$ErrorActionPreference = "Continue"
for ($i = 0; $i -lt 60; $i++) {
    $execution = az containerapp job execution show -g $ResourceGroup -n $JobName --job-execution-name $executionName `
        -o json --only-show-errors | ConvertFrom-Json
    $status = $execution.properties.status
    if ($status -in @('Succeeded', 'Failed')) { break }
    Start-Sleep -Seconds 10
}
$ErrorActionPreference = $prevEAP

if ($status -notin @('Succeeded', 'Failed')) {
    Write-Host "  !!   Import toujours en cours après 10 min (statut : $status) — verifiez plus tard :" -ForegroundColor Yellow
    Write-Host "       az containerapp job execution show -g $ResourceGroup -n $JobName --job-execution-name $executionName" -ForegroundColor DarkGray
    exit 0
}

# ── 4. Lecture du résultat (déposé par le Job dans le partage Azure Files) ──────
$tmpResult = "$env:TEMP\$executionName-result.json"
Remove-FileSafe $tmpResult
az storage file download --share-name $ShareName --account-name $StorageAccountName --account-key $storageKey `
    --path "$executionName-result.json" --dest $tmpResult --no-progress --output none --only-show-errors | Out-Null

if (-not (Test-Path $tmpResult)) {
    Write-Host "  !!   Job termine (statut $status) mais fichier de resultat introuvable." -ForegroundColor Yellow
    Write-Host "       Pas de sous-commande 'logs' pour les Container Apps Jobs (CLI) -- consultez" -ForegroundColor DarkGray
    Write-Host "       Log Analytics/Application Insights dans le portail Azure pour ce Job." -ForegroundColor DarkGray
    exit 0
}

$result = Get-Content $tmpResult -Raw | ConvertFrom-Json
Remove-FileSafe $tmpResult

if ($result.error) {
    Write-Host "  !!   Import échoué : $($result.error)" -ForegroundColor Yellow
    exit 0
}

if ($result.purge) {
    Write-Host "  OK   Base purgée : $($result.purge.committed)/$($result.purge.total) nœud(s)/relation(s) supprimé(s)" -ForegroundColor Green
}
Write-Host "  OK   Import terminé : $($result.import.nodes) nœuds, $($result.import.relationships) relations" -ForegroundColor Green
if ($result.fix_utf8 -and -not $result.fix_utf8.skipped) {
    Write-Host "  OK   Correctif UTF-8 appliqué : $($result.fix_utf8.fixed_count) nœud(s) Community corrigé(s)" -ForegroundColor Green
}

if ($tempBundle) { Remove-FileSafe $tempBundle }
