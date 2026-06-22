# 181. Forecast Signal Double-Counting And Dead Capture-Hour [COMPLETE 2026-06-22 - ML SCOPE REMOVED, EMPIRICAL FALLBACK GATED]

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

- [x] Quantify HGB forecast-feature attribution and serving pull/floor delta.
- [x] Decide and implement the pull/floor application scope.
- [x] Attach replay evidence for the selected pull/floor scope.
- [x] Use or remove `capture_hour` end to end.
- [x] Resolve empirical fallback forecast-shape per-market regressions, or
  gate/disable empirical fallback pull/floor where the stage evidence regresses.

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
`active_model_kind` and by runtime source identity, and it reads current
component sidecars before settlement so fresh live-forward tapes can prove
scope. After restarting the loops on current source and forcing a current
snapshot, the regenerated `data/backtest/distribution_stage_attribution.json`
has `forecast_shape_scope.status=PASS` for current identity
`master@1e175b4428b7 src:3c207862dc78facf`.
`current_code_feature_model_component_rows=1518` across `12` current-code
snapshots, and `current_code_feature_model_forecast_shape_rows=0`; the only
feature-model forecast-shape rows are stale (`stale_feature_model_forecast_shape_rows=270897`,
latest `2026-06-21T06:49:36.894359+00:00`). Empirical fallback rows remain
isolated (`empirical_forecast_shape_rows=1419`) with
`empirical_delta_brier=-0.012189291817646672` and
`empirical_delta_logloss=0.6523487776684005`.

The item remains partial because the remaining unchecked acceptance work is the
replay/attribution evidence for HGB forecast-feature contribution and aggregate
plus per-market regression deltas; the serving scope proof itself no longer
blocks.

Progress note 2026-06-22: `weather.reporting.forecast_double_counting` now
writes `data/backtest/item181_forecast_double_counting.json` and
`data/backtest/item181_forecast_double_counting_report.md`, combining HGB
forecast-feature attribution, forecast-pull/floor stage deltas, current-code
scope proof, and the `capture_hour` contract. The report proves the original
quantification gap is closed: all-day forecast-profile HGB permutation delta
MAE is `+0.44261106600585753`, early forecast-profile delta MAE is
`+0.5034720502189916`, and single-feature `forecast_high` all-day delta MAE is
`+0.41589399642072006`. Current-code ML scope still passes
(`current_code_feature_model_component_rows=1518`,
`current_code_feature_model_forecast_shape_rows=0`) and `capture_hour` is
contract-proven.

The first generated acceptance was `BLOCK`: settled stage evidence showed
overall `forecast_pull` improved Brier (`mean_delta_brier=-0.007767159087645951`)
but worsened log-loss (`mean_delta_logloss=+0.07173605011445329`). The empirical
fallback scope had aggregate Brier lift but large log-loss regression and
per-market regressions: Brier regressed Atlanta, Austin, Chicago, Dallas, and
Denver; log-loss regressed Atlanta, Austin, Chicago, Dallas, Denver, and San
Francisco.

I added an explicit empirical fallback forecast-shape policy in serving:
forecast pull/floor remains available only for markets whose settled empirical
stage evidence is non-regressing on both Brier and log-loss (`houston`,
`los-angeles`, `miami`, `nyc`, `seattle`, and `toronto`). Regenerating current
component evidence and the item-181 report after the policy change produced
`data/backtest/item181_forecast_double_counting.json` with `status=PASS`.
Final evidence: current identity `master@1e175b4428b7 src:f0eef80ee37a7f33`,
`current_code_feature_model_component_rows=902`,
`current_code_feature_model_forecast_shape_rows=0`, selected empirical fallback
rows `770`, selected empirical `mean_delta_brier=-0.023496184137963953`,
selected empirical `mean_delta_logloss=-0.08258785826303904`, and zero selected
empirical Brier/log-loss regressing markets. The suppressed empirical markets
remain diagnostic evidence only.

Related: items 182, 134, 135; `[[model-audit-2026-06-09]]`, `[[replay-ablation-findings]]`.
