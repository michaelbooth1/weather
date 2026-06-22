# 187. Forecast Shortwave-Radiation & Peak-Window Insolation Features [PARTIAL 2026-06-22 - GATE REFRESHED, ISOLATED REPLAY BLOCKED]

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
- [x] Machine-readable settlement-scored radiation/insolation gate artifact.
- [ ] Passing settlement-scored gate, with attention to morning/midday cutoffs.
- [ ] Optional: add true clear-sky-index features if the forecast source
      persistently exposes clear-sky shortwave radiation.

## 2026-06-22 Gate Rerun

The refreshed weak-input disposition keeps `open_meteo_forecast_profile` in
`served` disposition and positive at broad family level, but it still has `46`
features with `44` low-coverage/sparse rows. This does not close the item
because the radiation/insolation subset has not been isolated from the broader
forecast-profile family or settlement-scored for morning/midday lift with no
late-day regression.

## 2026-06-22 Radiation Gate Artifact

Added `weather.reporting.forecast_radiation_gate`, schema
`forecast_radiation_gate_v0.1`, with generated evidence at:

- `data/backtest/item187_forecast_radiation_gate.json`
- `data/backtest/item187_forecast_radiation_gate_report.md`

Current gate status: `BLOCK`.

Current supportive signal from the full forecast-profile replay:

- early cutoff Brier improves current by `-0.0015`, but trails market by
  `+0.0031`.
- midday cutoff Brier improves current by `-0.0026`, but trails market by
  `+0.0088`.
- late cutoff Brier is safe versus current at `-0.0002`.

That signal is not sufficient to close item 187 because the replay artifact is
`feature_subset=forecast_profile`, not an isolated
`forecast_cloud_solar_radiation` replay. The gate also blocks because direct
and diffuse radiation/direct-share permutation rows are absent from the current
HGB permutation artifact, the full-profile daily-first validation is not within
market tolerance, and high-disagreement guardrails block Austin, Denver, NYC,
San Francisco, and Seattle.

Next unblock: add a `forecast_cloud_solar_radiation` feature-subset train/replay
lane, replay it against settlement outcomes, then regenerate HGB permutation
evidence with the current feature schema so direct/diffuse radiation and
direct-share rows are present.

## 2026-06-22 Gate Refresh

I regenerated `data/backtest/item187_forecast_radiation_gate.json` and
`data/backtest/item187_forecast_radiation_gate_report.md`. The live gate
remains `BLOCK`.

Current blockers:

- `isolated_radiation_replay_missing`: the candidate replay is still scoped to
  `forecast_profile`, not `forecast_cloud_solar_radiation`.
- `direct_diffuse_permutation_evidence_missing`: direct/diffuse radiation and
  direct-share rows are absent from the current HGB permutation artifact.
- `blocked_validation_failed`: daily-first candidate validation is not within
  market tolerance.
- `market_guardrails_blocked`: Austin, Denver, NYC, San Francisco, and Seattle
  remain blocked.

The available full-profile signal is still only supportive context: early,
midday, and late cutoff slices improve current, but this is not isolated
radiation evidence and does not permit promotion.

Verification:

- `python -m pytest tests\reporting\test_forecast_radiation_gate.py tests\model\test_feature_store.py tests\sources\test_historical_sources.py tests\operations\test_schema_registry.py -q` -> 58 passed, 12 pre-existing sklearn all-missing fixture warnings.

Acceptance: forecast insolation features are available and settlement-scored,
with measured pre-peak skill improvement and no late-day regression.

Related: items 185, 27, 74; `[[highs-projection-data-gap-2026-06-20]]`.
