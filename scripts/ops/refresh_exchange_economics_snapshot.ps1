# Fetches a content-bound International Polymarket exchange-economics snapshot.
#
# This script intentionally does not accept the baseline. Baseline acceptance is
# an audited operator action after reviewing material drift and any required
# paper-evidence rescoring.
#
# Run from the repo root:
#   .\scripts\ops\refresh_exchange_economics_snapshot.ps1

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TargetDate = (Get-Date).ToString("yyyy-MM-dd"),
    [string]$EventMetadata = "",
    [string]$Snapshot = "",
    [string]$Platform = "polymarket_global"
)

if ($Platform -ne "polymarket_global") {
    throw "This host is International Polymarket only; refusing platform '$Platform'."
}

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv python not found at $python -- run from the repo with its venv created."
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
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
