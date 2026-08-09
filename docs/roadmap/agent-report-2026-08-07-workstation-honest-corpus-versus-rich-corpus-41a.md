# Workstation report 2026-08-07 — honest corpus versus rich corpus, 41a

## Verdict

**NO CANDIDATE — P0, P1, AND P2 PASS; P3 STOPS AT THE CODE-OWNED
12,600-CELL GATE WITH 12,586 CELLS.** The honest Previous Runs surface is real
but materially narrower than the settled archive: of 21 trainer fields across
leads 1–7 and three markets, only `temperature_2m` was complete. The requested
July 17–August 14 corpus was collected for 2021–2025 and all 12 markets with
12,180/12,180 point-in-time market-date-lead rows. The trainer can now select
honest, rich, or hybrid inputs from an explicit root.

The fixed first-retrain matrix nevertheless loses all 14 cutoff cells for
Denver on 2025-07-28. Its Weather Underground daily summary is present but has
17 hourly rows, below the unchanged serving/training floor of 18. All three
variants lose that market-day before forecast inputs are resolved. Fitting on
the remaining 12,586 cells would let the candidate size its own population and
would reintroduce the exact self-sizing defect that the handoff makes a binding
stop. I did not weaken the floor, substitute a label, fetch replacement WU
history, or fit an incomplete corpus.

Consequently no acceptance bar was selected, no A/B/C model was fitted, and no
clean captured-input evaluation exists. Centre, width, Brier, market gap,
crossed date × market intervals, power, `B − A`, and `B − C` are **not
measured**, rather than fabricated from unequal populations. P4 was not
entered; there is no candidate-bound replay or first-retrain candidate
preflight to report.

Implementation commit: `3f1c715d15e338d754d206f80fe12faf64d4008b` on
`codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a`.

## Branch, base, and safety state

- Required stacked base:
  `origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-40a`.
- Exact base commit: `7517a63175f2d368ec01ea3034e0f9c4d9cb6162`.
- The re-dispatch handoff was read from `origin/master` at
  `b5b3d452f27fe9104049d0e4361922a7dd78476b`.
- `docs/operations/reserved-confirmation-window.md` was checked at run time.
  No dates are reserved; the window remains armed but undated. No candidate was
  frozen and this mission did not declare the window.
- Workstation evidence stayed under the ignored run root
  `scratch/runs/weather-retrain-09-41a`. Nothing in `data/` was written by the
  collection or fit attempt.

## P0 — the real Previous Runs surface

The probe covered Toronto, Los Angeles, and Miami; July 17–18, 2021; all 21
fields in `OPEN_METEO_HOURLY_FIELDS`; and leads 1–7. This is 441
market-field-lead cells with 48 hourly values expected per cell.

| Result | Cells | Fields |
| --- | ---: | --- |
| Complete | **21** | `temperature_2m`, all 7 leads in all 3 markets |
| HTTP 200, all values null | **357** | 17 surface/radiation/wind/moisture fields |
| HTTP 400 | **63** | `temperature_925hPa`, `temperature_850hPa`, `geopotential_height_500hPa` |
| Total | **441** | 21 fields × 7 leads × 3 markets |

The two-host premise also passes independently in each market. The historical
host, when sent `previous_runs=1`, returned an unrenamed settled
`temperature_2m` series. The Previous Runs host returned
`temperature_2m_previous_day1`. All 48 paired non-null hours differed in each
of Toronto, Los Angeles, and Miami. The PIT surface is therefore genuine and
materially narrower than the 21-field settled archive.

Ignored receipt:
`scratch/runs/weather-retrain-09-41a/previous-runs-surface-probe.json`, SHA-256
`b89b5571a01f6b3f76f97d4610e269d7afbe8e15d310bb127fe2ef0a0e6957b8`.

The handoff's Toronto-only forecast-error concern is not an active 12-market
caller defect. `DEFAULT_FORECAST_DAILY` is Toronto-specific, but the CLI,
per-market loop, and family secondary-artifact path all pass
`daily_path_for(spec)` explicitly. Direct callers that omit the function
argument still receive the Toronto default.

## P1 — target-season collection

Collection called the existing `weather.sources.forecast_history.backfill`
path with its data root redirected to the ignored run root. It did not
hand-roll a provider fetch. Parameters were target 2026-07-31, target radius 7,
history radius 7, years 2021–2025, Previous Runs leads 1–7, model
`best_match`, and all 12 built-in markets. That produced the requested July
17–August 14 seasonal window through 120 market-year-host calls.

| Coverage | Result |
| --- | ---: |
| Markets complete | **12/12** |
| Seasonal target dates per market | **145** |
| Leads per target date | **7** |
| Expected PIT rows per market | **1,015** |
| Fleet PIT rows | **12,180/12,180** |
| Missing / duplicate / unexpected PIT keys | **0 / 0 / 0** |
| Settled rich archive | **PASS**, 12/12 markets, 145 dates each |
| Combined settled + PIT long rows per market | **27,840** |

Ignored receipt:
`scratch/runs/weather-retrain-09-41a/evidence/pit-collection-receipt.json`,
SHA-256
`0cc1bdcc0a18f93e18c818c8833c3cf09b601e1824022caf33fe9b62f258c111`.
The collected CSVs are workstation evidence, not published production data or
a production corpus.

## P2 — selectable trainer inputs

`ForecastTrainingVariantResolver` accepts only an explicit forecast-history
root and keeps these inputs distinct:

| Variant | Forecast high | Settled profiles | Forecast-relative marine fields |
| --- | --- | --- | --- |
| A, `honest` | fixed-lead Previous Runs | excluded | nulled |
| B, `rich` | settled historical archive | included | retained |
| C, `hybrid` | fixed-lead Previous Runs | included | nulled |

The reader validates source, issue-time basis, aware issue time, fixed lead,
market, station, native unit, 24 hourly rows, and duplicate target-date/lead
keys. It hashes every selected input file. `pooled_feature_cli` exposes
`--forecast-training-variant`, `--forecast-history-root`, and
`--pit-lead-days`. The research switch and the production PIT-manifest lane are
mutually exclusive; the existing immutable-manifest contract remains intact.

The fixed matrix was assembled through the real feature path until the gate
stopped it, proving that the new reader is not only a mocked CLI option.

## P3 — binding fixed-matrix refusal

The code-owned selection is five training years, July 24–August 7 in each year
(75 dates), cutoff hours 07–20 (14), and all 12 markets:
`75 × 14 × 12 = 12,600` required cells. The audit did not derive an expected
count from any candidate file.

| Market support | Result |
| --- | ---: |
| Eleven markets | **1,050/1,050 each** |
| Denver | **1,036/1,050** |
| Fleet | **12,586/12,600** |
| Missing | **14**, all Denver 2025-07-28 cutoffs |

`data/wunderground/kbkf/daily/daily_summary.csv` contains the Denver date with
`row_count=17`, first time `00:58`, last time `23:58`, and maximum native
temperature 99°F. `build_market_records` enforces the unchanged minimum row
count of 18 before resolving A, B, or C. Therefore the missing cell is shared
by every variant and cannot support an equal-population comparison.

Ignored audit:
`scratch/runs/weather-retrain-09-41a/fixed-training-matrix-audit.json`, file
SHA-256
`0182a60e4edfaf4be17bd682ad03a70cdf04c5c75d19e73831608b046d575cb8`;
content audit hash
`7f7cb302f4d95d1f915500ab695806162faa9bae7bfaa15dfe6817ccb13269cc`.

This is the sole binding candidate blocker reached by the mission. Repairing
the historical WU market-day or changing the fixed admission contract requires
new evidence and authority; silently dropping it is forbidden.

## P4 disposition and positive control

P4 applies only if a candidate qualifies, so candidate-bound replay and the
first-retrain preflight were not run. The inherited parity proof was rerun as a
positive control: `BLOCK`, 196 classified blockers, 4/4 known defect groups,
and **0 unexpected** blockers across 12 markets and 221 features. Its BLOCK is
the standing known-defect gate, not a regression from this mission.

Receipt SHA-256:
`b99c82823fe260cd95025b01f2f870793ea217c19eee74c5ae14edc4b9d399a0`.
A future candidate remains obligated to run its own parity and replay; this
incumbent control does not transfer.

## Verification

Executed with the healthy retained Python 3.12 environment at
`scratch/r30a/.venv` because the repository `venv` points to a removed Python
3.11 installation:

```text
pytest focused + adjacent source/calibration/blocker paths
59 passed in 17.18s

python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 713 Markdown files before this report)

git diff --check
PASS
```

Repository-wide pytest was attempted three times but did not yield a valid
branch-wide verdict in this workstation environment. A long workspace temp
path completed with 3,301 passes and 91 path/process/host-policy failures; a
short `C:\tmp` root became ACL-inaccessible mid-run and produced 737 setup
errors; a short workspace root reached 23% and then the process-control tests
terminated pytest without a summary. The temporary workspace root was removed.
No failure named the new resolver or trainer wiring in the completed run, and
the dedicated new tests pass. These infrastructure attempts are not relabeled
as either the four-failure master baseline or as code regressions.

## Per-file roll verdict

The repository-owned command was run after implementation commit `3f1c715d`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a
```

It inspected 48 changed files and 20 importable files. Live closures were
snapshot (`loop`), CLOB (`clob_loop`), and observation-trigger. The 275.1-hour
CLOB-enrichment closure was mechanically subsumed by live closure evidence.
Overall verdict: **ROLL-SENSITIVE**. Receipt SHA-256:
`9989788a334d5f2bd8e2401c6a3757097e153c0085b66e79407821eabc6901f6`.

| Importable changed file | Live closures | Verdict |
| --- | --- | --- |
| `src/weather/calibration/base_model_candidate.py` | none | Roll-free |
| `src/weather/calibration/forecast_training_contract.py` | none | Roll-free |
| `src/weather/calibration/pooled_feature_assembly.py` | none | Roll-free |
| `src/weather/calibration/pooled_feature_cli.py` | none | Roll-free |
| `src/weather/market/taker_bot_cli.py` | none | Roll-free |
| `src/weather/market/taker_bot_finalization.py` | none | Roll-free |
| `src/weather/model/model_distribution.py` | snapshot, observation-trigger | **Roll-sensitive** |
| `src/weather/model/model_features.py` | snapshot, observation-trigger | **Roll-sensitive** |
| `src/weather/model/model_sources.py` | snapshot, observation-trigger | **Roll-sensitive** |
| `src/weather/operations/agent_docs_audit.py` | none | Roll-free |
| `src/weather/operations/base_retrain.py` | none | Roll-free |
| `src/weather/operations/nightly_retrain.py` | none | Roll-free |
| `src/weather/operations/storage_classes.py` | none | Roll-free |
| `src/weather/operations/taker_bot_daily_roll.py` | none | Roll-free |
| `src/weather/reporting/scorecards/train_serve_feature_parity.py` | none | Roll-free |
| `src/weather/schema_registry_data.py` | snapshot, CLOB, observation-trigger | **Roll-sensitive; inherited additive-only change** |
| `src/weather/schema_registry_recent_data.py` | snapshot, CLOB, observation-trigger | **Roll-sensitive; inherited additive-only change** |
| `src/weather/sources/forecast_history.py` | snapshot, observation-trigger | **Roll-sensitive** |
| `src/weather/sources/forecast_training_corpus.py` | none | Roll-free |
| `src/weather/sources/forecast_training_variants.py` | none | Roll-free |

Every non-importable changed file is roll-free by the script's code-owned
documentation/configuration/test classification, individually:

- `README.md`
- `docs/architecture.md`
- `docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md`
- `docs/operations/PIT_FORECAST_TRAINING_CORPUS.md`
- `docs/operations/README.md`
- `docs/operations/data-retention-policy.md`
- `docs/operations/data-storage-class-contract.md`
- `docs/roadmap/agent-report-2026-08-02-workstation-build-base-retrain-step.md`
- `docs/roadmap/agent-report-2026-08-03-workstation-build-pit-forecast-corpus.md`
- `docs/roadmap/agent-report-2026-08-06-workstation-make-the-season-window-target-derived.md`
- `docs/roadmap/agent-report-2026-08-07-workstation-close-the-train-serve-parity-gap.md`
- `docs/roadmap/agent-report-2026-08-07-workstation-honest-corpus-versus-rich-corpus.md`
- `docs/roadmap/agent-report-2026-08-07-workstation-produce-the-first-retrained-candidate.md`
- `tests/calibration/test_forecast_training_contract.py`
- `tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json`
- `tests/market/test_taker_bot.py`
- `tests/model/test_estimate_distribution.py`
- `tests/model/test_feature_model_calibration.py`
- `tests/model/test_feature_skew.py`
- `tests/operations/test_agent_docs_audit.py`
- `tests/operations/test_base_retrain.py`
- `tests/operations/test_nightly_retrain.py`
- `tests/operations/test_storage_classes.py`
- `tests/operations/test_taker_bot_daily_roll.py`
- `tests/reporting/test_train_serve_feature_parity.py`
- `tests/sources/test_forecast_training_corpus.py`
- `tests/sources/test_forecast_training_variants.py`
- `tests/sources/test_historical_sources.py`

This report adds one roll-free Markdown file. The mission-owned implementation
files are all roll-free, but the stacked branch remains roll-sensitive because
of inherited files. Production must integrate through the 01:00–04:00 quiet
window procedure. Pushing the branch does not roll production.

## Production-host reproduction

Run from the production repository root
`C:\Users\micha\Desktop\github\weather`. These commands fetch and inspect the
branch without merging, restarting, collecting, fitting, or writing production
`data/`:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
git fetch origin codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a

git merge-base --is-ancestor `
  7517a63175f2d368ec01ea3034e0f9c4d9cb6162 `
  origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a

git show `
  origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a:docs/roadmap/agent-report-2026-08-07-workstation-honest-corpus-versus-rich-corpus-41a.md

git diff --check `
  origin/master...origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a
```

The load-bearing WU blocker is independently visible in the existing
production-owned path:

```powershell
Import-Csv `
  C:\Users\micha\Desktop\github\weather\data\wunderground\kbkf\daily\daily_summary.csv |
  Where-Object { $_.local_date -eq '2025-07-28' } |
  Select-Object local_date, row_count, first_time, last_time, `
    max_temp_native, max_temp_bucket_native, schema_version
```

For isolated source verification, create a disposable branch worktree and use
the production repository's interpreter:

```powershell
$verify = 'C:\tmp\weather-honest-rich-41a-verify'
git worktree add --detach $verify `
  origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a
Set-Location $verify
$python = 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe'
$env:PYTHONPATH = "$verify\src"

& $python -B -m pytest -p no:cacheprovider -q `
  tests\sources\test_forecast_training_variants.py `
  tests\sources\test_historical_sources.py `
  tests\calibration\test_forecast_training_contract.py `
  tests\calibration\test_family_unit_cli_admission.py `
  tests\calibration\test_pooled_feature_preselection_exclusion.py `
  tests\calibration\test_lock_blocker_end_to_end.py

& $python -B -m weather.reporting.scorecards.train_serve_feature_parity `
  --input tests\fixtures\train_serve_feature_parity_known_defects_v0.1.json `
  --run-root C:\tmp\weather-honest-rich-41a-parity `
  --proof-mode
```

Expected focused result: 59 passed. Expected parity result: BLOCK, 196
classified blockers, zero unexpected, and 4/4 known defect groups. The network
probe and 120-call collection are workstation-owned evidence and are not
prescribed during production capture hours.

## What was not done

- No acceptance bar was selected and no model or candidate was fitted.
- No A/B/C evaluation, contamination delta, crossed interval, or power result
  was invented from the incomplete matrix.
- No WU replacement history was fetched; no serving/training floor, 12,600-cell
  gate, known-defect gate, or probability contract was weakened.
- No candidate was frozen, replayed, released, registered, activated, promoted,
  or bound. No confirmation window was declared.
- No production `data/`, workstation mirror, `D:\weather-mirror`, credential,
  tape, ledger, artifact, release, pointer, scheduler, loop, supervisor,
  settlement chain, or live process was mutated.
- No paid provider was called. Only the explicitly authorized free Open-Meteo
  historical and Previous Runs endpoints were used.
- No production restart, pull request, merge, or branch deletion was performed.

## Commit

- Implementation commit:
  `3f1c715d15e338d754d206f80fe12faf64d4008b`.
- Report commit: the next commit on this branch.
- Final pushed branch head is authoritative.
