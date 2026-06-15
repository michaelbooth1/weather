# 51. Model Architecture Health Refactor [PARTIAL 2026-06-15 - NATIVE CLEANUP COMPLETE]

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
- [x] Finish the native-unit naming cleanup by moving serving and source code to
  `*_native` accessors, preserving legacy `temp_c` / `*_c` aliases only at I/O
  compatibility boundaries.
- [x] Replace top-level compatibility imports and scattered `sys.path` mutation
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

Canonical-import update (2026-06-15 UTC): the replay/promotion orchestration
slice now uses package imports instead of mutating `sys.path` inside package
modules. `weather.reporting.promotion_refresh`,
`weather.backtesting.replay_backtest`,
`weather.calibration.pooled_candidate_replay`, and
`weather.reporting.shadow_ab_monitor` now import internal modules through
`weather.*` package paths, while the top-level `src/*.py` wrappers remain thin
user-facing compatibility shims. `tests/operations/test_import_architecture.py`
ratchets this migrated slice so these modules, plus the daily/nightly
operations helpers, cannot reintroduce package-internal `sys.path` mutation or
legacy top-level imports. The broader import cleanup remains open for older
collection, source, calibration, reporting, and model modules. Verification:
`pytest tests/operations/test_import_architecture.py
tests/reporting/test_shadow_ab_monitor.py tests/operations/test_daily_refresh.py
tests/operations/test_nightly_retrain.py tests/backtesting/test_replay.py
tests/reporting/test_promotion_corpus.py
tests/calibration/test_pooled_candidate_replay.py
tests/calibration/test_promotion_refresh.py -q` passed (`70` tests).

Core-model import update (2026-06-15 UTC): the central model package now uses
canonical package imports instead of top-level compatibility shims.
`weather.model.toronto_model`, `model_constants`, `model_climatology`,
`model_distribution`, `model_distribution_signals`, `model_features`,
`model_sources`, and `model_presentation` import internal code through
`weather.*` paths, while the public `src/toronto_model.py` wrapper continues
to support legacy callers. The architecture ratchet now includes these model
modules. This removes top-level shim dependence from the active distribution
path without changing model behavior; broader cleanup remains open for older
collection, source, calibration, market, and reporting modules. Verification:
`pytest tests/operations/test_import_architecture.py
tests/model/test_estimate_distribution.py tests/model/test_live_floor.py
tests/model/test_late_day_lockin.py tests/model/test_bucket_transitions.py
tests/model/test_model_explanation.py tests/model/test_feature_store.py
tests/model/test_feature_skew.py tests/backtesting/test_replay.py
tests/reporting/test_promotion_corpus.py -q` passed (`126` tests,
`144` subtests); the legacy `from toronto_model import TorontoHighTempModel`
shim still imports successfully.

Backtesting import update (2026-06-15 UTC): the replay/scoring package is now
off top-level compatibility imports. `weather.backtesting.backtest`,
`replay`, `replay_ablation`, `settled_days`, and `settlement_ledger` now use
canonical `weather.*` imports and no longer mutate `sys.path`; the existing
top-level `src/backtest.py`, `src/replay.py`, and related wrappers remain the
user-facing shims. This brings the replay/fidelity surface under the same
architecture ratchet as the model and orchestration slices. Verification:
`pytest tests/operations/test_import_architecture.py
tests/backtesting/test_backtest.py tests/backtesting/test_replay.py
tests/backtesting/test_replay_ablation.py tests/backtesting/test_settled_days.py
tests/backtesting/test_settlement_ledger.py
tests/backtesting/test_settlement_units.py tests/reporting/test_promotion_corpus.py
-q` passed (`77` tests).

Package-import completion update (2026-06-15 UTC): package-internal code under
`src/weather` no longer depends on root-level compatibility shims or mutates
`sys.path` to find sibling modules. The architecture ratchet now covers the
migrated backtesting, calibration, collection, market, model, operations,
reporting, and source modules, including the report-rendering helpers that
previously kept top-level fallback imports. The public root-level `src/*.py`
wrappers remain as compatibility shims for existing commands. Verification:
the package-wide scan for migrated legacy imports and `sys.path` mutation is
clean; `pytest -q` passed (`599` tests, `149` subtests); and
`python -m src.schema_registry audit --strict` reported
`registered=72 discovered=133 unregistered_versions=0`. A fresh Toronto
promotion-corpus replay was saved to
`data/backtest/item51_import_cleanup_replay_report.md`: it scored `7` days,
`859` snapshots, and `9449` band rows with all-snapshot replayed Brier `0.0369`
vs recorded `0.0414` and market `0.0334`. The same-identity canary still had
`0` snapshots because the available corpus was captured under older replay
identities, so the item remains open for native-unit naming cleanup and a
future exact-identity/fidelity proof.

Native-accessor update (2026-06-15 UTC): the serving/model layer now has an
explicit native-temperature accessor layer. `feature_store` exposes
`row_temp_native`, `row_dewpoint_native`, `row_air_temp_native`, and
`row_forecast_high_native`, and `ModelUtilsMixin` routes model code through the
same helpers. Live source fetchers now emit native-named fields such as
`temp_native`, `dewpoint_native`, `forecast_high_native`, `day_max_native`,
`max_since_7am_native`, and `same_day_max_native` while preserving the legacy
`*_c` aliases for replay inputs, snapshot compatibility, and trained feature
schemas. Core feature extraction, forecast aggregation, distribution logic, and
presentation paths now read native accessors instead of direct `temp_c` /
`forecast_high_c` fields. The trained feature names such as `dewpoint_c` remain
unchanged for artifact compatibility. Verification: `pytest -q` passed (`601`
tests, `149` subtests); `python -m src.schema_registry audit --strict`
reported `registered=72 discovered=133 unregistered_versions=0`; and
`python -m src.replay_backtest --market toronto --corpus
data/backtest/promotion_corpus.json --out
data/backtest/item51_native_accessor_replay_report.md --disable-long-job-guard`
scored `7` days, `859` snapshots, and `9449` band rows with all-snapshot
replayed Brier `0.0369` vs recorded `0.0414` and market `0.0334`.

Native snapshot/calibration update (2026-06-15 UTC): snapshot persistence,
historical climatology caches, pooled candidate replay support values, and the
settlement-lag trainer now read native fields first while keeping legacy
`*_c` output columns and trained feature names as compatibility boundaries.
`SnapshotStore.source_values()` still writes the established snapshot tape
columns such as `wu_current_c` and `eccc_forecast_high_c`, but those values now
come from `temp_native`, `max_since_7am_native`, `same_day_max_native`, and
`forecast_high_native` when available. The historical target cache now retains
`temp_native` / `dewpoint_native` alongside the legacy aliases, and
settlement-lag rows carry `temp_native` internally. Verification: `pytest -q`
passed (`602` tests, `149` subtests); `python -m src.schema_registry audit
--strict` reported `registered=72 discovered=133 unregistered_versions=0`; and
`python -m src.replay_backtest --market toronto --corpus
data/backtest/promotion_corpus.json --out
data/backtest/item51_native_snapshot_replay_report.md --disable-long-job-guard`
again scored `7` days, `859` snapshots, and `9449` band rows with all-snapshot
replayed Brier `0.0369` vs recorded `0.0414` and market `0.0334`.

Native runtime/calibration ratchet update (2026-06-15 UTC): model runtime
high/max readers now go through shared `row_max_native`,
`row_max_since_7am_native`, and `row_same_day_max_native` helpers. The
observation-trigger state summary, `estimate_distribution()` entry path,
lock-in/falsification helpers, bucket-transition model, source presentation,
and SWOB source normalizer now prefer `*_native` values when both native and
legacy aliases exist. A new architecture ratchet prevents direct legacy
temperature reads from returning to model runtime and observation-trigger
modules while still allowing explicit compatibility writes such as snapshot
tape columns and trained artifact field names. The next calibration slice also
moved intraday-weight records and late-day continuation artifact records to
native temperature/dewpoint accessors while preserving the existing trained
feature name `dewpoint_c`. Verification: `pytest -q` passed (`608` tests,
`149` subtests); `python -m src.schema_registry audit --strict` reported
`registered=72 discovered=133 unregistered_versions=0`; and `python -m
src.replay_backtest --market toronto --corpus data/backtest/promotion_corpus.json
--out data/backtest/item51_native_runtime_calibration_replay_report.md
--disable-long-job-guard` scored `7` days, `859` snapshots, and `9449` band rows
with all-snapshot replayed Brier `0.0369` vs recorded `0.0414` and market
`0.0334`. The exact replay-identity canary remains unavailable for this older
corpus, and broader historical/source/reporting compatibility readers still
need review, so the native-unit cleanup and replay-fidelity checkbox remain
open.

Native replay/source-adapter update (2026-06-15 UTC): reconstructed replay
records now translate legacy snapshot tape fields into native-first internal
source payloads, emitting `temp_native`, `max_native`,
`max_since_7am_native`, `same_day_max_native`, `forecast_high_native`, and
`day_max_native` alongside the existing legacy aliases. Snapshot tape writes
still keep the established `*_c` column names, but `SnapshotStore.source_values()`
now reads source maxima through the shared native accessors before writing
those compatibility columns. The historical forecast source layer now loads
`forecast_high_native` and `target_temp_native` first, falling back to legacy
`forecast_high_c` / `target_temp_c` only for older files; source-redundancy
forecast ensemble features use the same native-first interpretation. Focused
tests cover reconstructed replay aliases, snapshot source values, native
forecast loaders, and forecast redundancy rows with conflicting native/legacy
values. Verification: `pytest -q` passed (`610` tests, `149` subtests);
`python -m src.schema_registry audit --strict` reported `registered=72
discovered=133 unregistered_versions=0`; and `python -m src.replay_backtest
--market toronto --corpus data/backtest/promotion_corpus.json --out
data/backtest/item51_native_replay_source_adapter_report.md
--disable-long-job-guard` scored `7` days, `859` snapshots, and `9449` band rows
with all-snapshot replayed Brier `0.0369` vs recorded `0.0414` and market
`0.0334`. Broader legacy readers in historical source backfills and reporting
remain to classify before the native-unit cleanup checkbox can close.

Native forecast-archive adapter update (2026-06-15 UTC): live forecast archive
writes now read hourly forecast rows and ECCC daily highs through
`row_temp_native` / `row_forecast_high_native` before writing the existing
`target_temp_c` and `forecast_high_c` compatibility columns. Forecast-archive
scoring also resolves forecast temperatures through the same native-first
accessors, so rows carrying future `target_temp_native` or
`forecast_high_native` fields score in the market's native unit without adding
new persisted columns in this slice. Regression coverage builds weather,
Open-Meteo, NWS, global-ensemble, and ECCC rows with conflicting native and
legacy aliases and proves the archive records the native values. Verification:
focused collection/source/reporting/replay tests passed (`71` tests);
`pytest -q` passed (`613` tests, `149` subtests) after rerunning once the
runtime-identity guard's source tree was stable; `python -m src.schema_registry
audit --strict` reported `registered=72 discovered=133
unregistered_versions=0`; and `python -m src.replay_backtest --market toronto
--corpus data/backtest/promotion_corpus.json --out
data/backtest/item51_native_forecast_archive_adapter_report.md
--disable-long-job-guard` scored `7` days, `859` snapshots, and `9449` band rows
with all-snapshot replayed Brier `0.0369` vs recorded `0.0414` and market
`0.0334`.

Native reader-adapter update (2026-06-15 UTC): the remaining model-adjacent
readers now resolve temperatures through native accessors or native-first
adapter helpers. `data_auditor`, `feature_store` historical anchors,
settlement-lag training, forecast-error training, probability calibration,
source redundancy, forecast history, WU daily summarization, data-layer audit,
supplemental-station validation, forecast-archive scoring, and WU max-since-7
validation all prefer `*_native` values when native and legacy aliases conflict.
Legacy `*_c` fields remain only as persisted CSV/report compatibility fields or
as true-Celsius external source inputs (`tmpc`, GHCNh temperature, ECCC SWOB
normalization, daily-summary Celsius projections). Regression tests deliberately
feed conflicting native and legacy values through each adapter. Verification:
`python -m pytest` passed (`623` tests); `python -m src.schema_registry audit
--strict` reported `registered=72 discovered=134 unregistered_versions=0`;
`git diff --check` reported only CRLF normalization warnings; and `python -m
src.replay_backtest --market toronto --corpus data/backtest/promotion_corpus.json
--out data/backtest/item51_native_reader_adapters_replay_report.md
--disable-long-job-guard` scored `7` days, `859` snapshots, and `9449` band rows
with all-snapshot replayed Brier `0.0369` vs recorded `0.0414` and market
`0.0334`. The exact replay-identity canary remains unavailable for this older
corpus, so the replay-fidelity checkbox remains open.
