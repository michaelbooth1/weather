# 136. Forecast Source-State Reliability Calibrator [PARTIAL 2026-06-18 - RELIABILITY SHADOW LIVE, DEGRADED SLICE BLOCKED]

Goal: convert forecast source count, source disagreement, and freshness state
from broad diagnostics into a calibrated reliability layer that adjusts
forecast confidence when source quality changes.

Source: `data/backtest/input_variable_significance_2026_06_18_report.md`.
The forecast-source-state family was much smaller than the forecast-profile
family but still showed measurable value:

- all-day family HGB permutation delta MAE: `0.0239`, q `0.0170`;
- early-day family HGB permutation delta MAE: `0.0318`, q `0.0209`;
- `forecast_source_count` individual HGB delta MAE: `0.0186`;
- `forecast_disagreement` individual HGB delta MAE: `0.0056`.

Item 105 proved the source-state ablation gate. This item is the next step:
turn the measured source-state signal into a calibrated reliability adjustment
for the forecast family, especially before observations dominate.

Why this matters: forecast inputs are strongest early, but early-day forecasts
are also most exposed to missing sources, stale payloads, and inter-source
disagreement. Treating source-state as a standalone feature can understate its
role: it should often scale the confidence of forecast-profile evidence.

## Design

1. Build a forecast reliability calibrator that consumes source count, forecast
   disagreement, payload age, stale/failed source states, and source-family
   availability.
2. Apply the calibrator as a confidence adjustment to forecast-profile output,
   not only as independent model columns.
3. Score reliability-adjusted candidates on all-fresh, degraded-source,
   high-disagreement, and low-source-count slices.
4. Separate missingness signal from genuine meteorological disagreement so the
   model does not learn source outage artifacts as weather.
5. Feed reliability state into market-making quote width, not just fair value.

- [x] Add a reliability-calibrated forecast-profile candidate.
- [x] Add paired replay slices for all-fresh, degraded-source, low-count, and
  high-disagreement snapshots.
- [x] Add a calibration curve showing forecast error versus source-state risk.
- [x] Add per-market source reliability thresholds for forecast-family
  confidence shrinkage.
- [ ] Surface the active source-state reliability reason in model explanations
  and quote-risk reports.
- [ ] Clear degraded-source and per-market reliability thresholds on pinned
  replay rows.

Acceptance: source-state reliability adjustment improves degraded-source and
high-disagreement slices without hurting all-fresh days, and promotion reports
show the reliability effect separately from raw forecast-profile skill.

## 2026-06-18 implementation update

Extended the shadow-variant export with optional source-state context columns:
`cutoff_regime`, `source_freshness_state`, `forecast_source_count_bucket`,
`forecast_disagreement_bucket`, and `forecast_bucket_pressure`. Regenerated
`data/backtest/item134_forecast_profile_shadow_variants.csv` from the pinned
forecast-profile replay so item 136 can score row-level source-state slices
without changing serving behavior.

Added `weather.reporting.forecast_source_state_reliability`, schema
`forecast_source_state_reliability_v0.1`. The report builds a non-serving
source-state reliability candidate by shrinking the forecast-profile
probability toward current serving probability as source-state risk rises.
Risk is keyed by source freshness, forecast source-count bucket, and forecast
disagreement bucket, and each row carries the active reliability reason.

Generated:

- `data/backtest/item136_reliability_calibrated_shadow_variants.csv`
- `data/backtest/item136_source_state_reliability.json`
- `data/backtest/item136_source_state_reliability_report.md`

The reliability candidate improves current replay daily-first
(`-0.0022` Brier delta versus current) and improves the high-disagreement slice
relative to raw forecast-profile skill (`-0.0002` delta versus raw forecast).
It does not clear acceptance: degraded-source rows are sparse (`22`) and worsen
raw forecast-profile skill by `+0.0022`, all-fresh rows are nearly flat but
slightly worse (`+0.0001`), and Houston blocks the per-market reliability
threshold with `+0.0012` delta versus raw forecast on risk rows.

Model explanations now surface a supplied `source_state_reliability` /
`forecast_source_state_reliability` payload. Quote-risk report wiring is still
open, so this item remains partial.
