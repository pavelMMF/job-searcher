param(
    [string]$DailyReviewTime = "09:00"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$schtasks = Join-Path $env:SystemRoot "System32\schtasks.exe"
$launcherDir = Join-Path $env:LOCALAPPDATA "JobCockpit"
$startupDir = [Environment]::GetFolderPath("Startup")

$dailyScript = Join-Path $repoRoot "run_daily_review.ps1"
$serverScript = Join-Path $repoRoot "start_cockpit_background.ps1"

if (-not (Test-Path $dailyScript)) {
    throw "Daily review script not found: $dailyScript"
}
if (-not (Test-Path $serverScript)) {
    throw "Server startup script not found: $serverScript"
}

function Invoke-Schtasks {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = & $schtasks @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $output | Out-Host
    if ($exitCode -ne 0) {
        throw "schtasks.exe failed with exit code $exitCode"
    }
}

New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null

$dailyLauncher = Join-Path $launcherDir "job_cockpit_daily_review.ps1"
$serverLauncher = Join-Path $launcherDir "job_cockpit_start_server.ps1"

Set-Content -Path $dailyLauncher -Encoding UTF8 -Value "& '$dailyScript'"
Set-Content -Path $serverLauncher -Encoding UTF8 -Value "& '$serverScript'"

$dailyTaskRun = "$powershell -NoProfile -ExecutionPolicy Bypass -File $dailyLauncher"
Invoke-Schtasks -Arguments @(
    "/Create",
    "/TN", "JobCockpit-DailyReview",
    "/SC", "DAILY",
    "/ST", $DailyReviewTime,
    "/TR", $dailyTaskRun,
    "/RL", "LIMITED",
    "/F"
)

$startupCmd = Join-Path $startupDir "JobCockpit-StartServer.cmd"
Set-Content -Path $startupCmd -Encoding ASCII -Value @(
    "@echo off",
    "$powershell -NoProfile -ExecutionPolicy Bypass -File $serverLauncher"
)

Write-Host "Installed scheduled tasks:"
Write-Host "- JobCockpit-DailyReview at $DailyReviewTime"
Write-Host "Installed startup shortcut:"
Write-Host "- $startupCmd"
