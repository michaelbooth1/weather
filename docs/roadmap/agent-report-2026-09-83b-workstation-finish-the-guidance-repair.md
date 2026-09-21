# Mission 2026-09-83b — Part A: finish the parser repair

**PARTIAL — parser requirements are implemented; the full suite has two
unresolved inventory/admission-contract failures. Final focused receipts follow
below. No failing gate was relaxed.**

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
The age diagnostic also prefers a supplied `cycle_age_at_use_hours` (Part B)
while preserving the parser's original-capture age in the raw wrapper. Absent
that optional field it keeps the existing behavior; there is no branch dependency.

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
migration implementation/gate was relaxed. Wrapper launches refused a busy
shared lease and were retried through admission without disturbing its holder.

The full suite at implementation commit `d4f82289` returned **6,100 passed,
34 skipped, 2 failed, 923 subtests passed**, one existing NumPy/netCDF4 binary-ABI
warning, in **2,748.32 seconds**. The final optional use-age preference and its
one additional test were added afterward; the final focused receipt identifies
that later coverage. The full suite was not silently described as an all-green
final-tip run. The two retained failures are:

| Failing test | Cause and exact remaining repair |
| --- | --- |
| `test_research_inventory_covers_every_script` | The 83a tool `nbm_target_fix.py` is missing from `tools/research/research_harness.py::SCRIPT_INVENTORY`. That registry is outside this mission's owned files. Its owner must register the tool with a network-free smoke. |
| `test_workstation_offline_allowlist_narrowly_admits_cold_archive_stage_and_restore` | The test requires every module to start with `weather.`, contradicting the 83a exact `tools.research.nbm_target_fix` admission exception. An owner must reconcile that contract and `tests/operations/test_workload_admission_script.py:330`; this mission did not relax the assertion or broaden admission. |

The unchanged replay, migration and parity regression tests passed in the
combined required run. These full-suite failures keep this handback PARTIAL;
neither the withdrawn download budget nor the accepted known-defect parity
BLOCK is reinstated as a blocker.

No candidate, fit, retirement, re-score, forecast-skill claim, outcome read,
floor change, gate relaxation, artifact write, paid-provider request, credential
access, exchange call, production write, Scheduler registration, capture
restart or master merge. No new external weather request was made. Tests and
table generation use retained station fixtures and synthetic timestamps only.

## Reproduction

Implementation commits: `d4f82289` and final code `3bb23a0c`.
[Full-suite failure receipt](nbm-finish-83b/full-suite.json) retains both exact
failures. [Roll tool output](nbm-finish-83b/roll-verdict.txt) is
**UNDECIDABLE: no live closure evidence**, exit 1; all four status files are
absent. The [per-file inventory](nbm-finish-83b/roll-inventory.json) leaves
closure memberships null. Treat this branch as roll-sensitive and obtain the
production host's own verdict and bounded suite before quiet-window adoption.
The three completed mission pytest basetemp directories were removed after
retaining receipts; source fixtures and archived weather bytes remain intact.

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
& "$repo/scripts/ops/roll_verdict.ps1" -Branch codex/nbm-target-fix-20260921 -Base origin/master
```

## A4 hourly table

Reproduced by the admitted `window` command: 192 rows, zero healthy unavailable hours. The [CSV](nbm-finish-83b/window.csv) records full timestamps. Each cell is `healthy cycle / age hours -> next cycle / age hours` after a 404. All cycle hours are UTC on target date D. Ages are at the beginning of each local hour; minutes add to the age within that hour. These are eligible cycle candidates, not a claim that a just-issued file is already published.

### standard time (2026-01-17)

| Local hour | Eastern | Central | Mountain | Pacific |
| --- | --- | --- | --- | --- |
| 00 | 01Z / 4 -> 00Z / 5 | 01Z / 5 -> 00Z / 6 | 07Z / 0 -> 01Z / 6 | 07Z / 1 -> 01Z / 7 |
| 01 | 01Z / 5 -> 00Z / 6 | 07Z / 0 -> 01Z / 6 | 07Z / 1 -> 01Z / 7 | 07Z / 2 -> 01Z / 8 |
| 02 | 07Z / 0 -> 01Z / 6 | 07Z / 1 -> 01Z / 7 | 07Z / 2 -> 01Z / 8 | 07Z / 3 -> 01Z / 9 |
| 03 | 07Z / 1 -> 01Z / 7 | 07Z / 2 -> 01Z / 8 | 07Z / 3 -> 01Z / 9 | 07Z / 4 -> 01Z / 10 |
| 04 | 07Z / 2 -> 01Z / 8 | 07Z / 3 -> 01Z / 9 | 07Z / 4 -> 01Z / 10 | 07Z / 5 -> 01Z / 11 |
| 05 | 07Z / 3 -> 01Z / 9 | 07Z / 4 -> 01Z / 10 | 07Z / 5 -> 01Z / 11 | 07Z / 6 -> 01Z / 12 |
| 06 | 07Z / 4 -> 01Z / 10 | 07Z / 5 -> 01Z / 11 | 07Z / 6 -> 01Z / 12 | 07Z / 7 -> 01Z / 13 |
| 07 | 07Z / 5 -> 01Z / 11 | 07Z / 6 -> 01Z / 12 | 07Z / 7 -> 01Z / 13 | 07Z / 8 -> 01Z / 14 |
| 08 | 07Z / 6 -> 01Z / 12 | 07Z / 7 -> 01Z / 13 | 07Z / 8 -> 01Z / 14 | 07Z / 9 -> 01Z / 15 |
| 09 | 07Z / 7 -> 01Z / 13 | 07Z / 8 -> 01Z / 14 | 07Z / 9 -> 01Z / 15 | 07Z / 10 -> 01Z / 16 |
| 10 | 07Z / 8 -> 01Z / 14 | 07Z / 9 -> 01Z / 15 | 07Z / 10 -> 01Z / 16 | 07Z / 11 -> 01Z / 17 |
| 11 | 07Z / 9 -> 01Z / 15 | 07Z / 10 -> 01Z / 16 | 07Z / 11 -> 01Z / 17 | 07Z / 12 -> 01Z / 18 |
| 12 | 07Z / 10 -> 01Z / 16 | 07Z / 11 -> 01Z / 17 | 07Z / 12 -> 01Z / 18 | 07Z / 13 -> 01Z / 19 |
| 13 | 07Z / 11 -> 01Z / 17 | 07Z / 12 -> 01Z / 18 | 07Z / 13 -> 01Z / 19 | 07Z / 14 -> 01Z / 20 |
| 14 | 07Z / 12 -> 01Z / 18 | 07Z / 13 -> 01Z / 19 | 07Z / 14 -> 01Z / 20 | 07Z / 15 -> 01Z / 21 |
| 15 | 07Z / 13 -> 01Z / 19 | 07Z / 14 -> 01Z / 20 | 07Z / 15 -> 01Z / 21 | 07Z / 16 -> 01Z / 22 |
| 16 | 07Z / 14 -> 01Z / 20 | 07Z / 15 -> 01Z / 21 | 07Z / 16 -> 01Z / 22 | 07Z / 17 -> 01Z / 23 |
| 17 | 07Z / 15 -> 01Z / 21 | 07Z / 16 -> 01Z / 22 | 07Z / 17 -> 01Z / 23 | 07Z / 18 -> 01Z / 24 |
| 18 | 07Z / 16 -> 01Z / 22 | 07Z / 17 -> 01Z / 23 | 07Z / 18 -> 01Z / 24 | 07Z / 19 -> unavailable |
| 19 | 07Z / 17 -> 01Z / 23 | 07Z / 18 -> 01Z / 24 | 07Z / 19 -> unavailable | 07Z / 20 -> unavailable |
| 20 | 07Z / 18 -> 01Z / 24 | 07Z / 19 -> unavailable | 07Z / 20 -> unavailable | 07Z / 21 -> unavailable |
| 21 | 07Z / 19 -> unavailable | 07Z / 20 -> unavailable | 07Z / 21 -> unavailable | 07Z / 22 -> unavailable |
| 22 | 07Z / 20 -> unavailable | 07Z / 21 -> unavailable | 07Z / 22 -> unavailable | 07Z / 23 -> unavailable |
| 23 | 07Z / 21 -> unavailable | 07Z / 22 -> unavailable | 07Z / 23 -> unavailable | 07Z / 24 -> unavailable |

### daylight time (2026-09-17)

| Local hour | Eastern | Central | Mountain | Pacific |
| --- | --- | --- | --- | --- |
| 00 | 01Z / 3 -> 00Z / 4 | 01Z / 4 -> 00Z / 5 | 01Z / 5 -> 00Z / 6 | 07Z / 0 -> 01Z / 6 |
| 01 | 01Z / 4 -> 00Z / 5 | 01Z / 5 -> 00Z / 6 | 07Z / 0 -> 01Z / 6 | 07Z / 1 -> 01Z / 7 |
| 02 | 01Z / 5 -> 00Z / 6 | 07Z / 0 -> 01Z / 6 | 07Z / 1 -> 01Z / 7 | 07Z / 2 -> 01Z / 8 |
| 03 | 07Z / 0 -> 01Z / 6 | 07Z / 1 -> 01Z / 7 | 07Z / 2 -> 01Z / 8 | 07Z / 3 -> 01Z / 9 |
| 04 | 07Z / 1 -> 01Z / 7 | 07Z / 2 -> 01Z / 8 | 07Z / 3 -> 01Z / 9 | 07Z / 4 -> 01Z / 10 |
| 05 | 07Z / 2 -> 01Z / 8 | 07Z / 3 -> 01Z / 9 | 07Z / 4 -> 01Z / 10 | 07Z / 5 -> 01Z / 11 |
| 06 | 07Z / 3 -> 01Z / 9 | 07Z / 4 -> 01Z / 10 | 07Z / 5 -> 01Z / 11 | 07Z / 6 -> 01Z / 12 |
| 07 | 07Z / 4 -> 01Z / 10 | 07Z / 5 -> 01Z / 11 | 07Z / 6 -> 01Z / 12 | 07Z / 7 -> 01Z / 13 |
| 08 | 07Z / 5 -> 01Z / 11 | 07Z / 6 -> 01Z / 12 | 07Z / 7 -> 01Z / 13 | 07Z / 8 -> 01Z / 14 |
| 09 | 07Z / 6 -> 01Z / 12 | 07Z / 7 -> 01Z / 13 | 07Z / 8 -> 01Z / 14 | 07Z / 9 -> 01Z / 15 |
| 10 | 07Z / 7 -> 01Z / 13 | 07Z / 8 -> 01Z / 14 | 07Z / 9 -> 01Z / 15 | 07Z / 10 -> 01Z / 16 |
| 11 | 07Z / 8 -> 01Z / 14 | 07Z / 9 -> 01Z / 15 | 07Z / 10 -> 01Z / 16 | 07Z / 11 -> 01Z / 17 |
| 12 | 07Z / 9 -> 01Z / 15 | 07Z / 10 -> 01Z / 16 | 07Z / 11 -> 01Z / 17 | 07Z / 12 -> 01Z / 18 |
| 13 | 07Z / 10 -> 01Z / 16 | 07Z / 11 -> 01Z / 17 | 07Z / 12 -> 01Z / 18 | 07Z / 13 -> 01Z / 19 |
| 14 | 07Z / 11 -> 01Z / 17 | 07Z / 12 -> 01Z / 18 | 07Z / 13 -> 01Z / 19 | 07Z / 14 -> 01Z / 20 |
| 15 | 07Z / 12 -> 01Z / 18 | 07Z / 13 -> 01Z / 19 | 07Z / 14 -> 01Z / 20 | 07Z / 15 -> 01Z / 21 |
| 16 | 07Z / 13 -> 01Z / 19 | 07Z / 14 -> 01Z / 20 | 07Z / 15 -> 01Z / 21 | 07Z / 16 -> 01Z / 22 |
| 17 | 07Z / 14 -> 01Z / 20 | 07Z / 15 -> 01Z / 21 | 07Z / 16 -> 01Z / 22 | 07Z / 17 -> 01Z / 23 |
| 18 | 07Z / 15 -> 01Z / 21 | 07Z / 16 -> 01Z / 22 | 07Z / 17 -> 01Z / 23 | 07Z / 18 -> 01Z / 24 |
| 19 | 07Z / 16 -> 01Z / 22 | 07Z / 17 -> 01Z / 23 | 07Z / 18 -> 01Z / 24 | 07Z / 19 -> unavailable |
| 20 | 07Z / 17 -> 01Z / 23 | 07Z / 18 -> 01Z / 24 | 07Z / 19 -> unavailable | 07Z / 20 -> unavailable |
| 21 | 07Z / 18 -> 01Z / 24 | 07Z / 19 -> unavailable | 07Z / 20 -> unavailable | 07Z / 21 -> unavailable |
| 22 | 07Z / 19 -> unavailable | 07Z / 20 -> unavailable | 07Z / 21 -> unavailable | 07Z / 22 -> unavailable |
| 23 | 07Z / 20 -> unavailable | 07Z / 21 -> unavailable | 07Z / 22 -> unavailable | 07Z / 23 -> unavailable |

At Pacific standard 23:00 the 07Z file is 24 hours old and remains reachable through 23:59 (24 h 59 min). The existing candidate search floors its UTC look-back to the hour. Failure of the final reachable file produces unavailable; it never selects a minimum or a maximum for tomorrow. No cycle-search or observed-high-floor change was made.
