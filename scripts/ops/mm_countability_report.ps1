<#
.SYNOPSIS
  Refresh the maker countable-day post-mortem.

.DESCRIPTION
  The MM gate cannot decide until enough maker days count toward the live-forward
  gate, so the countable-day YIELD is what sets the date the gate can rule. This
  keeps that number on disk instead of having it re-derived by hand.

  Light by construction: the post-mortem reads only the small
  preflight_remediation.json each maker run already writes, never the large
  per-run CSVs. Safe to run inside the graded capture window.
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

$md = Join-Path $outDir 'MM_COUNTABILITY.md'
$json = Join-Path $outDir 'mm_countability.json'

& $python -m weather.reporting.market.mm_countability_postmortem `
    --markdown-out $md --json-out $json
$code = $LASTEXITCODE
if ($code -ne 0) { throw "post-mortem exited $code" }

# Refresh the durable generated constants and the separate live scheduler view in the same
# pass. The latter belongs under ignored runtime state: committing a changing host timetable
# made the canonical document stale and dirtied the production tree every day.
# Never fail the countability report because either reference could not render.
try {
    & $python -m weather.operations.operating_reference `
        --out (Join-Path $RepoRoot 'docs\operations\OPERATING_REFERENCE.md') `
        --schedule-out (Join-Path $outDir 'OPERATING_SCHEDULE.md') | Out-Null
} catch {
    Write-Warning "operating reference refresh failed: $($_.Exception.Message)"
}

# Surface the number that matters in the task history itself.
$report = Get-Content $json -Raw | ConvertFrom-Json
$yield = if ($null -eq $report.countable_day_yield) { 'n/a' }
         else { '{0:P1}' -f $report.countable_day_yield }
$lastCounted = ($report.days | Where-Object { $_.counted } | Select-Object -Last 1).day
if (-not $lastCounted) { $lastCounted = 'never' }
"MM countable-day yield $yield ($($report.counted_days)/$($report.total_days)); last counted $lastCounted"
