# Workstation report 2026-08-02 — build the all-market base-retrain step

## Verdict

The candidate-safe all-market base-retrain step is implemented on a topic
branch based exactly on `master` at `73d53cde722bcd60f2c9ef1c4a3b57db7ba1b0ed`.
No model fit, retrain, artifact write, candidate scoring, real-corpus read,
fresh-date read, pointer change, scheduler change, promotion, or production-host
access occurred.

The new nightly plan contains exactly one unskippable
`all_market_base_retrain` step. Its seven identity/input bindings have empty
nightly parser values so an unconfigured real invocation fails closed; the
standalone CLI makes all seven required. The plan receipt names all twelve
built-in markets in native units and all five per-market candidate outputs.

## Implementation boundary

The new lane does not call `weather.calibration.feature_model.main()` or its
CLI. It accepts only a hash-bound JSONL feature corpus through the frozen corpus
manifest and writes the supplied immutable candidate paths. The fitter selects
the parent HGB/LR feature order exactly, obtains HGB constructor parameters from
the verified parent estimator, uses the serving-compatible legacy LR constants,
fits blocked-OOF HGB/blend and exact-distribution calibration, and declares a
contiguous positive-mass serving support separately from estimator classes.

The operational owner verifies the active parent release and all 84 market
component roles, proves the candidate root is new and outside the repository,
and inventories global model/calibration paths, `data/`, the active pointer,
and every parent release file around both a dry output probe and every market
fit. It copies all intentionally unchanged parent roles by exact hash, replaces
only twelve HGBs, twelve compatible LRs, and twelve probability-calibration
artifacts, rebuilds and verifies the semantic graph, and permits an inactive
research-only release only after all twelve triples pass.

The serving path now recognizes the candidate's target-date-aligned prior and
contiguous support. Legacy artifacts without those fields preserve current
behavior. A candidate support hole, missing prior bucket, or zero-mass bucket
fails rather than falling back to `model.classes_`.

## Intended preflight failures

Deterministic synthetic fixtures demonstrate both failures without reading a
real corpus:

- `test_preflight_demonstrates_zero_forecast_coverage_and_wu_blind_value_mismatch`
  reports `FORECAST_ARCHIVE_INCOMPLETE` with `coverage=0/1` for every market's
  parent-selected `forecast_high` and keeps `fit_authorized=false`.
- The same receipt reports `TRAIN_SERVE_PARITY_MISMATCH` for
  `rise_from_7am`; it records both the historical/live value difference and
  the missingness difference. The gate compares value, unit, category,
  missingness, and cutoff behavior rather than accepting a boolean receipt.
- A separate fully repaired synthetic manifest is the only fixture that gets
  exact `PASS`. It is not evidence about today's real inputs.

## Output isolation and fleet atomicity

`test_output_isolation_probe_detects_legacy_global_write` mutates a synthetic
global HGB path during the dry probe and gets `status=BLOCK` with different
before/after inventories. `test_fit_scope_inventory_aborts_when_a_runner_touches_global_artifacts`
attempts the same legacy write from a market runner; the fleet aborts before a
release builder is called. `test_toronto_nyc_only_success_is_not_releasable`
allows only those two markets to report success and proves no release call is
reachable.

Verification after implementation:

```text
python -m pytest tests/operations/test_base_retrain.py -q
11 passed

python -m pytest tests/calibration \
  tests/operations/test_release_candidate_contract.py \
  tests/operations/test_release_lifecycle.py \
  tests/test_release_serving.py tests/model -q
786 passed, 713 subtests passed

python -m pytest -q
3301 passed, 4 skipped, 820 subtests passed

python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 588 Markdown files)
```

The Windows full-suite run used a process-scoped PowerShell execution-policy
bypass for scheduler-contract tests and an extended-length pytest temp path for
the executor sandbox tests. The unmodified host defaults otherwise block those
tests before they exercise repository behavior.

## Specification findings

Three details needed an explicit disposition after contact with the code:

1. Parent HGB objects serialize their estimator parameters; parent LR JSON does
   not. The new lane can prove the HGB freeze from parent bytes, but for LR it
   must freeze and receipt the serving-compatible legacy constructor contract
   (`C=0.5`, `max_iter=1000`, `random_state=42`). It cannot truthfully claim
   those values were read from the parent LR artifact.
2. A production parent's point-in-time candidate-scoring qualification is bound
   to the old base distributions and cannot be copied after changing 36 base
   roles. The first lane therefore requires a research-only parent and builds a
   research-only inactive child. A future production-capable child needs new
   candidate scoring, which this handoff explicitly excluded.
3. The existing probability-calibration artifact also contains market-bin
   calibration learned from scored snapshots. With candidate scoring excluded,
   this lane refits candidate-specific multiclass exact-distribution
   calibration from blocked OOF rows and explicitly disables the market-bin
   transform. It does not reuse the old HGB's calibrator.

## Roll-sensitive files and merge block

The following changed files match `SOURCE_PATTERNS` and consume a capture-loop
roll when merged:

- `src/weather/calibration/base_model_candidate.py`
- `src/weather/model/model_distribution.py`
- `src/weather/model/model_features.py`
- `src/weather/operations/base_retrain.py`
- `src/weather/operations/nightly_retrain.py`
- `src/weather/schema_registry_data.py`

No `scripts/**/*.ps1` or `tools/**` file changed. Tests and documentation are
outside `SOURCE_PATTERNS`.

This should block merge until the operator deliberately accepts the fail-closed
nightly behavior and coordinates the seven scheduled-invocation bindings. Even
then, the first real fit remains blocked until the separate forecast-archive
and train/serve feature-contract repairs produce exact-PASS manifest evidence.
