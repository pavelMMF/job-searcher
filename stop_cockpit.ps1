param(
    [int]$Port = 8765
)

$ErrorActionPreference = "SilentlyContinue"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $repoRoot "job_cockpit\server.pid"

if (Test-Path $pidFile) {
    $pidValue = Get-Content $pidFile | Select-Object -First 1
    if ($pidValue) {
        Stop-Process -Id ([int]$pidValue) -Force
        Remove-Item $pidFile -Force
        Write-Host "Stopped Job Cockpit PID $pidValue"
        exit 0
    }
}

$connection = Get-NetTCPConnection -LocalPort $Port | Select-Object -First 1
if ($connection) {
    Stop-Process -Id $connection.OwningProcess -Force
    Write-Host "Stopped Job Cockpit on port $Port"
} else {
    Write-Host "No Job Cockpit process found on port $Port"
}
