# 49. Late-Day Forecast-Gap Continuation Training [COMPLETE 2026-06-15 - FORECAST-GAP ARTIFACTS LIVE]

Goal: finish the narrow late-day work that was ambiguous between item 8 and the
completed forecast-error component in item 22.

Source: item 22 completed the forecast-error distribution and live late-day tail
blend, but `late_day_model_coefs*.json` still train without `forecast_high` and
`forecast_gap` feature columns.

- [x] Add `forecast_high` and `forecast_gap` to the late-day continuation
  training rows and exported coefficient artifact schema for 15:00, 16:00, and
  17:00.
- [x] Preserve train/serve parity by sourcing the same forecast-gap fields from
  the feature store in training, replay, live inference, and explanation output.
- [x] Add a late-day continuation validation report with Brier/log loss,
  calibration, and ablation rows for forecast-gap features.
- [x] Re-run settlement-scored replay to prove the trained continuation change
  improves or at least does not regress the final distribution.

Acceptance: late-day forecast-gap features are trained, served, explained, and
validated as their own continuation-model improvement, not only as a live
forecast-error tail heuristic.

Implementation update (2026-06-15 UTC): `src.weather.calibration.feature_model`
now centralizes late-day numeric features, adds `forecast_high` and
`forecast_gap` to the 15:00/16:00/17:00 continuation training rows, scales those
features with the other numeric late-day inputs, and writes
`numeric_feature_names` / `numeric_feature_count` into newly exported
`late_day_model_coefs*.json` artifacts. The feature-model report gains a
late-day continuation validation section with day-split log loss, Brier, ECE,
and feature-family ablation rows, including the forecast family. Serving reads
late-day artifacts by exported feature name, so old 9-numeric artifacts and new
forecast-gap-aware artifacts both remain compatible; explanation output already
returns `forecast_high`, `forecast_gap`, and `forecast_tail_probability`.
Focused tests cover the late-day feature list, validation/ablation helper, old
artifact compatibility, and a new artifact whose forecast-gap coefficient moves
the continuation probability.

Completion update (2026-06-15 UTC): the tracked
`artifacts/models/coefs/late_day_model_coefs*.json` files were regenerated for
all 12 registered markets with `schema_version=late_day_model_coefs_v0.1`,
`numeric_feature_names`, `forecast_high`, and `forecast_gap` in the 15:00,
16:00, and 17:00 classifiers. `src.feature_model --late-day-only` now provides
a fast artifact-refresh path that reuses the same late-day training helper as
the full feature trainer and writes per-market late-day validation reports under
`data/wunderground/<station>/analysis/`. Pinned promotion-corpus replay over
51 market-days / 6,989 snapshots / 76,879 band rows improved all-snapshot
replayed Brier from `0.0443` to `0.0435` and daily-first replayed Brier from
`0.0435` to `0.0428` versus the pre-refresh report, so the trained continuation
artifact does not regress the final served distribution. Validation:

- `.\venv\Scripts\python.exe -m src.feature_model --market <market> --late-day-only`
  for all 12 registered markets.
- `.\venv\Scripts\python.exe -m src.replay_backtest --corpus data\backtest\promotion_corpus.json --out data\backtest\item49_late_day_replay_report.md`.
- `.\venv\Scripts\python.exe -m pytest tests\model\test_feature_model_ablation.py tests\calibration\test_forecast_error_model.py tests\backtesting\test_replay.py -q`: 30 passed.
