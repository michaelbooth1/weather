# Large Module Ownership Map

Last updated: 2026-07-03

Use this map when moving code behind compatibility facades. Public module names
and CLIs stay stable while implementation ownership moves into smaller modules.

Current module-size audit status:

- Warning threshold: 2,000 lines.
- Current warning count: 5 modules.
- Warning modules: `weather.market.mm_paper`, `weather.model.model_sources`,
  `weather.collection.snapshot_store`, `weather.schema_registry_data`, and
  `weather.reporting.daily.daily_learning`.
- A module can be marked "split complete" for an earlier item and still need a
  follow-on split if later feature growth pushes it back over the threshold.

| Module | Owner | Boundary | Status |
| :--- | :--- | :--- | :--- |
| `weather.calibration.pooled_feature_model` | Calibration | Compatibility facade for pooled feature assembly, density/band training, training orchestration, artifact IO, reporting, and CLI modules. Dynamic source-state features live in `weather.calibration.pooled_feature_source_state`. | Split complete for item 173. |
| `weather.calibration.pooled_candidate_replay` | Calibration | Compatibility facade for candidate replay orchestration, prediction attachment, variant export, and CLI. Diagnostics, CLOB microstructure shadow helpers, market verdicts, replay gates, and sidecar summaries live in `weather.calibration.pooled_candidate_replay_diagnostics`; Markdown rendering lives in `weather.calibration.pooled_candidate_replay_report`; scoring/variant row logic lives in `weather.calibration.pooled_candidate_scoring`. | Split complete for project structure Phase 3. |
| `weather.calibration.pooled_candidate_replay_diagnostics` | Calibration | Candidate replay diagnostics, CLOB microstructure overlay training/scoring, casebook annotation, market verdicts, replay safety gates, forecast-profile guardrails, and data-layer sidecar summary loading. | Owner module; must not import the `pooled_candidate_replay` facade. |
| `weather.market.taker_bot` | Market | Compatibility facade for strategy registry, tape IO, strategy evaluation, sizing/risk, scoring, reporting, bakeoff, finalization, and CLI modules. | Split complete for item 173. |
| `weather.model.model_sources` | Model | Serving-time source fetch orchestration, retry/backoff policy, source-group integration, and live/local source parsing for model assembly. | WARN in the 2026-07-03 audit. Next split should move provider-specific fetch/parsing helpers toward `weather.sources` or `weather.model.source_adapters`, keeping `model_sources` focused on serving-time source assembly. |
| `weather.reporting.promotion.promotion_refresh` | Reporting | Compatibility facade for gate readers, readiness decisions, gap analysis, report rendering, orchestration, and CLI modules. | Split complete for item 173. |
| `weather.reporting.data_quality.data_layer_audit` | Reporting | Compatibility facade for historical/source audit, gates, recommendations, payload assembly, and CLI. Snapshot collection and low-fill classification live in `weather.reporting.data_quality.data_layer_audit_collectors`; Markdown rendering lives in `weather.reporting.data_quality.data_layer_audit_report`; remediation payload assembly lives in `weather.reporting.data_quality.data_layer_audit_remediation`. | Split complete for project structure Phase 3. |
| `weather.reporting.data_quality.data_layer_audit_collectors` | Reporting | Snapshot folder scanning, sidecar eligibility, artifact presence, source-status collection, and low-fill field classification. | Owner module; must not import the `data_layer_audit` facade. |
| `weather.reporting.fleet.fleet_observability` | Reporting | Compatibility facade for artifact inventory/alerts, loop health, broad SLO gates, payload assembly, rendering, and CLI modules. | Split complete for item 173. |
| `weather.reporting.hourly.hourly_model_performance` | Reporting | Compatibility facade for scoring, slot slices, remediation gates, context loading, report rendering, and CLI modules. | Split complete for item 173. |
| `weather.operations.daily_refresh` | Operations | Compatibility facade for daily refresh orchestration, lock/preflight, reporting, and CLI owner modules. | Split complete for item 205; scheduled command and public imports stay stable. |
| `weather.operations.daily_refresh_locks` | Operations | Lock, stale-state repair, and disk-preflight helpers. | Owner module for item 205; must not import the facade. |
| `weather.operations.daily_refresh_steps` | Operations | Compatibility facade for the daily refresh runner. Step order/resume filtering live in `weather.operations.daily_refresh_registry`; settled-day barrier contracts live in `weather.operations.daily_refresh_settled_day`; status aggregation and variant-learning gate summaries live in `weather.operations.daily_refresh_status`; step adapters live in source, trading, and reporting family modules. | Item 318 step-family split complete; facade is back below the 2,000-line warning threshold. |
| `weather.operations.daily_refresh_source_steps` | Operations | Source-refresh, ingest quality, event metadata, settlement restore, and market-day label finalization step adapters. | Owner module for item 318; must not import the `daily_refresh` facade. |
| `weather.operations.daily_refresh_trading_steps` | Operations | Exchange economics, taker/maker evidence, CLOB tiering, replay status, and closed-day archive step adapters. | Owner module for item 318; must not import the `daily_refresh` facade. |
| `weather.operations.daily_refresh_reporting_steps` | Operations | Promotion, scorecard, lifecycle, observability, retention, snapshot evaluation, root-cause, daily learning, and daily flow step adapters. | Owner module for item 318; must not import the `daily_refresh` facade. |
| `weather.operations.daily_refresh_registry` | Operations | Step order, planned-step rows, and resume filtering for daily refresh. | Owner module for item 318; must not import the facade or step adapters. |
| `weather.operations.daily_refresh_settled_day` | Operations | Settled-day analysis barrier dependency graph, target-date selection, freshness countability, and barrier exception contract. | Owner module for item 318; must not import the facade or step adapters. |
| `weather.operations.daily_refresh_status` | Operations | Step execution row wrapping, rollup freshness status, pipeline summary, and variant-learning operational gate. | Owner module for item 318; must not import the facade or step adapters. |
| `weather.operations.daily_refresh_report` | Operations | Status Markdown rendering and report file writing. | Owner module for item 205; must not import the facade. |
| `weather.operations.daily_refresh_cli` | Operations | CLI parser and command handlers with facade-injected dependencies. | Owner module for item 205; must not import the facade. |
| `weather.operations.tape_backup` | Operations | Compatibility facade for export, restore drill, backup-job, status-report, and CLI behavior. Manifest/status helpers live in `weather.operations.tape_backup_manifest`; dedup repository helpers live in `weather.operations.tape_backup_dedup`; unmanifested cleanup/proof helpers live in `weather.operations.tape_backup_cleanup`. | Item 318 slice complete; owner module is back below the 2,000-line warning threshold. |
| `weather.operations.tape_backup_manifest` | Operations | Tape retention policy, manifest building, capacity checks, manifest validation, restore-drill SLA, backup status, and alert helpers. | Owner module for item 318; must not import the `tape_backup` facade. |
| `weather.operations.tape_backup_dedup` | Operations | Deduplicated repository preflight, restic command execution, repository status, backup, restore drill, and dedup backup job helpers. | Owner module for item 318; must not import the `tape_backup` facade. |
| `weather.operations.tape_backup_cleanup` | Operations | Unmanifested backup cleanup planning, durable restore proof verification, cleanup apply gates, and cleanup report rendering. | Owner module for item 318; must not import the `tape_backup` facade. |
| `weather.reporting.daily.daily_learning` | Reporting | Daily learning synthesis, retrain recommendations, output writing, CLI wiring, and compatibility exports for scorecard helpers. Input readers, input gates, experiment queue builders, and scorecard assembly live in `weather.reporting.daily.daily_learning_scorecard`; report rendering lives in `weather.reporting.daily.daily_learning_render`. | WARN in the 2026-07-03 audit. Next split should move learning-lane builders, promotion-confidence helpers, or retrain-plan assembly behind another daily-learning owner module. |
| `weather.reporting.daily.daily_learning_scorecard` | Reporting | Daily-learning artifact readers, input freshness/coverage/consistency gates, experiment queue item builders, label countability, calibration monitoring, and scorecard assembly. | Owner module for item 318; must not import the `daily_learning` facade. |
| `weather.market.mm_paper` | Market | Market-making paper orchestration, report/evidence export, model-variant promotion summaries, and compatibility exports for scoring helpers. Tape ingestion, conservative fill accounting, queue simulation, and P&L scoring live in `weather.market.mm_paper_scoring`. | WARN in the 2026-07-03 audit. Next split should move reward diagnostics, model-variant promotion gates, or fill-evidence completeness helpers out of the orchestration facade. |
| `weather.market.mm_paper_scoring` | Market | Active-day paper score freshness, quote/trade/book/mark tape readers, conservative fill simulation, queue companion scoring, and P&L summaries. | Owner module for item 318; must not import the `mm_paper` facade. |
| `weather.schema_registry` | Shared | Compatibility facade for schema version lookup, literal audit/check behavior, CLI rendering, and public registry-data exports. Static registry records live in `weather.schema_registry_data` and `weather.schema_registry_recent_data`; shared record types live in `weather.schema_registry_types`. | Item 318 slice complete; facade is back below the 2,000-line warning threshold. |
| `weather.schema_registry_data` | Shared | Static registered schema records, exclusion records, and lookup maps for the schema registry facade. | WARN in the 2026-07-03 audit. Acceptable as static registry data for now, but the next growth slice should move another schema family into `weather.schema_registry_recent_data` or a new static shard without importing producer modules. |
| `weather.schema_registry_recent_data` | Shared | Recent runtime, snapshot-sidecar, source-status, and taker schema records split from the main registry data shard. | Owner module for item 318; static data shard that imports only schema registry record types. |
| `weather.schema_registry_types` | Shared | Dependency-free schema registry dataclasses and registry schema version constant. | Owner module for item 318; shared by registry data shards and the public facade. |
| `weather.collection.snapshot_store` | Collection | Snapshot schema constants, readers, writers, and compatibility exports for backfill utilities. Backfill helpers and repair CLI behavior live in `weather.collection.snapshot_store_backfill`. | WARN in the 2026-07-03 audit. Next split should extract payload persistence, explanation sidecar, or replay-input helpers while preserving `SnapshotStore`'s public surface. |
| `weather.collection.snapshot_store_backfill` | Collection | Snapshot sidecar/cadence backfill helpers and snapshot-store utility CLI wiring. | Owner module for item 318; imports `SnapshotStore` lazily to avoid cycles. |
| `weather.market.taker_bot_bakeoff` | Market | Taker bakeoff orchestration, report rendering, champion/challenger ledger, and compatibility exports for replay/scoring helpers. Replay input, profitability verification, and model-variant scoring helpers live in `weather.market.taker_bot_bakeoff_scoring`. | Item 318 slice complete; owner module is back below the 2,000-line warning threshold. |
| `weather.market.taker_bot_bakeoff_scoring` | Market | Replay input normalization, current replay profitability verification, and model-variant bakeoff row expansion. | Owner module for item 318; must not import the `taker_bot_bakeoff` facade. |
| `weather.reporting.source_gates.source_family_inventory` | Reporting | Source-family input readers, family/gate classification, payload assembly, and CLI. Markdown rendering lives in `weather.reporting.source_gates.source_family_inventory_report`. | Item 318 slice complete; owner module is back below the 2,000-line warning threshold. |
| `weather.reporting.source_gates.source_family_inventory_report` | Reporting | Markdown rendering for source-family inventory artifacts. | Owner module for item 318; must not import the source-family inventory facade. |

Run the current audit with:

```powershell
python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md
```

The warning threshold is 2,000 lines. Item 318 owns the 2026-06-25 refreshed
warning set; each warning must keep a concrete owner, next split target, and
documented exception if it cannot be reduced immediately.

For a full repository structure snapshot, including tracked-file counts,
package line counts, compatibility shim counts, artifact sizes, and optional
ignored-data sizes / architecture-ratchet status, run:

```powershell
python -m weather.operations.structure_inventory --report data\backtest\structure_inventory_report.md
```

Add `--include-data-sizes` only when local disk-state sizing and budget warnings
are needed; ignored runtime data under `data/` can be very large.
