# Workstation report 2026-08-08 — exclude Denver station-days and fit

**VERDICT: the exclusion contract and A/B/C fits completed, but no candidate
qualifies. Stop without freezing a candidate or entering first-retrain
preflight.** The 2026-07-31 population is 899 market-days and 12,586
market/date/cutoff cells after the code-owned exclusion of Denver 2025-07-28.
Denver 2022-07-20 is named in the same versioned registry but is outside this
target's July 24–August 7 training window, so it has no balance cost here. All
three research-only fits completed. Honest and hybrid do not improve the
09:00–14:00 primary Brier comparison; rich has a tiny negative point estimate,
but its crossed interval includes zero, power is 0.054, it is worse all-hours,
and it deterministically returns an empty distribution on one captured San
Francisco input. Nothing was promoted or released.

## Branch, base, and boundaries

- Branch:
  `codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a`
- Required stacked base:
  `origin/codex/workstation-honest-corpus-versus-rich-corpus-2026-09-41a`
- Base commit: `50d0a3e9acfd43540ec5b01f3051c885298866d4`
- Implementation commit: `be322528a7884e3cec096d08f4e436f6fba86378`
- The handoff was read from `origin/master` at
  `17965307f561d15f4a9e45ef51c1e64fff8a71f3`.
- `docs/operations/reserved-confirmation-window.md` was checked before work.
  The confirmation window remains armed but undated; this mission did not
  declare, reserve, or consume it.

This was a workstation-only research and source mission. It made no production
write, registration change, scheduled-task change, restart, merge, mirror,
network collection, live-trading change, release binding, promotion, or model
artifact change. The fitted artifacts and measurement receipts are ignored
workstation evidence, explicitly `research_only=true` and
`release_eligible=false`.

## P0 — code-owned exclusion and exact population

`src/weather/operations/base_retrain.py` now owns the named policy
`first_retrain_station_day_exclusions_v1`. It records the station, date,
observed row count, floor, and reason for exactly the two established KBKF
station-days:

| Market | Station-day | Rows | Floor | Applicability to 2026-07-31 |
| --- | --- | ---: | ---: | --- |
| Denver | `kbkf` 2022-07-20 | 1 | 18 | Outside July 24–August 7; registered but inactive |
| Denver | `kbkf` 2025-07-28 | 17 | 18 | Inside; excluded |

The expected population is computed before any candidate is loaded:

```text
75 selected prior-year dates × 12 markets = 900 market-days
900 − 1 applicable named exclusion = 899 market-days
899 × 14 cutoff hours = 12,586 required cells
```

Denver contributes 74 days/1,036 cells; every other market contributes 75
days/1,050 cells. The balance cost is 1/900 fleet market-days (0.111%) and 1/75
Denver market-days (1.333%). The 2022 station-day adds no cost to this target.
For the control target 2026-07-27 both registry entries intersect the window,
and the same candidate-independent function derives 898 market-days/12,572
cells. Any other missing required day produces
`WU_UNAPPROVED_STATION_DAY_EXCLUSION`; a candidate cannot resize the gate with
its selected dates, counts, covered years, or omissions.

The actual KBKF retained summaries reproduce the established evidence:

| Date | First | Last | Rows | Recorded max |
| --- | --- | --- | ---: | ---: |
| 2022-07-20 | 00:58 | 00:58 | 1 | 71 °F |
| 2025-07-28 | 00:58 | 23:58 | 17 | 99 °F |

The 2025 day omits 15:58–17:58 and four later hours. The observation floor was
not changed.

## Corpus and fits

The repaired gate cleared exactly; the variant builder admitted no unlisted
subfloor station-day.

| Variant | Fleet rows | Denver rows | Other market rows | Fit outputs |
| --- | ---: | ---: | ---: | ---: |
| A — honest thin PIT forecast | 12,586 | 1,036 | 1,050 each | 12/12 |
| B — rich contaminated archive | 12,586 | 1,036 | 1,050 each | 12/12 |
| C — hybrid | 12,586 | 1,036 | 1,050 each | 12/12 |

The three corpora total 37,758 rows and 36 market fits. Parent HGB parameters,
feature order, year-blocked OOF calibration, and the 2021–2025 training horizon
were held fixed across variants. None of the 36 selected feature sets contains
`wind_gust` or `wind_shift`, so the handoff's conditional candidate-bound replay
trigger was false. All candidates were nevertheless replayed on captured inputs
for evaluation.

The acceptance bar was written before fitting and then left unchanged:

- primary: daily-first 09:00–14:00 candidate-minus-incumbent Brier must be
  negative, its crossed 95% upper bound must be below zero, and one-sided power
  at the observed effect must be at least 0.80;
- all-hour candidate-minus-incumbent and market-gap regression upper bounds must
  be no greater than +0.003;
- probability mass error must be at most `1e-10` and unexpected captured-input
  replay failures must be zero.

## Captured-input evaluation

Fits use 2021–2025 only. Evaluation uses the sealed, pre-2026-07-31 captured
population through 2026-07-30: 12,289 snapshots, 524 market-days, 50 target-date
clusters, and all 12 markets. The primary effective-cutoff slice contains 3,154
snapshots, 523 market-days, 49 target-date clusters, and 12 markets. Scores are
averaged within market-day first, then given equal market-day weight. Intervals
use 10,000 pigeonhole bootstrap draws with crossed target-date × market
clustering; power is one-sided noncentral-t sensitivity using the crossed
bootstrap standard error and 11 degrees of freedom.

### Primary effective-cutoff 09:00–14:00

All centre and width values are Celsius-equivalent. `Δ incumbent` is candidate
minus incumbent daily-first Brier, so negative is better.

| Variant | Brier | Δ incumbent (95% crossed CI) | Power | Market gap (95% CI) | Centre bias | Abs. centre error | Width |
| --- | ---: | --- | ---: | --- | ---: | ---: | ---: |
| A honest | 0.069120 | +0.000005 [-0.004601, +0.004821] | 0.050 | +0.017965 [+0.012624, +0.023660] | -0.069 | 1.008 | 1.327 |
| B rich | 0.069010 | -0.000105 [-0.005091, +0.005346] | 0.054 | +0.017855 [+0.012580, +0.023503] | +0.009 | 0.996 | 1.277 |
| C hybrid | 0.069120 | +0.000005 [-0.004661, +0.005001] | 0.050 | +0.017965 [+0.012590, +0.023713] | -0.069 | 1.008 | 1.327 |

The incumbent Brier is 0.069115 and the market Brier is 0.051155. The
80%-power MDE for candidate-minus-incumbent is 0.00636 for A, 0.00695 for B,
and 0.00654 for C. No primary comparison is remotely powered at its observed
effect. Each positive market gap excludes zero with power greater than 0.9999:
all three candidates remain worse than market prices on this slice.

### All hours

| Variant | Brier | Δ incumbent (95% crossed CI) | Power | Market gap (95% CI) | Centre bias | Abs. centre error | Width |
| --- | ---: | --- | ---: | --- | ---: | ---: | ---: |
| A honest | 0.060491 | +0.003292 [-0.002204, +0.009112] | 0.284 | +0.022310 [+0.017552, +0.027799] | -0.140 | 1.067 | 1.330 |
| B rich | 0.060850 | +0.003660 [-0.002093, +0.009551] | 0.316 | +0.022674 [+0.017985, +0.028077] | -0.039 | 1.031 | 1.276 |
| C hybrid | 0.060491 | +0.003292 [-0.002379, +0.009232] | 0.278 | +0.022310 [+0.017473, +0.027788] | -0.140 | 1.067 | 1.330 |

The incumbent Brier is 0.057199 and the market Brier is 0.038181. Every
candidate's upper confidence bound exceeds the +0.003 all-hour guardrail.

### Contamination contrasts

`B − A` is the measured contamination delta; `B − C` is residual contamination.
Positive means rich is worse.

| Slice | Contrast | Point | 95% crossed CI | Power | Paired snapshots |
| --- | --- | ---: | --- | ---: | ---: |
| 09:00–14:00 | B − A | -0.000110 | [-0.001524, +0.001341] | 0.066 | 3,154 |
| 09:00–14:00 | B − C | -0.000110 | [-0.001591, +0.001346] | 0.066 | 3,154 |
| All hours | B − A | +0.000370 | [-0.000800, +0.001536] | 0.145 | 12,288 |
| All hours | B − C | +0.000370 | [-0.000781, +0.001543] | 0.146 | 12,288 |

The inherited ~6% contamination price is not reproduced. The sign changes by
slice and every interval includes zero. Honest and hybrid are numerically
identical in this fit.

## Replay failure, parity, and acceptance disposition

Of 36,867 attempted candidate replays, 36,866 produced a valid distribution.
The sole failure is deterministic:

```text
variant: rich
market: san-francisco
target: 2026-06-12
snapshot: 20260612T030618-0400
failure: empty replay distribution
```

Fresh isolated replays produce unit-mass, 38-bucket distributions for honest
and hybrid on that exact record; rich again returns empty. Rich metrics and
B−A/B−C therefore use the 12,288 paired successful all-hour inputs and are
descriptive only. The failure is never silently dropped for acceptance: rich's
zero-failure guardrail is false. Among successful replays the maximum final
distribution mass error is `2.22e-16` and maximum band mass error is
`4.44e-16`.

No candidate qualifies:

- A and C miss the primary point, interval, power, and all-hour guardrails;
- B has a negative primary point but misses the interval, power, all-hour, and
  zero-failure guardrails;
- therefore no candidate was selected or frozen, and the conditional
  candidate-specific first-retrain preflight was not entered.

The inherited train/serve parity proof was rerun as a positive control. It
reproduces the standing `BLOCK`: 196 classified blocking findings, 4/4 known
defect groups rediscovered, 12 markets, 221 features, and **0 unexpected
blocking findings**. This known-defect control is separate from rich's captured
replay failure.

## Evidence receipts

The heavyweight receipts remain ignored workstation evidence and are not
release artifacts.

| Evidence | SHA-256 |
| --- | --- |
| Prefit acceptance bar | `57d68e046d3af2fe327c54c41b58e408aee67ffae7541080598d343f9359897f` |
| Corpus manifest file | `830861449439bc7bb9ed4f878ad7313054d1fcde41eb9e5ec5c77a6e46aad30` |
| Corpus manifest self-hash | `2d0149f89e0863b5e2bf7f843a92e9cc58ffdba2d2a3682c0bce43c8b104922f` |
| Candidate manifest file | `cb381b5ff9c46f2e7ffdee19092fbc2740debe2cdec568deaa7732f66ba380b6` |
| Candidate manifest self-hash | `6f908b582707c8cfdd8f82ae98af7a5537ddb1ba7155538bcbd4f5ab7cae3b79` |
| Evaluation summary | `59211d39f205be1136d33ac680e969ea9a754e35c5ecf3b2acb7677895d22f79` |
| Evaluation manifest file | `bcd6b7881a024eea831f80a2c44c2680ec5f8a540814270ad2e10c39d48f8ba4` |
| Evaluation manifest self-hash | `1a8ce8908d56a06da425dfc1bcbfccc85636ab0ff735fde819940d7e7bcb7cd8` |
| Rich replay-failure receipt | `3e10995ea46aef5ce169978ae171baf7b96d2ce79a20e52a78c6e3cce55e6da5` |
| Known-defect parity JSON | `ddd0ff58f8ab8535d8bd66b31436043e5560b83e5bdb23792f659620f1506278` |

## Verification

Executed with the retained Python 3.12 environment at `scratch/r30a/.venv`
because this checkout's repository `venv` points to a removed Python 3.11
installation:

```text
mission-owned + adjacent retrain/source/calibration/blocker tests
74 passed in 11.34s

train/serve known-defect parity positive control
BLOCK; 196 classified; 4/4 known groups; 0 unexpected

agent docs audit
PASS (18 agent files, 714 Markdown files before this report)

no-write syntax compile
PASS (776 Python files)

git diff --check
PASS
```

The standard `compileall` command could not create `__pycache__` directories in
the ACL-restricted `C:\tmp` worktree; the no-write syntax compile covers all
776 Python files instead. Repository-wide pytest completed with 3,302 passes,
830 subtests, 3 skips, and 91 failures. This is the same 91-failure
path/process/host-policy pattern reported by the predecessor's comparable full
run (then 3,301 passes), including long temporary CAS paths, process isolation,
and Windows path-policy tests. None names the changed retrain contract, and the
focused 74-test gate is clean. The run is not relabeled as the four-failure
master baseline.

## Per-file roll verdict

The repository-owned script was run after implementation commit `be322528`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a
```

It inspected 49 changed files and 20 importable files. Live closures were
snapshot (`loop`), CLOB (`clob_loop`), and observation-trigger. The 277.4-hour
CLOB-enrichment closure was mechanically subsumed by live closure evidence.
Overall verdict: **ROLL-SENSITIVE**. Receipt SHA-256:
`3548776d93d8726df3aa688c538cc0b3c6ef79afb6cecd766f189c14ee8a9adf`.

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
documentation/configuration/test classification. This report adds one more
roll-free Markdown file. The mission-owned implementation file
`base_retrain.py` is roll-free, but the stacked branch remains roll-sensitive
because of inherited files. Production must integrate it through the
01:00–04:00 quiet-window procedure. Pushing the branch does not roll production.

## Production-host reproduction

Run from the existing production repository
`C:\Users\micha\Desktop\github\weather` after fetching the branch. These
commands do not collect data, write production state, or enter preflight:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
git fetch origin `
  codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a

$verify = 'C:\tmp\weather-exclude-denver-fit-09-42a-verify'
git worktree add --detach $verify `
  origin/codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a
Set-Location $verify
$python = 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe'
$env:PYTHONPATH = "$verify\src"

& $python -B -m pytest -p no:cacheprovider -q `
  tests\operations\test_base_retrain.py `
  tests\sources\test_forecast_training_variants.py `
  tests\sources\test_historical_sources.py `
  tests\calibration\test_forecast_training_contract.py `
  tests\calibration\test_family_unit_cli_admission.py `
  tests\calibration\test_pooled_feature_preselection_exclusion.py `
  tests\calibration\test_lock_blocker_end_to_end.py

& $python -B -c `
  "from weather.operations.base_retrain import _training_population_for_target as p; import json; print(json.dumps(p('2026-07-31'), indent=2))"

& $python -B -m weather.reporting.scorecards.train_serve_feature_parity `
  --input tests\fixtures\train_serve_feature_parity_known_defects_v0.1.json `
  --run-root C:\tmp\weather-exclude-denver-fit-09-42a-parity `
  --proof-mode

Set-Location C:\Users\micha\Desktop\github\weather
Import-Csv .\data\wunderground\kbkf\daily\daily_summary.csv |
  Where-Object { $_.local_date -in @('2022-07-20', '2025-07-28') } |
  Select-Object local_date,row_count,first_time,last_time,`
    max_temp_native,max_temp_bucket_native,schema_version

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch origin/codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a
```

Expected focused result: 74 passed. Expected population: one applicable
exclusion, 899 market-days, and 12,586 cells. Expected parity positive control:
`BLOCK`, 196 classified blockers, 4/4 known groups, zero unexpected. Expected
roll verdict: `ROLL-SENSITIVE`.

## What was not done

- No candidate was selected, frozen, preflighted, promoted, bound, registered,
  or released.
- No artifact under tracked `artifacts/` was created or changed.
- No production tape, ledger, active pointer, scheduled task, supervisor,
  capture loop, market-making process, or trading setting was changed.
- No live trading, network collection, paid weather source, cleanup, mirror,
  restart, merge, or quiet-window action was performed.
- The reserved confirmation window remains armed but undated.
