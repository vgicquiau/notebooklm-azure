# start-dev.ps1 — Lance le serveur NotebookLM Azure en local
# Usage : depuis VS Code (Ctrl+Shift+B) ou directement dans un terminal PowerShell

$ProjectRoot  = $PSScriptRoot
$VenvActivate = Join-Path $ProjectRoot "api\.venv\Scripts\Activate.ps1"

if (-not (Test-Path $VenvActivate)) {
    Write-Host ""
    Write-Host "  ERREUR : venv introuvable." -ForegroundColor Red
    Write-Host "  Crée-le avec :" -ForegroundColor Yellow
    Write-Host "    cd notebooklm-azure" -ForegroundColor Yellow
    Write-Host "    python -m venv api\.venv" -ForegroundColor Yellow
    Write-Host "    api\.venv\Scripts\pip install -r api\requirements.txt" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

. $VenvActivate

# Ouvre le navigateur après 2.5s pendant que le serveur démarre
$null = Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2.5
    Start-Process "http://127.0.0.1:8000"
}

Write-Host ""
Write-Host "  NotebookLM Azure" -ForegroundColor Green
Write-Host "  http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "  Ctrl+C pour arreter" -ForegroundColor DarkGray
Write-Host ""

Set-Location $ProjectRoot
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
