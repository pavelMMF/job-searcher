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

Set-Location $repoRoot
& $PythonPath "job_cockpit\server.py" --host $HostName --port $Port
