# Project Levitate - Visual Flight Physics Lab: one-command start (Windows PowerShell 5.1+)
#   API      http://127.0.0.1:8100   (FastAPI, docs at /docs)
#   UI       http://127.0.0.1:5174   (Vite dev server, proxies /api to 8100)
# Usage:  powershell -ExecutionPolicy Bypass -File visual-lab\start.ps1 [-Preview]
param([switch]$Preview)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"
$py = Join-Path $venv "Scripts\python.exe"
$data = Join-Path $root "data"
New-Item -ItemType Directory -Force $data | Out-Null
if (-not (Test-Path $py)) {
    Write-Host "creating venv in $venv"
    python -m venv $venv
    & $py -m pip install --upgrade pip
    & $py -m pip install -r (Join-Path $root "backend\requirements.txt")
}
$fe = Join-Path $root "frontend"
if (-not (Test-Path (Join-Path $fe "node_modules"))) {
    Push-Location $fe; npm install --no-audit --no-fund; Pop-Location
}
foreach ($port in 8100, 5174) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) { Write-Host "port $port already in use by PID $($c.OwningProcess) - run stop.ps1 first"; exit 1 }
}
$api = Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "vlab.api:app", "--host", "127.0.0.1", "--port", "8100" `
    -WorkingDirectory (Join-Path $root "backend") -RedirectStandardOutput (Join-Path $data "api.out.log") `
    -RedirectStandardError (Join-Path $data "api.err.log") -PassThru -WindowStyle Hidden
if ($Preview) {
    Push-Location $fe; npm run build; Pop-Location
    $uiCmd = "npm run preview > ..\data\ui.out.log 2>&1"
} else {
    $uiCmd = "npm run dev > ..\data\ui.out.log 2>&1"
}
$ui = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $uiCmd -WorkingDirectory $fe -PassThru -WindowStyle Hidden
@{ api = $api.Id; ui = $ui.Id } | ConvertTo-Json | Set-Content -Encoding ascii (Join-Path $data "pids.json")
Start-Sleep -Seconds 4
Write-Host "Visual Flight Physics Lab"
Write-Host "  UI   http://127.0.0.1:5174"
Write-Host "  API  http://127.0.0.1:8100/docs"
Write-Host "  logs $data\*.log ; stop with visual-lab\stop.ps1"
