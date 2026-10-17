# Project Levitate research lab launcher.
#   .\start.ps1          -> API + built UI on http://127.0.0.1:8000
#   .\start.ps1 -Dev     -> API on :8000 and Vite dev server on http://127.0.0.1:5173
param([switch]$Dev)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    python -m venv (Join-Path $root ".venv")
    & $py -m pip install --disable-pip-version-check -r (Join-Path $root "backend\requirements.txt")
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) { Push-Location (Join-Path $root "frontend"); npm install; Pop-Location }
if ($Dev) {
    Start-Process -WorkingDirectory (Join-Path $root "frontend") -FilePath "npm.cmd" -ArgumentList "run", "dev"
} elseif (-not (Test-Path (Join-Path $root "frontend\dist"))) {
    Push-Location (Join-Path $root "frontend"); npm run build; Pop-Location
}
Push-Location (Join-Path $root "backend")
& $py -m uvicorn levitate.api:app --host 127.0.0.1 --port 8000
Pop-Location
