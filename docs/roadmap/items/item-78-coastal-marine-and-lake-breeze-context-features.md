# 78. Coastal Marine And Lake-Breeze Context Features [COMPLETE 2026-06-16 - MARINE CONTEXT REPORTING LIVE]

Goal: add free marine, tide, and coastal station context for markets whose daily
highs are affected by sea/lake breeze, marine layers, or water-temperature
gradients.

Source audit: `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`.
The audit verified NOAA CO-OPS air temperature, wind, and selected water
temperature products, and NDBC realtime flat files with wind, pressure, wave,
and water temperature fields. Sensor support is station-specific.

Why this is missing: the model has a coarse `coastal` market flag and wind
features, but it does not observe the local water/land temperature gradient,
coastal wind regime, or marine-layer risk that can suppress afternoon highs in
NYC, Miami, Houston, Los Angeles, San Francisco, Seattle, Chicago, and Toronto.

## Implementation Design

Source strategy:

- Add `weather.sources.marine_context` with schema `marine_context_v0.1`.
- Keep a static per-market station registry for coastal/lake-influenced
  markets. Each entry records provider (`coops`, `ndbc`, or Canadian marine
  via NDBC-format feeds), station id, distance, bearing, expected sensors,
  onshore-direction sector, and adoption rationale.
- Add parsers/builders for NOAA CO-OPS datagetter hourly meteorological
  products and NDBC realtime flat-file rows. The fetch wrapper returns explicit
  per-station availability, missing-sensor, stale-row, and provenance metadata.
- Include Toronto and Chicago as lake-influenced markets without changing the
  existing coarse `coastal` market flag used by pooled artifacts.

Feature strategy:

- Add live-only marine context columns to the shared feature schema with
  historical defaults of `None`, so unsupported markets and sparse stations do
  not create false zero evidence.
- Derive water-minus-air temperature, marine-air-minus-current-temperature,
  marine wind direction/speed, onshore/offshore flow, post-cutoff onshore
  reversal, breeze risk, marine-layer suppression, station count, latest age,
  and missing-sensor count.
- Gate direction and temperature features on actual sensor support and station
  freshness. Missing water temperature or wind rows remain `None`.

Verification:

- Test the station registry, CO-OPS request/parse normalization, NDBC
  flat-file parsing, stale/missing-sensor gates, live fetcher integration, and
  feature extraction on a lake/sea-breeze suppression fixture.

Out of scope for this implementation slice:

- Historical backfills and raw marine payload storage.
- Promotion into trained model features before settlement-scored adoption
  evidence is reviewed.

Completed implementation slice on 2026-06-15:

- Added `weather.sources.marine_context` with a per-market marine station
  registry, CO-OPS datagetter normalization, NDBC realtime flat-file parsing,
  provenance hashes, and explicit stale/missing-sensor station diagnostics.
- Registered `marine_context` for Toronto, NYC, Chicago, Houston, Los Angeles,
  Miami, San Francisco, and Seattle without changing inland market behavior or
  the existing coarse `coastal` flag.
- Bumped the feature schema to `toronto_feature_store_v1.0` and added live-only
  marine context features with historical `None` defaults.

Completion update on 2026-06-16:

- Added marine-context active-state extraction so only station-gated, fresh,
  required-sensor-complete marine stations surface in model explanations,
  source signal rows, source diagnostics, and the source freshness panel.
- Added a marine-context backtest/report helper that groups settlement misses,
  forecast overcalls, and high-has-stood reversals by market and marine regime
  (`breeze_risk`, `marine_layer_suppression`, onshore/offshore, neutral).
- Kept source-status CSV compatibility intact while adding richer gated marine
  state to JSON diagnostics and report-facing rows.

- [x] Build a per-market marine-context registry mapping coastal/lake markets
  to candidate CO-OPS, NDBC, and Canadian marine/SWOB stations with distance,
  bearing, sensor support, and adoption rationale.
- [x] Add live fetchers for CO-OPS hourly air temperature, water temperature,
  wind, pressure, and humidity where available, plus NDBC realtime meteorology
  and water temperature flat files.
- [x] Add missing-sensor and stale-station gates so unavailable water
  temperature or wind rows do not become false zeros.
- [x] Create features for water-minus-air temperature, coastal wind direction,
  onshore/offshore flow, post-cutoff wind reversal, lake/sea-breeze risk, and
  marine-layer suppression flags.
- [x] Backtest coastal features by market and regime against WU settlement
  misses, forecast overcalls, and high-has-stood reversals.
- [x] Surface active marine-context state in model explanation and source
  freshness reports only when the source passes station-specific gates.

Acceptance: coastal and lake-influenced markets get provenance-labelled marine
context features that improve or explain forecast errors in settlement-scored
replay, while inland markets and unsupported stations remain unaffected.
