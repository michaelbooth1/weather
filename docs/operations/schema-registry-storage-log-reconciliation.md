# Schema Registry Storage/Log Reconciliation

Date: 2026-06-23

The original roadmap audit found 47 unregistered schema-like literals. The
authoritative pre-fix source audit for Item 291 found 50. The reconciliation
below registers durable storage/log/report artifacts and excludes only
non-schema policy, strategy, or model identifiers.

Validation command:

```powershell
python -m weather.schema_registry audit --paths src --strict
```

Expected post-fix result: zero unregistered versions, with the five excluded
non-schema identifiers reported in `excluded_versions`.

| Version | Classification | Action | Owner | Notes |
| --- | --- | --- | --- | --- |
| `backtest_artifact_cleanup_v0.1` | durable cleanup manifest | registered | `weather.reporting.backtest_artifact_retention` | Guarded generated-artifact cleanup evidence. |
| `backtest_artifact_retention_v0.1` | durable retention report | registered | `weather.reporting.backtest_artifact_retention` | Generated backtest artifact inventory and disk-budget report. |
| `blocked_market_variant_basket_no_go_v0.1` | report artifact | registered | `weather.reporting.validation.variant_basket_selection_validation` | Blocked variant-basket disposition. |
| `candidate_replay_sidecar_eligibility_v0.1` | diagnostic artifact | registered | `weather.calibration.pooled_candidate_replay_diagnostics` | Candidate replay sidecar eligibility diagnostics. |
| `clob_order_book_tiering_v0.1` | storage operation report | registered | `weather.operations.clob_order_book_tiering` | CLOB order-book gzip tiering plan/apply report. |
| `cross_hub_quoteability_v0.1` | readiness report | registered | `weather.reporting.cross_hub_readiness` | Cross-hub quoteability evidence. |
| `cross_hub_run_log_summary_v0.1` | log summary artifact | registered | `weather.reporting.cross_hub_research_audit` | Cross-hub run-log summary. |
| `daily_progress_ledger_v0.1` | durable log artifact | registered | `weather.reporting.daily.daily_progress_ledger` | Append-only daily progress ledger. |
| `daily_refresh_disk_preflight_v0.1` | preflight report | registered | `weather.operations.daily_refresh_locks` | Daily-refresh disk-headroom preflight payload. |
| `daily_refresh_stale_lock_repair_v0.1` | repair report | registered | `weather.operations.daily_refresh_cli` | Stale lock repair payload. |
| `daily_rollup_freshness_v0.1` | freshness report | registered | `weather.reporting.daily.daily_rollup_freshness` | Compact rollup freshness status. |
| `feature_quality_quarantine_folder_v0.1` | row artifact | registered | `weather.reporting.data_quality.feature_quality_quarantine` | Per-folder quarantine row. |
| `feature_quality_quarantine_summary_v0.1` | summary artifact | registered | `weather.reporting.data_quality.feature_quality_quarantine` | Feature-quality quarantine summary. |
| `flat_notional_v1` | sizing policy identifier | excluded | `weather.market.taker_bot_sizing` | Not a serialized artifact schema. |
| `forecast_error_model_v0.2` | model/report artifact | registered | `weather.calibration.forecast_error_model` | Forecast error model artifact. |
| `forecast_radiation_calibration_v0.1` | calibration sidecar | registered | `weather.calibration.pooled_training` | Forecast radiation calibration sidecar. |
| `forecast_radiation_promotion_lane_v0.1` | gate report | registered | `weather.reporting.forecast_radiation_gate` | Forecast radiation promotion-lane report. |
| `item224_no_market_ranked_winner_repair_v0.1` | repair report | registered | `weather.reporting.item224_no_market_ranked_winner_repair` | Item 224 ranked-winner repair evidence. |
| `maker_default_v0` | model variant basket identifier | excluded | `weather.market.market_making_model_variants` | Not a serialized artifact schema. |
| `market_residual_repair_rejected_registry_v0.1` | registry artifact | registered | `weather.reporting.market.market_residual_repair_program` | Rejected-family registry. |
| `mm_evidence_starvation_v0.1` | trading evidence report | registered | `weather.reporting.market.trading_evidence` | Market-making evidence starvation summary. |
| `mm_fill_evidence_completeness_v0.1` | trading evidence report | registered | `weather.market.mm_paper` | Fill-evidence completeness report. |
| `mm_model_variant_bakeoff_v0.1` | model bakeoff report | registered | `weather.market.market_making_model_variants` | Market-making model-variant bakeoff. |
| `mm_model_variant_clustered_promotion_gate_v0.1` | promotion gate report | registered | `weather.market.mm_paper` | Clustered promotion gate. |
| `mm_model_variant_paper_bakeoff_v0.1` | paper bakeoff report | registered | `weather.market.mm_paper` | Paper-trading model-variant bakeoff. |
| `mm_preflight_recovery_closeout_v0.1` | recovery report | registered | `weather.market.market_making_preflight` | Market-making preflight recovery closeout. |
| `mm_useful_work_liveness_v0.1` | liveness report | registered | `weather.market.market_making_run` | Useful-work liveness status. |
| `observation_payload_backfill_batch_v0.1` | batch repair report | registered | `weather.collection.snapshot_store` | Observation payload backfill batch. |
| `observation_payload_backfill_v0.1` | repair report | registered | `weather.collection.snapshot_store` | Observation payload backfill. |
| `optional_market_event_streams_v0.1` | observability report | registered | `weather.reporting.fleet.fleet_observability` | Optional market event stream status. |
| `polymarket_symmetric_price_v1` | fee/pricing model identifier | excluded | `weather.market.taker_bot_sizing` | Not a serialized artifact schema. |
| `pooled_feature_band_hgb_forecast_radiation_v0.1` | model artifact | registered | `weather.calibration.pooled_training` | Pooled HGB forecast-radiation candidate. |
| `predawn_candidate_ten_minute_performance_v0.1` | performance sidecar | registered | `weather.reporting.predawn_weak_slot_repair` | Predawn candidate ten-minute performance. |
| `runtime_identity_evidence_v0.1` | reconciliation report | registered | `weather.reporting.runtime_identity_evidence` | Runtime identity evidence across model/trading artifacts. |
| `snapshot_core_sidecar_backfill_batch_v0.1` | batch repair report | registered | `weather.collection.snapshot_store` | Snapshot core sidecar backfill batch. |
| `snapshot_core_sidecar_backfill_v0.1` | repair report | registered | `weather.collection.snapshot_store` | Snapshot core sidecar backfill. |
| `snapshot_explanation_backfill_batch_v0.1` | batch repair report | registered | `weather.collection.snapshot_store` | Snapshot explanation backfill batch. |
| `snapshot_explanation_backfill_v0.1` | repair report | registered | `weather.collection.snapshot_store` | Snapshot explanation backfill. |
| `snapshot_explanations_v0.1` | sidecar artifact | registered | `weather.collection.snapshot_store` | Snapshot explanations sidecar. |
| `snapshot_sidecar_eligibility_v0.1` | diagnostic artifact | registered | `weather.calibration.pooled_candidate_replay_diagnostics` | Snapshot sidecar eligibility diagnostics. |
| `source_status_proof_v0.1` | proof artifact | registered | `weather.collection.collection_health` | Source-status freshness proof. |
| `taker_bot_policy_v0.1` | trading policy artifact | registered | `weather.market.taker_bot` | Taker bot policy/config payload. |
| `taker_clustered_promotion_gate_v0.1` | promotion gate report | registered | `weather.market.taker_bot_bakeoff` | Taker clustered promotion gate. |
| `taker_counterfactual_tape_v0.1` | durable tape artifact | registered | `weather.market.taker_bot_tape_io` | Counterfactual taker order tape. |
| `taker_current_replay_profitability_verification_v0.1` | verification report | registered | `weather.market.taker_bot_bakeoff` | Current replay profitability verification. |
| `taker_edge_permission_map_v0.1` | durable permission map | registered | `weather.market.taker_edge_permission` | Per-slice taker edge permission map. |
| `taker_model_variant_shadow_bakeoff_v0.1` | shadow bakeoff report | registered | `weather.market.taker_bot_bakeoff` | Taker model-variant shadow bakeoff. |
| `taker_profitability_artifact_verification_v0.2` | verification report | registered | `weather.market.taker_bot_bakeoff` | Registered as `taker_profitability_artifact_verification_v0_2`; supersedes v0.1. |
| `top_of_book_only_v1` | execution depth model identifier | excluded | `weather.market.taker_bot_sizing` | Not a serialized artifact schema. |
| `top_of_book_plus_1pct_depth_v1` | execution depth model identifier | excluded | `weather.market.taker_bot_strategy_registry` | Not a serialized artifact schema. |

Ongoing rule: if a literal names a durable file, row export, manifest, report,
repair output, sidecar, or log, register it in `weather.schema_registry` and use
`schema_version(...)` in producers. Only non-serialized policy/model identifiers
belong in `EXCLUDED_SCHEMA_LITERALS`, and each exclusion must include owner,
classification, and reason.
