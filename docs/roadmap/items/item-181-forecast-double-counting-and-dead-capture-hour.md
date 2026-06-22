# 181. Forecast Signal Double-Counting And Dead Capture-Hour [PARTIAL 2026-06-22 - SCOPE PROOF BLOCKED ON CURRENT FEATURE TAPE]

Goal: stop double-counting forecast signal on the feature-model path and resolve
the unused `capture_hour` parameter in the forecast-error component.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` finding M2 (also the
2026-06-09 audit finding #7). On the ML path the HGB already ingests forecast
features (`forecast_high`, `forecast_gap`, multi-model guidance), and the
pipeline then *also* runs `apply_forecast_floor` + `apply_forecast_pull`
([model_distribution.py:698-732](../../../src/weather/model/model_distribution.py#L698)),
re-injecting the same forecast consensus post-hoc. Separately,
`forecast_error_distribution(..., capture_hour=...)` accepts the hour but never
uses it ([calibration_runtime.py:411](../../../src/weather/model/calibration_runtime.py#L411)),
so the forecast-error component is not hour-conditioned at serve.

Why this matters: the team already found that tuning the pull window in isolation
backfires (2026-06-12 constants note), which is consistent with double-counting —
the right control is "how much forecast signal is already in the HGB," not the
pull window alone. A parameter that is threaded through but ignored is a latent
correctness/clarity trap.

## Design

1. Use the existing feature-ablation harness to measure how much forecast signal
   the HGB already carries, and the incremental replay value of serving
   pull/floor on the ML path versus fallback-only.
2. Gate forecast pull/floor to the empirical fallback path, or keep it on the ML
   path only where the replay delta is net-positive, documented with numbers.
3. Either consume `capture_hour` (hour-condition the forecast-error component) or
   delete the parameter and its call-site threading.

- [ ] Quantify HGB forecast-feature attribution and serving pull/floor delta.
- [x] Decide and implement the pull/floor application scope.
- [ ] Attach replay evidence for the selected pull/floor scope.
- [x] Use or remove `capture_hour` end to end.

Acceptance: forecast pull/floor on the ML path is justified by a measured replay
delta or removed, `forecast_error_distribution` either uses `capture_hour` or no
longer accepts it, and there is no aggregate or per-market regression.

Progress note 2026-06-21: the serving distribution stage now skips
`apply_forecast_floor` and `apply_forecast_pull` whenever the HGB/LR feature
model is active, leaving the post-hoc forecast-shape adjustment on the empirical
fallback path only. `forecast_error_distribution(..., capture_hour=...)` now
selects hour-specific `hour_stats` when present, with source/global fallback, and
offline forecast-error scoring passes each row's `capture_hour` through the same
selector. The remaining work is the item-182 replay/stage-attribution run that
quantifies aggregate and per-market deltas.

Progress note 2026-06-22: `distribution_stage_attribution` now emits a
`forecast_shape_scope` proof that splits `forecast_pull` rows by
`active_model_kind` and by runtime source identity. The regenerated
`data/backtest/distribution_stage_attribution.json` is still `BLOCK` for this
scope, but the blocker is now narrowed: `feature_model_forecast_shape_rows=268917`
and `stale_feature_model_forecast_shape_rows=268917`, while
`current_code_feature_model_component_rows=0` and
`current_code_feature_model_forecast_shape_rows=0` for current identity
`master@2e3672d99680 src:00ec00b3057e5468`. The latest stale feature-model
forecast-shape row is `2026-06-21T06:41:51.248605+00:00`. Empirical fallback
rows remain isolated (`empirical_forecast_shape_rows=1419`) with
`empirical_delta_brier=-0.012189291817646672` and
`empirical_delta_logloss=0.6523487776684005`. The next unblock is to
regenerate/replay current-code feature-model component tapes and require
`current_code_feature_model_forecast_shape_rows=0` before this item can close.

Related: items 182, 134, 135; `[[model-audit-2026-06-09]]`, `[[replay-ablation-findings]]`.
