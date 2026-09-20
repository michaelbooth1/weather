# Starts the Streamlit dashboard and opens the read-only Control Room.
#
# The durable loops are supervised separately by Windows Task Scheduler. This
# launcher is intentionally just the human-facing dashboard entrypoint.

param(
    [string]$RepoRoot = "",
    [string]$PythonPath = "",
    [string]$DataRepoRoot = "",
    [string]$AttemptRoot = "",
    [string]$CaptureStatusPath = "",
    [string]$PortableStatusPath = "",
    [int]$Port = 8501,
    [switch]$NoBrowser
)

if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$python = if ($PythonPath) { $PythonPath } else { Join-Path $RepoRoot "venv\Scripts\python.exe" }
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
    $monitorSources = @{
        WEATHER_MONITOR_DATA_REPO = $DataRepoRoot
        WEATHER_MONITOR_ATTEMPT_ROOT = $AttemptRoot
        WEATHER_MONITOR_CAPTURE_STATUS = $CaptureStatusPath
        WEATHER_MONITOR_PORTABLE_STATUS = $PortableStatusPath
    }
    foreach ($entry in $monitorSources.GetEnumerator()) {
        if ($entry.Value) {
            if (-not [IO.Path]::IsPathRooted($entry.Value)) { throw "Monitor source must be absolute: $($entry.Key)" }
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
        }
    }
    $arguments = @(
        "-m", "streamlit", "run", "app/streamlit_app.py",
        "--server.address", "127.0.0.1",
        "--server.port", "$Port",
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
        "--browser.gatherUsageStats", "false"
    )
    # BelowNormal so the dashboard yields to the capture loops. This host is
    # memory- and CPU-constrained, the loops run at AboveNormal, and a capture
    # gap costs a streak day; a slower page render costs nothing.
    $proc = Start-Process `
        -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    try {
        $proc.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
    } catch {
        Write-Host "warning: could not set BelowNormal priority: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 2
}

$url = "http://localhost:$Port/?market=control"
if (-not $NoBrowser) {
    Start-Process $url | Out-Null
}

Write-Host "Weather dashboard: $url"
Write-Host "Streamlit logs: $stdoutLog / $stderrLog"
