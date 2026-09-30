<#
.SYNOPSIS
  Refresh the generated operating reference (formerly also the maker countable-day post-mortem).

.DESCRIPTION
  The paper maker was retired and its runtime code, including
  weather.reporting.market.mm_countability_postmortem, was deleted on 2026-09-29
  (110o part 3). data/alerts/MM_COUNTABILITY.md and mm_countability.json are no
  longer refreshed; the last copies on disk are archived evidence.

  The script is kept because its host-local scheduled task also refreshes the
  generated operating reference and the live scheduler view, which have no other
  scheduled owner. Retire or rename that task in a separate owner-ops review.
  Light by construction. Safe to run inside the graded capture window.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = 'C:\Users\micha\Desktop\github\weather'
)

$ErrorActionPreference = 'Stop'
Set-Location $RepoRoot

$python = Join-Path $RepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "python not found at $python" }

$outDir = Join-Path $RepoRoot 'data\alerts'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

# Refresh the durable generated constants and the separate live scheduler view.
# The latter belongs under ignored runtime state: committing a changing host timetable
# made the canonical document stale and dirtied the production tree every day.
# Never fail the task because either reference could not render.
try {
    & $python -m weather.operations.operating_reference `
        --out (Join-Path $RepoRoot 'docs\operations\OPERATING_REFERENCE.md') `
        --schedule-out (Join-Path $outDir 'OPERATING_SCHEDULE.md') | Out-Null
} catch {
    Write-Warning "operating reference refresh failed: $($_.Exception.Message)"
}

"MM countable-day post-mortem retired 2026-09-29 (paper maker runtime deleted); operating reference refreshed"
