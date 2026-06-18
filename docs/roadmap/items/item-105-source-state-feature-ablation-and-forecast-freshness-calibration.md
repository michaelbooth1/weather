# 105. Source-State Feature Ablation And Forecast Freshness Calibration [COMPLETE 2026-06-18 - SOURCE-STATE ABLATION GATE LIVE]

Goal: prove whether source-health and forecast-age features improve settlement
accuracy before they influence promoted model decisions.

Source: 2026-06-16 local Python audit. The dynamic source-state path records
fresh/stale/failed counts, WU history age, source-status groups, the freshest
forecast payload age, and the maximum forecast age. Tests verify that these
fields are present and replay-compatible, but the code does not yet have a
named settlement-scored ablation that decides which source-state fields should
carry model weight during degraded-source days.

Why this matters: one fresh forecast can coexist with another stale or failed
forecast family. A model that only learns from the freshest payload age may
overtrust degraded-source snapshots, while a model that over-penalizes any
failure may throw away useful redundancy.

## Design

1. Add paired replay variants for dynamic source state:
   no source-state fields, current source-state fields, max-age-focused fields,
   per-family availability fields, and degraded-family interaction fields.
2. Score the variants by market, cutoff hour, late-day window, source-status
   group, and coastal/marine context.
3. Require daily-first settlement-scored lift and no material degradation on
   all-fresh days before source-state fields can move from shadow to serving.
4. Report feature value separately for Open-Meteo-family rate limiting, WU
   history staleness, METAR/current observation staleness, and official Toronto
   source degradation.
5. Feed losing variants back into the active feature schema as shadow-only or
   remove them from the served artifact.

- [x] Add source-state ablation variants to pooled candidate replay.
- [x] Compare freshest forecast age versus maximum forecast age as separate
  features.
- [x] Add source-family degradation indicators and interactions as a shadow
  variant.
- [x] Publish daily-first, market-level, and degraded-source slice scores.
- [x] Gate promotion on paired all-fresh and degraded-source performance.

Acceptance: dynamic source-state fields only influence serving when a paired
settlement replay shows they improve accuracy in degraded-source slices without
hurting all-fresh market days.

## Completion Notes

Completed 2026-06-18. `pooled_candidate_replay` now emits a non-serving
`source_state_ablation_v0.1` section whenever the replayed artifact declares
dynamic source-state features. The gate treats current serving as the
no-source-state control and the dynamic-source artifact as the candidate, then
scores aggregate, daily-first, all-fresh, degraded-source, source-freshness,
and per-market slices.

The report records source-state feature families separately, including freshest
forecast age, maximum forecast age, forecast-family degradation counts,
WU-history state, METAR state, status-group interactions, and cross-source
disagreement. It also writes Item-69-compatible shadow rows for
`source_state_no_source_state_current` and `source_state_dynamic_candidate`, so
the variant can be tracked without changing serving.

Verification:

- `python -m pytest tests\calibration\test_pooled_candidate_replay.py -q`
