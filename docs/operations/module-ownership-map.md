# Large Module Ownership Map

Last updated: 2026-06-20

Use this map when moving code behind compatibility facades. Public module names
and CLIs stay stable while implementation ownership moves into smaller modules.

| Module | Owner | Boundary | Status |
| :--- | :--- | :--- | :--- |
| `weather.calibration.pooled_feature_model` | Calibration | Compatibility facade for pooled feature assembly, density/band training, training orchestration, artifact IO, reporting, and CLI modules. Dynamic source-state features live in `weather.calibration.pooled_feature_source_state`. | Split complete for item 173. |
| `weather.market.taker_bot` | Market | Compatibility facade for strategy registry, tape IO, strategy evaluation, sizing/risk, scoring, reporting, bakeoff, finalization, and CLI modules. | Split complete for item 173. |
| `weather.reporting.promotion_refresh` | Reporting | Compatibility facade for gate readers, readiness decisions, gap analysis, report rendering, orchestration, and CLI modules. | Split complete for item 173. |
| `weather.reporting.fleet_observability` | Reporting | Compatibility facade for artifact inventory/alerts, loop health, broad SLO gates, payload assembly, rendering, and CLI modules. | Split complete for item 173. |
| `weather.reporting.hourly_model_performance` | Reporting | Compatibility facade for scoring, slot slices, remediation gates, context loading, report rendering, and CLI modules. | Split complete for item 173. |
| `weather.operations.daily_refresh` | Operations | Compatibility facade for daily refresh orchestration, lock/preflight, reporting, and CLI owner modules. | Split complete for item 205; scheduled command and public imports stay stable. |
| `weather.operations.daily_refresh_locks` | Operations | Lock, stale-state repair, and disk-preflight helpers. | Owner module for item 205; must not import the facade. |
| `weather.operations.daily_refresh_steps` | Operations | Step order, runner registry, step adapters, and status summary helpers. | Owner module for item 205; must not import the facade. |
| `weather.operations.daily_refresh_report` | Operations | Status Markdown rendering and report file writing. | Owner module for item 205; must not import the facade. |
| `weather.operations.daily_refresh_cli` | Operations | CLI parser and command handlers with facade-injected dependencies. | Owner module for item 205; must not import the facade. |

Run the current audit with:

```powershell
python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md
```

The warning threshold is 2,000 lines. The item-173 and item-205 target modules
are now below the threshold; any future warning should name a concrete owner
and next split.
