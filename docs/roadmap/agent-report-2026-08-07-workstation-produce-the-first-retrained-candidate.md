# Workstation report 2026-08-07 — produce the first retrained candidate

## Verdict

**BLOCK — the target-derived historical archive is complete and healthy for all 12 markets, but
the immutable PIT request contract cannot be staged from Open-Meteo Previous Runs. The first exact
Toronto/2021 request returns HTTP 400; field-level probes show only 1 of 21 required fields complete,
17 fields entirely null, 3 pressure-level fields rejected, and no provider issue time, availability
time, or run identity. The canonical ledger remains 0/60 complete and materialization blocks all 60
units. No candidate was fitted.**

This is the mission's explicit falsifying outcome: the preflight cannot be cleared from the
workstation, so the exact blocker inventory below is the result. Narrowing the years, deleting
fields, inventing issue evidence, or letting the candidate size its own gate would all violate the
binding contract.

## Branch, basis, and safety state

- Branch: `codex/workstation-produce-the-first-retrained-candidate-2026-09-38a`
- Required base branch:
  `origin/codex/workstation-make-the-season-window-target-derived-2026-09-33a`
- Base commit: `492bfbb7ca9655b5b9863e267878fec0a0ba984e`
- The required `-09-20a` rescue is an ancestor through `981b1d3a`.
- `docs/operations/reserved-confirmation-window.md` was checked at run time. No dates are reserved;
  the window remains armed but undated. This mission did not declare it.
- The repository venv still points to a removed Python 3.11 installation. Execution used an ignored,
  exact-pinned task runtime: Python 3.12.13, NumPy 2.4.6, Pandas 3.0.3, SciPy 1.17.1,
  scikit-learn 1.8.0, and Requests 2.34.2.
- The pre-existing workstation `data/forecast_history/cyyz` files are owned by the sync account and
  explicitly deny workstation writes. That ACL stopped the first publication attempt after five
  successful Toronto requests. It was not changed. The complete collection was rerun beneath the
  ignored isolated run root; no existing archive evidence was overwritten.

## P0 — target-derived historical archive: PASS

The collection called `weather.sources.forecast_history.backfill` for every live market with target
`2026-07-31`, training radius 7 days, climatology halo 7 days, years 2021–2025, and
`include_previous_runs=False`. The module therefore selected July 17–August 14 in each analog year.
No date range or request parameter was hand-built.

| Measure | Result |
| --- | ---: |
| Markets healthy | **12/12** |
| Analog years | 2021–2025 |
| Dates per year | 29 |
| Required dates per market | 145 |
| Required fleet market-dates | **1,740/1,740** |
| Historical hourly rows | **41,760** |
| Required core-field completeness | PASS in every market |
| Manifest target/window binding | MATCH in every market |
| HTTP 429 / rate-limit responses | **0** |

The isolated successful build used 60 HTTP requests. Five earlier Toronto requests also returned
HTTP 200 before the protected local archive refused publication, so the mission made 65 historical-
forecast calls in total. The provider was not the cause of that retry.

Coverage receipt:

- `scratch/runs/weather-retrain-09-38a/evidence/forecast-history-coverage.json`
- SHA-256:
  `97b0145ccd51871961795085c1f2c1011f1d5564c8120c585429b5926779eb9f`

This is a coverage result, not an outcome comparison. Statistical intervals and crossed
date × market clustering are not applicable.

## P1 — PIT staging falsifier: BLOCK

### Immutable plan

The canonical no-network planner produced:

| Plan field | Value |
| --- | ---: |
| Plan self-hash | `885d904c6c412b0486ac95fc4b633dd5014a8eb86334743c7083b261c1c8b1b8` |
| Plan file SHA-256 | `83c901e1a583d0caf7d024082467f3f888f10b1087da33e3ff45563acb565209` |
| Market/year units | 60 |
| Markets | 12 |
| Years | 5 |
| Dates per market | 75 |
| Fleet market-dates | 900 |
| Fleet market/date/cutoff cells | **12,600** |
| Field/date/cutoff cells | 264,600 |
| Candidate-controlled sizing | **none** |

The code-owned 12,600-cell gate remained intact. No source or candidate manifest changed its size.

### Exact request result

The first immutable request was Toronto/2021, July 24–August 7, model `gfs_seamless`, lead day 1,
and all 21 plan fields. The free endpoint returned HTTP 400 twice. The retained response says the
hourly variable list cannot initialize the pressure/height variable parser. The canonical stager
recorded 54 validation errors and status `failed`; no issue evidence was supplied because the
response contains none.

| Probe evidence | SHA-256 |
| --- | --- |
| `provider-probe.json` | `fd25acfd3bd2cc3d8ebe62af5ee90d829b9aa3da7c126d65710d4c5410fd5fc7` |
| Failed staging receipt | `758cd6a252dbdc2e79dbcfb6c1c274d18b83708f15cc815589bdbd07096b5c8a` |
| Append-only failure ledger | `7b254efc7b43ebd42c9b3c4b2cb5fa62088072e9d4841ca9dd783d5e1acc6147` |

### Field-level provider result

Twenty-one polite single-field diagnostics identified the exact failure surface without changing
the plan:

| Disposition | Required fields | Result |
| --- | --- | --- |
| Complete | `temperature_2m` | HTTP 200, 360/360 non-null rows |
| HTTP 200 but unusable | `cloud_cover`, `cloud_cover_low`, `cloud_cover_mid`, `cloud_cover_high`, `shortwave_radiation`, `wind_speed_10m`, `cape`, `direct_radiation`, `diffuse_radiation`, `wind_gusts_10m`, `visibility`, `precipitation_probability`, `precipitation`, `soil_temperature_0cm`, `soil_moisture_0_to_1cm`, `vapour_pressure_deficit`, `et0_fao_evapotranspiration` | **17 fields, each 360/360 null** |
| Provider rejects variable | `temperature_925hPa`, `temperature_850hPa`, `geopotential_height_500hPa` | **3 HTTP 400 responses** |

All 18 HTTP-200 responses contained the normal hourly envelope but no issue time, availability time,
initialization time, or run identifier. Open-Meteo documents Previous Runs as fixed lead-offset
series and directs exact-run consumers to Single Runs; the empirical response confirms that the
PIT plan's required issue/run receipt is not exposed here. The official source contract is
[Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api).

Field-probe receipt SHA-256:
`aa6663428a4ca398279ab40033384e4e8140cea564fef7dd4878a4c9757fa659`.

### Canonical staging and materialization result

| Gate | Result |
| --- | ---: |
| Required units | 60 |
| Complete units | **0** |
| Failed retained unit | Toronto/2021, `validation_not_complete` |
| Unfetched units after falsifier | 59 |
| Materialization | **BLOCK: incomplete=60** |
| Published corpus directory | **none** |

Collection stopped after the one-market/one-year provider probe and its bounded field diagnostics,
as the corpus contract requires. Fetching the other 59 exact units cannot repair an invalid request
schema, a 2021 matrix with 17 all-null fields, or absent issue evidence.

## Complete blocker inventory

These are independent blockers. None is collapsed into a summary boolean.

1. **PIT request schema:** the exact 21-field request is HTTP 400 because the three planned
   pressure/height variables are invalid on Previous Runs.
2. **PIT 2021 field availability:** 17 additional required fields return 360/360 null rows. Only
   `temperature_2m_previous_day1` is complete.
3. **PIT issue/availability identity:** successful responses expose no `issue_time_utc`,
   `available_at_utc`, initialization time, or run ID. The stager correctly rejects an empty issue-
   evidence list; no timestamps were invented.
4. **PIT corpus publication:** the verified ledger is 0/60 and the materializer blocks all 60 units,
   so no PIT manifest exists and none of the 12,600 required selection cells is preflightable.
5. **Reviewed collector:** the base branch still contains no authorized collector. The only
   `stage_response` callers are the corpus module and tests. This mission used bounded ignored probe
   runners; production has no durable collector command to repeat until the provider contract is
   redesigned.
6. **Verified parent release:** this checkout has neither `artifacts/releases/` nor
   `artifacts/releases/current_release.json`. `base_retrain.load_parent_contract()` requires the
   explicit parent to match an active pointer before it reaches `evaluate_preflight`. Release #1 is
   deferred, and this mission was forbidden to manufacture or activate a parent.
7. **Hash-bound base feature corpus:** there is no real all-market retrain corpus manifest or
   producer on this branch. The schema is emitted only by deterministic tests. P0 archive coverage
   does not by itself create labels, feature rows, parity samples, support folds, or artifact-regime
   bindings.
8. **Train/serve parity:** the required positive control remains BLOCK with 220 blocking findings.
   It covers 12/12 markets and 221/221 fields, rediscovers all four declared defects, and reports the
   two unclassified serving drops named by the handoff: `wind_gust_kmh` in 12 markets and
   `wind_shift_3h_degrees` in 12 markets. There is no candidate-specific PASS report.
9. **Class support:** the retained 12-market class-support prerequisite cannot be recomputed or
   cleared without real feature/label records. No support gate was weakened and no years were added.
10. **Candidate-specific calibration:** no blocked-OOF plan, fit receipt, or candidate calibration
    exists because fitting was not authorized by a passing preflight.
11. **Artifact-regime binding:** no feature records exist carrying one code/source/artifact regime,
    so the July 31 provenance-boundary prerequisite remains uncleared.

The actual base-retrain CLI was not made to emit a synthetic preflight receipt. It would stop before
`evaluate_preflight` on blockers 4, 6, and 7. Fabricating a parent, PIT manifest, or feature corpus
would make the blocker count look smaller without making the training input real.

## P2 — candidate comparison, crossed clustering, and power

No candidate was fitted, frozen, released, promoted, registered, or activated. Therefore there is
no incumbent comparison, no deduplicated `(market, target_date)` evaluation population, and no
crossed date × market estimate or power calculation to report. The statistical verdict is **not
powered / not applicable**, not a directional model story.

The parity positive-control receipt is:

- status `BLOCK`;
- 12 markets, 29 cases, 221 features, 2,908 compared cells;
- 220 blocking findings and 24 unexpected blockers;
- self-hash `bb0bd439a001fe12a7f2dc1d70f7bf2d3371bf40899cbe64262539675c449742`.

## Production-host reproduction

Run from the production repository root recorded by retained status evidence:
`C:\Users\micha\Desktop\github\weather`. These commands are reproduction instructions for the
production agent; the workstation did not execute them on production.

Target-derived historical archive collection:

```powershell
$markets = @('toronto','nyc','atlanta','austin','chicago','dallas','denver','houston','los-angeles','miami','san-francisco','seattle')
foreach ($market in $markets) {
  .\venv\Scripts\python.exe -m weather.sources.forecast_history --market $market backfill `
    --start-year 2021 --end-year 2025 --pause 0.4 --no-previous-runs `
    --target-date 2026-07-31
}
.\venv\Scripts\python.exe -m weather.sources.forecast_history fleet-coverage `
  --target-date 2026-07-31 --years 2021,2022,2023,2024,2025 `
  --json-out data\backtest\first-retrain-forecast-history-coverage.json `
  --out data\backtest\first-retrain-forecast-history-coverage.md
```

Immutable PIT plan and exact first request:

```powershell
.\venv\Scripts\python.exe -m weather.sources.forecast_training_corpus plan `
  --out scratch\runs\weather-retrain-09-38a\pit-plan.json `
  --years 2021,2022,2023,2024,2025 --target-year 2026 `
  --season-start 07-24 --season-end 08-07 `
  --cutoff-hours 7,8,9,10,11,12,13,14,15,16,17,18,19,20 `
  --source-model gfs_seamless --lead-days 1

@'
from weather.sources.forecast_training_corpus import load_plan
import requests
plan = load_plan(r"scratch\runs\weather-retrain-09-38a\pit-plan.json")
request = next(row for row in plan["requests"] if row["market_id"] == "toronto" and row["year"] == 2021)
response = requests.get(request["endpoint"], params=request["params"], timeout=90)
print(response.status_code)
print(response.json())
'@ | .\venv\Scripts\python.exe -
```

Canonical incomplete-ledger and materialization refusal:

```powershell
.\venv\Scripts\python.exe -m weather.sources.forecast_training_corpus resume-status `
  --plan scratch\runs\weather-retrain-09-38a\pit-plan.json `
  --staging-root scratch\runs\weather-retrain-09-38a\pit-staging
.\venv\Scripts\python.exe -m weather.sources.forecast_training_corpus materialize `
  --plan scratch\runs\weather-retrain-09-38a\pit-plan.json `
  --staging-root scratch\runs\weather-retrain-09-38a\pit-staging `
  --publish-root scratch\runs\weather-retrain-09-38a\pit-published
```

Parity positive control:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.scorecards.train_serve_feature_parity `
  --input tests\fixtures\train_serve_feature_parity_known_defects_v0.1.json `
  --run-root scratch\runs\weather-retrain-09-38a\parity-known-defects `
  --proof-mode
```

## Per-file roll verdict

The required command was run after fast-forwarding the clean local `master` ref to
`origin/master`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-produce-the-first-retrained-candidate-2026-09-38a
```

It inspected 41 inherited changed files before this report was added, of which 18 were importable,
and returned **ROLL-SENSITIVE**. The CLOB-enrichment closure was 267.2 hours old and was reported as
dormant; the live snapshot, CLOB, and observation-trigger closures were used. Receipt SHA-256:
`0a6339996dab99ce7d11924a716c10a2e19b66d86aa0645116efa24dbf9c0195`.

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
| `src/weather/operations/agent_docs_audit.py` | none | Roll-free |
| `src/weather/operations/base_retrain.py` | none | Roll-free |
| `src/weather/operations/nightly_retrain.py` | none | Roll-free |
| `src/weather/operations/storage_classes.py` | none | Roll-free |
| `src/weather/operations/taker_bot_daily_roll.py` | none | Roll-free |
| `src/weather/reporting/scorecards/train_serve_feature_parity.py` | none | Roll-free |
| `src/weather/schema_registry_data.py` | snapshot, CLOB, observation-trigger | **Roll-sensitive; additive-only** |
| `src/weather/schema_registry_recent_data.py` | snapshot, CLOB, observation-trigger | **Roll-sensitive; additive-only** |
| `src/weather/sources/forecast_history.py` | snapshot, observation-trigger | **Roll-sensitive** |
| `src/weather/sources/forecast_training_corpus.py` | none | Roll-free |

The two schema-registry diffs are verified additive-only: 25 additions/0 deletions and 70
additions/0 deletions. This mission did not edit them.

The script classifies every remaining inherited file as roll-free because it is documentation,
configuration, a test, or a fixture. Per file:

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
- `tests/calibration/test_forecast_training_contract.py`
- `tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json`
- `tests/market/test_taker_bot.py`
- `tests/model/test_estimate_distribution.py`
- `tests/model/test_feature_model_calibration.py`
- `tests/operations/test_agent_docs_audit.py`
- `tests/operations/test_base_retrain.py`
- `tests/operations/test_nightly_retrain.py`
- `tests/operations/test_storage_classes.py`
- `tests/operations/test_taker_bot_daily_roll.py`
- `tests/reporting/test_train_serve_feature_parity.py`
- `tests/sources/test_forecast_training_corpus.py`
- `tests/sources/test_historical_sources.py`
- `docs/roadmap/agent-report-2026-08-07-workstation-produce-the-first-retrained-candidate.md`

The branch must merge only through the 01:00–04:00 quiet-window procedure. This report and its
commit are roll-free, but they do not change the inherited branch verdict.

## Verification

```text
forecast-history focused tests: 5 passed
PIT corpus + base retrain + parity tests: 38 passed
target-derived fleet coverage: PASS, 12/12
PIT resume ledger: 0/60 complete
PIT materialization: BLOCK, incomplete=60
parity positive control: BLOCK, all 4 known defects rediscovered, coverage complete
roll verdict: ROLL-SENSITIVE
```

The root full suite was not rerun: this mission changed no source or test file, and master is already
documented red on four unowned failures. The focused owner controls passed under the exact pinned
runtime.

## What was not done

- No paid endpoint, credential, market endpoint, WU fetch, or provider other than the explicitly
  authorized free Open-Meteo endpoints was used.
- No production `data/`, mirror, `D:\weather-mirror`, scheduled task, loop, supervisor, settlement
  chain, or live process was read or mutated. The sync credential was never read.
- No existing workstation tape, ledger, archive, release, or pointer was deleted, rewritten, or
  permission-modified.
- No PIT field, year, cutoff, market, required cell, issue requirement, trusted floor, class-support
  rule, promotion gate, or artifact-regime rule was relaxed.
- No model was fitted; no candidate or inactive release was constructed; no release was registered,
  promoted, activated, or merged; no confirmation window was declared.
- No PR was opened.

## Commit

- Evidence/report commit: to be recorded in the final branch-head metadata commit.
- Final branch head: the pushed branch ref is authoritative.
