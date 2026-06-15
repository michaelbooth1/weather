# 60. Snapshot Range-Band Audit Schema And Serving Version Guard [COMPLETE 2026-06-15 - RANGE SCHEMA AND STALE-CODE GUARD LIVE]

Goal: make snapshot, component, and replay artifacts sufficient to audit native
range bands and catch stale serving processes immediately.

Miami audit source (2026-06-15): the same market window showed a clean current
code replay near 29% for 92-93 F, while a later persisted CSV row showed 0%.
Current `bin_probability` correctly sums range bands over `[value, value_hi]`,
but `snapshots_long.csv` and `components_long.csv` persist only `bin_value_c`.
That makes it hard to distinguish "92 only" from "92-93" in downstream audit
tools. The persisted rows were also labeled `v0.5.8` while current constants
were `v0.5.10`, and feature-schema rows alternated between v0.4 and v0.5.

- [x] Add `bin_value_hi_c` or a native-unit equivalent to snapshot long rows,
  component rows, CLOB feature rows where needed, and wide-row band keys.
- [x] Add a migration/backfill helper or compatibility reader so old rows
  without `bin_value_hi_c` can reconstruct the high endpoint from `range_label`
  and market metadata.
- [x] Add a snapshot self-check that recomputes each band probability from the
  persisted distribution and stored bin metadata, then fails or warns when the
  stored row differs materially.
- [x] Add a runtime version guard for snapshot and watcher processes: emitted
  `model_version`, feature schema, and code identity must match the current
  runtime identity or surface as a stale-process/preflight incident.
- [x] Extend replay and dashboard diagnostics to show exact range semantics,
  model version, feature schema version, and current code identity for the
  latest row.

Acceptance: a future audit can reconstruct 92-93 F exactly from persisted
artifacts without querying Polymarket again, and stale snapshot/watch processes
cannot silently emit mixed-version model rows.

Implementation update (2026-06-15): future `snapshots_long.csv` and
`components_long.csv` rows now persist `bin_value_hi_c` next to `bin_value_c`.
Wide snapshot keys include the full native range (`eq_90_91c` instead of
`eq_90c`), and CLOB feature joins consume the explicit upper endpoint when it is
present. Legacy replay/backtest readers remain compatible: old rows without
`bin_value_hi_c` still reconstruct the endpoint from `range_label`. Existing
CSV files are widened in place when a new schema column appears, so an already
started market-day tape does not silently drop the new audit fields.

Snapshot writes now run a probability self-check before appending artifacts:
each persisted band row is reconstructed from stored band metadata and compared
with `bin_probability(distribution, band)`. A mismatch raises instead of
silently writing an unauditable row. Snapshot JSONL and replay inputs also carry
runtime identity metadata, feature schema version, and the self-check result.

The weather snapshot loop now treats a process-start runtime identity that no
longer matches the current source tree as `STALE_CODE`; the loop records the
incident and skips capture, and the supervisor restarts it. The Streamlit latest
snapshot inspection displays native band endpoints, model version, feature
schema version, runtime source fingerprint, and runtime code state. Replay
reports include a band-semantics audit showing explicit endpoint rows versus
legacy label-fallback rows.

Verification:

- `pytest tests\model\test_feature_store.py tests\backtesting\test_settlement_units.py tests\backtesting\test_replay.py tests\collection\test_loop_supervisor.py tests\market\test_market_microstructure.py -q`
  passed: 66 tests.
- `pytest tests\backtesting\test_backtest.py tests\backtesting\test_replay.py tests\backtesting\test_settlement_units.py tests\operations\test_observation_trigger.py tests\collection\test_loop_supervisor.py tests\collection\test_collection_robustness.py tests\market\test_market_microstructure.py tests\calibration\test_pooled_candidate_replay.py tests\model\test_feature_store.py -q`
  passed: 138 tests.
- `python -m compileall` passed for the edited snapshot, replay, backtest,
  CLOB feature, and Streamlit modules.
