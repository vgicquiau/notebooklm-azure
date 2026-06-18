# start-dev.ps1 — Lance le serveur NotebookLM Azure en local
# Usage : depuis VS Code (Ctrl+Shift+B) ou directement dans un terminal PowerShell
#
# -SkipSSL : sur poste avec proxy d'entreprise (Zscaler, Forcepoint...) qui intercepte le TLS,
#            les appels HTTPS du SDK Azure (requests/certifi) échouent avec
#            CERTIFICATE_VERIFY_FAILED. Ce mode injecte les certificats racine Zscaler du
#            store Windows dans le bundle certifi du venv (même traitement que
#            deploy.ps1 -SkipSSL, rejouable indépendamment si le venv est recréé).
#   .\start-dev.ps1 -SkipSSL

param(
    [switch]$SkipSSL
)

$ProjectRoot  = $PSScriptRoot
$VenvActivate = Join-Path $ProjectRoot "api\.venv\Scripts\Activate.ps1"
$VenvPython   = Join-Path $ProjectRoot "api\.venv\Scripts\python.exe"

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

if ($SkipSSL) {
    Write-Host "  Mode SSL : bypass active (proxy entreprise)" -ForegroundColor Yellow
    $venvCertifi = & $VenvPython -c "import certifi; print(certifi.where())"

    $alreadyInjected = (Test-Path $venvCertifi) -and (Select-String -Path $venvCertifi -Pattern "Zscaler Root CA" -Quiet)
    if ($alreadyInjected) {
        Write-Host "  Certificats Zscaler deja presents dans certifi (venv)" -ForegroundColor DarkGray
    } else {
        $zscalerCerts = @(Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
            Where-Object { $_.Subject -match "Zscaler" })
        if ($zscalerCerts.Count -gt 0) {
            foreach ($cert in $zscalerCerts) {
                $pem = "# Zscaler Root CA (thumbprint $($cert.Thumbprint))`n" +
                       "-----BEGIN CERTIFICATE-----`n" +
                       [Convert]::ToBase64String($cert.Export('Cert'), 'InsertLineBreaks') +
                       "`n-----END CERTIFICATE-----`n"
                Add-Content -Path $venvCertifi -Value $pem -Encoding ascii
            }
            Write-Host "  $($zscalerCerts.Count) certificat(s) Zscaler injecte(s) dans certifi (venv)" -ForegroundColor Green
        } else {
            Write-Host "  Aucun certificat Zscaler trouve dans le store Windows" -ForegroundColor Yellow
        }
    }
    Write-Host ""
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
