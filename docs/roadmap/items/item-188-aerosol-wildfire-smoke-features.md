# 188. Aerosol & Wildfire-Smoke Suppression Features [PARTIAL 2026-06-24 - AQ ARCHIVE AND SMOKE SLICE PREP LIVE, RETRAIN BLOCKED]

Goal: stop the model being blind to wildfire smoke, a regime that suppresses
the daytime maximum by dimming surface heating and producing one-sided warm
busts.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`,
Gap 4. Thick smoke dims the surface and lowers the daytime maximum
([California smoke temperature anomaly, ACP 2024](https://acp.copernicus.org/articles/24/6937/2024/));
operational smoke fields exist ([HRRR-Smoke, NWS](https://www.weather.gov/mfr/HRRR_smoke_tutorial)).
The model previously had no aerosol/smoke feature, so on heavy-smoke days every
input could still point warm while the realized high came in low.

Why this matters: timely. Canadian wildfire smoke has driven multi-degree Tmax
anomalies over Toronto and NYC in recent summers, the exact markets this project
trades.

## Status

2026-06-21: a low-friction Open-Meteo Air Quality source path is live. The
runtime now fetches `open_meteo_air_quality` whenever a market already fetches
`open_meteo`, sharing the same provider-family serialization and cache budget.
The source records hourly `pm2_5`, `pm10`, `aerosol_optical_depth`, `dust`,
`us_aqi`, and `european_aqi` rows with provenance pointing to CAMS via the
Open-Meteo Air Quality API.

The shared train/live feature path now merges AQ rows into the Open-Meteo
forecast profile by local hour and exposes:

- remaining-window and next-3h aerosol optical depth means.
- remaining-window and next-3h PM2.5 means.
- remaining-window PM10 and dust means.
- `forecast_smoke_suppression_flag`, a one-sided smoke-risk flag from PM2.5,
  AOD, or dust thresholds.

Existing trained artifacts continue selecting by their trained feature names, so
these new columns stay inert until an AQ backfill/retrain promotes them.

## Design

1. Add Open-Meteo Air Quality as the first adapter because the official API
   exposes CAMS-backed global/European PM2.5, PM10, AOD, dust, and AQI fields
   with the same coordinate/timezone contract as the forecast API.
2. Derive heating-window AQ features in `forecast_profile_features` so live and
   historical feature extraction stay centralized.
3. Keep the prior one-sided by exposing a smoke-suppression flag; the feature
   family can pull the upper tail down after retraining without inventing a
   warm-side boost.
4. Gate via the settlement-scored feature-value gate (item 27), with a
   high-AOD/high-PM smoke-day slice rather than only aggregate scoring.

- [x] Add the Open-Meteo Air Quality aerosol adapter with provenance.
- [x] Add heating-window AOD/PM2.5/PM10/dust + smoke-flag features.
- [x] Track Open-Meteo Air Quality as an expanded Open-Meteo source-family
      payload in source inventory.
- [x] Machine-readable AQ/smoke settlement gate artifact.
- [x] Add historical AQ backfill/replay-safe archive support so the feature
      family can be used by future promoted artifacts.
- [x] Add high-AOD/high-PM smoke-slice data prep for later settlement replay.
- [ ] Settlement-scored gate with an explicit high-AOD/high-PM smoke-day slice.

## 2026-06-24 AQ Archive and Smoke-Slice Prep

Implemented replay-safe Open-Meteo Air Quality archive support without active
artifact retraining. `weather.sources.open_meteo_archives` now has:

- idempotent AQ archive writes with content-addressed raw payloads.
- `air-quality backfill` and `air-quality coverage` CLI commands.
- historical backfill planner support via source
  `open_meteo_air_quality`.

Added `weather.reporting.source_gates.forecast_smoke_slice_prep`, schema
`forecast_smoke_slice_prep_v0.1`, which reads archived AQ hourly rows and emits
market/date join keys for `high_smoke` and `high_aod_high_pm` replay slices.
`weather.reporting.source_gates.source_family_inventory` now reports Open-Meteo AQ archive
coverage as `historical_smoke_archive_available`,
`partial_historical_smoke_archive`, or `historical_smoke_archive_missing`.

This intentionally does not retrain or promote an active artifact. The
AQ/smoke gate remains blocked until the AQ archive is populated across the
training/evaluation window, a smoke-scoped candidate is trained/replayed, AQ
features are selected by the candidate artifact, permutation evidence exists,
and the high-AOD/high-PM slice is settlement-scored.

Verification:

- `python -m pytest tests\sources\test_open_meteo_archives.py tests\sources\test_historical_sources.py tests\collection\test_historical_backfill_runner.py tests\reporting\test_source_family_inventory.py tests\reporting\test_forecast_smoke_slice_prep.py tests\reporting\test_forecast_smoke_gate.py tests\operations\test_schema_registry.py -q` -> 67 passed.

## 2026-06-22 Gate Rerun

The refreshed child-gate evidence does not promote AQ/smoke yet. The live
Open-Meteo AQ path is present, but the available weak-family evidence is still
under the broader Open-Meteo forecast-profile surface and lacks a historical AQ
archive, retrain-selectable artifact columns, and a dedicated high-AOD/high-PM
settlement slice. The next unblock remains AQ backfill or replay-safe live
history, followed by a smoke-slice gate.

## 2026-06-22 AQ/Smoke Gate Artifact

Added `weather.reporting.source_gates.forecast_smoke_gate`, schema
`forecast_smoke_gate_v0.1`, with generated evidence at:

- `data/backtest/item188_forecast_smoke_gate.json`
- `data/backtest/item188_forecast_smoke_gate_report.md`

Also updated `weather.reporting.source_gates.source_family_inventory` so
`open_meteo_air_quality` is classified under the `open_meteo_expanded` source
family. The refreshed inventory remains `PASS` and now sees
`open_meteo_air_quality` in both source status and forecast payloads.

Current smoke gate status: `BLOCK`.

Blockers:

- the available replay is `feature_subset=forecast_profile`, not an isolated
  AQ/smoke replay.
- historical archive status is still `partial_forecast_history_archive`, not a
  historical AQ/smoke archive.
- all seven AQ/smoke columns are cataloged, but zero are selected by the active
  artifact feature names.
- the current HGB permutation artifact has no AQ/smoke feature rows.
- no high-AOD/high-PM settlement slice exists yet.
- the borrowed full forecast-profile replay still fails daily-first market
  tolerance.

Next unblock: backfill or replay-save Open-Meteo Air Quality history, train a
smoke-scoped candidate with AQ/smoke columns selected, regenerate HGB
permutation evidence, and add the high-smoke settlement slice.

## 2026-06-22 Gate Refresh

I regenerated `data/backtest/item188_forecast_smoke_gate.json` and
`data/backtest/item188_forecast_smoke_gate_report.md`. The live gate remains
`BLOCK`.

The source/payload side has improved versus the earlier gate note:
`open_meteo_air_quality` is now present in both source-status and
forecast-payload inventory, and all seven AQ/smoke columns are cataloged.

Current blockers:

- `isolated_smoke_replay_missing`: the candidate replay is still scoped to
  `forecast_profile`, not an aerosol/smoke feature family.
- `historical_aq_backfill_missing`: historical archive status is
  `partial_forecast_history_archive`.
- `smoke_features_not_selected_by_active_artifact`: zero AQ/smoke columns are
  selected by the active artifact.
- `smoke_permutation_evidence_missing`: no AQ/smoke rows are in the HGB
  permutation artifact.
- `blocked_validation_failed`: daily-first candidate validation is not within
  market tolerance.
- `high_smoke_settlement_slice_missing`: high-smoke slice rows are `0`.

This keeps the AQ/smoke family shadow-only until replay-safe AQ history, a
scoped smoke candidate, permutation evidence, and high-AOD/high-PM settlement
slices exist.

Verification:

- `python -m pytest tests\reporting\test_forecast_smoke_gate.py tests\model\test_forecast_feature.py tests\model\test_feature_store.py tests\operations\test_schema_registry.py -q` -> 48 passed, 12 pre-existing sklearn all-missing fixture warnings.

Acceptance: an aerosol/smoke family is available and settlement-scored, with
measured Tmax-bust reduction on the high-AOD slice and no aggregate regression.

Related: items 185, 27, 79; `[[highs-projection-data-gap-2026-06-20]]`.
