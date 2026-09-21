# Mission 2026-09-83b — Part A: finish the parser repair

**PARTIAL — implementation and 549 required regression checks pass; full-suite
and final qualification receipts pending.**

Branch `codex/nbm-target-fix-20260921`, continued exactly from
`e1b6639384d9f6a82608b3dee83b79dcc628eb0d`; its original master base is
`e28530af67c7371fc7b2c08bbd0e26cfe72a28f9`. Part B is independent. Section 3
decisions are accepted without reopening them. The source contract no longer
requires redundant manifest token columns or treats the old fetch budget or
the accepted known-defect parity BLOCK as a parser-repair blocker.

## A1 — stored diagnostics, never predictors

Chose the existing `FEATURE_DIAGNOSTIC_COLUMNS` category. Its consumers
`build_live_feature_record`, `audit_row` and captured-input feature replay
preserve these fields; `FEATURE_AUDIT_COLUMNS` is the complete serialized row,
including both diagnostics and predictors, so adding only there would lose
the fields before serialization. `empty_us_guidance_features` retains null
provenance on historical/absent rows. The NBM predictor list is restored to its
original 15 names. Both source-gate reports inherit that list without a report
code change. Tests exercise single-market and late-day training selectors for
all 12 markets, pooled feature/band matrices and all subset selectors, and both
source-gate feature inventories. No model is fitted or scored by those tests.

Keep v1.17: the durable persisted feature-row layout gains four diagnostics.
`src/weather/AGENTS.md` requires durable schemas to be registered and readers,
writers, migrations and tests updated together; the serialized audit contract
has changed even though the selectable vector has returned to its prior list.
The prior schema-registry change is not additive-only: v1.17 remains active
and v1.16 remains legacy. No artifact or trained selector was rewritten.

## A2/A3 — clock rejection and manifest replay

`NBPClockError` is a `ValueError` carrying the full unavailable payload, including
bytes, station/target identity, parser version, selected token and seven raw
values. Live capture catches only that error and returns a specific invalid,
naive or pre-issue timestamp reason; it does not substitute older guidance or
discard the other sources. Replay still raises. All three clocks are tested.

The real `SnapshotStore.write_forecast_payloads` writer plus the retained CAS
bytes reproduce a v2 07Z maximum, its group/token and seven raw values, a v2
13Z unavailable decision, and the v1 13Z wrong-period p50=72 with tomorrow's
12Z validity. The existing serialized extraction-identity JSON is decoded
before replay. `snapshot_store.py` is untouched.

## A4 — cycle reachability

The full standard/daylight hourly table and reproduction receipt follow below.
All four configured US timezones have a healthy reachable file for every local
hour. The search algorithm is unchanged. A 404 may exhaust the window late in
Pacific standard time; that is unavailable, not permission to use a wrong period.

## Checks and exclusions

Required combined 83a checks: **549 passed in 13.76 seconds**. The first focused
test run had three new-test failures because the manifest stores extraction
identity as JSON text; decoding it fixed the test caller. No replay, parity or
migration implementation/gate was relaxed. An initial wrapper launch refused a
busy shared lease; the unchanged admitted retry ran. Full-suite result pending.

No candidate, fit, retirement, re-score, forecast-skill claim, outcome read,
floor change, gate relaxation, artifact write, paid-provider request, credential
access, exchange call, production write, Scheduler registration, capture
restart or master merge. No new external weather request was made. Tests and
table generation use retained station fixtures and synthetic timestamps only.

## Reproduction

From this branch's worktree in PowerShell, use the project interpreter and the
repository-owned wrapper. Supply fresh, short `--basetemp` paths and remove only
those test directories after retaining results. Production qualification uses
the production host's own roll verdict and bounded suite, not these commands.

```powershell
$repo = (Get-Location).Path
$python = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
function Invoke-83b([string]$kind, [string[]]$tokens) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
        (ConvertTo-Json -InputObject $tokens -Compress)))
    & "$repo/scripts/ops/workstation_heavy.ps1" -Kind $kind -PythonPath $python `
        -ArgumentsBase64 $encoded -RepoRoot $repo
}
$prior = Get-Content docs/roadmap/nbm-target-fix-20260921/verification.json -Raw | ConvertFrom-Json
Invoke-83b pytest (@('-m','pytest','-q') + @($prior.test_files) + @('--basetemp','C:/tmp/83b-a-check'))
Invoke-83b pytest @('-m','pytest','-q','--basetemp','C:/tmp/83b-a-full')
Invoke-83b weather_heavy @('-m','tools.research.nbm_target_fix','window','--output',"$repo/scratch/83b-window-reproduce")
Invoke-83b weather_heavy @('-m','weather.reporting.scorecards.train_serve_feature_parity',
    '--input',"$repo/tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json",
    '--run-root',"$repo/scratch/83b-parity-reproduce")
Invoke-83b compileall @('-m','compileall','-q','app','src','tests','tools/research/nbm_target_fix.py')
& $python -m weather.operations.agent_docs_audit
& $python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
& "$repo/scripts/ops/roll_verdict.ps1" -RepoRoot $repo -Branch codex/nbm-target-fix-20260921 -Base origin/master
```
