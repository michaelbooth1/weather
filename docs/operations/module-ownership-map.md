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
| `weather.operations.daily_refresh` | Operations | Daily refresh orchestration facade. | Still above the 2,000-line warning threshold and tracked as the remaining non-item-173 split target. |

Run the current audit with:

```powershell
python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md
```

The warning threshold is 2,000 lines. The item-173 target modules are now below
the threshold; the current generated audit has one warning for
`weather.operations.daily_refresh`.
