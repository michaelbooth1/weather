# 75. US Official Forecast Grid And Multi-Model Guidance [COMPLETE 2026-06-16 - US GUIDANCE REPLAY DIAGNOSTICS LIVE]

Goal: add official US forecast-grid and model-specific guidance as structured
features for the Fahrenheit market family.

Source audit: `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`.
The audit smoke tests verified NWS `forecastGridData`, Open-Meteo `/v1/gfs`
model columns for `gfs_seamless`, `ncep_hrrr_conus`, `ncep_nbm_conus`, and
`ncep_nam_conus`, and raw NOMADS/S3 access for NBM and HRRR.

Why this is missing: the current system uses NWS hourly period forecasts and an
Open-Meteo/GFS ensemble source, but does not consume raw NWS grid data or
separate HRRR/NBM/NAM/GFS model columns. That hides useful forecast disagreement
and uncertainty structure.

## Implementation Design

Source additions:

- Add two US-only live sources: `nws_grid` and `open_meteo_multimodel`.
- `nws_grid` reuses `points/{lat},{lon}` but follows the
  `forecastGridData` URL instead of `forecastHourly`. It stores grid metadata
  by market, requests the grid JSON, and normalizes target-day grid values for
  temperature, maxTemperature, dewpoint, relativeHumidity, skyCover,
  windDirection, windSpeed, probabilityOfPrecipitation, quantitativePrecipitation,
  weather, and hazards.
- `open_meteo_multimodel` uses `https://api.open-meteo.com/v1/gfs` with models
  `gfs_seamless,ncep_hrrr_conus,ncep_nbm_conus,ncep_nam_conus`. Smoke testing
  confirmed this endpoint returns suffixed columns such as
  `temperature_2m_ncep_hrrr_conus`; the adapter will normalize those into
  per-hour `models` dictionaries and per-day `day_model_highs`.
- Non-US markets return an unavailable payload for both sources; US market specs
  opt into both live sources.

Feature schema:

- Bump the active feature schema from `toronto_feature_store_v0.8` to
  `toronto_feature_store_v0.9`, preserving v0.8 as legacy.
- Add live guidance feature columns:
  `nws_grid_high`, `nws_grid_vs_forecast_high`,
  `nws_grid_pop_after_cutoff_max`, `nws_grid_qpf_after_cutoff_sum`,
  `nws_grid_sky_cover_after_cutoff_mean`, `nws_grid_hazard_count`,
  `open_meteo_multimodel_high_spread`, `open_meteo_gfs_high_delta`,
  `open_meteo_hrrr_high_delta`, `open_meteo_nbm_high_delta`,
  `open_meteo_nam_high_delta`, `open_meteo_nbm_hrrr_disagreement`, and
  `open_meteo_multimodel_next_3h_spread`.
- Historical training records default these columns to `None` until there is a
  provenance-preserving archive/backfill path. This keeps live-only diagnostics
  from silently entering model training.

Verification:

- Add parser tests for NWS grid rows, payload hash/metadata, and
  zero-valued POP/QPF fields.
- Add parser tests for Open-Meteo multi-model request parameters, suffixed
  columns, day highs, and spread.
- Add live feature-extraction tests for NWS grid deltas and multi-model spread.
- Update schema-registry tests and run targeted feature/source/schema tests,
  compile, and schema literal audit.

Out of scope for this implementation slice:

- Historical NBM/HRRR/NAM/GFS backfills from NOMADS/S3 or previous-run APIs.
- Promotion decisions before settlement-scored replay evidence is reviewed.

Implementation slice completed 2026-06-15:

- Added US-only `nws_grid` and `open_meteo_multimodel` live sources for built-in
  US markets.
- Added NWS grid metadata caching, grid row normalization, payload hashing,
  provider update fields, and zero-preserving POP/QPF handling.
- Added Open-Meteo `/v1/gfs` multi-model parsing for GFS, HRRR, NBM, and NAM
  suffixed columns.
- Added `toronto_feature_store_v0.9` live guidance features with historical
  defaults set to `None` until archives exist.
- Verified parser, feature, cache TTL, schema, compile, and schema-audit paths.

Completed implementation slice on 2026-06-16:

- Bumped the active feature schema to `toronto_feature_store_v1.3`, preserving
  v1.2 as legacy, for additive US guidance run metadata and diagnostics.
- Added NWS grid run-age metadata plus explicit live-only archive markers for
  NWS grid and Open-Meteo GFS/HRRR/NBM/NAM guidance fields.
- Added additive feature columns for NWS grid run age, Open-Meteo multi-model
  run age, run-to-run high change hooks, and NBM/HRRR disagreement after
  cutoff.
- Added US guidance replay diagnostics comparing forecast consensus with NWS
  grid and model-specific Open-Meteo guidance by market, cutoff, and weather
  regime.

- [x] Add a US-only NWS `forecastGridData` adapter that resolves
  `points/{lat},{lon}` to the grid URL and extracts temperature,
  maxTemperature, dewpoint, relativeHumidity, skyCover, wind, POP, QPF,
  weather, and hazards.
- [x] Cache NWS points/grid metadata by market and record provider update time,
  fetched time, row counts, payload hash, and API error state.
- [x] Add an Open-Meteo `/v1/gfs` multi-model adapter for
  `gfs_seamless`, `ncep_hrrr_conus`, `ncep_nbm_conus`, and
  `ncep_nam_conus`, using the same requested variables as item 74 where
  available.
- [x] Build features for NWS max/high versus forecast consensus, HRRR/NBM/NAM
  high deltas, multi-model high spread, model run age, run-to-run changes, and
  NBM/HRRR disagreement after cutoff.
- [x] Archive historical model-specific forecasts where the provider supports
  previous runs or single-run retrieval, and explicitly mark fields that are
  live-only until a backfill path exists.
- [x] Add replay diagnostics comparing current forecast consensus with the new
  official-grid and multi-model guidance by market, cutoff, and weather regime.

Acceptance: US markets have structured NWS grid rows and model-specific
GFS/HRRR/NBM/NAM guidance available as provenance-preserving features, with
missing historical coverage blocked from model training unless explicitly gated
as live-only diagnostics.
