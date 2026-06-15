# 24. Unified Feature Store And Train/Serve Parity [COMPLETE]

Goal: prevent future train/serve skew and make every feature explainable.

- [x] Move shared feature schema into one module used by training,
  backtests, live inference, and explanations.
- [x] Version every live feature vector and future model artifact export with a
  shared feature schema.
- [x] Add a feature parity test: historical/live feature extraction for the
  same synthetic day must match.
- [x] Persist per-snapshot feature vectors next to probabilities for audits.
- [x] Add feature-schema and snapshot feature-persistence tests.
- [x] Move the full historical feature-construction logic into the shared
  feature-store module, not only the schema/record layer.
- [x] Add ablation reporting so each feature family's value is visible.
- [x] Add backtest joins from probability rows to feature vectors so item-20
  report deltas can be sliced by feature families.

Acceptance: feature changes can be reviewed from one code path and tied to
measured backtest deltas.

Audit note (2026-06-14): analog search still has a deliberately stricter
feature extraction path because it rejects missing data instead of filling
train/serve defaults. Item 51 owns the replay-safe consolidation of that path
onto shared primitives.

Codex implementation status (2026-05-31): complete. `src/feature_store.py` now
defines `toronto_feature_store_v0.1`, the canonical feature column order, audit
columns, and helpers to build serializable live feature records.
`src/model_features.py` adds the schema version to live extraction and exposes
`live_feature_record()`.
`src/feature_model.py` now imports the shared feature column order, uses
`feature_store.build_historical_feature_record()` for historical training
records, and stamps future LR/HGB/late-day artifacts with the schema version.
`src/toronto_model.py` returns a `feature_vector` from model builds, and
`src/snapshot_tracker.py` persists feature vectors to `features_long.csv` and
`features.jsonl` next to snapshot probabilities. `src.backtest` now joins
`features_long.csv` by `snapshot_id`, reports feature-vector coverage, and will
slice scores by the forecast-gap feature once feature-audited snapshots exist.
`data/wunderground/cyyz/analysis/feature_model_report.md` now includes
feature-family ablation tables over 5,823 HGB leave-one-out validation rows.
The ablation shows the observed temperature path dominates value
(overall delta log loss +2.3907 when neutralized), with smaller positive
contributions from wind regime, forecast, and atmosphere features; cloud regime
is currently neutral to slightly negative in this sensitivity pass.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_feature_store.py tests\test_forecast_feature.py tests\test_collection_robustness.py -q`: 20 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_feature_store.py tests\test_forecast_feature.py -q`: 8 passed, including live-vs-historical feature parity for a synthetic day.
- `.\venv\Scripts\python.exe -m pytest tests\test_backtest.py tests\test_feature_store.py -q`: 28 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_feature_model_ablation.py tests\test_feature_store.py -q`: 8 passed.
- `.\venv\Scripts\python.exe src\feature_model.py`: regenerated
  `artifacts/models/coefs/feature_model_coefs.json`, `artifacts/models/hgb/feature_model_hgb.pkl`,
  `artifacts/models/coefs/late_day_model_coefs.json`, and
  `data/wunderground/cyyz/analysis/feature_model_report.md` with ablation
  tables. This full LOO retrain is slow enough that item 26 should add a faster
  sampled/incremental research mode before routine model-comparison work.
- `.\venv\Scripts\python.exe -m src.backtest data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026 --quality-grades complete,manual_override`: regenerated
  `data/backtest/backtest_report.md` with feature-vector coverage. After
  coverage-aware labels, only May 28 is in the strict quality-filtered headline
  sample, so current historical tapes have 0/704 scored rows with feature
  vectors because feature persistence starts with new snapshots.
- `.\venv\Scripts\python.exe -m pytest -q`: 141 passed after item-26 ensemble tests were added.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.
