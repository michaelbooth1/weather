# 188. Aerosol & Wildfire-Smoke Suppression Features [PARTIAL 2026-06-21 - OPEN-METEO AQ FEATURE PATH LIVE, SMOKE-SLICE GATE PENDING]

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
- [ ] Add historical AQ backfill/retrain support so the feature family is
      selectable by promoted artifacts.
- [ ] Settlement-scored gate with an explicit high-AOD/high-PM smoke-day slice.

Acceptance: an aerosol/smoke family is available and settlement-scored, with
measured Tmax-bust reduction on the high-AOD slice and no aggregate regression.

Related: items 185, 27, 79; `[[highs-projection-data-gap-2026-06-20]]`.
