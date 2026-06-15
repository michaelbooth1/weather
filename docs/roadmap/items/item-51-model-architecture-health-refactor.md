# 51. Model Architecture Health Refactor [PARTIAL 2026-06-15 - ANALOG FEATURE VIEW]

Goal: turn the 2026-06-14 model-logic audit into replay-gated structural
cleanup, without hiding behavioral changes inside refactors.

- [x] Consolidate analog/today feature extraction with feature-store and live
  extraction by returning a strict/no-default view from the same primitive,
  rather than maintaining a second hand-rolled analog path.
- [x] Back `estimate_distribution()` component snapshots and metadata with a
  shared distribution-state object.
- [x] Break the remaining `estimate_distribution()` transforms into explicit
  named pipeline stages so each live-signal transform is individually testable
  and explainable.
- [ ] Finish the native-unit naming cleanup by moving serving and source code to
  `*_native` accessors, preserving legacy `temp_c` / `*_c` aliases only at I/O
  compatibility boundaries.
- [ ] Replace top-level compatibility imports and scattered `sys.path` mutation
  with package imports and canonical CLI entry points, keeping old wrappers only
  as thin user-facing shims during migration.
- [ ] Keep every step gated by replay identity/fidelity checks and full pytest,
  with any intentional probability deltas baselined before promotion.

Acceptance: no hidden behavior change ships under the health-refactor label;
exact replay deltas are zero or intentionally baselined, the full suite passes,
and item 24 no longer overclaims analog-search consolidation.

Distribution-pipeline update (2026-06-15 UTC): `model_distribution` now uses
`DistributionPipelineState` to own named probability snapshots and final
metadata for each `estimate_distribution()` run. The public
`_last_distribution_components` payload shape is preserved, but snapshots such
as `post_live_signals`, live-observed floors, late-day continuation/lock-in,
`pre_calibration_model`, and `final_model` are now recorded through the shared
state object. The live-signal selection branch is also extracted into the named
`distribution_live_signals()` stage with tests covering the feature-model,
calibrated-empirical, and fallback empirical paths. Focused regression tests
assert the state object behavior and that `components.final_model` exactly
equals the returned distribution.
Verification: `pytest tests\model\test_estimate_distribution.py
tests\model\test_live_floor.py tests\model\test_late_day_lockin.py
tests\model\test_bucket_transitions.py tests\model\test_model_explanation.py -q`
passed (`69` tests). The remaining replay-identity proof remains open before
this item can close.

Distribution-stage update (2026-06-15 UTC): `estimate_distribution()` now calls
explicit stage methods for the feature/empirical model path, bucket-transition
blend, live-signal application, hard floors, intraday tail target, plausible
cap, forecast floor/pull, validated current-max floor, observed-floor ladder,
late-day continuation, and late-day lock-in. New focused tests exercise the
feature-model path stage, live-signal application stage, calibrated-empirical
forecast no-op path, and observed-floor stage snapshots directly. Verification:
`pytest tests\model\test_estimate_distribution.py
tests\model\test_live_floor.py tests\model\test_late_day_lockin.py
tests\model\test_bucket_transitions.py tests\model\test_model_explanation.py -q`
passed (`73` tests).

Analog-feature update (2026-06-15 UTC): analog search now consumes the shared
feature extraction primitives instead of maintaining its own today/historical
feature path. `extract_live_features(..., strict=True)` and
`build_historical_feature_record(..., strict=True)` reject missing
cutoff-aligned analog inputs instead of filling seasonal defaults, and
`find_analog_days()` projects those shared records through `analog_feature_view()`.
Focused tests prove analog calls the shared live extractor in strict mode,
preserves cutoff-row behavior, and returns no analogs when required cutoff data
would otherwise need defaults. Verification:
`pytest tests\calibration\test_intraday_calibration.py
tests\model\test_feature_store.py tests\model\test_feature_skew.py
tests\model\test_toronto_model_bugs.py -q` passed (`57` tests,
`144` subtests).
