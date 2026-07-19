param(
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

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = Join-Path $repoRoot "job_cockpit\core"

$logDir = Join-Path $repoRoot "job_cockpit\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "daily_review.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"

Add-Content -Path $logFile -Value "[$timestamp] Starting daily review"

Set-Location $repoRoot
& $PythonPath -c @"
import json
from storage import Store
from agents import run_agent

store = Store('job_cockpit/cockpit.db')
result = run_agent(store, 'wide_search')
print(json.dumps({
    'ok': result.ok,
    'message': result.message,
    'payload': result.payload,
}, ensure_ascii=False))
"@ 2>&1 | Tee-Object -FilePath $logFile -Append

$exitCode = $LASTEXITCODE
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
Add-Content -Path $logFile -Value "[$timestamp] Finished daily review with exit code $exitCode"
exit $exitCode
