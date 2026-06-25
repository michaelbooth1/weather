# Large Module Ownership Map

Last updated: 2026-06-25

Use this map when moving code behind compatibility facades. Public module names
and CLIs stay stable while implementation ownership moves into smaller modules.

| Module | Owner | Boundary | Status |
| :--- | :--- | :--- | :--- |
| `weather.calibration.pooled_feature_model` | Calibration | Compatibility facade for pooled feature assembly, density/band training, training orchestration, artifact IO, reporting, and CLI modules. Dynamic source-state features live in `weather.calibration.pooled_feature_source_state`. | Split complete for item 173. |
| `weather.calibration.pooled_candidate_replay` | Calibration | Compatibility facade for candidate replay orchestration, prediction attachment, variant export, and CLI. Diagnostics, CLOB microstructure shadow helpers, market verdicts, replay gates, and sidecar summaries live in `weather.calibration.pooled_candidate_replay_diagnostics`; Markdown rendering lives in `weather.calibration.pooled_candidate_replay_report`; scoring/variant row logic lives in `weather.calibration.pooled_candidate_scoring`. | Split complete for project structure Phase 3. |
| `weather.calibration.pooled_candidate_replay_diagnostics` | Calibration | Candidate replay diagnostics, CLOB microstructure overlay training/scoring, casebook annotation, market verdicts, replay safety gates, forecast-profile guardrails, and data-layer sidecar summary loading. | Owner module; must not import the `pooled_candidate_replay` facade. |
| `weather.market.taker_bot` | Market | Compatibility facade for strategy registry, tape IO, strategy evaluation, sizing/risk, scoring, reporting, bakeoff, finalization, and CLI modules. | Split complete for item 173. |
| `weather.reporting.promotion_refresh` | Reporting | Compatibility facade for gate readers, readiness decisions, gap analysis, report rendering, orchestration, and CLI modules. | Split complete for item 173. |
| `weather.reporting.data_quality.data_layer_audit` | Reporting | Compatibility facade for historical/source audit, gates, recommendations, payload assembly, and CLI. Snapshot collection and low-fill classification live in `weather.reporting.data_quality.data_layer_audit_collectors`; Markdown rendering lives in `weather.reporting.data_quality.data_layer_audit_report`; remediation payload assembly lives in `weather.reporting.data_quality.data_layer_audit_remediation`. | Split complete for project structure Phase 3. |
| `weather.reporting.data_quality.data_layer_audit_collectors` | Reporting | Snapshot folder scanning, sidecar eligibility, artifact presence, source-status collection, and low-fill field classification. | Owner module; must not import the `data_layer_audit` facade. |
| `weather.reporting.fleet.fleet_observability` | Reporting | Compatibility facade for artifact inventory/alerts, loop health, broad SLO gates, payload assembly, rendering, and CLI modules. | Split complete for item 173. |
| `weather.reporting.hourly_model_performance` | Reporting | Compatibility facade for scoring, slot slices, remediation gates, context loading, report rendering, and CLI modules. | Split complete for item 173. |
| `weather.operations.daily_refresh` | Operations | Compatibility facade for daily refresh orchestration, lock/preflight, reporting, and CLI owner modules. | Split complete for item 205; scheduled command and public imports stay stable. |
| `weather.operations.daily_refresh_locks` | Operations | Lock, stale-state repair, and disk-preflight helpers. | Owner module for item 205; must not import the facade. |
| `weather.operations.daily_refresh_steps` | Operations | Step adapter compatibility surface for the daily refresh runner. Step order/resume filtering live in `weather.operations.daily_refresh_registry`; settled-day barrier contracts live in `weather.operations.daily_refresh_settled_day`; status aggregation and variant-learning gate summaries live in `weather.operations.daily_refresh_status`. | Item 318 slice complete; owner module is back below the 2,000-line warning threshold and must not import the `daily_refresh` facade. |
| `weather.operations.daily_refresh_registry` | Operations | Step order, planned-step rows, and resume filtering for daily refresh. | Owner module for item 318; must not import the facade or step adapters. |
| `weather.operations.daily_refresh_settled_day` | Operations | Settled-day analysis barrier dependency graph, target-date selection, freshness countability, and barrier exception contract. | Owner module for item 318; must not import the facade or step adapters. |
| `weather.operations.daily_refresh_status` | Operations | Step execution row wrapping, rollup freshness status, pipeline summary, and variant-learning operational gate. | Owner module for item 318; must not import the facade or step adapters. |
| `weather.operations.daily_refresh_report` | Operations | Status Markdown rendering and report file writing. | Owner module for item 205; must not import the facade. |
| `weather.operations.daily_refresh_cli` | Operations | CLI parser and command handlers with facade-injected dependencies. | Owner module for item 205; must not import the facade. |
| `weather.operations.tape_backup` | Operations | Tape manifest/status, retention/pruning, restore drill, and CLI orchestration. | Item 318 warning module; next split target is manifest/status first, then retention/pruning and restore drill helpers. |
| `weather.reporting.daily.daily_learning` | Reporting | Daily learning input readers, learning synthesis, retrain recommendations, report rendering, and CLI wiring. | Item 318 warning module; next split target is readers, synthesis/decision model, report rendering, and CLI wiring inside `weather.reporting.daily`. |
| `weather.market.mm_paper` | Market | Market-making paper tape ingestion, accounting/scoring, report rendering, evidence export, and CLI orchestration. | Item 318 warning module; next split target is tape ingestion and accounting/scoring before report/evidence export. |
| `weather.schema_registry` | Shared | Schema registry data, audit/check logic, and CLI rendering. | Item 318 warning module; defer first split until active 314/316/317 schema-registry edits settle, then split registry data from audit/check behavior. |
| `weather.collection.snapshot_store` | Collection | Snapshot schema constants, readers, writers, sidecar backfill/migration helpers, and repair CLI behavior. | Item 318 warning module; next split target is schema constants/readers before writers and repair helpers. |
| `weather.market.taker_bot_bakeoff` | Market | Taker bakeoff artifact readers, scoring, profitability verification, report rendering, and CLI. | Item 318 warning module; next split target is artifact readers and scoring before report rendering. |
| `weather.reporting.source_family_inventory` | Reporting | Source-family input readers, family/gate classification, report rendering, and CLI. | Item 318 warning module; next split target is input readers and classification before report rendering. |

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
