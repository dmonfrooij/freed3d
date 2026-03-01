# FREE3D - Start
Set-Location $PSScriptRoot
if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "[FOUT] Run eerst: .\install.ps1" -ForegroundColor Red; Read-Host; exit 1
}
Write-Host "[*] FREE3D starten op http://localhost:8000 ..." -ForegroundColor Cyan
$root = $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root'; .\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir backend"
Start-Sleep 4
Start-Process "http://localhost:8000"
Write-Host "[OK] Klaar. Sluit het backend venster om te stoppen." -ForegroundColor Green
