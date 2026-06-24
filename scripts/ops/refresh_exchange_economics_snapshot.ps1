# Publishes a current exchange-economics snapshot from the tracked template.
#
# This script intentionally does not accept the baseline. Baseline acceptance is
# an audited operator action after reviewing material drift and any required
# paper-evidence rescoring.
#
# Run from the repo root:
#   .\scripts\ops\refresh_exchange_economics_snapshot.ps1

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TargetDate = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd"),
    [string]$Template = "",
    [string]$Snapshot = "",
    [string]$Platform = "polymarket_us"
)

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv python not found at $python -- run from the repo with its venv created."
}

$arguments = @(
    "-m",
    "weather.market.exchange_economics",
    "publish",
    "--target-date",
    $TargetDate,
    "--platform",
    $Platform
)
if ($Template) {
    $arguments += @("--template", $Template)
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
