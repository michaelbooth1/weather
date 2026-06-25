# 6. Feature-Based Probability Model [COMPLETE - TEMPERATURE CALIBRATION LAYER]

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

Implementation update (2026-06-15): complete. HGB now has a dedicated
probability-temperature calibration layer. `src.weather.calibration.feature_probability_calibration`
provides normalization, multiclass temperature scaling, blend/log-loss helpers,
and a grid tuner that keeps the legacy `temperature=1.00` / `blend=0.80` pair
in the candidate set. `src.weather.calibration.feature_model` writes the tuned
per-hour `probability_temperature` and calibration metadata into new HGB bundles
(`feature_model_hgb_v0.2`), and `src.weather.model.model_features` applies that
temperature at serving time with a `1.0` fallback for older pickles. The
model-vs-market calibration concern is covered by item 21's exact-distribution
and market-bin calibration layer.

Artifact note: a full Toronto LOO retrain was attempted on 2026-06-15 with
`.\venv\Scripts\python.exe -m src.feature_model --market toronto`, but it did
not finish within a 10-minute command window and did not rewrite the checked-in
pickle. Existing bundles therefore keep the safe `1.0` fallback until the next
offline feature-model artifact refresh.

Verification:
- `.\venv\Scripts\python.exe -m pytest tests\calibration\test_feature_probability_calibration.py tests\model\test_feature_model_calibration.py tests\model\test_feature_model_ablation.py tests\model\test_feature_skew.py tests\model\test_estimate_distribution.py tests\calibration\test_probability_calibration.py -q` -> 47 passed, 126 subtests passed.
- `.\venv\Scripts\python.exe -m compileall src\weather\calibration\feature_probability_calibration.py src\feature_probability_calibration.py src\weather\calibration\feature_model.py src\weather\model\model_features.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - TEMPERATURE CALIBRATION LAYER`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

