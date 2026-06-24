# 74. Open-Meteo Expanded Environmental Forecast Features [COMPLETE 2026-06-16 - PROMOTION GATE AND MISSING-ZERO REPORT LIVE]

Goal: turn the free-source audit's lowest-friction weather inputs into
train/serve-parity features before investing in heavier GRIB pipelines.

Source audit: `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`.
The smoke test confirmed that Open-Meteo already returns CAPE, pressure-level
temperature, 500 hPa height, direct/diffuse radiation, gusts, visibility,
precipitation, soil state, VPD, ET0, and model-specific columns through JSON.

Why this is missing: the current Open-Meteo adapter stores total cloud,
cloud-layer, shortwave, wind, and GFS ensemble spread, but the model still lacks
vertical thermal structure, land-surface state, detailed energy-budget fields,
and explicit convection/heating-interruption variables.

## Implementation Design

Schema changes:

- Bump the active feature schema from `toronto_feature_store_v0.7` to
  `toronto_feature_store_v0.8`, preserving v0.7 as a legacy registry entry.
- Bump the Open-Meteo long forecast archive from `forecast_history_long_v2` to
  `forecast_history_long_v3`, preserving v2 as a legacy registry entry.
- Keep existing model artifacts serving by relying on trained `feature_names`
  selection. The new columns are additive; this item does not promote a model
  trained on the new shape.

Raw source contract:

- Extend live `fetch_open_meteo()` and historical
  `fetch_historical_forecast_payload()` with the same hourly JSON fields:
  `cape`, `temperature_925hPa`, `temperature_850hPa`,
  `geopotential_height_500hPa`, `direct_radiation`, `diffuse_radiation`,
  `wind_gusts_10m`, `visibility`, `precipitation_probability`,
  `precipitation`, `soil_temperature_0cm`, `soil_moisture_0_to_1cm`,
  `vapour_pressure_deficit`, and `et0_fao_evapotranspiration`.
- Normalize row keys once at the source boundary. Live rows use concise model
  keys such as `direct_radiation`, `wind_gust_kmh`,
  `temperature_925hpa`, and `geopotential_height_500hpa`; historical rows store
  the same names in `forecast_history_long_v3` so train/serve parity does not
  depend on Open-Meteo's mixed-case API spelling.
- Historical v1/v2 files remain readable. Missing additive fields load as
  `None`; zeros from the provider stay numeric zeros.

Derived feature contract:

- Add shared `forecast_profile_features()` outputs for remaining direct and
  diffuse radiation sums, next-3h direct and diffuse radiation means,
  remaining and next-3h precipitation, next-3h precipitation probability max,
  remaining and next-3h CAPE, CAPE trend, 925/850 hPa thermal structure, 500 hPa
  height, max gust, minimum visibility, soil temperature/moisture, VPD, and ET0.
- Pressure-level lapse proxies are temperature differences in native units:
  surface-minus-925 hPa and 925-minus-850 hPa over the remaining forecast
  window. They are intentionally named proxies because pressure-level heights
  are not converted to geometric lapse rates in this slice.

Verification:

- Extend forecast-profile train/live parity tests with the new fields and
  representative nonzero and zero values.
- Extend forecast-history row and profile-loader tests to prove v3 raw fields
  are written and loaded.
- Add a narrow live Open-Meteo adapter test that verifies the hourly request
  includes the expanded variables and the returned row contains normalized
  fields.
- Update schema-registry tests for the active v0.8/v3 versions.

Out of scope for this implementation slice:

- Running full historical backfills for all markets.
- Retraining, replay scoring, or promoting models that consume the new feature
  columns.
- Running the fleet-scale backfill/retrain/replay jobs inside this
  implementation slice; the promotion gate requires those artifacts before
  promotion.

Implementation slice completed 2026-06-15:

- Added `toronto_feature_store_v0.8` expanded profile columns and shared
  train/serve feature derivation.
- Added live Open-Meteo request and row normalization for the expanded hourly
  fields.
- Added `forecast_history_long_v3` historical row/profile support and retained
  v2 compatibility for missing additive fields.
- Added focused tests for train/live parity, historical row/profile loading,
  live adapter request parsing, schema registry lookup, compile, and schema
  literal audit.

Completed implementation slice on 2026-06-16:

- Added a forecast-profile missing-vs-zero report that separates provider
  missing fields from true numeric zeroes for expanded Open-Meteo fields,
  including direct/diffuse radiation.
- Added markdown rendering for the missing-vs-zero report.
- Added an expanded Open-Meteo feature promotion gate that blocks promotion
  until all active-market forecast-history backfills, per-market retraining,
  pooled retraining, and settlement-scored replay lift are present.

- [x] Extend live Open-Meteo forecast fetching with `cape`,
  `temperature_925hPa`, `temperature_850hPa`,
  `geopotential_height_500hPa`, `direct_radiation`, `diffuse_radiation`,
  `wind_gusts_10m`, `visibility`, `precipitation_probability`,
  `precipitation`, `soil_temperature_0cm`, `soil_moisture_0_to_1cm`,
  `vapour_pressure_deficit`, and `et0_fao_evapotranspiration`.
- [x] Extend the historical forecast archive schema and backfill path for the
  same fields, preserving `source_model`, issue/run metadata, payload hash,
  valid time, unit, and source URL.
- [x] Add shared forecast-profile feature helpers for remaining-day CAPE,
  next-3h CAPE, pressure-level lapse proxies, 500 hPa height, remaining
  direct/diffuse radiation, gust risk, visibility, precipitation after cutoff,
  soil state, VPD, and ET0.
- [x] Keep old artifacts serving by selecting trained feature names rather than
  assuming the newest schema shape.
- [x] Add a promotion gate requiring forecast-history backfills for all active
  markets, per-market and pooled retraining, and replay/gauntlet scoring before
  promotion.
- [x] Add reporting that separates missing-provider fields from true zero
  meteorological values, especially for recent near-real-time radiation fields.

Acceptance: the expanded Open-Meteo feature family is available in both live
serving and historical training rows, has source-freshness and payload lineage,
and is promoted only after settlement-scored evidence shows no-market model
improvement versus the current serving feature set.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - PROMOTION GATE AND MISSING-ZERO REPORT LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

