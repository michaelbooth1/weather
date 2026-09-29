# Agent report 2026-09-111c — storage classification for 5f/5g disk relief

Verdict: PASS — classifications and the watchdog list are implemented and
fixture-verified. Nothing was deleted, no production data was read, and no
Scheduler change was made.

Mission: owner task 111c. Branch `codex/storage-class-5g-20260929` from
`origin/master` `164f12d0`. Code commit `d9756e8f5beecd294f59ced20db7340c8aeb6fe1`;
this report is a separate docs-only commit on top of it. Disk relief, so it may
merge during the exam period (STATE_OF_PLAY exam-period merge policy).

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
   `mm_runs/*/*/mm_scoring_projection_manifest.json`. Before this change it was
   unclassified.
3. **5f attribution sidecar.** `backtest/active_variant_shadow_attribution.jsonl`
   joins `backtest_row_exports`, the family of its sibling
   `active_variant_shadow_long.csv`. The two classifications are identical.
   `jsonl` is added to the `analysis_projection` allowed formats.
4. **Watchdog expected-disabled list.** `scripts/ops/health_watchdog.ps1` now has
   a reviewed `$expectedDisabledTasks` map:
   `WeatherMarketMakingDailyRoll` and `WeatherMarketMakingDailyRollSupervisor`,
   each with the reason "live and paper maker paused by owner 2026-09-25". A flag
   is moved to a standing note only when it is exactly `<task> unexpectedly
   DISABLED` or `<task> is armed for … but DISABLED - it will not fire` (checked
   case-sensitively) and `<task>` is on the list. Every other flag about those
   tasks, and every other disabled task (including one whose name starts with a
   listed name), still alerts. The latest-state JSON records the list as
   `expected_disabled_tasks`. `status.ps1` is unchanged: it already lists both
   tasks as expected-disabled. The deployed watchdog (`aa99048`) runs an older
   status copy, so the watchdog-side list covers it.
5. Docs: `data-storage-class-contract.md` (5f/5g paragraph) and the
   `WeatherHostHealthWatchdog` row of `OPERATIONS_DESIGN.md`.

## Verification (fixtures only)

- `test_storage_classes.py`: both projection names under two run ids, including
  one containing `risk-order`, classify as `mm_scoring_projection`. The manifest
  is protected canonical evidence. `order_lifecycle.jsonl` still classifies as
  lifecycle evidence. The sidecar classification equals its sibling's.
- `test_cleanup_preflight.py`: a reviewed cleanup manifest over all three paths
  gives preflight `PASS`, with `analysis_projection` for each and the named rebuild
  source. The projection manifest classifies as retained canonical evidence.
- `test_health_watchdog_script.py` (native PowerShell): both maker tasks'
  disabled flags become notes carrying the reason. `WeatherSomeOtherTask
  unexpectedly DISABLED`, a name that merely starts with a listed name, and a
  non-disabled flag about a listed task all still alert. With only the two listed
  flags, the watchdog reports `OK` and no alerts.
- Repo-wide audits and the ops ratchets (schema registry, import architecture,
  agent docs, path policy, module size, ops alarm path, ops script ratchets,
  status script, operating reference) were run with the focused suites. Exact
  counts are in the PR description. GitHub CI results are recorded on the PR.

## Roll verdict

`src/weather/operations/storage_classes.py` is imported by cleanup and inventory
tooling. Get the mechanical verdict from `scripts\ops\roll_verdict.ps1 -Branch
codex/storage-class-5g-20260929` on production before landing. Do not derive it by
hand. The `.ps1`, docs and tests are roll-free.

## Production adoption after owner-ops review (watchdog)

New watchdog SHA-256: `8d989f5f5a0eda9c4d533d96b74117ba7cec466938da3f129e1b0fa3d258e07c`.
Status SHA-256 (unchanged, same as 110n): `8cebcbac61df462b5253aab704e615faabeeb7749aa34cc830e356a951f59b44`.
Hashes are over the LF bytes that `.gitattributes` (`eol=lf`) checks out.

Run the following on production only after owner-ops review, after the source has
landed, and from the production master checkout. It is not an instruction to run
Scheduler changes on the workstation.

```powershell
$productionRoot = ([string](git rev-parse --show-toplevel)).Trim()
if (([string](git branch --show-current)).Trim() -cne 'master') { throw 'Use production master' }
$reviewedTip = 'd9756e8f5beecd294f59ced20db7340c8aeb6fe1'
git merge-base --is-ancestor $reviewedTip HEAD
if ($LASTEXITCODE -ne 0) { throw 'Reviewed source has not landed' }
$deploymentRoot = Join-Path (Split-Path $productionRoot -Parent) 'weather-watchdog-deployed-111c-d9756e8f'
$env:GIT_LFS_SKIP_SMUDGE = '1'
git worktree add --detach $deploymentRoot $reviewedTip
if ($LASTEXITCODE -ne 0) { throw 'Deployment checkout was not created; inspect before retrying' }
& (Join-Path $deploymentRoot 'scripts/ops/register_health_watchdog.ps1') `
    -RepoRoot $productionRoot `
    -WatchdogScriptPath (Join-Path $deploymentRoot 'scripts/ops/health_watchdog.ps1') `
    -ExpectedSelfSha256 '8d989f5f5a0eda9c4d533d96b74117ba7cec466938da3f129e1b0fa3d258e07c' `
    -StatusScriptPath (Join-Path $deploymentRoot 'scripts/ops/status.ps1') `
    -ExpectedStatusScriptSha256 '8cebcbac61df462b5253aab704e615faabeeb7749aa34cc830e356a951f59b44'
Get-ScheduledTask -TaskName 'WeatherHostHealthWatchdog' | Select-Object -ExpandProperty Actions
```

This supersedes the pending 110n re-registration (`1fc7ba35`). The 111c source
contains that change plus the expected-disabled list, so run only one of the two.

## Limits and follow-ups

- No cleanup manifest was rebuilt or applied. The 5f/5g review manifests under
  `data/alerts/storage-decisions-20260929/` were built before this change, so
  regenerate them after landing so they carry the new families and rebuild sources.
- The rebuild-source tapes `quote_intents_long.csv` /
  `model_variant_quote_intents_long.csv` are still unclassified. Cleanup preflight
  therefore blocks their deletion, which is the safe default. Registering them as
  canonical evidence is a separate reviewed decision.
- Only the depth-2 run layout named in the task is covered. The `*` in `fnmatch`
  also crosses `/`, so a deeper path with the same basename would match. No such
  writer exists.
