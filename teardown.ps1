#Requires -Version 5.1
<#
.SYNOPSIS
    Supprime toutes les ressources Azure NotebookLM et nettoie l'environnement local.

.PARAMETER ProjectName
    Préfixe du projet utilisé lors du deploy.ps1 (défaut : nlmazure).

.PARAMETER Force
    Supprime sans demander confirmation.

.EXAMPLE
    .\teardown.ps1

.EXAMPLE
    .\teardown.ps1 -ProjectName monprojet -Force
#>
param(
    [string]$ProjectName = "nlmazure",
    [switch]$Force
)

$rg = "rg-$ProjectName-prod"

Write-Host ""
Write-Host "  NotebookLM Azure — Suppression" -ForegroundColor Red
Write-Host "  ══════════════════════════════" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Resource Group ciblé : $rg" -ForegroundColor White
Write-Host ""
Write-Host "  Ressources qui seront supprimées :" -ForegroundColor Yellow
Write-Host "  - Azure OpenAI (déploiements GPT-4o + Embeddings)" -ForegroundColor DarkGray
Write-Host "  - Azure AI Search (index notebooklm-chunks)" -ForegroundColor DarkGray
Write-Host "  - Azure Document Intelligence" -ForegroundColor DarkGray
Write-Host "  - Azure Key Vault" -ForegroundColor DarkGray
Write-Host "  - Azure Blob Storage" -ForegroundColor DarkGray
Write-Host "  - Container Registry" -ForegroundColor DarkGray
Write-Host "  - Container App + environnement" -ForegroundColor DarkGray
Write-Host "  - Application Insights + Log Analytics" -ForegroundColor DarkGray
Write-Host ""

if (-not $Force) {
    $confirm = Read-Host "  Tapez 'SUPPRIMER' pour confirmer (ou Entrée pour annuler)"
    if ($confirm -ne 'SUPPRIMER') {
        Write-Host "  Annulé." -ForegroundColor Green
        Write-Host ""
        exit 0
    }
}

# Vérifier que le RG existe
$exists = az group exists --name $rg 2>&1
if ($exists -ne 'true') {
    Write-Host "  Resource Group '$rg' introuvable — rien à supprimer." -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

Write-Host ""
Write-Host "  Suppression en cours…" -ForegroundColor Red
az group delete --name $rg --yes --no-wait --only-show-errors 2>&1 | Out-Null

Write-Host "  La suppression s'exécute en arrière-plan (5-10 min)." -ForegroundColor DarkGray
Write-Host "  Suivre la progression : Portail Azure → Resource Groups → $rg" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Fichiers locaux à supprimer manuellement si souhaité :" -ForegroundColor White
Write-Host "  - .env          (contient vos endpoints Azure)" -ForegroundColor DarkGray
Write-Host "  - api\.venv\    (virtualenv Python)" -ForegroundColor DarkGray
Write-Host ""
