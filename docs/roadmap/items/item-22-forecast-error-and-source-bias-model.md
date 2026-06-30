# 22. Forecast-Error And Source-Bias Model [COMPLETE]

Goal: replace heuristic forecast caps/floors with learned error distributions.

- [x] Score disabled paid-provider, Open-Meteo, and ECCC forecast archives by horizon,
  source, time of day, wind/cloud regime, and target-season window.
- [x] Learn source-specific bias, MAE/RMSE, and tail miss rates against WU final
  highs.
- [x] Convert forecast highs into probability components instead of point caps.
- [x] Model source disagreement explicitly; agreement should tighten the
  distribution and disagreement should widen it.
- [x] Add forecast-error features to analog search and late-day continuation.

Acceptance: a forecast component improves settlement-scored performance beyond
the current forecast-cap/floor heuristics in item 20.

Codex implementation status (2026-05-31): complete for the first item-22
artifact-backed forecast component. `src/forecast_error_model.py` now trains
`artifacts/calibration/forecast_error_model.json` and
`data/backtest/forecast_error_report.md` from the historical Open-Meteo daily
forecast archive plus settled snapshot forecast tapes. It learns source-level
observed-minus-forecast bias, MAE/RMSE, within-1 C rate, and >=2 C tail miss
rates for Open-Meteo, disabled paid-provider, and ECCC city-page forecasts. Live inference
loads the artifact in `src/toronto_model.py`, and `src/model_distribution.py`
uses the learned forecast-error distribution in the existing `forecast_cap`
component slot so calibrated empirical weights remain compatible while the
component itself is no longer a one-bucket point cap. Multi-source disagreement
widens the component distribution. Analog search now includes Open-Meteo
forecast gap in its distance and returned feature payloads, and late-day
continuation blends in the forecast-error component's above-current-bucket tail
probability when the artifact is available.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_forecast_error_model.py tests\test_estimate_distribution.py tests\test_intraday_calibration.py -q`: 35 passed.
- `.\venv\Scripts\python.exe -m src.forecast_error_model train data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: wrote
  `artifacts/calibration/forecast_error_model.json` and
  `data/backtest/forecast_error_report.md`.
- Forecast-component artifact replay improved exact-bucket Brier from 0.7433
  for the prior cap proxy to 0.6387, and log loss from 1.7935 to 1.2643 over
  552 forecast rows.
- Leave-one-year validation on the historical daily Open-Meteo archive improved
  Brier from 0.7185 to 0.6417 and log loss from 1.6525 to 1.1919 over 296
  rows.
- `.\venv\Scripts\python.exe -m pytest -q`: 118 passed.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.

Implementation caveat: the artifact proves the forecast component is better
than the old point-cap proxy, but it does not yet prove the whole calibrated
model beats Polymarket. That still depends on more settled market-day tapes and
item-20 end-to-end scoring.

Follow-up now unlocked: item 23 should learn WU settlement lag and revision
behavior so non-resolution observations can move probabilities through a
measured catch-up curve rather than ad-hoc soft floors.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

