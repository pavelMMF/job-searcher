param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $repoRoot "start_cockpit_background.ps1"
$url = "http://$HostName`:$Port"
$healthUrl = "$url/api/health"
$rootUrl = "$url/"
$logPath = Join-Path $repoRoot "job_cockpit\launcher.log"

function Write-LaunchLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Encoding UTF8 -Value "[$timestamp] $Message"
}

if (-not (Test-Path $startScript)) {
    throw "Cannot find start script: $startScript"
}

Write-LaunchLog "Starting Job Cockpit launcher for $url"
& powershell -NoProfile -ExecutionPolicy Bypass -File $startScript -HostName $HostName -Port $Port | Out-Null

function Test-CockpitReady {
    try {
        Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $rootUrl -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            return $false
        }
    }
}

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    if (Test-CockpitReady) {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) {
    Write-LaunchLog "Server did not become ready at $healthUrl"
    throw "Job Cockpit did not become ready at $healthUrl"
}
Write-LaunchLog "Server is ready at $healthUrl"

$programFiles = [Environment]::GetFolderPath("ProgramFiles")
$programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
$browserCandidates = @()
if ($programFiles) {
    $browserCandidates += Join-Path $programFiles "Microsoft\Edge\Application\msedge.exe"
}
if ($programFilesX86) {
    $browserCandidates += Join-Path $programFilesX86 "Microsoft\Edge\Application\msedge.exe"
}
$browserCandidates += Join-Path $env:LOCALAPPDATA "Microsoft\Edge\Application\msedge.exe"
$browserCandidates += Join-Path $programFiles "Google\Chrome\Application\chrome.exe"
if ($programFilesX86) {
    $browserCandidates += Join-Path $programFilesX86 "Google\Chrome\Application\chrome.exe"
}
$browserCandidates += Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe"

foreach ($appPath in @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
)) {
    $entry = Get-ItemProperty -Path $appPath -ErrorAction SilentlyContinue
    if ($entry) {
        $defaultPath = $entry."(default)"
        if ($defaultPath) {
            $browserCandidates += $defaultPath
        }
    }
}

$browser = $browserCandidates | ForEach-Object { $_.Trim('"') } | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) {
    $edgeCommand = Get-Command msedge.exe -ErrorAction SilentlyContinue
    $chromeCommand = Get-Command chrome.exe -ErrorAction SilentlyContinue
    if ($edgeCommand) {
        $browser = $edgeCommand.Source
    } elseif ($chromeCommand) {
        $browser = $chromeCommand.Source
    }
}

if (-not $browser) {
    Write-LaunchLog "Microsoft Edge or Google Chrome was not found."
    throw "Microsoft Edge or Google Chrome was not found."
}
Write-LaunchLog "Using browser: $browser"

$appProfile = Join-Path $env:LOCALAPPDATA "JobCockpit\cockpit_app_v2"
New-Item -ItemType Directory -Force -Path $appProfile | Out-Null
Write-LaunchLog "Using app profile: $appProfile"

$cachePaths = @(
    (Join-Path $appProfile "Default\Cache"),
    (Join-Path $appProfile "Default\Code Cache"),
    (Join-Path $appProfile "Default\GPUCache"),
    (Join-Path $appProfile "Default\Service Worker\CacheStorage"),
    (Join-Path $appProfile "Default\Service Worker\ScriptCache"),
    (Join-Path $appProfile "GPUCache"),
    (Join-Path $appProfile "ShaderCache"),
    (Join-Path $appProfile "GrShaderCache")
)
foreach ($cachePath in $cachePaths) {
    if (Test-Path $cachePath) {
        Remove-Item -LiteralPath $cachePath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Start-Process -FilePath $browser -ArgumentList @(
    "--app=$url",
    "--user-data-dir=$appProfile",
    "--window-size=1440,980",
    "--disable-gpu",
    "--disable-features=CalculateNativeWinOcclusion,msEdgeStartupBoost",
    "--no-first-run"
)
Write-LaunchLog "Launched app window for $url"
exit 0
