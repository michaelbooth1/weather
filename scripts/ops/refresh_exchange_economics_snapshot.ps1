# Fetches a content-bound International Polymarket exchange-economics snapshot.
#
# This script intentionally does not accept the baseline. Baseline acceptance is
# an audited operator action after reviewing material drift and any required
# paper-evidence rescoring.
#
# Every run (scheduled or manual) writes data\logs\exchange_economics_refresh_status.json
# atomically and appends the same record to exchange_economics_refresh_history.jsonl:
# status (PASS / FAIL / REFUSED / ERROR), exit_code, reason and the bounded tail of
# the collector's output. A nonzero task result is diagnosed from that file
# (Swarm P audit F1, 2026-10-07: two silent exit-1 runs).
#
# Run from the repo root:
#   .\scripts\ops\refresh_exchange_economics_snapshot.ps1

param(
    [string]$RepoRoot = "",
    [string]$TargetDate = (Get-Date).ToString("yyyy-MM-dd"),
    [string]$EventMetadata = "",
    [string]$Snapshot = "",
    [string]$Platform = "polymarket_global"
)

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 leaves $PSScriptRoot empty inside param() defaults
# under `powershell -File`; derive the default here. An explicit -RepoRoot wins.
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

$script:StatusPath = $null
$script:StartedUtc = (Get-Date).ToUniversalTime().ToString("o")

function Write-RefreshStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][int]$ExitCode,
        [Parameter(Mandatory = $true)][string]$Reason,
        [string[]]$OutputTail = @()
    )
    if (-not $script:StatusPath) { return }
    try {
        $record = [ordered]@{
            schema = "exchange_economics_refresh_status"
            schema_version = 1
            task = "WeatherExchangeEconomicsSnapshotRefresh"
            status = $Status
            exit_code = $ExitCode
            reason = $Reason
            target_date = $TargetDate
            platform = $Platform
            started_at_utc = $script:StartedUtc
            finished_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            pid = $PID
            output_tail = @($OutputTail)
        }
        $json = $record | ConvertTo-Json -Compress -Depth 4
        $directory = Split-Path -Parent $script:StatusPath
        $temporary = Join-Path $directory ("exchange_economics_refresh_status.{0}.tmp" -f $PID)
        [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporary -Destination $script:StatusPath -Force
        $history = Join-Path $directory "exchange_economics_refresh_history.jsonl"
        [IO.File]::AppendAllText($history, $json + "`n", (New-Object Text.UTF8Encoding($false)))
    }
    catch {
        # Status is diagnostic only; never mask the run's own exit code.
        Write-Warning ("could not write refresh status: {0}" -f $_.Exception.Message)
    }
}

trap {
    $message = [string]$_.Exception.Message
    Write-RefreshStatus -Status "ERROR" -ExitCode 1 -Reason ("unhandled: {0}" -f $message)
    Write-Error $message -ErrorAction Continue
    exit 1
}

$logDirectory = Join-Path $RepoRoot "data\logs"
if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
}
$script:StatusPath = Join-Path $logDirectory "exchange_economics_refresh_status.json"

if ($Platform -ne "polymarket_global") {
    Write-RefreshStatus -Status "REFUSED" -ExitCode 2 -Reason "platform '$Platform' is not polymarket_global"
    Write-Error "This host is International Polymarket only; refusing platform '$Platform'." -ErrorAction Continue
    exit 2
}

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-RefreshStatus -Status "REFUSED" -ExitCode 3 -Reason "venv python not found at $python"
    Write-Error "venv python not found at $python -- run from the repo with its venv created." -ErrorAction Continue
    exit 3
}

$arguments = @(
    "-m",
    "weather.market.exchange_economics",
    "collect-global",
    "--target-date",
    $TargetDate
)
if ($EventMetadata) {
    $arguments += @("--event-metadata", $EventMetadata)
}
if ($Snapshot) {
    $arguments += @("--snapshot", $Snapshot)
}

Push-Location $RepoRoot
try {
    # Native stderr lines arrive as ErrorRecords under Windows PowerShell 5.1;
    # keep them non-terminating so the exit code, not the first stderr line, decides.
    $ErrorActionPreference = "Continue"
    $output = @(& $python @arguments 2>&1 | ForEach-Object { "$_" })
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
}
finally {
    Pop-Location
}
$output | ForEach-Object { Write-Output $_ }
$tail = @($output | Select-Object -Last 40 | ForEach-Object {
    if ($_.Length -gt 1000) { $_.Substring(0, 1000) } else { $_ }
})
if ($null -eq $code) { $code = 1 }
if ($code -ne 0) {
    Write-RefreshStatus -Status "FAIL" -ExitCode $code -Reason "collector exited $code" -OutputTail $tail
    exit $code
}
Write-RefreshStatus -Status "PASS" -ExitCode 0 -Reason "snapshot collected" -OutputTail $tail
exit 0
