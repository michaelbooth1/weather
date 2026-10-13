# Agent report 2026-09-111c — storage classification for 5f/5g disk relief

Verdict: PASS — the classifications, the preflight rebuild-source check and the
watchdog list are implemented and fixture-verified. Nothing was deleted, no
production data was read, and no Scheduler change was made.

Mission: [workstation handoff 111c](workstation-handoff-2026-09-111c-storage-class-5g.md).
Branch `codex/storage-class-5g-20260929` from `origin/master` `164f12d0`, with
`origin/master` `b0032a90` merged in (no rebase). The reviewed source tip is
`4f2f4813ee60c6730463167a7b234e0cb6c36143`. It contains the classifications,
the preflight check, and the final watchdog. The filter sits inside the
classification loop so that `test_ops_alarm_path`'s slice evaluation stays
self-contained. Later commits are docs-only. Disk relief, so it may merge during the exam period.

## Changes

1. **5g maker scoring projections.** New family `mm_scoring_projection`
   (`analysis_projection`, unprotected) matches
   `mm_runs/*/*/mm_scoring_projection.csv` and
   `mm_runs/*/*/model_variant_mm_scoring_projection.csv`. Its rebuild source names
   the sibling `quote_intents_long.csv` / `model_variant_quote_intents_long.csv`,
   bound by size+mtime in `mm_scoring_projection_manifest.json`. Readers already
   fail closed to those canonical tapes when the binding does not validate, and
   `weather.market.mm_scoring_projection backfill` rebuilds the projections.
   It is registered before `market_making_lifecycle_risk` so that family's
   `*risk*` / `*order*` substring globs cannot capture a run id containing them.
2. **Projection manifests stay retained.** New family
   `mm_scoring_projection_manifest` (`canonical_evidence`, protected) matches
   `mm_runs/*/*/mm_scoring_projection_manifest.json`. It was unclassified before.
3. **5f attribution sidecar.** `backtest/active_variant_shadow_attribution.jsonl`
   joins `backtest_row_exports`, the family of its sibling
   `active_variant_shadow_long.csv`. The two classifications are identical.
   `jsonl` is added to the `analysis_projection` allowed formats.
4. **Preflight rebuild-source check.** For every `mm_scoring_projection`
   candidate, `cleanup_preflight` runs
   `weather.market.mm_scoring_projection.validate_run_scoring_projection` on the
   candidate's run folder. The check (`mm_scoring_projection_rebuild_source`)
   BLOCKs unless all of these hold:
   - the manifest exists;
   - both canonical quote-intent tapes are present with their bound size+mtime;
   - the projection bytes match the manifest's SHA-256 and the header is exact.

   A classification alone cannot show that the rebuild source still rebuilds the
   projection, so this check is needed. As a result, a run whose sources were
   appended after projection, or whose projections are already partly deleted,
   blocks until reviewed.
5. **Watchdog expected-disabled list.** `scripts/ops/health_watchdog.ps1` now has
   a reviewed `$expectedDisabledTasks` map:
   `WeatherMarketMakingDailyRoll` and `WeatherMarketMakingDailyRollSupervisor`,
   each with the reason "live and paper maker paused by owner 2026-09-25".
   A flag becomes a standing note only when both conditions hold:
   - `<task>` is on the list;
   - the flag is exactly `<task> unexpectedly DISABLED` or
     `<task> is armed for … but DISABLED - it will not fire` (case-sensitive).

   These still alert:
   - every other flag about those two tasks;
   - every other disabled task, including one whose name only starts with a
     listed name.

   The latest-state JSON records the list as `expected_disabled_tasks`.
   `status.ps1` is unchanged; it already lists both tasks as expected-disabled.
6. Docs: `data-storage-class-contract.md` (5f/5g paragraph) and the
   `WeatherHostHealthWatchdog` row of `OPERATIONS_DESIGN.md`.

## Verification (fixtures only)

- `test_storage_classes.py`: both projection names classify as
  `mm_scoring_projection` under two run ids, one of them containing `risk-order`.
  The manifest is protected canonical evidence. `order_lifecycle.jsonl` is still
  lifecycle evidence. The sidecar's classification equals its sibling's.
- `test_cleanup_preflight.py`:
  - A reviewed manifest over all three paths gives preflight `PASS`. The fixture
    is a real bound run written by `write_run_scoring_projections`.
  - Each path classifies as `analysis_projection` with the named rebuild source.
  - The projection manifest classifies as retained canonical evidence.
  - Preflight BLOCKs both projections in three cases: the variant quote-intent
    source is missing, it was appended after binding, or the projection manifest
    is missing.
- `test_health_watchdog_script.py` (native PowerShell):
  - Both maker tasks' disabled flags become notes carrying the reason.
  - These still alert: `WeatherSomeOtherTask unexpectedly DISABLED`, a name that
    only starts with a listed name, and a non-disabled flag about a listed task.
  - With only the two listed flags, the watchdog reports `OK` and no alerts.
- The repo-wide audits (schema registry, import architecture, agent docs, path
  policy, module size) ran with the focused suites and the ops ratchets. The PR
  records the counts and the GitHub CI conclusion.

## Roll verdict (per file)

`scripts\ops\roll_verdict.ps1` needs production capture-supervisor closure
evidence, so it cannot run on the workstation. The binding verdict is
`scripts\ops\roll_verdict.ps1 -Branch origin/codex/storage-class-5g-20260929`
run on production. This table does not replace it.

| File | Expected verdict |
| --- | --- |
| src/weather/operations/storage_classes.py | Python: use the mechanical verdict. No collection or market capture module imports it directly. Its direct importers are cleanup, tiering, archive, retention and inventory tools, `event_day_manifest`, and `calibration/residual_distribution_corpus`. |
| src/weather/operations/cleanup_preflight.py | Python: use the mechanical verdict. Only cleanup and reclaim tools import it. |
| scripts/ops/health_watchdog.ps1 | Roll-free (.ps1). The change takes effect only after the re-registration below. |
| docs/operations/OPERATIONS_DESIGN.md, docs/operations/data-storage-class-contract.md | Roll-free |
| docs/roadmap/agent-report-2026-09-111c-storage-class-5g.md, docs/roadmap/correspondence-index.md | Roll-free |
| tests/operations/test_storage_classes.py, test_cleanup_preflight.py, test_health_watchdog_script.py | Roll-free |

## Production adoption after owner-ops review (watchdog)

New watchdog SHA-256: `e93c240b48898cf75b550a9bf1d6dc7a285d1a6ffc3f99d5bf3ba8156d2be1e3`.
Status SHA-256 (unchanged, same as 110n): `8cebcbac61df462b5253aab704e615faabeeb7749aa34cc830e356a951f59b44`.
Both hashes are over the LF bytes checked out under `.gitattributes` `eol=lf`.

Run this only on production, only after owner-ops review, and only after the
source has landed. Run it from the production master checkout. It is not an
instruction to run Scheduler changes on the workstation.

```powershell
$productionRoot = ([string](git rev-parse --show-toplevel)).Trim()
if (([string](git branch --show-current)).Trim() -cne 'master') { throw 'Use production master' }
$reviewedTip = '4f2f4813ee60c6730463167a7b234e0cb6c36143'
git merge-base --is-ancestor $reviewedTip HEAD
if ($LASTEXITCODE -ne 0) { throw 'Reviewed source has not landed' }
$deploymentRoot = Join-Path (Split-Path $productionRoot -Parent) 'weather-watchdog-deployed-111c-4f2f4813'
$env:GIT_LFS_SKIP_SMUDGE = '1'
git worktree add --detach $deploymentRoot $reviewedTip
if ($LASTEXITCODE -ne 0) { throw 'Deployment checkout was not created; inspect before retrying' }
& (Join-Path $deploymentRoot 'scripts/ops/register_health_watchdog.ps1') `
    -RepoRoot $productionRoot `
    -WatchdogScriptPath (Join-Path $deploymentRoot 'scripts/ops/health_watchdog.ps1') `
    -ExpectedSelfSha256 'e93c240b48898cf75b550a9bf1d6dc7a285d1a6ffc3f99d5bf3ba8156d2be1e3' `
    -StatusScriptPath (Join-Path $deploymentRoot 'scripts/ops/status.ps1') `
    -ExpectedStatusScriptSha256 '8cebcbac61df462b5253aab704e615faabeeb7749aa34cc830e356a951f59b44'
Get-ScheduledTask -TaskName 'WeatherHostHealthWatchdog' | Select-Object -ExpandProperty Actions
```

The handoff says the 110n watchdog was adopted on 2026-09-29. This command
replaces it with the same source plus the expected-disabled list.

## Limits and follow-ups

- No cleanup manifest was rebuilt or applied. The 5f/5g preflight under
  `data/alerts/storage-decisions-20260929/` predates this change. Rerun it after
  landing so it carries the new families and the rebuild-source check.
- The rebuild-source tapes `quote_intents_long.csv` and
  `model_variant_quote_intents_long.csv` are still unclassified, so preflight
  blocks their deletion. That is the safe default. Classifying them as canonical
  evidence is a separate reviewed decision.
- The patterns target the depth-2 run layout named in the handoff. `fnmatch`'s
  `*` also crosses `/`, so a deeper path with the same basename would match. No
  writer produces one. Preflight still requires a validating manifest in that
  file's own folder, so such a file cannot pass without a bound source.
