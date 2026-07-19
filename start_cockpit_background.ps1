param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8765,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not $PythonPath) {
    if (Test-Path $bundledPython) {
        $PythonPath = $bundledPython
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonPath = "python"
    } else {
        throw "Python was not found. Set -PythonPath to a Python executable."
    }
}

# Some Codex/Windows sessions expose both PATH and Path, which breaks Start-Process.
# Keep the original path value so the bundled Python can still find its DLLs.
$pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
if (-not $pathValue) {
    $pathValue = [Environment]::GetEnvironmentVariable("PATH", "Process")
}
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")

function Test-CockpitAlreadyRunning {
    $healthUrl = "http://$HostName`:$Port/api/health"
    $rootUrl = "http://$HostName`:$Port/"
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

try {
    if (Test-CockpitAlreadyRunning) {
        Write-Host "Job Cockpit already running at http://$HostName`:$Port"
        exit 0
    }
} catch {
    # Not running yet.
}

$stdout = Join-Path $repoRoot "job_cockpit\server.out.log"
$stderr = Join-Path $repoRoot "job_cockpit\server.err.log"
$pidFile = Join-Path $repoRoot "job_cockpit\server.pid"

$process = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList @("job_cockpit\server.py", "--host", $HostName, "--port", [string]$Port) `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

Set-Content -Path $pidFile -Value $process.Id
Write-Host "Job Cockpit running at http://$HostName`:$Port"
Write-Host "PID: $($process.Id)"
