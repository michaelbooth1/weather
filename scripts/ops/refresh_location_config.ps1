# Refreshes the generated Polymarket event-metadata config from live data.
#
# Regenerates config/location_market_events.json so the collection loops always
# hold the current and upcoming daily temperature-market events plus their CLOB
# token maps. When this config goes stale the loops have no tokens to capture
# once the market day rolls past the last pre-loaded event -- the root cause of
# the 2026-06-29 capture gap (config had not been refreshed since 2026-06-27 and
# lacked the june-29 events).
#
# Run from the repo root:
#   .\scripts\ops\refresh_location_config.ps1

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Locations = "config/locations.json",
    [string]$EventMetadata = "config/location_market_events.json"
)

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv python not found at $python -- run from the repo with its venv created."
}

$arguments = @(
    "-m",
    "weather.operations.location_config_refresh",
    "--locations",
    $Locations,
    "--event-metadata",
    $EventMetadata
)

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
