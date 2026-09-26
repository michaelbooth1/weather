# Canonical snapshot projection readers

- **Owns:** the four retired capture CSV views, their JSONL read adapters and consumer inventory.
- **Read when:** adding a snapshot consumer or changing capture's duplicate CSV output.
- **Read instead:** [cold snapshot compression](cold-snapshot-compression.md) for retained-path NTFS compression;
  [storage classes](data-storage-class-contract.md) for deletion authority.
- **Verify with:** `weather.projection_io`, `SnapshotStore.append_projection`, and `tests/test_projection_io.py`.

| Retired new-day capture CSV | Canonical source | Row interpretation |
| --- | --- | --- |
| `snapshots_long.csv` | `snapshots.jsonl` | Ordered `bands` rows from each capture record |
| `features_long.csv` | `features.jsonl` | One feature audit row per record |
| `variant_predictions_long.csv` | `variant_predictions.jsonl` | One variant row per record |
| `snapshot_explanations_long.csv` | `snapshot_explanations.jsonl` | Shared capture/reader explanation flattening |

New capture days write those canonical tapes without creating these four CSVs.
An existing CSV continues receiving rows for the remainder of its day. Readers
prefer that existing CSV, so historical settlement hashes and partially
migrated days do not acquire mixed provenance. This retires creation, not
historical retention. Explicit legacy backfill commands may still rebuild a
CSV; no retained projection is removed by this change. Other projection
families, including the separate CLOB feature table, keep their existing policy.

`projection_source` returns the physical source used for existence, stat and
hash checks; it does not pretend a JSONL file is a CSV. `projection_glob` unions
the two filenames and deduplicates event folders. `open_projection` supplies a
streaming CSV text view for existing CSV parsers; `read_projection_frame` uses
that view with Pandas' existing type inference. Binary reads bind the actual
source bytes. Neither adapter writes files. Common `weather.io` row readers
use the same contract. Whole-record tails stay inside the caller's byte budget,
discard an initial partial record, reject an incomplete final record and
retain the existing stability and batch-boundary diagnostics.

The release clock, settlement ledger, preselection source checks and residual
corpus manifest proofs bind the actual canonical filename/hash on new days.
Old CSV bindings remain exact. Preselection decodes its already bounded,
hash-bound bytes without reopening a changing source. Invalid objects,
duplicate JSON keys and incomplete records fail visibly. The closed-market-day
archive reader exposes `canonical_jsonl` provenance when no CSV representation
exists, including the source file hash. A JSONL-only day remains discoverable
to settled-day labels and qualification gates.

## Consumer inventory

The list below covers direct source constructors, discovery, generic CSV reads,
and physical-input hash bindings. Each uses `projection_io`, the common
`weather.io` readers, `discover_settled_folders`, or `read_market_day_artifact`.
App views consume those owners and have no direct references to these names.
The PowerShell CLOB enrichment reference concerns `clob_features_long.csv`,
which is a separate retained family.

- `src/weather/backtesting/backtest.py`
- `src/weather/backtesting/replay_ablation.py`
- `src/weather/backtesting/replay_backtest.py`
- `src/weather/backtesting/settled_days.py`
- `src/weather/backtesting/settlement_io.py`
- `src/weather/backtesting/settlement_ledger.py`
- `src/weather/backtesting/snapshot_analytics.py`
- `src/weather/backtesting/tape_scoring.py`
- `src/weather/calibration/afternoon_residual_centering.py`
- `src/weather/calibration/forecast_error_model.py`
- `src/weather/calibration/model_ensemble.py`
- `src/weather/calibration/pooled_candidate_replay.py`
- `src/weather/calibration/pooled_candidate_replay_report.py`
- `src/weather/calibration/probability_calibration.py`
- `src/weather/calibration/residual_distribution_corpus.py`
- `src/weather/calibration/settlement_lag_model.py`
- `src/weather/collection/collection_health.py`
- `src/weather/collection/forecast_archive.py`
- `src/weather/collection/forecast_tracker.py`
- `src/weather/market/market_day_labels.py`
- `src/weather/market/market_latest_inputs.py`
- `src/weather/market/market_making_preflight.py`
- `src/weather/market/market_making_run_support.py`
- `src/weather/market/market_microstructure.py`
- `src/weather/market/market_microstructure_capture.py`
- `src/weather/market/market_microstructure_features.py`
- `src/weather/market/mm_policy.py`
- `src/weather/operations/daily_refresh_reporting_steps.py`
- `src/weather/operations/market_making_tape_encoding.py`
- `src/weather/operations/observation_trigger.py`
- `src/weather/operations/release_admissibility_clock.py`
- `src/weather/operations/replay_cache_retention.py`
- `src/weather/operations/settled_day_freshness.py`
- `src/weather/reporting/candidate_lifecycle/model_market_disagreement_audit.py`
- `src/weather/reporting/candidate_lifecycle/price_free_model_learning.py`
- `src/weather/reporting/casebooks/disagreement_casebook.py`
- `src/weather/reporting/casebooks/severe_tail_ex_ante.py`
- `src/weather/reporting/data_quality/clob_coverage_audit.py`
- `src/weather/reporting/data_quality/data_layer_audit.py`
- `src/weather/reporting/data_quality/data_layer_audit_collectors.py`
- `src/weather/reporting/data_quality/feature_quality_quarantine.py`
- `src/weather/reporting/fleet/fleet_observability_gates.py`
- `src/weather/reporting/hourly/hourly_model_scoring.py`
- `src/weather/reporting/hourly/ten_minute_model_performance.py`
- `src/weather/reporting/location_analysis/location_trust.py`
- `src/weather/reporting/promotion/promotion_corpus.py`
- `src/weather/reporting/research/quotable_edge.py`
- `src/weather/reporting/research/skill_gap_decomposition.py`
- `src/weather/reporting/scorecards/live_variant_settlement_scorecard.py`
- `src/weather/reporting/scorecards/model_history.py`
- `src/weather/reporting/scorecards/settled_day_root_cause.py`
- `src/weather/reporting/scorecards/snapshot_evaluation.py`
- `src/weather/reporting/scorecards/winner_rank_parity.py`
- `src/weather/reporting/serving_gates/runtime_identity_evidence.py`
- `src/weather/reporting/source_gates/nbm_probabilistic_tmax_settlement_scoring.py`
- `src/weather/reporting/source_gates/source_family_inventory.py`
- `src/weather/reporting/validation/point_in_time_evaluation.py`
- `src/weather/reporting/validation/wu_max_since_7_validation.py`
- `src/weather/sources/eccc_swob_history.py`
- `tools/research/input_variable_significance.py`
- `tools/research/measure_high_so_far_population_09_70a.py`
- `tools/research/measure_replay_trust_09_75a.py`
- `tools/research/missing_information/extract.py`
- `tools/research/missing_information/supplement.py`
- `tools/research/morning_guidance/run.py`
- `tools/research/nbm_target_trace/run.py`

Non-reader references remain in `storage_classes`, `event_day_manifest`, and
`closed_day_projection_registry` as retention/schema/rebuild contracts; they
must continue recognizing historical CSVs. `snapshot_store_backfill` explicitly
mutates legacy CSV cadence columns, so a missing CSV remains a visible no-op;
it must not replace canonical JSONL with CSV text. `SnapshotStore` uses the
adapter for cadence reads and canonical sidecar IDs before explicit backfills.
`pooled_candidate_replay_report` is report text. `market_day_labels`,
`point_in_time_evaluation` and fleet/report facades delegate to the shared
discovery/artifact readers. Maker preflight/run support and tape-encoding
references concern the separate CLOB feature CSV.

## Verification and rollout

Run the focused projection, capture, settlement/admissibility, archive,
preselection and consumer tests with all four repository audits. The source
identity guard intentionally rejects edits during an active capture test run;
freeze source while testing. The native 81 MiB compression fixture checks
retained path, SHA-256, file identity and timestamp for the larger token limit.

Treat source changes as roll-sensitive until the production closure verdict
is obtained. Apply the reader migration together with the small capture writer
switch; adopting only the writer change would hide days from older readers.
The compression wrapper is roll-free, but its Python dependency must be present
at the reviewed source tip before invocation. No scheduler registration,
production inventory, production compression or evidence removal is performed
by implementation tests.
