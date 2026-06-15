# 27. Weather Regime And Microclimate Features [PARTIAL - MICROCLIMATE FEATURES PLUMBED]

Goal: add physically meaningful signal once the evaluation/calibration loop is
strong enough to judge it.

- [x] Add solar/radiation and cloud-thickness features from Open-Meteo or other
  stable sources.
- [x] Add lake-breeze/onshore-flow indicators for Pearson and Toronto-specific
  warm-season patterns.
- [ ] Add pressure tendency, humidity/dewpoint, wind shift, and gust features to
  late-day continuation where they are not already used.
- [ ] Evaluate whether feature value differs by month/season and cutoff hour.
- [ ] Promote only features that improve out-of-sample item-20 metrics.

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
  humidity/dewpoint, wind speed, and wind-regime one-hots. Wind-shift/gust
  additions remain open until the archived inputs are clean enough to evaluate.
- Verification: `pytest tests\model\test_feature_store.py
  tests\model\test_feature_skew.py tests\model\test_feature_model_ablation.py
  tests\calibration\test_pooled_feature_model.py -q` passed.
