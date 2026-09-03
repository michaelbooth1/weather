# Repository-owned launcher for the recurring paper-live-forward maker roll.
# Both scheduled tasks call this wrapper so their policy arguments cannot drift.
[CmdletBinding()]
param(
    [ValidateSet("start", "ensure")][string]$Verb = "ensure",
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Timezone = "America/Toronto",
    [string]$StartAfterLocalTime = "07:05",
    [string]$StartNoLaterThanLocalTime = "20:00",
    [string]$BudgetUsdc = "500",
    [string]$Mode = "paper-live-forward",
    [string]$Markets = "all",
    [int]$IntervalSeconds = 60,
    [double]$QuoteSize = 20.0,
    [double]$MaxBandNotional = 25.0,
    [double]$MaxEventNotional = 25.0,
    [long]$MinFreeBytes = 34359738368,
    [switch]$EnableMarketHarvestCompanion
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "production interpreter is missing: $python"
}
if ($Mode -ne "paper-live-forward") {
    throw "this recurring task wrapper is paper-only"
}

$arguments = @(
    "-m", "weather.operations.market_making_daily_roll", $Verb,
    "--timezone", $Timezone,
    "--budget-usdc", $BudgetUsdc,
    "--mode", $Mode,
    "--markets", $Markets,
    "--interval-seconds", [string]$IntervalSeconds,
    "--config", "quote_size=$QuoteSize",
    "--config", "max_band_notional=$MaxBandNotional",
    "--config", "max_event_notional=$MaxEventNotional",
    "--min-free-bytes", [string]$MinFreeBytes
)
if ($EnableMarketHarvestCompanion) {
    $arguments += "--enable-market-harvest-companion"
}
if ($Verb -eq "ensure") {
    $arguments += @(
        "--start-after-local-time", $StartAfterLocalTime,
        "--start-no-later-than-local-time", $StartNoLaterThanLocalTime
    )
}

$process = Start-Process -FilePath $python -ArgumentList $arguments `
    -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden
try { $process.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal } catch {}
exit 0
