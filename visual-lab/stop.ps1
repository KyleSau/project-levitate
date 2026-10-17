# Stops only the processes started by start.ps1 (by PID) plus whatever listens on 8100 / 5174.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root "data\pids.json"
if (Test-Path $pidFile) {
    $p = Get-Content $pidFile | ConvertFrom-Json
    foreach ($id in @($p.api, $p.ui)) { if ($id) { & taskkill /PID $id /T /F 2>$null | Out-Null } }
    Remove-Item $pidFile
}
foreach ($port in 8100, 5174) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($x in $c) { Stop-Process -Id $x.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Write-Host "stopped visual-lab servers (ports 8100, 5174)"
