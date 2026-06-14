# Starts the Streamlit dashboard and opens the Operations page.
#
# The durable loops are supervised separately by Windows Task Scheduler. This
# launcher is intentionally just the human-facing dashboard entrypoint.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [int]$Port = 8501,
    [switch]$NoBrowser
)

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv python not found at $python -- run setup first."
}

$dataDir = Join-Path $RepoRoot "data"
$logDir = Join-Path $dataDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdoutLog = Join-Path $logDir "streamlit_stdout.log"
$stderrLog = Join-Path $logDir "streamlit_stderr.log"

$isListening = $false
try {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    $isListening = $null -ne $listener
} catch {
    $isListening = $false
}

if (-not $isListening) {
    $arguments = @(
        "-m", "streamlit", "run", "app.py",
        "--server.port", "$Port",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false"
    )
    Start-Process `
        -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog | Out-Null
    Start-Sleep -Seconds 2
}

$url = "http://localhost:$Port/?market=ops"
if (-not $NoBrowser) {
    Start-Process $url | Out-Null
}

Write-Host "Weather dashboard: $url"
Write-Host "Streamlit logs: $stdoutLog / $stderrLog"
