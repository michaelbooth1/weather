# 187. Forecast Shortwave-Radiation & Peak-Window Insolation Features [PARTIAL 2026-06-21 - RADIATION FEATURE PATH LIVE, GATE PENDING]

Goal: feed the model the forecast surface energy input that drives daytime
heating: downward shortwave radiation, direct/diffuse radiation mix, and
peak-window cloud cover.

Source: `docs/roadmap/high-temperature-projection-research-audit-2026-06-20.md`,
Gap 3. The legacy model reasoned about clouds categorically (`cloud_group`,
NWS-grid sky-cover) and did not reliably expose the continuous radiation flux
those clouds modulate. Insolation/cloud-based models outperform
temperature-only models for this quantity ([MDPI Climate 2019](https://www.mdpi.com/2225-1154/7/7/89);
[all-sky Tmax ML reconstruction](https://www.sciencedirect.com/science/article/abs/pii/S0169809522003842)).

Why this matters: nearly free. The model already fetches Open-Meteo forecast
rows, and the forecast API path already carries hourly `shortwave_radiation`,
`direct_radiation`, `diffuse_radiation`, and cloud-layer fields.

## Status

2026-06-21: forecast radiation features are available in the shared train/live
feature store and covered by parity tests:

- remaining-window shortwave sum and next-3h shortwave mean.
- remaining-window direct and diffuse radiation sums.
- next-3h direct and diffuse radiation means.
- remaining-window and next-3h direct-radiation share, using paired
  direct/diffuse rows as a clearness proxy.
- remaining-window total/low/mid/high cloud means, total/low cloud maxima, and
  3h total-cloud trend.

The implementation deliberately does not claim a true clear-sky index because
the current persisted Open-Meteo payload does not carry a clear-sky shortwave
field. If a stable provider field is added, this item can add an explicit
`forecast_*_clear_sky_index` alongside the existing direct-share proxy.

## Design

1. In `forecast_profile_features`, keep the existing shared train/live feature
   path and derive radiation features from normalized forecast rows.
2. Use the Open-Meteo fields already collected by `fetch_open_meteo`:
   `shortwave_radiation`, `direct_radiation`, `diffuse_radiation`, and
   cloud-layer fields.
3. Keep the existing `cloud_group` regime; the radiation features are continuous
   complements, not replacements.
4. Gate via the settlement-scored feature-value gate (item 27); validate that
   morning/midday hours improve without late-day regression.

- [x] Add forecast shortwave / peak-window cloud / direct-radiation share features.
- [x] Wire Open-Meteo radiation fields through the existing fetch path.
- [ ] Settlement-scored gate, with attention to morning/midday cutoffs.
- [ ] Optional: add true clear-sky-index features if the forecast source
      persistently exposes clear-sky shortwave radiation.

Acceptance: forecast insolation features are available and settlement-scored,
with measured pre-peak skill improvement and no late-day regression.

Related: items 185, 27, 74; `[[highs-projection-data-gap-2026-06-20]]`.
