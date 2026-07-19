$ErrorActionPreference = "Stop"

$schtasks = Join-Path $env:SystemRoot "System32\schtasks.exe"
$launcherDir = Join-Path $env:LOCALAPPDATA "JobCockpit"
$startupDir = [Environment]::GetFolderPath("Startup")

foreach ($taskName in @("JobCockpit-DailyReview", "JobCockpit-StartServerAtLogon")) {
    & $schtasks /Query /TN $taskName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        & $schtasks /Delete /TN $taskName /F | Out-Host
    } else {
        Write-Host "$taskName was not installed"
    }
}

foreach ($launcher in @(
    "job_cockpit_daily_review.ps1",
    "job_cockpit_start_server.ps1",
    "job_cockpit_daily_review.cmd",
    "job_cockpit_start_server.cmd"
)) {
    $path = Join-Path $launcherDir $launcher
    if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Force
        Write-Host "Removed $path"
    }
}

$startupCmd = Join-Path $startupDir "JobCockpit-StartServer.cmd"
if (Test-Path $startupCmd) {
    Remove-Item -LiteralPath $startupCmd -Force
    Write-Host "Removed $startupCmd"
}
