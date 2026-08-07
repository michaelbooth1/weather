# Workstation report 2026-08-07 — honest corpus versus rich corpus

## Verdict

**P0 FALSIFIED THE HANDED CORPUS-INVENTORY PREMISE; MANDATORY STOP.** The
independently accessible workstation files do contain **2,135** rows with
`issue_time_basis = fixed_lead_day_offset`, but their composition is not the
composition asserted by the handoff. All 12 station files carry lead days
**1–7**, not 1–4. For Toronto, every lead has 52 rows in each year 2021–2025,
so those years have **364 rows/year**, not 416; 2026 contributes another 315
rows. The exact identity is therefore `5 × 52 × 7 + 45 × 7 = 2,135`.

The delegation contract says the workstation mirror is not authoritative for
live production state. Accordingly, this report does not claim that it has
proved the current production file's composition. It establishes the narrower
and load-bearing result required by P0: the production claim cannot be
independently reproduced from the evidence available to this mission and is
contradicted by every local station copy plus its manifest and the collector's
code-owned default. The handoff says **“If any of this is wrong, stop and say
so.”** I stopped before calling either Open-Meteo host, collecting a corpus,
changing the trainer, declaring an acceptance bar, fitting a model, or
evaluating a candidate.

## Branch, base, and safety state

- Branch: `codex/workstation-honest-corpus-versus-rich-corpus-2026-09-40a`
- Required stacked base:
  `origin/codex/workstation-close-the-train-serve-parity-gap-2026-09-39a`
- Base commit: `0da83657685b1b41bc7dbc1363da34e553fc44b2`
- The handoff was read from `origin/master` at
  `e3f4e511d80be0ebea09800dec3e217092e228a0`.
- `docs/operations/reserved-confirmation-window.md` was checked at run time.
  No dates are reserved; the window remains armed but undated. This mission did
  not declare it.
- The isolated worktree was
  `C:\tmp\weather-honest-corpus-09-40a`. No conclusion or reproduction command
  depends on retaining that scratch path.

## P0 measurement

The audited Toronto file was:

`C:\Users\Michael\Documents\github\weather\data\forecast_history\cyyz\forecast_daily_by_issue.csv`

- File SHA-256:
  `32bbe7c837e79162060d3477ca3ac2e00c0d3e3dfd5e4665915d8c95babee417`
- Adjacent manifest SHA-256:
  `53f7607366fccbd2311073c28062cdfc9f34511993c10918265bf91c22db545f`
- Source: `open_meteo_previous_runs` on every audited fixed-lead row.
- Target range: `2021-05-10` through `2026-06-23`.

| Target year | Rows at each lead 1–7 | Fixed-lead rows/year |
| --- | ---: | ---: |
| 2021 | 52 | **364** |
| 2022 | 52 | **364** |
| 2023 | 52 | **364** |
| 2024 | 52 | **364** |
| 2025 | 52 | **364** |
| 2026 | 45 | **315** |
| **Total** |  | **2,135** |

Filtering the first five years to the claimed leads 1–4 yields **208** rows per
year, not 416. The result is not Toronto-specific: `cyyz`, `katl`, `kaus`,
`kbkf`, `kdal`, `khou`, `klax`, `klga`, `kmia`, `kord`, `ksea`, and `ksfo`
all contain 2,135 fixed-lead rows, leads 1–7, years 2021–2026, and the same
target-date bounds.

Three independent local contracts agree:

1. The CSV row inventory above.
2. Its manifest declares `previous_runs.leads = [1,2,3,4,5,6,7]` and per-year
   hourly counts consistent with 52 dates × 7 leads × 24 hours for 2021–2025.
3. `src/weather/sources/forecast_history.py` defines
   `DEFAULT_PREVIOUS_RUN_LEADS = (1,2,3,4,5,6,7)`, and the daily issue writer
   groups one daily high by lead for every returned target date.

The matching total of 2,135 is therefore a coincidence of different
populations, not confirmation of the asserted inventory. Accepting only the
total would conceal the exact schema/lead mismatch P0 was written to catch.

## Consequence for P1–P4

The mandatory stop fired at the cheapest falsifying test. These questions
remain **unmeasured by this mission**:

- whether the archive host ignores `previous_runs=` and returns an unchanged,
  unrenamed settled series;
- whether PIT `temperature_2m_previous_day1` differs in 23 of 24 hours;
- the full 21-field × 7-lead Previous Runs surface;
- July 17–August 14 PIT coverage for 2021–2025 across all 12 markets;
- thin-honest versus rich-contaminated candidate performance;
- centre, width, Brier, market gap, crossed date × market intervals, power, and
  the contamination delta `B − A`;
- train/serve parity, candidate-bound replay, and first-retrain preflight for a
  new candidate.

No acceptance bar was declared because fitting was never reached. No point
estimate, directional claim, inherited ~6% contamination price, or “not
powered” candidate comparison is reported. Carrying any of those forward would
turn a P0 refusal into fabricated evidence.

## Production-host reproduction

Run from the production repository root named by retained production evidence:
`C:\Users\micha\Desktop\github\weather`. These are read-only reproduction
commands for the production agent; this workstation did not execute them on
production.

```powershell
Set-Location C:\Users\micha\Desktop\github\weather

$files = Get-ChildItem data\forecast_history -Filter forecast_daily_by_issue.csv -Recurse
foreach ($file in ($files | Sort-Object FullName)) {
    $rows = @(Import-Csv $file.FullName | Where-Object {
        $_.issue_time_basis -eq 'fixed_lead_day_offset'
    })
    [pscustomobject]@{
        station = $file.Directory.Name
        rows = $rows.Count
        leads = (($rows.lead_days | Sort-Object -Unique) -join ',')
        years = ((($rows.target_date | ForEach-Object { $_.Substring(0, 4) }) |
            Sort-Object -Unique) -join ',')
        minimum_target = ($rows.target_date | Sort-Object | Select-Object -First 1)
        maximum_target = ($rows.target_date | Sort-Object | Select-Object -Last 1)
    }
}

$toronto = @(Import-Csv data\forecast_history\cyyz\forecast_daily_by_issue.csv |
    Where-Object { $_.issue_time_basis -eq 'fixed_lead_day_offset' })
$toronto | Group-Object {
    "$($_.target_date.Substring(0, 4))|$($_.lead_days)"
} | Sort-Object Name | Select-Object Name, Count

Get-FileHash data\forecast_history\cyyz\forecast_daily_by_issue.csv -Algorithm SHA256
Get-FileHash data\forecast_history\cyyz\manifest.json -Algorithm SHA256
Get-Content -Raw data\forecast_history\cyyz\manifest.json
Select-String -Path src\weather\sources\forecast_history.py -Pattern `
    'DEFAULT_PREVIOUS_RUN_LEADS|previous_runs_leads'
```

If production really has 416 rows/year and only leads 1–4, that is a distinct
population from the workstation evidence despite the identical 2,135 total.
The production agent should record its exact file hash and explain which
collector/window produced it before redispatching P1; neither host should infer
population identity from the total alone.

## Per-file roll verdict

The repository-owned command was run from the workstation repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-honest-corpus-versus-rich-corpus-2026-09-40a
```

It inspected the 45 inherited changed files before this report was added, of
which 19 were importable. The three live closures were snapshot (`loop`), CLOB
(`clob_loop`), and observation-trigger. The 269.5-hour-old CLOB-enrichment
closure was mechanically **SUBSUMED** by the live CLOB closure. The verdict is
**ROLL-SENSITIVE**; this report adds one roll-free Markdown file and does not
change it.

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

Every remaining inherited file is roll-free by the script's code-owned
docs/config/tests/PowerShell classification, individually:

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
- `tests/sources/test_historical_sources.py`
- `docs/roadmap/agent-report-2026-08-07-workstation-honest-corpus-versus-rich-corpus.md`

The inherited schema-registry changes are additive-only; this mission did not
edit either registry. Production must merge the branch only through the
01:00–04:00 quiet-window procedure. Committing and pushing the branch does not
roll production.

## Verification

- Audited all 12 local `forecast_daily_by_issue.csv` files and the Toronto
  year × lead cross-tab.
- Verified Toronto CSV and manifest hashes.
- Checked the collector default and grouping path in source.
- Ran the repository-owned roll verdict: `ROLL-SENSITIVE`.
- Ran `weather.operations.agent_docs_audit` after adding this report.
- Ran `git diff --check` and reviewed the complete stacked branch diff.

The root test suite was not run. P0 stopped before any source or test change,
and the only mission-owned change is this dated report. The four failures named
in `STATE_OF_PLAY.md` were neither encountered nor reclassified.

## What was not done

- No Open-Meteo, WU, market, paid, or credentialed endpoint was called.
- No production `data/`, workstation mirror, `D:\weather-mirror`, credential,
  tape, ledger, artifact, release, pointer, scheduler, loop, supervisor,
  settlement chain, or live process was mutated.
- No source, trainer, schema, fixture, test, gate, serving floor, feature set,
  or required-cell count was changed or weakened.
- No corpus was collected, materialized, replaced, or published.
- No acceptance bar was selected; no model was fitted; no candidate was
  frozen, replayed, released, registered, activated, promoted, or merged.
- No confirmation window was declared and no pull request was opened.

## Commit

- Evidence/report commit: `3098bba3d066fd030294b7b481710934bc4e6fcc`.
- Final metadata commit: the pushed branch head is authoritative.
