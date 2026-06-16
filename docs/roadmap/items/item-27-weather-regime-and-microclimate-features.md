# 27. Weather Regime And Microclimate Features [COMPLETE 2026-06-15 - FEATURE-VALUE GATE LIVE]

Goal: add physically meaningful signal once the evaluation/calibration loop is
strong enough to judge it.

- [x] Add solar/radiation and cloud-thickness features from Open-Meteo or other
  stable sources.
- [x] Add lake-breeze/onshore-flow indicators for Pearson and Toronto-specific
  warm-season patterns.
- [x] Add pressure tendency, humidity/dewpoint, wind shift, and gust features to
  late-day continuation where they are not already used.
- [x] Evaluate whether feature value differs by month/season and cutoff hour.
- [x] Promote only features that improve out-of-sample item-20 metrics.

Acceptance: new weather features improve the calibrated model, not just feature
importance charts.

Implementation update 2026-06-15:

- Forecast profile features already include remaining solar, next-3h solar,
  total/low/mid/high cloud features, cloud trend, and ensemble spread in the
  v0.5 feature schema.
- The v0.6 feature schema adds `onshore_flow`, `onshore_wind_speed_kmh`, and
  `lake_breeze_proxy`; both live and historical feature extraction use the same
  market-aware helper, including pooled model training.
- Feature ablation reporting now groups the new indicators under
  `microclimate`.
- Late-day continuation already includes pressure, pressure trend,
  humidity/dewpoint, wind speed, and wind-regime one-hots.
- Verification: `pytest tests\model\test_feature_store.py
  tests\model\test_feature_skew.py tests\model\test_feature_model_ablation.py
  tests\calibration\test_pooled_feature_model.py -q` passed.

Implementation update 2026-06-15 UTC:

- The v0.7 shared feature schema adds `wind_gust_kmh` and
  `wind_shift_3h_degrees`.
- Historical feature extraction and live feature extraction now compute the
  same gust and compass-aware 3h wind-shift features.
- Late-day continuation training and serving can consume the new numeric
  fields after retrain; existing artifacts keep serving because they select
  their trained feature names.
- Focused verification: `pytest tests\model\test_feature_store.py
  tests\model\test_feature_skew.py tests\model\test_feature_model_ablation.py
  tests\calibration\test_forecast_error_model.py
  tests\operations\test_schema_registry.py -q` passed (`40` tests,
  `144` subtests).

Completion update 2026-06-15:

- `src.feature_model --item27-report-only` now writes
  `data/wunderground/cyyz/analysis/item27_feature_value_report.md` and the
  machine-readable
  `data/wunderground/cyyz/analysis/item27_feature_value_gate.json`.
- The gate uses deterministic held-out day folds and reports settlement-style
  log-loss/Brier by cutoff hour, by month, by meteorological season, and by
  cutoff-hour/month.
- The promotion rule is conservative: a feature family is `promote` only when
  neutralizing that family worsens both held-out log-loss and held-out Brier.
- Current Toronto gate result: `microclimate` and `observed_temp_path` promote;
  `atmosphere`, `wind_regime`, `forecast`, and `cloud_regime` remain blocked
  because at least one held-out metric was non-positive. This avoids treating
  feature plumbing or importance-style sensitivity as promotion evidence.
- Verification:
  `python -m src.feature_model --market toronto --item27-report-only --item27-folds 5`
  regenerated the report over 9,100 held-out rows, and
  `python -m pytest tests/model/test_feature_model_ablation.py -q` passed
  (`8` tests).
