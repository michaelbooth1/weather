# 96. Pure Distribution Result And Calibration Runtime Boundary [COMPLETE 2026-06-16 - DISTRIBUTION RESULT OWNS METADATA]

Goal: finish the model-build refactor by removing distribution metadata side
effects and separating runtime artifact application from calibration training.

Source: 2026-06-16 architecture review. `ModelBuildResult` and
`DistributionResult` exist, but `DistributionResult.from_model()` still reads
`_last_*` attributes after `estimate_distribution()` mutates model instance
state. Model runtime code also imports calibration modules for artifact loading
and probability adjustments.

Why this is missing: the explicit contract work preserved the legacy model
facade while moving callers toward returned result objects. The next step is to
make the probability engine build the result directly instead of serializing
mutable model state after the fact.

- [x] Change `estimate_distribution_result()` so it constructs and returns
  `DistributionResult` directly from local pipeline variables.
- [x] Restrict `_last_*` attributes to compatibility-only fields populated from
  the returned `DistributionResult`, not used as the source of truth.
- [x] Move runtime artifact readers and appliers out of calibration training
  modules into a runtime-oriented package, for example
  `weather.model.calibration_runtime` or `weather.model.artifact_runtime`.
- [x] Keep training modules as artifact producers, reports, and CLIs; keep
  model runtime modules as artifact consumers.
- [x] Add tests proving repeated and interleaved distribution calls on one model
  instance do not leak component payloads, calibration context, family-secondary
  gates, or active model kind.
- [x] Add an import-boundary guard for high-risk cycles between `weather.model`
  runtime modules and calibration CLI/training modules.

Acceptance: distribution metadata is returned as explicit data, compatibility
side effects cannot become stale source-of-truth state, and model runtime no
longer depends on broad calibration training modules.

## Design

Make the direction of ownership explicit.

- Calibration modules produce artifacts.
- Runtime calibration modules load and apply artifacts.
- Model distribution code composes sources, runtime artifacts, and probability
  stages into a `DistributionResult`.
- Presentation and snapshot persistence consume the returned result, not model
  instance scratch fields.

Verification strategy:

- Focused model contract and repeated-build tests.
- Replay and snapshot-store tests that consume distribution metadata.
- Import architecture guard for model/calibration boundary rules.
- Full suite after runtime artifact ownership moves.

## Completion

Completed 2026-06-16.

- Added `weather.model.calibration_runtime` as the serving-time boundary for
  calibration artifact loading and application: probability calibration,
  continuous-density calibration, forecast-error distributions, settlement-lag
  probabilities, feature-model temperature scaling, and family-secondary
  manifest loading.
- Moved model runtime imports from `weather.calibration.*` training modules to
  `weather.model.calibration_runtime`; calibration modules remain artifact
  producers, reports, and CLIs.
- Changed `estimate_distribution_result()` to execute the distribution pipeline
  and return a `DistributionResult` built from local pipeline variables.
  `estimate_distribution()` now delegates to that result and returns only the
  distribution.
- Reworked `_last_distribution_components`,
  `_last_probability_calibration_context`, `_last_family_secondary_gate`, and
  `_last_distribution_result` so they are compatibility fields populated from
  the returned result. Compatibility payloads are deep-copied to avoid aliasing
  the result object.
- Threaded the family-secondary gate into pipeline metadata explicitly instead
  of reading it back from legacy `_last_*` state.
- Added a model/calibration import-boundary guard to
  `tests/operations/test_import_architecture.py`.
- Added a model contract regression proving stale `_last_*` fields are ignored,
  current result metadata is rebuilt, and legacy compatibility fields do not
  alias the returned `DistributionResult`.

Verification:

- `.\venv\Scripts\python.exe -m pytest tests\model\test_estimate_distribution.py tests\model\test_validation.py tests\model\test_market_units.py tests\calibration\test_probability_calibration.py tests\calibration\test_forecast_error_model.py tests\calibration\test_settlement_lag_model.py tests\calibration\test_feature_probability_calibration.py tests\operations\test_import_architecture.py -q`
  (96 passed)
- `.\venv\Scripts\python.exe -m pytest tests\calibration\test_intraday_calibration.py tests\model\test_bucket_transitions.py tests\model\test_late_day_lockin.py tests\model\test_feature_model_calibration.py tests\model\test_feature_model_ablation.py -q`
  (49 passed)
- `.\venv\Scripts\python.exe -m pytest -q` (816 passed, 491 subtests passed)

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - DISTRIBUTION RESULT OWNS METADATA`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

