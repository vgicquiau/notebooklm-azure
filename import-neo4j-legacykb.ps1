#Requires -Version 5.1
<#
.SYNOPSIS
    Upload du dump GraphML vers le conteneur neo4j-legacykb et import via APOC.

.DESCRIPTION
    Appelé automatiquement par deploy.ps1 après le déploiement Bicep (quand
    deployLegacyKb=true). Peut aussi être relancé seul à tout moment — après mise à
    jour du dump GraphML, ou pour repeupler une nouvelle instance neo4j-legacykb
    (nouveau -ProjectName, nouveau Resource Group...) — sans rien redéployer :

    1. Upload le fichier GraphML dans le partage Azure Files monté sur le conteneur.
    2. Attend que l'API HTTPS de Neo4j (port 7473) réponde (jusqu'à 3 minutes — le
       temps que le conteneur démarre et installe le plugin APOC).
    3. Exécute `CALL apoc.import.graphml(...)` via l'API transactionnelle HTTPS de Neo4j.

    -StorageAccountName et -Fqdn sont optionnels : si omis, ils sont découverts
    automatiquement depuis -ResourceGroup (recherche du conteneur ACI
    "aci-neo4j-legacykb-*" et de son volume Azure Files monté). Seul -ResourceGroup
    et -Neo4jPassword sont donc nécessaires dans le cas courant.

.PARAMETER ResourceGroup
    Resource Group contenant le storage account et le conteneur ACI neo4j-legacykb.

.PARAMETER StorageAccountName
    Nom du storage account dédié. Découvert automatiquement depuis -ResourceGroup si omis.

.PARAMETER ShareName
    Nom du partage Azure Files (défaut "neo4j-import").

.PARAMETER Fqdn
    FQDN du conteneur ACI (ex. neo4j-legacykb-nlmrep-prod.francecentral.azurecontainer.io).
    Découvert automatiquement depuis -ResourceGroup si omis.

.PARAMETER Neo4jPassword
    Mot de passe du compte neo4j (utilisateur fixe "neo4j"). Demandé interactivement si absent.

.PARAMETER DumpPath
    Chemin du fichier GraphML à importer. Défaut : docs/extract/repartition_cleaned_export.graphml.

.PARAMETER ProjectName
    Préfixe du projet (suffixe du conteneur "aci-neo4j-legacykb-<ProjectName>-<Environment>").
    Nécessaire seulement si -ResourceGroup contient plusieurs conteneurs neo4j-legacykb
    (ex. plusieurs déploiements successifs sous des noms de projet différents) — sinon le
    conteneur unique trouvé est utilisé automatiquement.

.PARAMETER Environment
    Suffixe d'environnement (défaut "prod"). Utilisé avec -ProjectName pour désambiguïser.

.PARAMETER SkipSSL
    Bypass SSL pour proxy d'entreprise (Zscaler, Forcepoint, etc.) — même mécanisme que deploy.ps1.

.EXAMPLE
    # Cas courant : un seul conteneur neo4j-legacykb dans le RG — tout est découvert
    # automatiquement, mot de passe demandé interactivement
    .\import-neo4j-legacykb.ps1 -ResourceGroup rg-sp5-d-vgi-azu-repart-nlm-txt -SkipSSL

.EXAMPLE
    # Plusieurs conteneurs neo4j-legacykb dans le meme RG (deploiements successifs) —
    # -ProjectName desambiguise lequel cibler
    .\import-neo4j-legacykb.ps1 -ResourceGroup rg-sp5-d-vgi-azu-repart-nlm-txt -ProjectName nlmrep -SkipSSL

.EXAMPLE
    # Paramètres explicites (instance non standard, ou découverte automatique indisponible)
    .\import-neo4j-legacykb.ps1 -ResourceGroup rg-nlmrep-prod `
        -StorageAccountName stneo4jkbnlmrepprod -ShareName neo4j-import `
        -Fqdn neo4j-legacykb-nlmrep-prod.francecentral.azurecontainer.io `
        -Neo4jPassword (Get-Content secret.txt)
#>
param(
    [Parameter(Mandatory)] [string]$ResourceGroup,
    [string]$StorageAccountName = "",
    [string]$ShareName = "neo4j-import",
    [string]$Fqdn = "",
    [string]$ProjectName = "",
    [string]$Environment = "prod",
    [SecureString]$Neo4jPassword,
    [string]$DumpPath = "",
    [switch]$SkipSSL
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

function ConvertFrom-SecureStringPlain([SecureString]$sec) {
    if ($null -eq $sec) { return "" }
    $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($ptr) }
    finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Remove-FileSafe([string]$Path) {
    # Remove-Item échoue sur les comptes Windows dont le nom contient un point (ex.
    # "v.gicquiau" -> %TEMP% en 8.3 short-name "V5C98~1.GIC") avec une PSArgumentException
    # qui bypass -ErrorAction. [System.IO.File]::Delete() contourne le provider PowerShell.
    try { [System.IO.File]::Delete($Path) } catch {}
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

# ── Découverte automatique du conteneur ACI et du storage account ──────────────
if (-not $Fqdn -or -not $StorageAccountName) {
    Write-Host "       Decouverte automatique du conteneur neo4j-legacykb dans '$ResourceGroup'..." -ForegroundColor DarkGray
    # Filtrage cote PowerShell (Where-Object) plutot que via --query JMESPath : une
    # chaine --query se terminant par "]" juste avant le guillemet fermant casse le
    # relais az.cmd -> python.exe sur ce poste (les guillemets entourant l'argument
    # disparaissent silencieusement, CMD.EXE choppe alors sur le "]" nu : "] etait inattendu").
    $allAci = az container list -g $ResourceGroup -o json 2>&1 | ConvertFrom-Json
    $candidates = @($allAci | Where-Object { $_.name -like 'aci-neo4j-legacykb*' })

    if ($candidates.Count -eq 0) {
        Write-Host "  ERREUR : aucun conteneur 'aci-neo4j-legacykb-*' trouve dans '$ResourceGroup'." -ForegroundColor Red
        Write-Host "           Precisez -Fqdn et -StorageAccountName manuellement." -ForegroundColor DarkGray
        exit 1
    } elseif ($candidates.Count -eq 1) {
        $aci = $candidates[0]
    } elseif ($ProjectName) {
        $expectedName = "aci-neo4j-legacykb-$ProjectName-$Environment"
        $aci = $candidates | Where-Object { $_.name -eq $expectedName } | Select-Object -First 1
        if (-not $aci) {
            Write-Host "  ERREUR : aucun conteneur nomme '$expectedName' parmi les $($candidates.Count) trouves :" -ForegroundColor Red
            foreach ($c in $candidates) { Write-Host "           - $($c.name)" -ForegroundColor DarkGray }
            exit 1
        }
    } else {
        Write-Host "  ERREUR : $($candidates.Count) conteneurs neo4j-legacykb trouves dans '$ResourceGroup' — ambigu :" -ForegroundColor Red
        foreach ($c in $candidates) { Write-Host "           - $($c.name)" -ForegroundColor DarkGray }
        Write-Host "           Precisez -ProjectName (et -Environment si different de 'prod'), ou -Fqdn directement." -ForegroundColor DarkGray
        exit 1
    }

    if (-not $Fqdn) {
        $Fqdn = $aci.ipAddress.fqdn
    }
    if (-not $StorageAccountName) {
        $aciDetail = az container show -g $ResourceGroup --name $aci.name -o json 2>&1 | ConvertFrom-Json
        $StorageAccountName = ($aciDetail.volumes |
            Where-Object { $_.azureFile.shareName -eq $ShareName } |
            Select-Object -First 1).azureFile.storageAccountName
    }
    Write-Host "  OK   Conteneur : $($aci.name)  |  FQDN : $Fqdn  |  Storage : $StorageAccountName" -ForegroundColor Green
}

if (-not $Fqdn -or -not $StorageAccountName) {
    Write-Host "  ERREUR : impossible de determiner Fqdn/StorageAccountName automatiquement." -ForegroundColor Red
    Write-Host "           Precisez-les explicitement via -Fqdn et -StorageAccountName." -ForegroundColor DarkGray
    exit 1
}

if ($null -eq $Neo4jPassword -or $Neo4jPassword.Length -eq 0) {
    Write-Host ""
    Write-Host "        Mot de passe neo4j-legacykb :" -ForegroundColor White
    $Neo4jPassword = Read-Host -AsSecureString "        Neo4j password"
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

# ── 1. Upload du dump dans le partage Azure Files ───────────────────────────────
# Upload via clé de compte — --auth-mode login nécessite soit le rôle "Storage File
# Data SMB Share Contributor" (insuffisant pour les gros fichiers sans
# --enable-file-backup-request-intent), soit "Storage File Data Privileged Contributor"
# (bypass ACL, rôle plus large). La clé de compte évite cette dépendance RBAC
# supplémentaire pour cette opération ponctuelle de mise en place — rôle Contributor
# (déjà nécessaire pour le reste du déploiement) suffit pour la lire.
$storageKey = az storage account keys list -g $ResourceGroup -n $StorageAccountName --query '[0].value' -o tsv 2>&1
az storage file upload --share-name $ShareName --account-name $StorageAccountName --account-key $storageKey `
    --no-progress `
    --source $DumpPath --path $dumpFileName --output none --only-show-errors 2>&1 | Out-Null
Write-Host "  OK   Dump GraphML uploadé : $StorageAccountName/$ShareName/$dumpFileName" -ForegroundColor Green

# ── 2. Attente disponibilité Neo4j (démarrage conteneur + installation APOC) ────
# HTTP (7474) désactivé — health check sur HTTPS (7473) avec cert auto-signé accepté.
#
# Note : un scriptblock PowerShell ({ $true }) comme ServerCertificateValidationCallback
# échoue par intermittence — .NET invoque ce callback sur un thread sans runspace
# PowerShell pendant le handshake TLS, ce qui fait planter le callback lui-même
# ("Il n'y a pas d'instance d'exécution disponible..."), et la connexion échoue
# silencieusement (SendFailure). Un délégué .NET compilé via Add-Type n'a pas ce
# problème puisqu'il ne dépend pas du moteur PowerShell à l'exécution.
if (-not ([System.Management.Automation.PSTypeName]'TrustAllCertsPolicy').Type) {
    Add-Type @"
using System.Net;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy {
    public static bool ValidationCallback(object sender, X509Certificate certificate, X509Chain chain, SslPolicyErrors sslPolicyErrors) {
        return true;
    }
}
"@
}
# Cast direct [Type]::Method peu fiable en PowerShell 5.1 pour les conversions
# méthode-vers-délégué — CreateDelegate via réflexion fonctionne de façon constante.
$TrustAllCertsCallback = [System.Delegate]::CreateDelegate(
    [System.Net.Security.RemoteCertificateValidationCallback],
    [TrustAllCertsPolicy].GetMethod('ValidationCallback')
)

Write-Host "       Attente démarrage de neo4j-legacykb (jusqu'à 3 min)…" -ForegroundColor DarkGray
$ready = $false
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = $TrustAllCertsCallback
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
$plainPass = ConvertFrom-SecureStringPlain $Neo4jPassword
if ([string]::IsNullOrWhiteSpace($plainPass)) {
    Write-Host "  ERREUR : mot de passe neo4j-legacykb vide." -ForegroundColor Red
    exit 1
}

$authPair = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("neo4j:$plainPass"))
$plainPass = $null  # Libère la référence dès que possible

$cypher = "CALL apoc.import.graphml('file:///var/lib/neo4j/import/$dumpFileName', {readLabels: true}) YIELD nodes, relationships RETURN nodes, relationships"
$body = @{ statements = @(@{ statement = $cypher }) } | ConvertTo-Json -Depth 5

# Le certificat Bolt/HTTPS est auto-signé (généré par deploy.ps1) — on désactive
# temporairement la validation TLS pour cet appel, puis on restaure avant de quitter.
$_origCallback = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = $TrustAllCertsCallback
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

    # ── 4. Correctif double-encodage UTF-8 des nœuds Community ──────────────────
    # apoc.import.graphml décode systématiquement les chaînes du GraphML en
    # Latin-1 au lieu d'UTF-8 (bug déterministe, indépendant du dump) — corrigé une
    # fois pour de bon ici plutôt que comme étape manuelle à chaque import.
    $fixUtf8Path = Join-Path $ProjectRoot "fix_utf8.cypher"
    if (Test-Path $fixUtf8Path) {
        # Get-Content -Raw attache des NoteProperties caches (PSPath, ReadCount...) a la
        # chaine renvoyee -- ConvertTo-Json les serialise alors aussi, encapsulant le texte
        # sous une cle "value" au lieu d'une simple chaine ("Could not map the incoming
        # JSON" cote Neo4j). La ré-interpolation "$(...)" force une chaine .NET neuve, sans
        # cette decoration PSObject.
        $fixCypherText = "$(Get-Content $fixUtf8Path -Raw -Encoding UTF8)"
        $fixBody = @{ statements = @(@{ statement = $fixCypherText }) } | ConvertTo-Json -Depth 5
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $TrustAllCertsCallback
        try {
            $fixResp = Invoke-RestMethod -Uri "https://${Fqdn}:7473/db/neo4j/tx/commit" -Method Post `
                -Headers @{ Authorization = "Basic $authPair"; "Content-Type" = "application/json; charset=utf-8" } `
                -Body ([System.Text.Encoding]::UTF8.GetBytes($fixBody)) -TimeoutSec 60
            $fixedCount = $fixResp.results[0].data[0].row[0]
            Write-Host "  OK   Correctif UTF-8 appliqué : $fixedCount nœud(s) Community corrigé(s)" -ForegroundColor Green
        } catch {
            Write-Host "  !!   Correctif UTF-8 échoué : $($_.Exception.Message)" -ForegroundColor Yellow
        } finally {
            [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $null
        }
    }
}

$authPair = $null
if ($tempBundle) { Remove-FileSafe $tempBundle }
