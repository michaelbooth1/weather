# 27. Weather Regime And Microclimate Features [NEW]

Goal: add physically meaningful signal once the evaluation/calibration loop is
strong enough to judge it.

- [ ] Add solar/radiation and cloud-thickness features from Open-Meteo or other
  stable sources.
- [ ] Add lake-breeze/onshore-flow indicators for Pearson and Toronto-specific
  warm-season patterns.
- [ ] Add pressure tendency, humidity/dewpoint, wind shift, and gust features to
  late-day continuation where they are not already used.
- [ ] Evaluate whether feature value differs by month/season and cutoff hour.
- [ ] Promote only features that improve out-of-sample item-20 metrics.

Acceptance: new weather features improve the calibrated model, not just feature
importance charts.
