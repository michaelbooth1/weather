# 106. Time-Blocked Active-Day Validation And Leakage Audit [COMPLETE 2026-06-17 - BLOCKED VALIDATION GATE LIVE]

Goal: make feature-value claims robust to nearby-day, season, market, and
active-day leakage.

Source: 2026-06-16 local Python audit. The older feature-family validation uses
date-ordinal modulo folds, while pooled models mainly expose a holdout-year
path. Those checks are useful, but they are not the same as validating against
future active days, heat-wave blocks, or market-specific regimes.

Why this matters: weather-market rows are correlated within seasons and market
days. A feature can look useful when adjacent calendar days are split across
folds, then fail on a contiguous active-day block or a new market regime.

## Design

1. Add explicit validation split modes to feature-model and pooled-model
   reports: leave-one-market-day, holdout-month/heat-wave block, holdout-year,
   rolling forward block, and current active-day replay.
2. Record the split mode, held-out dates, held-out markets, and row counts in
   every training artifact and report.
3. Compare each candidate's lift under the current split and the stricter
   blocked splits, with a named leakage-risk verdict.
4. Require promotion candidates to pass daily-first blocked validation, not only
   aggregate row-level validation.
5. Add regression tests that ensure same target-date rows never appear in both
   train and validation partitions for any split mode.

- [x] Add reusable validation split utilities for market-day and blocked-date
  partitions.
- [x] Wire blocked validation into feature-family, pooled density, and pooled
  band reports.
- [x] Add leakage diagnostics to promotion and shadow-monitor reports.
- [x] Gate promotion on daily-first blocked validation.
- [x] Add tests for no same-day leakage across all validation split modes.

Acceptance: every promoted model artifact can state which blocked validation
split it passed, and feature-value reports flag cases where modulo/date-row
validation overstates lift versus blocked active-day validation.

## Completion Notes

Completed 2026-06-17. Added reusable blocked split utilities for
leave-one-market-day, holdout-month, holdout-year, rolling-forward block, and
current-active-day partitions. Pooled candidate replay now emits a
`blocked_candidate_validation_gate_v0.1` payload, blocks cutover when
daily-first blocked validation fails, and records per-market blocked-validation
status. Promotion refresh carries that gate into readiness blockers and refuses
otherwise passing market rows when the gate fails. Daily learning treats failed
blocked validation as a P0 blocker.

Pooled bucket, density, and band artifacts/reports now include compact
`blocked_validation_v0.1` audit summaries. Item-27 feature-value reports also
flag their deterministic modulo folds as non-promotion-grade unless the blocked
audit is clean and reviewed.

Verification:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\calibration\test_blocked_validation.py tests\calibration\test_pooled_candidate_replay.py tests\calibration\test_promotion_refresh.py tests\model\test_feature_model_ablation.py tests\reporting\test_daily_learning.py tests\operations\test_schema_registry.py
.\venv\Scripts\python.exe -m pytest -q tests\calibration\test_pooled_feature_model.py tests\model\test_feature_model_calibration.py
```

Result: 62 passed, then 25 passed.
