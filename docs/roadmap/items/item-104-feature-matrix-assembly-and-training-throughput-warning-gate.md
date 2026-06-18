# 104. Feature Matrix Assembly And Training Throughput Warning Gate [COMPLETE 2026-06-17 - THROUGHPUT GATE LIVE]

Goal: keep model retraining fast and predictable as the feature set grows.

Source: 2026-06-16 local Python audit. `python -m pytest -q` passed, but the
suite emitted 1078 warnings, dominated by pandas `PerformanceWarning:
DataFrame is highly fragmented` from `weather.calibration.pooled_feature_model`
and `weather.calibration.feature_model`. The warnings come from adding many
missing feature columns one at a time before training or validation.

Why this matters: the model feature surface now includes source health,
microstructure, gridded guidance, marine context, MRMS, and reanalysis fields.
Column-by-column insertion is not a math error, but it makes nightly retraining
slower and less reliable exactly when the project needs broader replay
coverage.

## Design

1. Replace repeated `frame[column] = None` / `df[column] = np.nan` loops in
   feature-frame builders with a single schema-aligned construction:
   build the requested column set once, reindex once, and copy once before
   dummy expansion.
2. Preserve artifact compatibility by keeping feature names and feature order
   byte-stable for existing trained bundles.
3. Add a focused test that runs feature-frame construction with pandas
   `PerformanceWarning` treated as an error.
4. Add a small benchmark row to the training reports: rows, columns, build
   seconds, model fit seconds, and warning count.
5. Keep the runtime serving path unchanged unless the benchmark shows the same
   fragmentation issue there.

- [x] Refactor `feature_frame`, `band_feature_frame`, and
  `feature_model_frame` to avoid repeated DataFrame column insertion.
- [x] Preserve existing feature column names and ordering for current artifacts.
- [x] Add warning-as-error coverage for the frame builders.
- [x] Add training-report timing and warning-count fields for feature matrix
  assembly.
- [x] Re-run the pooled F-family and Toronto feature-model tests with no pandas
  fragmentation warnings.

Acceptance: full pytest still passes, feature-frame tests fail on pandas
fragmentation warnings, and training reports expose matrix-build cost before a
candidate can be promoted.

## Completion Notes

Completed 2026-06-17. The pooled F-family, pooled density, pooled band, and
Toronto feature-model builders now schema-align frames in one pass and create
dummy blocks via bulk concatenation rather than repeated column insertion.
Training artifacts and reports now carry matrix rows, matrix columns, matrix
build seconds, model fit seconds, and pandas performance-warning counts.

Verification:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\calibration\test_pooled_feature_model.py tests\model\test_feature_model_ablation.py tests\model\test_feature_model_calibration.py
```

Result: 33 passed with no pandas fragmentation warnings.
