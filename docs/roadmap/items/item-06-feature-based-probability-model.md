# 6. Feature-Based Probability Model [IMPLEMENTED - CALIBRATION NEXT]

- [x] Build a tabular training set with one row per historical day per cutoff hour.
- [x] Include features:
  high so far, current/latest temp, rise from 7 AM, wind direction/speed,
  cloud regime, dew point, humidity, pressure trend, and forecast max.
- [x] Train a simple interpretable model first:
  multinomial logistic regression, isotonic-calibrated random forest, or
  gradient boosting with calibration.
- [x] Keep the empirical model as a baseline and fallback.

Codex audit (2026-05-28): partial. `src/feature_model.py` builds per-hour rows,
exports logistic-regression coefficients, exports a HistGradientBoosting model,
and `src/toronto_model.py` falls back to the empirical baseline. Issues found:
the feature set omits forecast max, the gradient boosting model is not
calibrated, the checked-in training script has `RUN_LOO = False` so reruns do
not regenerate the evaluation report, and the feature-model report lacks Brier
or calibration metrics.

Codex update (2026-05-31): the old item-6 audit notes are partly superseded.
`src/feature_model.py` now includes `forecast_high` and `forecast_gap`, has
`RUN_LOO = True`, exports refreshed LR/HGB/late-day artifacts, and writes
`data/wunderground/cyyz/analysis/feature_model_report.md` with log loss, Brier,
accuracy, ECE, and tuned per-hour HGB blend weights. Remaining accuracy work:
the HGB output is still not probability-calibrated with a dedicated
Platt/isotonic/temperature layer, and validation is still model-vs-history
rather than model-vs-Polymarket market-bin edge. New item 21 owns this.
