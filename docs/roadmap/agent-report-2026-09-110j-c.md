# Agent report 2026-09-110j-c — compress on close and canonical projection readers

**Verdict: implemented and fixture-qualified; production execution and closure verdict remain host-side.**
Branch `codex/compress-on-close-20260926`, independently based on `origin/master`
`965374a0edc6fcb65d66e257be9e404cc9af8d60`. Assigned handoff read from
`origin/codex/owner-decisions-0926-day` at `ed075014161e6e0b0f8d3e9d0fc8dd265356d2c2`
(descendant of required `8cf764d26`). No production data, credentials, venue,
Drive, task registration, live-order or merge actions were performed.

## Delivered behavior

- A bounded close-time maintenance mode targets `clob_tokens.jsonl` first, then
  `clob_tokens.csv`, after market-local close, two-hour quiescence and CLOB
  writer release. It uses the existing native retained-byte verifier, an
  explicit 256 MiB file allowance, a one-GiB/32-file invocation limit and a
  50 GiB free-space floor. The wrapper retains host/source/lease bindings,
  protected windows, 600-second deadline, health checks and complete Job
  teardown. It issues no delete authority and registers no scheduled task.
- Native synthetic verification covers an **81 MiB token JSONL** and token CSV:
  unchanged path, SHA-256, file ID and mtime, positive verified allocation
  savings and before/after journals. NTFS keeps all token readers byte- and
  path-compatible. The configurable handle limit matches mission 91a's change;
  the original 64 MiB default and old exact-request lane remain intact.
- The four named capture duplicates use canonical JSONL on new days.
  Existing CSV days continue appending so legacy source hashes remain valid.
  Capture's writer switch uses one small `append_projection` method; historical
  tapes are retained. Explicit old-CSV backfills remain separate operations.
- Discovery, labels, settlement bindings, the release clock, manifest-backed
  residual corpus, bounded preselection, CSV/Pandas reads, health checks,
  scorecards, research tools and capture cadence reads use a shared streaming
  adapter. Physical paths/hashes remain honest; no reader materializes a CSV
  file. Bounded tails retain their byte and complete-record limits. The full
  consumer census and representation contract are in
  [snapshot-projection-readers.md](../operations/snapshot-projection-readers.md).

## Verification

The frozen-source consumer selection completed **766 passed, 2 skipped,
35 subtests passed**; its two failures were the new guide's missing index link
and untracked status. Both documentation issues are corrected in this branch.
The final committed-source focused run passed **77 tests and 2 subtests**,
including all four mandatory audits and the projection, native compression,
capture and admissibility regressions. All runs used
`workstation_heavy.ps1 -Kind pytest`, the repository interpreter and explicit
`--basetemp C:/Users/Michael/AppData/Local/Temp/weather-110j-c`.

The broader selection covered the matching test files for every changed owner
with a same-name test, plus common IO, capture robustness, captured-input hash,
forecast persistence and point-in-time preselection tests. An earlier active
run correctly rejected source edits through the runtime-identity guard; the
subsequent qualification run held source fixed. PowerShell parsing of the
extended wrapper reported no errors. No production compression savings are
claimed. This task's exact temporary fixture directory was removed after the
final run; the worktree and reports are retained.

## Production commands

Before integration on production, obtain the repository-owned verdict:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch codex/compress-on-close-20260926 -Base origin/master
```

The tool returned **UNDECIDABLE: no live closure evidence**, naming the missing
loop, CLOB, observation-trigger and enrichment status files. Conservatively treat Python
source as roll-sensitive until production determines its imported closure.
Adopt the readers and capture switch together in the verdict-required lane.
Do not land the writer subset alone. The native handle-limit change overlaps
91a identically; preserve both the nightly lane and `-CompressOnClose` when
integrating wrapper changes. Regenerate the correspondence index after merging.

From the reviewed source checkout, with the current owner/host-bound policy
described in [the owning runbook](../operations/cold-snapshot-compression.md):

```powershell
$repo = (Resolve-Path .).Path
$tip = (git rev-parse HEAD).Trim()
$request = Join-Path $repo 'scratch/compress-on-close-approved.json'
$hash = (Get-FileHash -LiteralPath $request -Algorithm SHA256).Hash.ToLowerInvariant()
.\scripts\ops\cold_snapshot_compression_run.ps1 -CompressOnClose -ProductionRepoRoot $repo -RequestPath $request -RequestSha256 $hash -ExpectedSourceTip $tip -OutputRoot (Join-Path $repo 'scratch/cold_snapshot_compression/close-plan-01')
.\scripts\ops\cold_snapshot_compression_run.ps1 -CompressOnClose -Apply -ProductionRepoRoot $repo -RequestPath $request -RequestSha256 $hash -ExpectedSourceTip $tip -OutputRoot (Join-Path $repo 'scratch/cold_snapshot_compression/close-apply-01')
```

These commands are for production after integration; neither was executed here.
Each attempt directory is create-only. A failed or interrupted attempt requires
inspection, not reuse. The command is admitted overnight maintenance, not work
performed inside a live capture write. The runbook names its fixed selection,
policy fields and refusal conditions.

## Per-file roll classification

`roll-sensitive` below is conservative treatment for Python source without
production closure evidence; it does not claim every listed reader is imported
by capture. Tests, documentation and PowerShell are roll-free by contract.

| File | Treatment |
| --- | --- |
| `docs/operations/cold-snapshot-compression.md` | roll-free |
| `docs/operations/package-boundaries.md` | roll-free |
| `docs/operations/README.md` | roll-free |
| `docs/operations/snapshot-projection-readers.md` | roll-free |
| `docs/roadmap/agent-report-2026-09-110j-c.md` | roll-free |
| `docs/roadmap/correspondence-index.md` | roll-free |
| `scripts/ops/cold_snapshot_compression_run.ps1` | roll-free |
| `src/weather/backtesting/backtest.py` | roll-sensitive |
| `src/weather/backtesting/replay_ablation.py` | roll-sensitive |
| `src/weather/backtesting/replay_backtest.py` | roll-sensitive |
| `src/weather/backtesting/settled_days.py` | roll-sensitive |
| `src/weather/backtesting/settlement_io.py` | roll-sensitive |
| `src/weather/backtesting/settlement_ledger.py` | roll-sensitive |
| `src/weather/backtesting/snapshot_analytics.py` | roll-sensitive |
| `src/weather/backtesting/tape_scoring.py` | roll-sensitive |
| `src/weather/calibration/afternoon_residual_centering.py` | roll-sensitive |
| `src/weather/calibration/forecast_error_model.py` | roll-sensitive |
| `src/weather/calibration/model_ensemble.py` | roll-sensitive |
| `src/weather/calibration/pooled_candidate_replay.py` | roll-sensitive |
| `src/weather/calibration/probability_calibration.py` | roll-sensitive |
| `src/weather/calibration/residual_distribution_corpus.py` | roll-sensitive |
| `src/weather/calibration/settlement_lag_model.py` | roll-sensitive |
| `src/weather/collection/collection_health.py` | roll-sensitive |
| `src/weather/collection/forecast_archive.py` | roll-sensitive |
| `src/weather/collection/forecast_tracker.py` | roll-sensitive |
| `src/weather/collection/snapshot_store.py` | roll-sensitive |
| `src/weather/io.py` | roll-sensitive |
| `src/weather/market/market_latest_inputs.py` | roll-sensitive |
| `src/weather/market/market_microstructure_capture.py` | roll-sensitive |
| `src/weather/market/market_microstructure_features.py` | roll-sensitive |
| `src/weather/market/mm_policy.py` | roll-sensitive |
| `src/weather/operations/closed_market_day_archive.py` | roll-sensitive |
| `src/weather/operations/compress_on_close.py` | roll-sensitive |
| `src/weather/operations/daily_refresh_reporting_steps.py` | roll-sensitive |
| `src/weather/operations/ntfs_file_compression.py` | roll-sensitive |
| `src/weather/operations/observation_trigger.py` | roll-sensitive |
| `src/weather/operations/release_admissibility_clock.py` | roll-sensitive |
| `src/weather/operations/replay_cache_retention.py` | roll-sensitive |
| `src/weather/operations/settled_day_freshness.py` | roll-sensitive |
| `src/weather/projection_io.py` | roll-sensitive |
| `src/weather/reporting/candidate_lifecycle/model_market_disagreement_audit.py` | roll-sensitive |
| `src/weather/reporting/candidate_lifecycle/price_free_model_learning.py` | roll-sensitive |
| `src/weather/reporting/casebooks/disagreement_casebook.py` | roll-sensitive |
| `src/weather/reporting/casebooks/severe_tail_ex_ante.py` | roll-sensitive |
| `src/weather/reporting/data_quality/clob_coverage_audit.py` | roll-sensitive |
| `src/weather/reporting/data_quality/data_layer_audit_collectors.py` | roll-sensitive |
| `src/weather/reporting/data_quality/data_layer_audit.py` | roll-sensitive |
| `src/weather/reporting/data_quality/feature_quality_quarantine.py` | roll-sensitive |
| `src/weather/reporting/hourly/hourly_model_scoring.py` | roll-sensitive |
| `src/weather/reporting/hourly/ten_minute_model_performance.py` | roll-sensitive |
| `src/weather/reporting/location_analysis/location_trust.py` | roll-sensitive |
| `src/weather/reporting/promotion/promotion_corpus.py` | roll-sensitive |
| `src/weather/reporting/research/quotable_edge.py` | roll-sensitive |
| `src/weather/reporting/research/skill_gap_decomposition.py` | roll-sensitive |
| `src/weather/reporting/scorecards/live_variant_settlement_scorecard.py` | roll-sensitive |
| `src/weather/reporting/scorecards/model_history.py` | roll-sensitive |
| `src/weather/reporting/scorecards/settled_day_root_cause.py` | roll-sensitive |
| `src/weather/reporting/scorecards/snapshot_evaluation.py` | roll-sensitive |
| `src/weather/reporting/scorecards/winner_rank_parity.py` | roll-sensitive |
| `src/weather/reporting/serving_gates/runtime_identity_evidence.py` | roll-sensitive |
| `src/weather/reporting/source_gates/nbm_probabilistic_tmax_settlement_scoring.py` | roll-sensitive |
| `src/weather/reporting/source_gates/source_family_inventory.py` | roll-sensitive |
| `src/weather/reporting/validation/wu_max_since_7_validation.py` | roll-sensitive |
| `src/weather/schema_registry_recent_data.py` | roll-sensitive |
| `src/weather/sources/eccc_swob_history.py` | roll-sensitive |
| `tests/collection/test_live_variant_predictions.py` | roll-free |
| `tests/operations/test_compress_on_close.py` | roll-free |
| `tests/operations/test_import_architecture.py` | roll-free |
| `tests/operations/test_release_admissibility_clock.py` | roll-free |
| `tests/test_projection_io.py` | roll-free |
| `tools/research/input_variable_significance.py` | roll-sensitive |
| `tools/research/measure_high_so_far_population_09_70a.py` | roll-sensitive |
| `tools/research/measure_replay_trust_09_75a.py` | roll-sensitive |
| `tools/research/missing_information/extract.py` | roll-sensitive |
| `tools/research/missing_information/supplement.py` | roll-sensitive |
| `tools/research/morning_guidance/run.py` | roll-sensitive |
| `tools/research/nbm_target_trace/run.py` | roll-sensitive |
