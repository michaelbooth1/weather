# 9. Analog Search [COMPLETE]

- [x] Add a dashboard panel showing the closest historical analog days.
- [x] Match on:
  date window, high by current hour, 7 AM-noon rise, wind regime, cloud regime,
  and dew point.
- [x] Add forecast profile / forecast gap to analog distance now that forecast
  history features are available.
- [x] Show each analog's final WU high and path through the day.

Codex audit (2026-05-28): mostly passes. The dashboard shows closest analogs,
final WU highs, and temperature paths, using the historical target-date window,
high so far, rise from 7 AM, wind/cloud regime, and dew point. Issue found:
forecast profile is not included in the analog distance.

Codex update (2026-05-31): unchanged. Keep this item open until analog distance
uses the same forecast information as the feature model, or explicitly proves
that forecast distance does not improve analog usefulness.

Implementation status (2026-06-13): complete -- the open checkbox was delivered by
item 22's analog work (2026-05-31) and verified here. `find_analog_days`
(`src/model_features.py`) computes today's Open-Meteo `forecast_gap` (forecast
high minus high-so-far), loads the historical per-day forecast index, and
includes the standardized forecast-gap term in the analog distance
(`w_forecast_gap * d_forecast_gap`, model_features.py:897 and :907-918); the
returned analog payloads carry `forecast_high` / `forecast_gap`
(model_features.py:859-860, :948-949). The payload is regression-covered by
`tests/test_intraday_calibration.py` (asserts `forecast_gap` in the analog
result). Analog distance now uses the same Open-Meteo forecast information as
the feature model, satisfying the item's gate.
